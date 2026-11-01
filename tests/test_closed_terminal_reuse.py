"""A closed terminal's reused TTY is not its still-unresolved delivery identity."""

import json
import os
from copy import deepcopy

import pytest
from conftest import request
from test_visible_handoff import callback, visible  # noqa: F401

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import AgentInput, BridgeError, canonical
from kirabridge.message_manager import MessageSend
from kirabridge.visible_binding import load_refresh, overlay_path, save_refresh

# The visible fixture is imported for pytest dependency injection.
# ruff: noqa: F811


def successor(window=6022, shell=42082, agent=42144):
    return {
        "pane_id": f"terminal:{window}:ttys002",
        "expected_pid": shell,
        "agent_pid": agent,
        "agent_candidate": "codex",
        "tty": "/dev/ttys002",
        "transport": "terminal_app",
        "identity_ambiguous": False,
        "busy": True,
        "processes": [
            {"pid": shell, "ppid": shell - 1, "name": "zsh", "image": "/bin/zsh"},
            {"pid": agent, "ppid": shell, "name": "codex", "image": "/bin/codex"},
        ],
    }


def retain_unknown(bridge, binding, identifier="old-unknown", state="unknown"):
    message = bridge.messages._send(
        "chatgpt",
        MessageSend(
            recipient="codex",
            conversation_id=identifier,
            idempotency_key=identifier,
            body="Original uncertain work; never replay",
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
            canonical(binding.model_dump()),
            message["id"],
            state,
            1,
            1,
            canonical({"terminal_input_attempted": True, "automatic_retry": False}),
        ),
    )
    bridge.store.db.execute(
        "INSERT INTO visible_handoff_events(id,at,state,evidence) VALUES(?,1,?,?)",
        (identifier, state, canonical({"terminal_input_attempted": True})),
    )
    return original_history(bridge, identifier), message["id"]


def original_history(bridge, identifier):
    return {
        "row": dict(
            bridge.store.db.execute(
                "SELECT * FROM visible_handoffs WHERE id=?", (identifier,)
            ).fetchone()
        ),
        "events": [
            tuple(row)
            for row in bridge.store.db.execute(
                "SELECT * FROM visible_handoff_events WHERE id=? ORDER BY seq", (identifier,)
            )
        ],
    }


def install_native_model(monkeypatch, bridge, model):
    """Keep the actual absence proof and task selection; fake only OS transport."""

    async def selected(principal, pane, pid):
        row = model["row"]
        if (pane, pid) != (row["pane_id"], row["expected_pid"]):
            raise BridgeError("session_selection_changed", "Original terminal is closed")
        return deepcopy(row)

    async def catalog(principal, *, transport=None):
        return {"status": "available", "sessions": [deepcopy(model["row"])]}

    async def identity(pid, **kwargs):
        row = model["row"]
        process = next(p for p in row["processes"] if p["pid"] == pid)
        return (
            f"{os.getuid()} ttys002 Fri Oct 30 20:26:00 2026 {process['ppid']} {process['image']}"
        )

    async def processes():
        model["proof_calls"].append("ps")
        if "ps_error" in model:
            raise BridgeError("visible_absence_unproven", model["ps_error"])
        if "pid_snapshots" in model:
            return model["pid_snapshots"].pop(0)
        return frozenset({1, model["row"]["expected_pid"], model["row"]["agent_pid"]})

    async def windows():
        model["proof_calls"].append("windows")
        return deepcopy(
            model.get(
                "native_windows",
                {
                    "running": True,
                    "windows": [
                        {
                            "window_id": int(model["row"]["pane_id"].split(":")[1]),
                            "ttys": ["/dev/ttys002"],
                        }
                    ],
                },
            )
        )

    async def read(*args, **kwargs):
        return {"text": model["text"]}

    async def native_read(*args, **kwargs):
        return model["text"]

    async def insert(principal, args, *, before_transport=None):
        assert args.submit is False
        if before_transport is not None:
            await before_transport()
        model["input_calls"].append(("insert", args.pane_id, args.text))
        model["text"] = "› " + args.text
        return {"paste_event_sent": True, "return_sent": False, "agent_confirmed": False}

    async def submit(principal, pane, pid, *, expected_screen=None):
        model["input_calls"].append(("return", pane, pid))
        addressed = bridge.store.db.execute(
            "SELECT message_id FROM visible_handoffs WHERE target='codex' AND state='submitting'"
        ).fetchone()
        model["text"] = "› "
        if addressed is None:
            return  # Raw session.input has no internal work message or agent ACK.
        message = next(
            m for m in bridge.messages.receive("codex")["messages"] if m["id"] == addressed[0]
        )
        bridge.messages.ack("codex", message["id"], message["receipt"])
        bridge.messages.send(
            "codex",
            MessageSend(
                recipient=principal,
                conversation_id=message["conversation_id"],
                idempotency_key="reply-" + message["id"],
                reply_to=message["id"],
                body="Successor received exactly this new request",
                kind="result",
                request_reply=False,
                dispatch=False,
            ),
        )

    monkeypatch.setattr(type(bridge.sessions.terminal_app), "available", property(lambda _: True))
    monkeypatch.setattr(bridge.sessions.terminal_app, "process_identity", identity)
    monkeypatch.setattr(bridge.sessions.terminal_app, "process_ids", processes)
    monkeypatch.setattr(bridge.sessions.terminal_app, "window_inventory", windows)
    monkeypatch.setattr(bridge.sessions.terminal_app, "read", native_read)
    monkeypatch.setattr(bridge.sessions, "selected", selected)
    monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    monkeypatch.setattr(bridge.sessions, "read", read)
    monkeypatch.setattr(bridge.sessions, "insert", insert)
    monkeypatch.setattr(bridge.sessions, "press_return", submit)


