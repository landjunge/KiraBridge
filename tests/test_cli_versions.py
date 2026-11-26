from types import SimpleNamespace

import pytest

from kirabridge.agent_manager import cli_versions
from kirabridge.discovery import _record_cli_versions
from kirabridge.task_manager.store import Store


def test_cli_version_parser_uses_only_bounded_version_text():
    assert cli_versions._version_text(b"Qwen Code v0.28.0\n") == "0.28.0"
    assert cli_versions._version_text(b"unknown output") is None


@pytest.mark.parametrize(
    ("kind", "version", "status"),
    [
        ("qwen_acp", "0.27.2", "compatible"),
        ("qwen_acp", "0.28.0", "unsupported"),
        (None, "0.28.0", "unsupported"),
        ("claude_code", "2.1.319", "unknown"),
        (None, "1.2.3", "unknown"),
        ("qwen_acp", None, "unknown"),
    ],
)
def test_cli_compatibility_is_explicit_and_unknown_fails_open(kind, version, status):
    cli = "qwen" if kind is None and version == "0.28.0" else None
    assert cli_versions.compatibility(kind, version, cli=cli)["status"] == status


@pytest.mark.asyncio
async def test_inventory_finds_path_cli_and_marks_running(monkeypatch, tmp_path):
    executable = tmp_path / "qwen"
    executable.write_text("fixture")
    executable.chmod(0o700)
    monkeypatch.setattr(
        cli_versions.shutil,
        "which",
        lambda name: str(executable) if name == "qwen" else None,
    )

    async def probe(_path):
        return {"status": "observed", "version": "0.28.0"}

    monkeypatch.setattr(cli_versions, "_probe", probe)
    rows = await cli_versions.inventory(
        {"qwen": SimpleNamespace(executable=str(executable), kind="qwen_acp")},
        ["qwen"],
        {"qwen"},
    )

    assert len(rows) == 1
    assert rows[0]["cli"] == "qwen"
    assert rows[0]["running"] is True
    assert rows[0]["version"] == "0.28.0"
    assert rows[0]["compatibility"] == {
        "status": "unsupported",
        "reason": "qwen_acp_version_not_in_supported_set",
    }


@pytest.mark.asyncio
async def test_inventory_keeps_custom_configured_cli_path(monkeypatch, tmp_path):
    executable = tmp_path / "claude-managed"
    executable.write_text("fixture")
    executable.chmod(0o700)
    monkeypatch.setattr(cli_versions.shutil, "which", lambda _name: None)

    async def probe(_path):
        return {"status": "observed", "version": "2.1.319"}

    monkeypatch.setattr(cli_versions, "_probe", probe)
    rows = await cli_versions.inventory(
        {"claude": SimpleNamespace(executable=str(executable), kind="claude_code")},
        ["claude"],
        {"claude-managed"},
    )

    assert rows == [
        {
            "cli": "claude",
            "agent_id": "claude",
            "adapter": "claude_code",
            "executable": str(executable.resolve()),
            "version": "2.1.319",
            "probe_status": "observed",
            "running": True,
            "compatibility": {
                "status": "unknown",
                "reason": "version_policy_not_declared_for_adapter",
            },
        }
    ]


def test_version_observations_record_only_baseline_and_changes(tmp_path):
    store = Store(tmp_path / "bridge.sqlite3")
    bridge = SimpleNamespace(store=store)
    qwen = {
        "cli": "qwen",
        "version": "0.28.0",
        "executable": "/opt/homebrew/bin/qwen",
        "probe_status": "observed",
        "compatibility": {"status": "unsupported"},
    }

    initial = _record_cli_versions(bridge, [qwen])
    assert initial[0]["event"] == "cli.compatibility"
    assert _record_cli_versions(bridge, [qwen]) == []
    changed = _record_cli_versions(
        bridge, [{**qwen, "version": "0.28.1", "compatibility": {"status": "unknown"}}]
    )

    assert changed[0]["previous"]["version"] == "0.28.0"
    assert changed[0]["current"]["version"] == "0.28.1"
    events = [row[0] for row in store.db.execute("SELECT kind FROM audit ORDER BY seq")]
    assert events == ["cli.version_observed", "cli.version_changed"]
    store.close()
