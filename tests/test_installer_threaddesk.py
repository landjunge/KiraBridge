"""Installer-managed ThreadDesk library: bundle placement, config switch, rollback."""

import hashlib
import importlib.util
import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

PIN = "ab" * 20
CONFIG = """# operator comment stays
data_dir = "{state}"

[threaddesk]
enabled = true
command = "/old/venv/bin/python"  # old interpreter
args = ["-m", "threaddesk.ui.mcp_stdio"]
workspace = "/ws"
source_root = "/old/shared/threaddesk-770bbc9/src"
timeout = 15

[terminal]
command = "/untouched"
"""


@pytest.fixture
def installer():
    path = Path(__file__).parents[1] / "installer/install.py"
    spec = importlib.util.spec_from_file_location("install_td_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bundle(tmp_path):
    root = tmp_path / "bundle"
    files = {
        "threaddesk/pyproject.toml": b'[project]\nname = "threaddesk"\n',
        "threaddesk/src/threaddesk/__init__.py": b"",
        "threaddesk/src/threaddesk/ui/mcp_stdio.py": b"print('td')\n",
    }
    for name, data in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)
    manifest = {
        "threaddesk": PIN,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
    }
    return root, manifest


def test_bundled_library_is_placed_once_and_verified(installer, tmp_path):
    root, manifest = bundle(tmp_path)
    args = SimpleNamespace(prefix=tmp_path / "install")
    library = installer.threaddesk_library(args, root, manifest)
    target = args.prefix / "shared" / ("threaddesk-" + PIN[:7])
    assert library == {"commit": PIN, "source_root": str(target / "src")}
    assert (target / "src/threaddesk/ui/mcp_stdio.py").read_bytes() == b"print('td')\n"
    # A later run (update) accepts the same bytes plus Python's own caches.
    (target / "src/threaddesk/__pycache__").mkdir()
    (target / "src/threaddesk/__pycache__/x.pyc").write_bytes(b"cache")
    assert installer.threaddesk_library(args, root, manifest) == library
    (target / "src/threaddesk/extra.py").write_text("planted")
    with pytest.raises(RuntimeError, match="differs from bundle"):
        installer.threaddesk_library(args, root, manifest)
    assert installer.threaddesk_library(args, root, {"files": {}}) is None


def test_config_switch_changes_only_the_two_values(installer):
    values = {"source_root": "/new/src", "command": "/release/python"}
    text = CONFIG.format(state="/s")
    result = installer.threaddesk_config(text, values)
    before, after = tomllib.loads(text), tomllib.loads(result)
    assert after["threaddesk"] == {**before["threaddesk"], **values}
    assert {k: v for k, v in after.items() if k != "threaddesk"} == {
        k: v for k, v in before.items() if k != "threaddesk"
    }
    assert result.splitlines()[0] == "# operator comment stays"
    assert after["terminal"]["command"] == "/untouched"
    assert installer.threaddesk_config('data_dir = "/s"\n', values) is None
    other = text.replace('["-m", "threaddesk.ui.mcp_stdio"]', '["serve"]')
    assert installer.threaddesk_config(other, values) is None


def run_activation(installer, monkeypatch, tmp_path, release_name):
    prefix = tmp_path / "install"
    prefix.mkdir(mode=0o700, exist_ok=True)
    release = prefix / "releases" / release_name
    (release / "source/.venv/bin").mkdir(parents=True)
    (release / "source/.venv/bin/python").write_text("")
    library = {"commit": PIN, "source_root": str(prefix / "shared/threaddesk-abababa/src")}
    (release / "release.json").write_text(
        json.dumps({"version": "0.8.0rc46", "commit": "c" * 40, "threaddesk": library})
    )
    args = SimpleNamespace(
        prefix=prefix,
        config=tmp_path / "config.toml",
        launcher=tmp_path / "bin/kirabridge",
        plist=tmp_path / "service.plist",
        service="launchd",
        full_access=False,
    )
    monkeypatch.setattr(installer, "loaded", lambda args: True)
    monkeypatch.setattr(installer, "cli", lambda *a, **kw: {"version": "0.8.0rc45"})
    monkeypatch.setattr(
        installer, "wait_health", lambda *a, **kw: {"version": "0.8.0rc46", "runtime": {"pid": 1}}
    )
    monkeypatch.setattr(installer, "stop_service", lambda args: None)
    monkeypatch.setattr(installer, "start_service", lambda args: None)
    monkeypatch.setattr(installer, "final_check", lambda *a: None)
    installer.activate(args, release)
    return args, release, library


def section(path):
    return tomllib.loads(path.read_text())["threaddesk"]


def test_install_update_and_rollback_switch_threaddesk(installer, monkeypatch, tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(CONFIG.format(state=tmp_path / "state"))
    config.chmod(0o600)
    original = config.read_bytes()
    args, first, library = run_activation(installer, monkeypatch, tmp_path, "rc46")
    assert section(config)["source_root"] == library["source_root"]
    assert section(config)["command"] == str(first / "source/.venv/bin/python")
    assert config.stat().st_mode & 0o777 == 0o600
    assert (
        Path(json.loads((args.prefix / "current.json").read_text())["backup"])
        / "config.before.toml"
    ).read_bytes() == original
    # Update: the next release takes over its own Python; rollback returns to the first.
    _, second, _ = run_activation(installer, monkeypatch, tmp_path, "rc47")
    assert section(config)["command"] == str(second / "source/.venv/bin/python")
    installer.rollback(args)
    assert section(config)["command"] == str(first / "source/.venv/bin/python")
    installer.rollback(args)
    assert config.read_bytes() == original


def test_rollback_keeps_values_changed_after_install(installer, monkeypatch, tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(CONFIG.format(state=tmp_path / "state"))
    args, _, _ = run_activation(installer, monkeypatch, tmp_path, "rc46")
    edited = config.read_text().replace("timeout = 15", "timeout = 30")
    edited = installer.threaddesk_config(edited, {"command": "/operator/python"})
    config.write_text(edited)
    installer.rollback(args)
    assert section(config)["command"] == "/operator/python"
    assert section(config)["timeout"] == 30