def input_task(row, identifier="fresh-after-close"):
    return {
        "id": identifier,
        "principal": "chatgpt",
        "operation": "session.input",
        "args": {
            "pane_id": row["pane_id"],
            "expected_pid": row["expected_pid"],
            "text": "Only this newly authorized request",
            "submit": True,
            "require_idle": True,
        },
    }


async def durable_literal_input(bridge, task):
    """Idempotency belongs to the real task owner, not direct executor calls."""
    value = request(task["operation"], task["args"], task_id=task["id"])
    await bridge.tasks.start()
    try:
        bridge.prepare(task["principal"], value)
        first = await bridge.tasks.wait(task["principal"], task["id"], timeout=3)
        assert first["state"] == "completed", first
        bridge.prepare(task["principal"], value)
        repeated = await bridge.tasks.wait(task["principal"], task["id"], timeout=3)
        assert repeated["state"] == "completed" and repeated["attempt"] == 1
        return first["result"], repeated["result"]
    finally:
        await bridge.tasks.stop()


@pytest.mark.parametrize("route", ["explicit", "default"])
async def test_closed_terminal_reused_tty_accepts_new_handoff_without_replaying_old(
    visible, monkeypatch, route
):
    bridge, _ = visible
    old = bridge.config.visible_handoffs.bindings["codex"].model_copy(deep=True)
    before, message_id = retain_unknown(bridge, old)
    model = {"row": successor(), "text": "› ", "proof_calls": [], "input_calls": []}
    install_native_model(monkeypatch, bridge, model)
    if route == "explicit":
        task = input_task(model["row"])
        result, repeated = await durable_literal_input(bridge, task)
        assert result["return_sent"] and repeated["return_sent"]
        assert not result["execution_confirmed"]
    else:
        await bridge.visible_handoffs.dispatch_ready("chatgpt", "codex")
        task = {"id": "fresh-default-after-close", "principal": "chatgpt"}
        args = AgentInput(agent="codex", prompt="Only this newly authorized request", cwd="/tmp")
        result = await bridge.visible_handoffs.execute(task, args, callback, callback)
        repeated = await bridge.visible_handoffs.execute(task, args, callback, callback)
        assert result["success"] and repeated["success"]
    assert [call[0] for call in model["input_calls"]] == ["insert", "return"]
    assert model["proof_calls"][:3] == ["ps", "windows", "ps"]
    assert original_history(bridge, "old-unknown") == before
    assert bridge.messages.get("chatgpt", message_id)["acknowledged"] is None
    if route == "default":
        assert bridge.visible_handoffs.status("chatgpt", task["id"])["state"] == "completed"
    assert bridge.store.db.execute("SELECT count(*) FROM visible_handoffs").fetchone()[0] == (
        2 if route == "default" else 1
    )


