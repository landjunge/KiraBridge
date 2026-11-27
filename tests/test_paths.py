import json
from pathlib import Path

from kirabridge import paths


def test_legacy_fallback_when_no_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("KIRABRIDGE_FAMILY_HOME", str(tmp_path / "fam"))
    home = Path.home()
    assert not paths.layout_active()
    assert paths.config_file() == home / ".config/kirabridge/config.toml"
    assert paths.data_dir() == home / ".local/share/kirabridge"
    assert paths.state_dir() == home / ".local/state/kirabridge"
    assert paths.credentials_file() == home / ".config/kirabridge/credentials.json"
    assert not (tmp_path / "fam").exists()


def test_prepared_manifest_keeps_legacy_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("KIRABRIDGE_FAMILY_HOME", str(tmp_path / "fam"))
    out = paths.write_manifests("1.0")
    assert out["layout_state"] == "prepared"
    assert not paths.layout_active()
    assert paths.config_dir() == Path.home() / ".config/kirabridge"
    paths.write_manifests("1.1")
    tool = json.loads((tmp_path / "fam/KiraBridge/tool.json").read_text())
    assert tool["version"] == "1.1"
    family = json.loads((tmp_path / "fam/family.json").read_text())
    assert family["tools"]["kirabridge"]["dir"] == "KiraBridge"
    assert not (tmp_path / "fam/KiraBridge/config").exists()


def test_active_layout_resolves_new_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("KIRABRIDGE_FAMILY_HOME", str(tmp_path / "fam"))
    paths.write_manifests("1.0")
    tool_json = tmp_path / "fam/KiraBridge/tool.json"
    tool = json.loads(tool_json.read_text())
    tool["layout_state"] = "active"
    tool_json.write_text(json.dumps(tool))
    root = tmp_path / "fam/KiraBridge"
    assert paths.layout_active()
    assert paths.config_file() == root / "config/config.toml"
    assert paths.data_dir() == root / "data"
    assert paths.relay_log_file() == root / "state/logs/kirabridge-remote-relay.log"
    assert paths.write_manifests("2")["layout_state"] == "active"
