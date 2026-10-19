import importlib.util
import json
import plistlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import request


@pytest.fixture
def installer():
    path = Path(__file__).parents[1] / "installer/install.py"
    spec = importlib.util.spec_from_file_location("install_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_busy_guard_prevents_switch_without_touching_tasks(installer, bridge, config, tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("data_dir = " + json.dumps(str(config.state_path)))
    value = request("file.list", {"path": config.principals["local"].roots[0]})
    bridge.prepare("local", value)
    with pytest.raises(RuntimeError, match="BUSY"):
        with installer.idle_guard(path):
            pytest.fail("must not enter activation")
    assert bridge.store.get(value.task_id, "local")["state"] == "created"


def test_private_atomic_write_rejects_symlink_and_preserves_original(installer, tmp_path):
    target = tmp_path / "real"
    target.write_text("preserve")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(RuntimeError, match="symlink"):
        installer.atomic(link, "replace")
    assert target.read_text() == "preserve"
    p = tmp_path / "private"
    installer.atomic(p, "private", 0o600)
    assert p.stat().st_mode & 0o777 == 0o600


def test_launchd_failure_restores_previous_definition_without_config_restore(
    installer, tmp_path, monkeypatch
):
    prefix = tmp_path / "install"
    prefix.mkdir(mode=0o700)
    config = tmp_path / "config.toml"
    config.write_text("data_dir = " + json.dumps(str(tmp_path / "state")))
    original_config = config.read_bytes()
    launcher = tmp_path / "bin/kirabridge"
    launcher.parent.mkdir()
    launcher.write_bytes(b"OLD_LAUNCHER\n")
    plist = tmp_path / "service.plist"
    old_plist = plistlib.dumps(
        {
            "Label": installer.LABEL,
            "ProgramArguments": [
                "old-python",
                "-m",
                "kirabridge.cli",
                "--config",
                str(config),
                "serve",
                "--transport",
                "http",
            ],
        }
    )
    plist.write_bytes(old_plist)
    release = prefix / "releases/new"
    release.mkdir(parents=True)
    (release / "release.json").write_text(json.dumps({"version": "0.6.0", "commit": "a" * 40}))
    args = SimpleNamespace(
        prefix=prefix,
        config=config,
        launcher=launcher,
        plist=plist,
        service="launchd",
        full_access=True,
    )
    monkeypatch.setattr(installer, "loaded", lambda args: True)
    monkeypatch.setattr(installer, "cli", lambda *a, **kw: {"version": "0.5.2"})
    monkeypatch.setattr(installer, "wait_health", lambda *a, **kw: {"version": "0.5.2"})
    operations = []
    monkeypatch.setattr(installer, "stop_service", lambda args: operations.append("stop"))

    def start(args):
        operations.append("start")
        if operations.count("start") == 1:
            raise RuntimeError("SIMULATED launchd bootstrap failure")

    monkeypatch.setattr(installer, "start_service", start)
    with pytest.raises(RuntimeError, match="SIMULATED"):
        installer.activate(args, release)
    assert launcher.read_bytes() == b"OLD_LAUNCHER\n"
    assert plist.read_bytes() == old_plist
    assert config.read_bytes() == original_config
    assert not (prefix / "current.json").exists()
    assert operations == ["stop", "start", "stop", "start"]


def test_command_timeout_is_bounded_and_does_not_leave_parent_running(installer):
    import subprocess
    import sys

    with pytest.raises(subprocess.TimeoutExpired):
        installer.run([sys.executable, "-c", "import time;time.sleep(20)"], timeout=0.05)
