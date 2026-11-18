"""Technical whiteboard entries stay in KiraBridge. Synthetic boards only."""

import hashlib
import json
from pathlib import Path

from mcp.types import CallToolResult

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import ThreadDeskManageInput
from kirabridge.threaddesk_dynamic import call


def _desk(tmp_path: Path) -> Path:
    root = tmp_path / "desk"
    (root / "threads").mkdir(parents=True)
    (root / "whiteboard" / "board-1").mkdir(parents=True)
    (root / "threads" / "board-1.json").write_text(json.dumps({"id": "board-1", "title": "Probe"}))
    (root / "state.json").write_text(json.dumps({"current_id": "other"}))
    return root


def _append(entry_type, **data):
    payload = {"actor": "Grok", "actor_type": "grok", "content": "kurz", **data}
    if entry_type is not None:
        payload["entry_type"] = entry_type
    thread_id = payload.pop("thread_id", "board-1")
    return ThreadDeskManageInput(
        operation_id="op-" + (entry_type or "missing"),
        action="whiteboard_append",
        id=thread_id,
        expected_revision=0,
        data=payload,
    )


async def _run(manager, args):
    async def running(_evidence):
        return None

    return await manager.execute({"id": "task-1", "principal": "local"}, args, running)


def _files(root: Path) -> list[str]:
    board = root / "whiteboard" / "board-1"
    return sorted(path.name for path in board.glob("*.json"))


def _audit(bridge):
    rows = bridge.store.db.execute(
        "SELECT kind, principal, metadata, hash, at FROM audit WHERE kind=?",
        ("whiteboard.technical",),
    ).fetchall()
    return rows


async def test_technical_types_are_stored_and_not_written(bridge, tmp_path):
    root = _desk(tmp_path)
    bridge.threaddesk.settings.workspace = str(root)
    bridge.threaddesk.store = bridge.store
    for entry_type in ("progress", "claimed", "task", "problem"):
        result = await _run(bridge.threaddesk, _append(entry_type, content=entry_type + "-text"))
        assert result["success"] is True
        assert result["value"]["routed"] == "kirabridge"
        assert result["value"]["stored"] is True
        assert "Pläne" in result["value"]["explanation"]
    assert _files(root) == []
    rows = _audit(bridge)
    assert [json.loads(row["metadata"])["entry_type"] for row in rows] == [
        "progress",
        "claimed",
        "task",
        "problem",
    ]
    assert all(row["hash"] and row["principal"] == "local" and row["at"] for row in rows)


async def test_decision_result_note_and_unknown_still_reach_threaddesk(bridge, tmp_path):
    root = _desk(tmp_path)
    bridge.threaddesk.settings.workspace = str(root)
    bridge.threaddesk.store = bridge.store
    for entry_type in ("decision", "result", "note"):
        result = await _run(bridge.threaddesk, _append(entry_type, content="bleibt " + entry_type))
        assert result["success"] is True
        assert result["value"].get("routed") != "kirabridge"
        assert result["value"]["entry_type"] == entry_type
    from kirabridge.bridge_core.models import BridgeError

    try:
        await _run(bridge.threaddesk, _append("heartbeat", content="unbekannt"))
    except BridgeError as exc:
        assert exc.code == "invalid_arguments"
    else:
        raise AssertionError("unknown entry types keep the existing ThreadDesk validation")
    names = _files(root)
    assert len(names) == 3
    assert _audit(bridge) == []
    state = json.loads((root / "state.json").read_text())
    assert state["current_id"] == "other"