@pytest.mark.parametrize(
    "failure",
    [
        "old-window",
        "old-shell-pid",
        "old-agent-pid",
        "old-agent-reappears",
        "invalid-window-inventory",
        "partial-window-inventory",
        "failed-process-inventory",
        "same-window",
        "overlapping-agent-pid",
        "current-working",
        "current-input",
    ],
)
async def test_reused_tty_does_not_release_unproven_identity_or_overwrite_new_input(
    visible, monkeypatch, failure
):
    bridge, _ = visible
    old = bridge.config.visible_handoffs.bindings["codex"].model_copy(deep=True)
    before, message_id = retain_unknown(bridge, old)
    model = {"row": successor(), "text": "› ", "proof_calls": [], "input_calls": []}
    new_pids = frozenset({1, model["row"]["expected_pid"], model["row"]["agent_pid"]})
    if failure == "old-window":
        model["native_windows"] = {
            "running": True,
            "windows": [{"window_id": 101, "ttys": ["/dev/ttys999"]}],
        }
    elif failure in {"old-shell-pid", "old-agent-pid", "old-agent-reappears"}:
        existing = old.expected_pid if failure == "old-shell-pid" else old.agent_pid
        model["pid_snapshots"] = (
            [new_pids, new_pids | {existing}]
            if failure == "old-agent-reappears"
            else [new_pids | {existing}]
        )
    elif failure == "invalid-window-inventory":
        model["native_windows"] = {"windows": []}
    elif failure == "partial-window-inventory":
        model["native_windows"] = {"running": True, "windows": [], "incomplete": True}
    elif failure == "failed-process-inventory":
        model["ps_error"] = "Process inventory is unavailable"
    elif failure == "same-window":
        model["row"] = successor(window=101)
    elif failure == "overlapping-agent-pid":
        model["row"] = successor(agent=old.agent_pid)
    elif failure == "current-working":
        model["text"] = "• Working (1s • esc to interrupt)\n\n› "
    elif failure == "current-input":
        model["text"] = "› User's unsent input"
    install_native_model(monkeypatch, bridge, model)
    with pytest.raises(BridgeError) as error:
        await bridge.execute(input_task(model["row"]), callback, callback)
    assert error.value.code == {
        "current-working": "visible_target_working",
        "current-input": "visible_input_not_empty",
    }.get(failure, "visible_target_busy")
    assert not model["input_calls"]
    assert original_history(bridge, "old-unknown") == before
    assert bridge.messages.get("chatgpt", message_id)["acknowledged"] is None
    assert bridge.store.db.execute("SELECT count(*) FROM visible_handoffs").fetchone()[0] == 1


@pytest.mark.parametrize("state", ["planned", "inserting", "sent", "confirmed"])
async def test_reused_tty_keeps_inflight_old_process_reservation(visible, monkeypatch, state):
    bridge, _ = visible
    old = bridge.config.visible_handoffs.bindings["codex"].model_copy(deep=True)
    before, _ = retain_unknown(bridge, old, state=state)
    row = successor()
    model = {
        "row": row,
        "text": "› ",
        "proof_calls": [],
        "input_calls": [],
        "pid_snapshots": [frozenset({1, row["expected_pid"], row["agent_pid"], old.agent_pid})],
    }
    install_native_model(monkeypatch, bridge, model)
    with pytest.raises(BridgeError) as error:
        await bridge.execute(input_task(row), callback, callback)
    assert error.value.code == "visible_target_busy"
    assert not model["input_calls"] and original_history(bridge, "old-unknown") == before


async def test_raw_input_bypasses_proven_dead_sent_reservation_without_rewriting_or_replay(
    visible, monkeypatch
):
    bridge, _ = visible
    old = bridge.config.visible_handoffs.bindings["codex"].model_copy(deep=True)
    before, message_id = retain_unknown(bridge, old, state="sent")
    model = {"row": successor(), "text": "› ", "proof_calls": [], "input_calls": []}
    install_native_model(monkeypatch, bridge, model)
    task = input_task(model["row"])
    result, repeated = await durable_literal_input(bridge, task)
    assert result["return_sent"] and repeated["return_sent"]
    assert [call[0] for call in model["input_calls"]] == ["insert", "return"]
    after = original_history(bridge, "old-unknown")
    assert after == before
    assert bridge.messages.get("chatgpt", message_id)["acknowledged"] is None
    assert bridge.store.get(task["id"], "chatgpt")["state"] == "completed"


