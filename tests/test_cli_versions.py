import json
import os
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
        ("qwen_acp", "0.27.2", "unknown"),
        ("qwen_acp", "0.28.0", "unknown"),
        ("qwen_acp", "0.99.9", "unknown"),
        (None, "0.28.0", "unknown"),
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
    bindir = tmp_path / "bin"
    bindir.mkdir()
    executable = bindir / "qwen"
    executable.write_text("fixture")
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(bindir))

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
    assert rows[0]["search_order"] == -1  # Explicit configured executable wins over PATH.
    assert rows[0]["compatibility"] == {
        "status": "unknown",
        "reason": "version_policy_not_declared_for_adapter",
    }


@pytest.mark.asyncio
async def test_inventory_keeps_custom_configured_cli_path(monkeypatch, tmp_path):
    executable = tmp_path / "claude-managed"
    executable.write_text("fixture")
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", "")

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
            "search_order": -1,
            "version": "2.1.319",
            "probe_status": "observed",
            "running": True,
            "compatibility": {
                "status": "unknown",
                "reason": "version_policy_not_declared_for_adapter",
            },
        }
    ]


@pytest.mark.asyncio
async def test_inventory_observes_all_path_installations_in_search_order(monkeypatch, tmp_path):
    first = tmp_path / "first" / "claude"
    second = tmp_path / "second" / "claude"
    first.parent.mkdir()
    second.parent.mkdir()
    for executable in (first, second):
        executable.write_text("fixture")
        executable.chmod(0o700)
    monkeypatch.setenv("PATH", os.pathsep.join((str(first.parent), str(second.parent))))

    async def probe(executable):
        version = "2.1.332" if executable == str(first) else "2.1.236"
        return {"status": "observed", "version": version}

    monkeypatch.setattr(cli_versions, "_probe", probe)
    rows = await cli_versions.inventory({}, [], set())

    assert [row["executable"] for row in rows] == [str(first.resolve()), str(second.resolve())]
    assert [row["version"] for row in rows] == ["2.1.332", "2.1.236"]
    assert [row["search_order"] for row in rows] == [0, 1]


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


def test_version_observation_compares_complete_set_not_probe_order(tmp_path):
    store = Store(tmp_path / "bridge.sqlite3")
    bridge = SimpleNamespace(store=store)
    first = {
        "cli": "claude",
        "version": "2.1.332",
        "executable": "/opt/claude-a",
        "search_order": 0,
        "probe_status": "observed",
        "compatibility": {"status": "unknown"},
    }
    second = {
        **first,
        "version": "2.1.236",
        "executable": "/opt/claude-b",
        "search_order": 1,
    }

    assert _record_cli_versions(bridge, [first, second]) == []
    # A different probe/iteration order still represents the same set; the
    # deterministic PATH priority selects the primary executable each time.
    assert _record_cli_versions(bridge, [second, first]) == []
    observed = [
        json.loads(row[0])
        for row in store.db.execute(
            "SELECT metadata FROM audit WHERE kind='cli.version_observed' ORDER BY seq"
        )
    ]
    assert len(observed) == 1
    assert observed[0]["version"] == "2.1.332"
    assert [row["version"] for row in observed[0]["installations"]] == [
        "2.1.332",
        "2.1.236",
    ]

    changed = _record_cli_versions(bridge, [first])
    assert len(changed) == 1
    assert changed[0]["event"] == "cli.version_changed"
    assert len(changed[0]["previous"]["installations"]) == 2
    assert len(changed[0]["current"]["installations"]) == 1
    assert _record_cli_versions(bridge, [first]) == []
    store.close()


def test_legacy_single_path_record_is_silently_upgraded_to_set_baseline(tmp_path):
    store = Store(tmp_path / "bridge.sqlite3")
    bridge = SimpleNamespace(store=store)
    store.audit(
        "cli.version_observed",
        "service",
        None,
        {
            "cli": "claude",
            "version": "2.1.332",
            "executable": "/opt/claude-a",
            "probe_status": "observed",
            "compatibility": "unknown",
        },
    )
    rows = [
        {
            "cli": "claude",
            "version": version,
            "executable": executable,
            "search_order": priority,
            "probe_status": "observed",
            "compatibility": {"status": "unknown"},
        }
        for version, executable, priority in (
            ("2.1.332", "/opt/claude-a", 0),
            ("2.1.236", "/opt/claude-b", 1),
        )
    ]

    assert _record_cli_versions(bridge, rows) == []
    assert _record_cli_versions(bridge, rows) == []
    events = [row[0] for row in store.db.execute("SELECT kind FROM audit ORDER BY seq")]
    assert events == ["cli.version_observed", "cli.version_observed"]
    store.close()


def test_first_observation_reports_unsupported_secondary_installation(tmp_path):
    store = Store(tmp_path / "bridge.sqlite3")
    bridge = SimpleNamespace(store=store)
    rows = [
        {
            "cli": "qwen",
            "version": "0.27.3",
            "executable": "/opt/qwen-supported",
            "search_order": 0,
            "probe_status": "observed",
            "compatibility": {"status": "compatible"},
        },
        {
            "cli": "qwen",
            "version": "0.28.0",
            "executable": "/opt/qwen-newer",
            "search_order": 1,
            "probe_status": "observed",
            "compatibility": {"status": "unsupported"},
        },
    ]

    changes = _record_cli_versions(bridge, rows)
    assert len(changes) == 1
    assert changes[0]["event"] == "cli.compatibility"
    assert changes[0]["current"]["version"] == "0.27.3"
    assert len(changes[0]["current"]["installations"]) == 2
    assert _record_cli_versions(bridge, rows) == []
    store.close()


def test_cli_version_history_is_read_once_for_many_cli_rows(tmp_path):
    store = Store(tmp_path / "bridge.sqlite3")
    bridge = SimpleNamespace(store=store)
    rows = [
        {
            "cli": f"tool-{index}",
            "version": "1.2.3",
            "executable": f"/opt/tool-{index}",
            "search_order": 0,
            "probe_status": "observed",
            "compatibility": {"status": "unknown"},
        }
        for index in range(12)
    ]
    statements = []
    store.db.set_trace_callback(statements.append)

    assert _record_cli_versions(bridge, rows) == []

    store.db.set_trace_callback(None)
    history_queries = [
        statement
        for statement in statements
        if statement.startswith("SELECT metadata FROM audit WHERE kind IN")
    ]
    assert len(history_queries) == 1
    store.close()


def test_cli_version_change_never_sends_team_message(monkeypatch):
    from kirabridge import discovery

    sent = []
    bridge = SimpleNamespace(teams=SimpleNamespace(send=lambda *a: sent.append(a)))
    monkeypatch.setattr(
        discovery, "_record_cli_versions", lambda *_: [{"event": "cli.version_changed"}]
    )
    assert not hasattr(discovery, "_notify_cli_version_changes")
    for version in ("0.99.9", "9.9.9"):
        assert cli_versions.compatibility("qwen_acp", version, cli="qwen")["status"] != (
            "unsupported"
        )
    discovery._record_cli_versions(bridge, [])
    assert sent == []
