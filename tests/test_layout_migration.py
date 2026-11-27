import json
import plistlib
import subprocess
import sys
from pathlib import Path

from kirabridge import layout_migration


def test_report_is_read_only_and_finds_references(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".config/kirabridge").mkdir(parents=True)
    (home / ".config/kirabridge/config.toml").write_text(f'x = "{home}/.local/share/kirabridge"')
    (home / ".local/share/kirabridge").mkdir(parents=True)
    (home / ".local/share/kirabridge/bridge.sqlite3-wal").write_bytes(b"w")
    agents = home / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    (agents / "com.kirabridge.bridge.plist").write_bytes(
        plistlib.dumps({"Label": "x", "A": str(home / ".config/kirabridge/config.toml")})
    )
    monkeypatch.setenv("KIRABRIDGE_FAMILY_HOME", str(tmp_path / "fam"))
    monkeypatch.setattr(layout_migration.paths.Path, "home", lambda: home)
    before = sorted(p for p in tmp_path.rglob("*"))
    out = layout_migration.report(home)
    assert sorted(p for p in tmp_path.rglob("*")) == before
    assert out["writes"] is False and out["layout_active"] is False
    assert out["references"]["services"][0]["fixed_paths"]
    assert any("WAL" in line for line in out["risks"])
    assert not (tmp_path / "fam").exists()


def test_apply_is_refused(tmp_path):
    env = {
        "KIRABRIDGE_FAMILY_HOME": str(tmp_path / "fam"),
        "PATH": "",
        "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
    }
    done = subprocess.run(
        [sys.executable, "-m", "kirabridge.cli", "migrate-layout", "--apply"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert done.returncode != 0
    assert "nicht freigegeben" in done.stderr
    assert not (tmp_path / "fam").exists()