async def test_two_closed_successors_and_daemon_reopen_keep_original_overlay_anchor(
    visible, monkeypatch
):
    bridge, _ = visible
    original = bridge.config.visible_handoffs.bindings["codex"].model_copy(deep=True)
    before, old_message = retain_unknown(bridge, original)
    model = {"row": successor(), "text": "› ", "proof_calls": [], "input_calls": []}
    install_native_model(monkeypatch, bridge, model)
    await bridge.visible_handoffs.dispatch_ready("chatgpt", "codex")
    first = bridge.config.visible_handoffs.bindings["codex"].model_copy(deep=True)
    first_history, first_message = retain_unknown(bridge, first, "first-successor-unknown")
    model["row"] = successor(window=7000, shell=50000, agent=50001)
    await bridge.visible_handoffs.dispatch_ready("chatgpt", "codex")
    latest = bridge.config.visible_handoffs.bindings["codex"].model_copy(deep=True)
    saved = json.loads(overlay_path(bridge.config).read_text())["codex"]
    assert saved["replaced_pane_id"] == original.pane_id
    assert saved["replaced_expected_pid"] == original.expected_pid
    assert saved["replaced_agent_pid"] == original.agent_pid
    assert saved["pane_id"] == latest.pane_id
    reopened_config = bridge.config.model_copy(deep=True)
    reopened_config.visible_handoffs.bindings["codex"] = original
    reopened = Bridge(reopened_config)
    try:
        assert reopened.config.visible_handoffs.bindings["codex"] == latest
        install_native_model(monkeypatch, reopened, model)
        args = AgentInput(agent="codex", prompt="New request after daemon restart", cwd="/tmp")
        task = {"id": "new-after-two-closes-and-restart", "principal": "chatgpt"}
        result = await reopened.visible_handoffs.execute(task, args, callback, callback)
        assert result["success"]
        assert [call[0] for call in model["input_calls"]] == ["insert", "return"]
        assert original_history(reopened, "old-unknown") == before
        assert original_history(reopened, "first-successor-unknown") == first_history
        assert reopened.messages.get("chatgpt", old_message)["acknowledged"] is None
        assert reopened.messages.get("chatgpt", first_message)["acknowledged"] is None
    finally:
        reopened.store.close()


def test_refresh_chain_does_not_override_new_manual_binding(visible):
    bridge, _ = visible
    configured = bridge.config.visible_handoffs.bindings["codex"].model_copy(deep=True)
    first = configured.model_copy(
        update={"pane_id": "terminal:200:ttys002", "expected_pid": 2000, "agent_pid": 2001}
    )
    second = first.model_copy(
        update={"pane_id": "terminal:300:ttys002", "expected_pid": 3000, "agent_pid": 3001}
    )
    save_refresh(bridge.config, "codex", configured, first)
    save_refresh(bridge.config, "codex", first, second)
    manual = configured.model_copy(
        update={"pane_id": "terminal:900:ttys009", "expected_pid": 9000, "agent_pid": 9001}
    )
    bridge.config.visible_handoffs.bindings["codex"] = manual
    load_refresh(bridge.config)
    assert bridge.config.visible_handoffs.bindings["codex"] == manual
    manual_successor = manual.model_copy(
        update={"pane_id": "terminal:901:ttys009", "expected_pid": 9010, "agent_pid": 9011}
    )
    save_refresh(bridge.config, "codex", manual, manual_successor)
    saved = json.loads(overlay_path(bridge.config).read_text())["codex"]
    assert saved["replaced_pane_id"] == manual.pane_id
    bridge.config.visible_handoffs.bindings["codex"] = configured
    load_refresh(bridge.config)
    assert bridge.config.visible_handoffs.bindings["codex"] == configured
    bridge.config.visible_handoffs.bindings["codex"] = manual
    load_refresh(bridge.config)
    assert bridge.config.visible_handoffs.bindings["codex"] == manual_successor
