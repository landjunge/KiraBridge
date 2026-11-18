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


def _audit_count(owner):
    db = owner.db if hasattr(owner, "db") else owner.store.db
    return db.execute("SELECT COUNT(*) AS n FROM audit").fetchone()["n"]


def _states(**expect):
    from kirabridge.technical_entries import latest_technical_states

    rows = latest_technical_states()
    return [row for row in rows if all(row.get(key) == value for key, value in expect.items())]


def _kept(body):
    assert body["routed"] == "kirabridge"
    assert body["kept"] == "latest_state_only"
    assert body.get("stored") is not True
    assert "stored" not in body


async def test_technical_types_keep_latest_state_and_are_not_written(bridge, tmp_path):
    root = _desk(tmp_path)
    bridge.threaddesk.settings.workspace = str(root)
    bridge.threaddesk.store = bridge.store
    before = _audit_count(bridge)
    for entry_type in ("progress", "claimed", "task", "problem"):
        result = await _run(bridge.threaddesk, _append(entry_type, content=entry_type + "-text"))
        assert result["success"] is True
        _kept(result["value"])
        assert "Pläne" in result["value"]["explanation"]
        found = _states(principal="local", thread_id="board-1", actor="Grok", entry_type=entry_type)
        assert len(found) == 1
        assert found[0]["content"] == entry_type + "-text"
    assert _files(root) == []
    assert _audit_count(bridge) == before
    assert _audit(bridge) == []


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
    before = _audit_count(bridge)
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
    _kept(result["value"])
    assert _files(root) == []
    assert _audit_count(bridge) == before
    saved = _states(principal="local", thread_id="", actor="", entry_type="progress")
    assert len(saved) == 1
    assert saved[0]["content"] == text[:2000]
    assert saved[0]["content_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert saved[0]["thread_id"] == ""
    assert len(saved[0]["content"]) <= 2000


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
        before = _audit_count(bridge)
        pool = fake_peer(bridge, [_board_tool("td_whiteboard__append")], effect)
        outcome = await call(bridge, "local", "td_whiteboard__append", payload, "claim-1")
        assert outcome["success"] is True
        assert outcome["routed"] == "kirabridge"
        assert outcome["kept"] == "latest_state_only"
        assert outcome.get("stored") is not True
        assert "stored" not in outcome
        _kept(outcome["value"])
        assert "Pläne" in outcome["explanation"]
        assert calls == []
        assert pool.call.await_count == 0
        assert _audit_count(bridge) == before
        saved = _states(principal="local", thread_id="board-1", actor="Codex", entry_type="claimed")
        assert len(saved) == 1
        assert saved[0]["content"] == "claim text"
        assert isinstance(saved[0]["at"], float)


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


def test_mcp_append_helper_keeps_latest_state_without_a_workspace(tmp_path):
    from kirabridge.bridge_core.config import Config
    from kirabridge.task_manager.store import Store
    from kirabridge.technical_entries import mcp_append_decision

    config = Config(data_dir=str(tmp_path / "state"))
    store = Store(config.state_path / "bridge.sqlite3")
    bridge = type("Bridge", (), {"config": config, "store": store})()
    before = _audit_count(store)
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
        _kept(decision)
        assert "aktuelle Stände" in decision["explanation"]
        saved = _states(principal="local", thread_id="", actor="", entry_type="problem")
        assert len(saved) == 1
        assert len(saved[0]["content"]) == 2000
        assert saved[0]["content_sha256"] == hashlib.sha256(("y" * 5000).encode()).hexdigest()
        assert _audit_count(store) == before
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


async def test_same_key_keeps_only_the_new_state(bridge, tmp_path):
    root = _desk(tmp_path)
    bridge.threaddesk.settings.workspace = str(root)
    bridge.threaddesk.store = bridge.store
    before = _audit_count(bridge)
    first = await _run(bridge.threaddesk, _append("progress", content="alt", thread_id="same-1"))
    second = await _run(bridge.threaddesk, _append("progress", content="neu", thread_id="same-1"))
    assert first["success"] is True and second["success"] is True
    _kept(second["value"])
    found = _states(principal="local", thread_id="same-1", actor="Grok", entry_type="progress")
    assert len(found) == 1
    assert found[0]["content"] == "neu"
    assert _audit_count(bridge) == before
    assert _files(root) == []


async def test_different_keys_keep_separate_states(bridge, tmp_path):
    root = _desk(tmp_path)
    bridge.threaddesk.settings.workspace = str(root)
    bridge.threaddesk.store = bridge.store
    before = _audit_count(bridge)
    await _run(bridge.threaddesk, _append("progress", content="eins", thread_id="split-1"))
    await _run(
        bridge.threaddesk,
        _append("progress", content="zwei", thread_id="split-1", actor="Ada"),
    )
    await _run(bridge.threaddesk, _append("task", content="drei", thread_id="split-2"))
    grok = _states(principal="local", thread_id="split-1", actor="Grok", entry_type="progress")
    ada = _states(principal="local", thread_id="split-1", actor="Ada", entry_type="progress")
    task = _states(principal="local", thread_id="split-2", actor="Grok", entry_type="task")
    assert len(grok) == len(ada) == len(task) == 1
    assert (grok[0]["content"], ada[0]["content"], task[0]["content"]) == ("eins", "zwei", "drei")
    assert _audit_count(bridge) == before
    assert _files(root) == []


def test_many_calls_with_one_key_keep_a_single_state(tmp_path):
    from kirabridge.bridge_core.config import Config
    from kirabridge.task_manager.store import Store
    from kirabridge.technical_entries import latest_technical_states, retained_record

    config = Config(data_dir=str(tmp_path / "state"))
    store = Store(config.state_path / "bridge.sqlite3")
    before = _audit_count(store)
    before_states = len(latest_technical_states())
    try:
        last = None
        for index in range(10_000):
            last = retained_record(
                store,
                "local",
                "whiteboard_append",
                {
                    "thread_id": "flood-1",
                    "entry_type": "progress",
                    "actor": "Grok",
                    "content": "n-" + str(index),
                },
            )
        assert last["kept"] == "latest_state_only"
        assert last.get("stored") is not True
        found = _states(principal="local", thread_id="flood-1", actor="Grok", entry_type="progress")
        assert len(found) == 1
        assert found[0]["content"] == "n-9999"
        assert len(latest_technical_states()) == before_states + 1
        assert _audit_count(store) == before
    finally:
        store.close()


async def test_broken_fields_still_succeed(bridge, tmp_path):
    root = _desk(tmp_path)
    bridge.threaddesk.settings.workspace = str(root)
    bridge.threaddesk.store = bridge.store
    before = _audit_count(bridge)

    class BadText:
        def __str__(self):
            raise RuntimeError("unprintable")

    result = await _run(
        bridge.threaddesk,
        ThreadDeskManageInput(
            operation_id="op-broken",
            action="whiteboard_append",
            id=None,
            expected_revision=0,
            data={
                "entry_type": "problem",
                "content": {"not": "text"},
                "actor": None,
                "thread_id": 12,
                "external_key": 7,
            },
        ),
    )
    from kirabridge.technical_entries import retained_record

    direct = retained_record(
        bridge.store,
        None,
        "whiteboard_append",
        {"entry_type": "task", "content": BadText(), "actor": ["nope"], "thread_id": {"id": 1}},
    )
    assert result["success"] is True
    _kept(result["value"])
    _kept(direct)
    assert _audit_count(bridge) == before
    assert _files(root) == []
