"""Explicit native resources do not borrow another pane's unknown delivery lock."""

import pytest
from test_visible_handoff import callback, visible  # noqa: F401
from test_visible_selection import new_native_selection, new_row, new_selection

from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.message_manager import MessageSend


@pytest.mark.parametrize(
    "reservation",
    [
        "independent",
        "same-pane",
        "same-tty",
        "same-window",
        "pid-overlap",
        "active",
        "same-task",
        "unverified-native",
    ],
)
async def test_submitted_explicit_handoff_preserves_other_unknown_resource(
    visible,  # noqa: F811
    config,
    monkeypatch,
    reservation,
):
    bridge, transport = visible
    transport.update(target="codex", text="› ")
    row = new_row()
    if reservation == "unverified-native":
        await new_selection(bridge, monkeypatch, row)
    else:
        await new_native_selection(bridge, monkeypatch, row)
    old_binding = config.visible_handoffs.bindings["codex"].model_copy(deep=True)
    if reservation == "same-pane":
        old_binding.pane_id = row["pane_id"]
    elif reservation == "same-tty":
        old_binding.pane_id = "terminal:101:ttys006"
    elif reservation == "same-window":
        old_binding.pane_id = "terminal:202:ttys002"
    elif reservation == "pid-overlap":
        old_binding.agent_pid = 901
    identifier = "fresh-submit" if reservation == "same-task" else "old-unknown"
    message = bridge.messages._send(
        "chatgpt",
        MessageSend(
            conversation_id="old-uncertain-resource",
            recipient="codex",
            body="Old uncertain input; never replay",
            idempotency_key="old-uncertainty",
            dispatch=False,
        ),
        visible_internal=True,
    )
    bridge.store.db.execute(
        "INSERT INTO visible_handoffs VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            identifier,
            "chatgpt",
            "codex",
            "old-request-hash",
            canonical(old_binding.model_dump()),
            message["id"],
            "sent" if reservation == "active" else "unknown",
            1,
            1,
            canonical({"reason": "visible_target_not_ready", "automatic_retry": False}),
        ),
    )
    before = dict(
        bridge.store.db.execute(
            "SELECT * FROM visible_handoffs WHERE id=?", (identifier,)
        ).fetchone()
    )
    original_default = config.visible_handoffs.bindings["codex"].model_dump()
    task = {
        "id": "fresh-submit",
        "principal": "chatgpt",
        "operation": "session.input",
        "args": {
            "pane_id": row["pane_id"],
            "expected_pid": row["expected_pid"],
            "text": "New independent request",
            "submit": True,
            "require_idle": True,
        },
    }
    if reservation == "independent":
        result = await bridge.execute(task, callback, callback)
        assert result["success"] and transport["calls"] == ["insert", "return"]
        assert bridge.visible_handoffs.status("chatgpt", task["id"])["state"] == "completed"
        # A positively completed new task can be read again, never pasted again.
        repeated = await bridge.execute(task, callback, callback)
        assert repeated["success"] and transport["calls"] == ["insert", "return"]
    else:
        with pytest.raises(BridgeError) as error:
            await bridge.execute(task, callback, callback)
        expected = (
            "handoff_conflict"
            if reservation == "same-task"
            else "visible_selection_required"
            if reservation == "unverified-native"
            else "visible_target_busy"
        )
        assert error.value.code == expected and not transport["calls"]
    after = dict(
        bridge.store.db.execute(
            "SELECT * FROM visible_handoffs WHERE id=?", (identifier,)
        ).fetchone()
    )
    assert after == before
    assert not bridge.store.db.execute(
        "SELECT 1 FROM visible_handoff_events WHERE id=?", (identifier,)
    ).fetchone()
    assert bridge.messages.get("chatgpt", message["id"])["acknowledged"] is None
    assert config.visible_handoffs.bindings["codex"].model_dump() == original_default