async def test_long_text_and_missing_fields_do_not_fail(bridge, tmp_path):
    root = _desk(tmp_path)
    bridge.threaddesk.settings.workspace = str(root)
    bridge.threaddesk.store = bridge.store
    text = "x" * 100_000
    result = await _run(
        bridge.threaddesk,
        ThreadDeskManageInput(
            operation_id="op-long",
            action="whiteboard_append",
            id=None,
            expected_revision=0,
            data={"entry_type": "progress", "content": text},
        ),
    )
    assert result["success"] is True
    assert result["value"]["stored"] is True
    assert _files(root) == []
    saved = json.loads(_audit(bridge)[-1]["metadata"])
    assert saved["content"] == text[:2000]
    assert saved["content_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert saved["thread_id"] == ""
    assert len(saved["content"]) <= 2000


def _board_tool(name):
    from types import SimpleNamespace

    return SimpleNamespace(
        name=name,
        description="Synthetic whiteboard append",
        annotations=SimpleNamespace(readOnlyHint=False, destructiveHint=False, openWorldHint=False),
        inputSchema={"type": "object", "additionalProperties": True, "properties": {}},
    )


async def test_dynamic_progress_does_not_call_threaddesk(config):
    from test_threaddesk_dynamic_lifecycle import configured, fake_peer

    configured(config)
    calls = []

    async def effect(*args, **kwargs):
        calls.append(args[1] if len(args) > 1 else args)
        return CallToolResult(content=[], structuredContent={"ok": True})

    payload = {
        "workspace_id": "ws1",
        "arguments": {
            "id": "board-1",
            "actor": "Codex",
            "entry_type": "claimed",
            "content": "claim text",
        },
        "operation_id": "claim-1",
    }
    async with Bridge(config) as bridge:
        pool = fake_peer(bridge, [_board_tool("td_whiteboard__append")], effect)
        outcome = await call(bridge, "local", "td_whiteboard__append", payload, "claim-1")
        assert outcome["success"] is True
        assert outcome["routed"] == "kirabridge"
        assert outcome["stored"] is True
        assert "Pläne" in outcome["explanation"]
        assert calls == []
        assert pool.call.await_count == 0
        rows = bridge.store.db.execute(
            "SELECT metadata FROM audit WHERE kind=?", ("whiteboard.technical",)
        ).fetchall()
        saved = json.loads(rows[-1]["metadata"])
        assert saved["entry_type"] == "claimed"
        assert saved["actor"] == "Codex"
        assert saved["thread_id"] == "board-1"
        assert isinstance(saved["at"], float)


async def test_dynamic_decision_still_calls_the_peer(config):
    from test_threaddesk_dynamic_lifecycle import configured, fake_peer

    configured(config)
    seen = []

    async def effect(*args, **kwargs):
        seen.append(args[1] if len(args) > 1 else args)
        return CallToolResult(content=[], structuredContent={"ok": True, "duplicate": False})

    payload = {"id": "board-1", "entry_type": "decision", "content": "bleiben", "actor": "Ada"}
    async with Bridge(config) as bridge:
        pool = fake_peer(bridge, [_board_tool("td_whiteboard__append")], effect)
        outcome = await call(bridge, "local", "td_whiteboard__append", payload, "keep-1")
    assert outcome.get("routed") != "kirabridge"
    assert pool.call.await_count >= 1
    assert seen


async def test_switch_off_restores_whiteboard_writes(bridge, tmp_path):
    root = _desk(tmp_path)
    bridge.config.threaddesk.route_technical_entries = False
    bridge.threaddesk.settings.workspace = str(root)
    bridge.threaddesk.store = bridge.store
    result = await _run(bridge.threaddesk, _append("progress", content="wieder auf das Board"))
    assert result["success"] is True
    assert result["value"].get("routed") != "kirabridge"
    assert result["value"]["entry_type"] == "progress"
    assert _files(root) == [result["value"]["id"] + ".json"]
    assert _audit(bridge) == []


def test_proxy_keeps_technical_appends_off_the_peer_catalog():
    from kirabridge.technical_entries import proxy_retention

    desk = type("Desk", (), {"route_technical_entries": True})()
    config = type("Cfg", (), {"threaddesk": desk})()
    kept = proxy_retention(
        config,
        "td_whiteboard__append",
        {"arguments": {"entry_type": "task", "content": "intern", "id": "board-9"}},
    )
    assert kept["name"] == "td_whiteboard__append"
    assert kept["arguments"]["arguments"]["entry_type"] == "task"
    assert (
        proxy_retention(
            config,
            "td_whiteboard__append",
            {"entry_type": "note", "content": "sichtbar"},
        )
        is None
    )
    assert proxy_retention(config, "td_whiteboard__entry", {"entry_type": "progress"}) is None
    config.threaddesk.route_technical_entries = False
    assert (
        proxy_retention(config, "td_whiteboard_append", {"entry_type": "progress", "content": "x"})
        is None
    )


def test_mcp_append_helper_stores_without_a_workspace(tmp_path):
    from kirabridge.bridge_core.config import Config
    from kirabridge.task_manager.store import Store
    from kirabridge.technical_entries import mcp_append_decision

    config = Config(data_dir=str(tmp_path / "state"))
    store = Store(config.state_path / "bridge.sqlite3")
    bridge = type("Bridge", (), {"config": config, "store": store})()
    try:
        decision = mcp_append_decision(
            bridge,
            "local",
            thread_id="",
            entry_type="problem",
            content="y" * 5000,
            actor="",
            actor_type="",
            external_key=None,
        )
        assert decision["routed"] == "kirabridge"
        assert decision["stored"] is True
        assert "aktuelle Stände" in decision["explanation"]
        saved = json.loads(
            store.db.execute(
                "SELECT metadata FROM audit WHERE kind=?", ("whiteboard.technical",)
            ).fetchone()["metadata"]
        )
        assert saved["entry_type"] == "problem"
        assert len(saved["content"]) == 2000
        assert saved["content_sha256"] == hashlib.sha256(("y" * 5000).encode()).hexdigest()
        passed = mcp_append_decision(
            bridge,
            "local",
            thread_id="board-1",
            entry_type="result",
            content="bleibt",
            actor="Ada",
            actor_type="human",
            external_key=None,
        )
        assert passed is None
    finally:
        store.close()
