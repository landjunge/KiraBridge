import asyncio
import json
import time

import pytest
from conftest import request
from test_mcp import http_bridge  # noqa: F401

from kirabridge.bridge_core.config import AgentConfig, VisibleTerminalBinding
from kirabridge.bridge_core.models import AgentInput, BridgeError, UncertainExecution
from kirabridge.message_manager import MessageSend


@pytest.fixture
def visible(bridge, config, monkeypatch):
    names = ["chatgpt", "grok_app", "codex", "grok"]
    for name in names:
        policy = config.principals["local"].model_copy(deep=True)
        policy.capabilities += ["session.inspect", "message.send", "message.read", "message.ack"]
        policy.approval_mode = "automatic"
        policy.message_peers = [other for other in names if other != name]
        config.principals[name] = policy
    config.visible_handoffs.enabled = True
    config.visible_handoffs.bindings = {
        target: VisibleTerminalBinding(
            pane_id="terminal:100:ttys001" if target == "grok" else "terminal:101:ttys002",
            expected_pid=123 if target == "grok" else 124,
            agent_pid=456 if target == "grok" else 457,
            ready_pattern=r"│\s*❯\s*│" if target == "grok" else r"(?m)^›\s*$",
        )
        for target in ["codex", "grok"]
    }
    config.agents = {target: AgentConfig(kind="grok_acp") for target in ["codex", "grok"]}
    transport = {"text": "╭\n│ ❯ │\n╰", "calls": [], "ack": True, "reply": True, "fail": False}

    async def selected(principal, pane, pid):
        if (pane, pid) == ("terminal:100:ttys001", 123):
            return {
                "pane_id": pane,
                "expected_pid": pid,
                "processes": [{"pid": 456, "name": "grok"}],
                "busy": True,
            }
        if (pane, pid) == ("terminal:101:ttys002", 124):
            return {
                "pane_id": pane,
                "expected_pid": pid,
                "processes": [{"pid": 457, "name": "codex"}],
                "busy": True,
            }
        raise BridgeError("session_selection_changed", "stale target")

    async def read(*args):
        return {"text": transport["text"]}

    async def insert(principal, args, *, before_transport=None):
        assert not args.submit
        if before_transport is not None:
            await before_transport()
        transport["calls"].append("insert")
        transport["inserted_body"] = args.text
        transport["text"] = (
            "› " + args.text
            if transport.get("target") == "codex"
            else "╭\n│ ❯ " + args.text + "\n╰"
        )
        return {"paste_event_sent": True, "return_sent": False, "agent_confirmed": False}

    async def submit(principal, pane, pid, *, expected_screen=None):
        transport["calls"].append("return")
        target = transport.get("target", "grok")
        # The cooperating test receiver reads its authenticated mailbox. Routing
        # metadata is no longer extracted from injected instructions in the UI.
        addressed = bridge.store.db.execute(
            "SELECT message_id FROM visible_handoffs WHERE target=? AND state='submitting'",
            (target,),
        ).fetchone()
        transport["text"] = "› " if transport.get("target") == "codex" else "╭\n│ ❯ │\n╰"
        if transport["fail"]:
            raise UncertainExecution("uncertain_return", "Unknown return delivery")
        messages = bridge.messages.receive(target)["messages"]
        if not addressed:
            return  # Literal session.input sends no work message and requires no ACK.
        message = next(m for m in messages if m["id"] == addressed[0])
        if transport["ack"]:
            bridge.messages.ack(target, message["id"], message["receipt"])
        if transport["reply"]:
            bridge.messages.send(
                target,
                MessageSend(
                    recipient=principal,
                    conversation_id=message["conversation_id"],
                    idempotency_key="reply",
                    reply_to=message["id"],
                    body="independent review",
                    kind="result",
                    request_reply=False,
                    dispatch=False,
                ),
            )

    monkeypatch.setattr(bridge.sessions, "selected", selected)
    monkeypatch.setattr(bridge.sessions, "read", read)
    monkeypatch.setattr(bridge.sessions, "insert", insert)
    monkeypatch.setattr(bridge.sessions, "press_return", submit)
    return bridge, transport


@pytest.mark.parametrize(
    "code", ["visible_target_not_ready", "session_busy", "session_selection_changed"]
)
async def test_final_session_preflight_refusal_is_not_an_uncertain_paste(
    visible, monkeypatch, code
):
    bridge, transport = visible
    original_insert = bridge.sessions.insert

    async def refused(principal, args, *, before_transport=None):
        # The real session manager checks readiness/identity before this callback.
        assert before_transport is not None
        raise BridgeError(code, "Synthetic final preflight refusal")

    monkeypatch.setattr(bridge.sessions, "insert", refused)
    task = {"id": "final-preflight", "principal": "chatgpt"}
    args = AgentInput(agent="grok", prompt="Only this authorized task", cwd="/tmp")
    with pytest.raises(BridgeError) as exc:
        await bridge.visible_handoffs.execute(task, args, callback, callback)
    assert exc.value.code == code
    assert not isinstance(exc.value, UncertainExecution)
    status = bridge.visible_handoffs.status("chatgpt", task["id"])
    assert status["state"] == "interrupted"
    assert status["evidence"]["terminal_input_attempted"] is False
    assert status["evidence"]["preinput_abort"] is True
    assert not any(e["state"] == "inserting" for e in status["events"])
    assert transport["calls"] == []
    # A fresh independent request is not locked by a paste that never started.
    await bridge.visible_handoffs.dispatch_ready("chatgpt", "grok")
    monkeypatch.setattr(bridge.sessions, "insert", original_insert)
    result = await bridge.visible_handoffs.execute(
        {"id": "new-after-final-preflight", "principal": "chatgpt"}, args, callback, callback
    )
    assert result["success"] and transport["calls"] == ["insert", "return"]
    # The old id is still not automatically replayed.
    with pytest.raises(UncertainExecution):
        await bridge.visible_handoffs.execute(task, args, callback, callback)
    assert transport["calls"] == ["insert", "return"]


@pytest.mark.parametrize("target", ["codex", "grok"])
async def test_body_edit_between_paste_and_return_never_submits(visible, target):
    bridge, transport = visible
    transport["target"] = target
    transport["text"] = "› " if target == "codex" else "╭\n│ ❯ │\n╰"

    async def edited(evidence):
        assert evidence["state"] == "inserted"
        transport["text"] = transport["text"].replace("AUTHORIZED", "UNAUTHORIZED")

    task = {"id": "edited-paste", "principal": "chatgpt"}
    args = AgentInput(agent=target, prompt="AUTHORIZED request", cwd="/tmp")
    with pytest.raises(UncertainExecution):
        await bridge.visible_handoffs.execute(task, args, callback, edited)
    assert transport["calls"] == ["insert"]
    status = bridge.visible_handoffs.status("chatgpt", task["id"])
    assert status["state"] == "unknown"
    assert not any(e["state"] == "return_sent" for e in status["events"])
    with pytest.raises(UncertainExecution):
        await bridge.visible_handoffs.execute(task, args, callback, callback)
    assert transport["calls"] == ["insert"]


@pytest.mark.parametrize("failure", ["timeout", "cancelled", "focus_changed"])
async def test_failure_after_native_boundary_stays_unknown_and_blocks_new_input(
    visible, monkeypatch, failure
):
    bridge, transport = visible

    async def uncertain(principal, args, *, before_transport=None):
        await before_transport()
        transport["calls"].append("native_attempt")
        if failure == "timeout":
            raise TimeoutError("A secret exception detail must not enter diagnostics")
        if failure == "cancelled":
            raise asyncio.CancelledError()
        raise BridgeError("visible_focus_changed", "A secret terminal detail")

    monkeypatch.setattr(bridge.sessions, "insert", uncertain)
    task = {"id": "native-boundary", "principal": "chatgpt"}
    args = AgentInput(agent="grok", prompt="PRIVATE_AUTHORIZED_BODY", cwd="/tmp")
    with pytest.raises(UncertainExecution):
        await bridge.visible_handoffs.execute(task, args, callback, callback)
    status = bridge.visible_handoffs.status("chatgpt", task["id"])
    assert status["state"] == "unknown"
    assert any(e["state"] == "inserting" for e in status["events"])
    assert not any(e["state"] == "return_sent" for e in status["events"])
    with pytest.raises(BridgeError) as blocked:
        await bridge.visible_handoffs.execute(
            {"id": "fresh-after-uncertain", "principal": "chatgpt"}, args, callback, callback
        )
    assert blocked.value.code == "visible_target_busy"
    with pytest.raises(UncertainExecution):
        await bridge.visible_handoffs.execute(task, args, callback, callback)
    assert transport["calls"] == ["native_attempt"]
    records = [
        json.loads(row[0])
        for row in bridge.store.db.execute(
            "SELECT metadata FROM audit WHERE kind='control.handoff.diagnostic' ORDER BY seq"
        )
    ]
    assert len(records) == 3
    assert records[0]["phase"] == "inserting"
    assert records[0]["error"] == "visible_handoff_unknown"
    assert records[0]["duration_ms"] >= 0 and records[0]["at"] > 0
    encoded = json.dumps(records)
    assert "PRIVATE_AUTHORIZED_BODY" not in encoded
    assert "secret" not in encoded
    assert "text" not in records[0] and "screen" not in records[0]


async def test_missing_return_acceptance_never_claims_execution_or_resends(visible, monkeypatch):
    bridge, transport = visible

    async def no_clear(principal, pane, pid, *, expected_screen=None):
        transport["calls"].append("return")

    monkeypatch.setattr(bridge.sessions, "press_return", no_clear)
    monkeypatch.setattr("kirabridge.visible_handoff.RETURN_OBSERVATION_TIMEOUT", 0)
    task = {"id": "return-not-accepted", "principal": "chatgpt"}
    args = AgentInput(agent="grok", prompt="Only once", cwd="/tmp")
    with pytest.raises(UncertainExecution):
        await bridge.visible_handoffs.execute(task, args, callback, callback)
    status = bridge.visible_handoffs.status("chatgpt", task["id"])
    assert status["state"] == "unknown"
    assert status["evidence"]["reason"] == "visible_submit_unknown"
    assert any(e["state"] == "return_sent" for e in status["events"])
    assert not any(e["state"] in {"sent", "confirmed", "completed"} for e in status["events"])
    with pytest.raises(UncertainExecution):
        await bridge.visible_handoffs.execute(task, args, callback, callback)
    assert transport["calls"] == ["insert", "return"]


async def callback(evidence):
    pass


@pytest.mark.parametrize("sender", ["chatgpt", "grok_app", "codex", "grok"])
@pytest.mark.parametrize("target", ["codex", "grok"])
@pytest.mark.parametrize(
    "body", ["Nur diesen Auftrag bearbeiten.", "  KiraBridge ACK KB-END-user\nÄnderung 最後  "]
)
async def test_body_only_handoff_never_adds_text_or_requires_agent_protocol(
    visible, sender, target, body
):
    import hashlib

    bridge, transport = visible
    transport.update(target=target, ack=False, reply=False)
    transport["text"] = "› " if target == "codex" else "╭\n│ ❯ │\n╰"
    task = {"id": "literal-body", "principal": sender}
    args = AgentInput(agent=target, prompt=body, cwd="/tmp", timeout=0.01, wait_for_reply=False)
    result = await bridge.visible_handoffs.execute(task, args, callback, callback)
    assert transport["inserted_body"].encode("utf-8") == body.encode("utf-8")
    assert result["scope"] == "visible_input_delivery" and result["return_sent"]
    assert not result["agent_confirmed"] and not result["request_reply_satisfied"]
    assert not result["project_completion_verified"] and not result["work_completion_verified"]
    assert "text" not in result and "reply_id" not in result["evidence"]
    assert (
        result["evidence"]["expected_payload_sha256"] == hashlib.sha256(body.encode()).hexdigest()
    )
    message = bridge.messages.get(sender, result["message_id"])
    assert message["body"] == body and message["acknowledged"] is None
    assert bool(message["request_reply"]) is False
    repeated = await bridge.visible_handoffs.execute(task, args, callback, callback)
    assert repeated["scope"] == "visible_input_delivery"
    assert transport["calls"] == ["insert", "return"]


@pytest.mark.parametrize("wait_for_reply", [True, False])
async def test_real_authenticated_reply_has_priority_over_transport_receipt(
    visible, wait_for_reply
):
    bridge, transport = visible
    args = AgentInput(
        agent="grok", prompt="Only this exact body", cwd="/tmp", wait_for_reply=wait_for_reply
    )
    result = await bridge.visible_handoffs.execute(
        {"id": "genuine-reply", "principal": "chatgpt"}, args, callback, callback
    )
    assert result["scope"] == "agent_turn" and result["text"] == "independent review"
    assert result["evidence"]["agent_confirmed"] and result["evidence"]["reply_id"]
    status = bridge.visible_handoffs.status("chatgpt", "genuine-reply")
    original = bridge.messages.get("chatgpt", status["message_id"])
    assert bool(original["request_reply"]) is wait_for_reply
    assert transport["inserted_body"] == args.prompt
    assert transport["calls"] == ["insert", "return"]


@pytest.mark.parametrize("mode", [True, False, None])
async def test_explicit_unsubmitted_continuation_preserves_durable_reply_preference(visible, mode):
    from kirabridge.bridge_core.models import canonical

    bridge, transport = visible
    transport.update(ack=False, reply=False)
    args = AgentInput(
        agent="grok", prompt="Exactly the original draft", cwd="/tmp", wait_for_reply=mode is True
    )

    async def stop_before_return(evidence):
        if evidence["state"] == "inserted":
            raise UncertainExecution("visible_insert_unknown", "Own controlled pre-Return stop")

    with pytest.raises(UncertainExecution):
        await bridge.visible_handoffs.execute(
            {"id": "own-unsubmitted", "principal": "chatgpt"},
            args,
            callback,
            stop_before_return,
        )
    assert transport["calls"] == ["insert"]
    if mode is None:
        status = bridge.visible_handoffs.status("chatgpt", "own-unsubmitted")
        inserted = next(event for event in status["events"] if event["state"] == "inserted")
        evidence = {
            key: value for key, value in inserted["evidence"].items() if key != "wait_for_reply"
        }
        bridge.store.db.execute(
            "UPDATE visible_handoff_events SET evidence=? WHERE seq=?",
            (canonical(evidence), inserted["seq"]),
        )
        with pytest.raises(BridgeError) as error:
            await bridge.visible_handoffs.continue_unsubmitted(
                "chatgpt", "own-unsubmitted", callback
            )
        assert error.value.code == "return_reconciliation_required"
        assert transport["calls"] == ["insert"]
    else:
        status = await bridge.visible_handoffs.continue_unsubmitted(
            "chatgpt", "own-unsubmitted", callback
        )
        sent = next(event for event in status["events"] if event["state"] == "sent")
        assert sent["evidence"]["wait_for_reply"] is mode
        assert bridge.visible_handoffs.body_only_transport_delivery(status) is (mode is False)
        assert transport["calls"] == ["insert", "return"]


async def test_default_reply_observer_times_out_without_rewriting_body_or_changing_mode(visible):
    from kirabridge.bridge_core.models import digest

    bridge, transport = visible
    transport.update(ack=False, reply=False)
    args = AgentInput(agent="grok", prompt="Unmodified user body", cwd="/tmp", timeout=0.01)
    assert args.wait_for_reply is True
    task = {"id": "default-wait", "principal": "chatgpt"}
    with pytest.raises(UncertainExecution) as error:
        await bridge.visible_handoffs.execute(task, args, callback, callback)
    assert error.value.code == "visible_reply_unknown"
    status = bridge.visible_handoffs.status("chatgpt", task["id"])
    historical_args = args.model_dump()
    historical_args.pop("wait_for_reply")
    assert status["request_hash"] == digest({"principal": "chatgpt", "args": historical_args})
    assert transport["inserted_body"] == args.prompt and status["state"] == "unknown"
    with pytest.raises(BridgeError) as conflict:
        await bridge.visible_handoffs.execute(
            task, args.model_copy(update={"wait_for_reply": False}), callback, callback
        )
    assert conflict.value.code == "handoff_conflict"
    assert transport["calls"] == ["insert", "return"]


@pytest.mark.parametrize("late_ack", [False, True])
async def test_default_observer_timeout_does_not_reactivate_released_input_slot(visible, late_ack):
    bridge, transport = visible
    transport.update(ack=False, reply=False)
    args = AgentInput(agent="grok", prompt="Original work", cwd="/tmp", timeout=0.35)
    task = {"id": "waiting-and-released", "principal": "chatgpt"}
    waiter = asyncio.create_task(bridge.visible_handoffs.execute(task, args, callback, callback))
    async with asyncio.timeout(1):
        while "return" not in transport["calls"]:
            await asyncio.sleep(0)
    binding = bridge.config.visible_handoffs.bindings["grok"]
    # A pre-mode version could have released this exact body-only slot already.
    # Upgrading the reply observer must preserve that proven historical release.
    await bridge.visible_handoffs.check_target("chatgpt", "grok", binding, ready=True)
    before = bridge.visible_handoffs.status("chatgpt", task["id"])
    bridge.visible_handoffs.transition(
        task["id"],
        "unknown",
        {
            **before["evidence"],
            "reason": "body_only_target_ready",
            "input_reservation_released": True,
            "target_readiness": "verified_ready_before_new_input",
        },
    )
    if late_ack:
        original = bridge.messages.receive("grok")["messages"][0]
        bridge.messages.ack("grok", original["id"], original["receipt"])
    with pytest.raises(UncertainExecution) as error:
        await waiter
    assert error.value.code == "visible_reply_unknown"
    status = bridge.visible_handoffs.status("chatgpt", task["id"])
    assert bridge.visible_handoffs.body_only_input_released(status)
    assert status["evidence"]["reply_observer_error"] == "reply_unconfirmed"
    assert not any(event["state"] == "confirmed" for event in status["events"])
    transport.update(ack=False, reply=False)
    result = await bridge.visible_handoffs.execute(
        {"id": "next-after-observer", "principal": "chatgpt"},
        args.model_copy(update={"wait_for_reply": False}),
        callback,
        callback,
    )
    assert result["scope"] == "visible_input_delivery"
    assert transport["calls"] == ["insert", "return", "insert", "return"]


@pytest.mark.parametrize("mode", [True, False, None])
async def test_ack_free_ready_release_requires_explicit_internal_transport_mode(visible, mode):
    from kirabridge.bridge_core.models import canonical

    bridge, transport = visible
    transport.update(ack=False, reply=False)
    args = AgentInput(
        agent="grok", prompt="Mode-bound work", cwd="/tmp", wait_for_reply=mode is True
    )
    task = {"id": "mode-bound", "principal": "chatgpt"}
    waiter = None
    if mode is True:
        waiter = asyncio.create_task(
            bridge.visible_handoffs.execute(task, args, callback, callback)
        )
        async with asyncio.timeout(1):
            while "return" not in transport["calls"]:
                await asyncio.sleep(0)
    else:
        assert (await bridge.visible_handoffs.execute(task, args, callback, callback))["submitted"]
    if mode is None:
        status = bridge.visible_handoffs.status("chatgpt", task["id"])
        event = next(event for event in status["events"] if event["state"] == "sent")
        evidence = {
            key: value for key, value in event["evidence"].items() if key != "wait_for_reply"
        }
        bridge.store.db.execute(
            "UPDATE visible_handoff_events SET evidence=? WHERE seq=?",
            (canonical(evidence), event["seq"]),
        )
    binding = bridge.config.visible_handoffs.bindings["grok"]
    try:
        if mode is False:
            await bridge.visible_handoffs.reconcile_target_reservations("chatgpt", "grok", binding)
            status = bridge.visible_handoffs.status("chatgpt", task["id"])
            assert bridge.visible_handoffs.body_only_input_released(status)
            assert status["evidence"]["wait_for_reply"] is False
        else:
            with pytest.raises(BridgeError) as error:
                await bridge.visible_handoffs.reconcile_target_reservations(
                    "chatgpt", "grok", binding
                )
            assert error.value.code == "visible_target_busy"
        assert transport["calls"] == ["insert", "return"]
    finally:
        if waiter is not None:
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter


@pytest.mark.parametrize(
    "body", ["", " leading\ttext \n\n", "› user text\nKB-END-original", "\\x00"]
)
def test_prompt_builder_preserves_every_character_without_interpreting_user_markers(body):
    from kirabridge.visible_handoff import VisibleHandoffs

    assert VisibleHandoffs.prompt("chatgpt", "codex", "id", body, "message", "channel") == body


async def test_body_only_input_slot_releases_only_after_fresh_same_target_ready(visible):
    bridge, transport = visible
    transport.update(ack=False, reply=False)
    args = AgentInput(
        agent="grok", prompt="One exact request", cwd="/tmp", timeout=0.01, wait_for_reply=False
    )
    first = {"id": "first-delivery", "principal": "chatgpt"}
    result = await bridge.visible_handoffs.execute(first, args, callback, callback)
    old_message = bridge.messages.get("chatgpt", result["message_id"])
    second = await bridge.visible_handoffs.execute(
        {"id": "second-delivery", "principal": "chatgpt"}, args, callback, callback
    )
    assert second["scope"] == "visible_input_delivery"
    old = bridge.visible_handoffs.status("chatgpt", first["id"])
    assert old["state"] == "unknown"
    assert old["evidence"]["reason"] == "body_only_target_ready"
    assert old["evidence"]["input_reservation_released"] is True
    assert old["evidence"]["target_readiness"] == "verified_ready_before_new_input"
    assert bridge.messages.get("chatgpt", old_message["id"])["acknowledged"] is None
    assert (await bridge.visible_handoffs.execute(first, args, callback, callback))["submitted"]
    assert transport["calls"] == ["insert", "return", "insert", "return"]


@pytest.mark.parametrize("frame", ["Known /resume menu", "› existing authorized draft"])
@pytest.mark.parametrize("late_ack", [False, True])
async def test_released_body_only_slot_does_not_override_current_return_guards(
    visible, monkeypatch, frame, late_ack
):
    bridge, transport = visible
    transport.update(target="codex", text="› ", ack=False, reply=False)
    args = AgentInput(
        agent="codex", prompt="Original body", cwd="/tmp", timeout=0.01, wait_for_reply=False
    )
    result = await bridge.visible_handoffs.execute(
        {"id": "released-before-menu", "principal": "chatgpt"}, args, callback, callback
    )
    binding = bridge.config.visible_handoffs.bindings["codex"]
    await bridge.visible_handoffs.reconcile_target_reservations("chatgpt", "codex", binding)
    before = bridge.visible_handoffs.status("chatgpt", "released-before-menu")
    assert bridge.visible_handoffs.body_only_input_released(before)
    if late_ack:
        original = bridge.messages.receive("codex")["messages"][0]
        assert original["id"] == result["message_id"]
        bridge.messages.ack("codex", original["id"], original["receipt"])
    transport["text"] = frame

    async def forbidden(*args, **kwargs):
        raise AssertionError("A released historical slot cannot require a new empty composer")

    monkeypatch.setattr(bridge.visible_handoffs, "check_target", forbidden)
    monkeypatch.setattr(
        bridge.sessions,
        "current_selection",
        lambda: ("codex", binding, {binding.expected_pid: {}, binding.agent_pid: {}}),
    )
    await bridge.visible_handoffs.reconcile_target_reservations(
        "chatgpt", "codex", binding, explicit_return_task_id="current-observed-return"
    )
    after = bridge.visible_handoffs.status("chatgpt", "released-before-menu")
    assert bridge.visible_handoffs.body_only_input_released(after)
    assert after["events"] == before["events"]
    assert transport["calls"] == ["insert", "return"]


@pytest.mark.parametrize(
    "invalid_release",
    [
        None,
        {"input_reservation_released": False},
        {"prompt_format": "legacy"},
        {"return_sent": False},
        {"target_readiness": "cached"},
    ],
)
async def test_active_or_incompletely_released_body_only_slot_still_requires_fresh_ready(
    visible, invalid_release
):
    bridge, transport = visible
    transport.update(target="codex", text="› ", ack=False, reply=False)
    args = AgentInput(
        agent="codex", prompt="Original body", cwd="/tmp", timeout=0.01, wait_for_reply=False
    )
    await bridge.visible_handoffs.execute(
        {"id": "active-before-menu", "principal": "chatgpt"}, args, callback, callback
    )
    binding = bridge.config.visible_handoffs.bindings["codex"]
    if invalid_release is not None:
        await bridge.visible_handoffs.reconcile_target_reservations("chatgpt", "codex", binding)
        released = bridge.visible_handoffs.status("chatgpt", "active-before-menu")
        bridge.visible_handoffs.transition(
            "active-before-menu", "unknown", {**released["evidence"], **invalid_release}
        )
    transport["text"] = "› existing authorized draft"
    with pytest.raises(BridgeError) as error:
        await bridge.visible_handoffs.reconcile_target_reservations("chatgpt", "codex", binding)
    assert error.value.code == "visible_input_not_empty"
    assert transport["calls"] == ["insert", "return"]


def retain_legacy_handoff(bridge, args, *, state="sent", reason="legacy", identifier="legacy"):
    from kirabridge.bridge_core.models import canonical, digest

    original = bridge.messages._send(
        "chatgpt",
        MessageSend(
            recipient=args.agent,
            conversation_id=identifier,
            idempotency_key=identifier,
            body=args.prompt,
            dispatch=False,
        ),
        visible_internal=True,
    )
    binding = bridge.config.visible_handoffs.bindings[args.agent]
    hash_args = args.model_dump()
    if args.wait_for_reply:
        hash_args.pop("wait_for_reply")
    bridge.store.db.execute(
        "INSERT INTO visible_handoffs VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            identifier,
            "chatgpt",
            args.agent,
            digest({"principal": "chatgpt", "args": hash_args}),
            canonical(binding.model_dump()),
            original["id"],
            state,
            1,
            1,
            canonical({"reason": reason}),
        ),
    )
    bridge.store.db.execute(
        "INSERT INTO visible_handoff_events(id,at,state,evidence) VALUES(?,1,?,?)",
        (identifier, state, canonical({"reason": reason})),
    )
    return original


async def test_legacy_sent_handoff_is_not_reinterpreted_as_body_only_delivery(visible):
    bridge, transport = visible
    args = AgentInput(agent="grok", prompt="Historical body", cwd="/tmp", timeout=0.01)
    retain_legacy_handoff(bridge, args)
    with pytest.raises(UncertainExecution) as error:
        await bridge.visible_handoffs.execute(
            {"id": "legacy", "principal": "chatgpt"}, args, callback, callback
        )
    assert error.value.code == "visible_reply_unknown"
    with pytest.raises(BridgeError) as busy:
        await bridge.visible_handoffs.execute(
            {"id": "new", "principal": "chatgpt"}, args, callback, callback
        )
    assert busy.value.code == "visible_target_busy" and not transport["calls"]


async def test_legacy_hash_without_wait_field_accepts_genuine_late_reply_without_input(visible):
    bridge, transport = visible
    args = AgentInput(agent="grok", prompt="Historical body", cwd="/tmp", timeout=0.01)
    original = retain_legacy_handoff(bridge, args)
    delivered = bridge.messages.receive("grok")["messages"][0]
    bridge.messages.ack("grok", delivered["id"], delivered["receipt"])
    bridge.messages.send(
        "grok",
        MessageSend(
            recipient="chatgpt",
            conversation_id=original["conversation_id"],
            idempotency_key="late-legacy",
            reply_to=original["id"],
            body="Real historical result",
            kind="result",
            request_reply=False,
            dispatch=False,
        ),
    )
    result = await bridge.visible_handoffs.execute(
        {"id": "legacy", "principal": "chatgpt"}, args, callback, callback
    )
    assert result["scope"] == "agent_turn" and result["text"] == "Real historical result"
    assert result["evidence"]["agent_confirmed"] and not transport["calls"]


async def test_legacy_unknown_marker_cannot_authorize_a_new_return(visible):
    bridge, transport = visible
    args = AgentInput(agent="grok", prompt="Historical body", cwd="/tmp", timeout=0.01)
    retain_legacy_handoff(bridge, args, state="unknown", reason="visible_insert_unknown")
    transport["text"] = "╭\n│ ❯ Historical body\nKB-END-old-marker\n╰"
    with pytest.raises(BridgeError) as error:
        await bridge.visible_handoffs.continue_unsubmitted("chatgpt", "legacy", callback)
    assert error.value.code == "return_reconciliation_required" and not transport["calls"]


async def test_eve_literal_session_input_reports_delivery_without_claiming_a_reply(
    visible, config, monkeypatch
):
    from test_visible_selection import new_native_selection, new_row

    from kirabridge.bridge_core.config import GrokConnectorConfig
    from kirabridge.grok_connector.conversation import result_for_conversation

    bridge, transport = visible
    config.grok_connector = GrokConnectorConfig(enabled=True, public_origin="https://voice.example")
    row = new_row()
    row["processes"][-1].update(name="grok", image="/bin/grok")
    await new_native_selection(bridge, monkeypatch, row)
    value = request(
        "session.input",
        {"pane_id": row["pane_id"], "expected_pid": 900, "text": "First line\nSecond line"},
    )
    async with bridge:
        bridge.prepare("grok_app", value)
        task = await bridge.tasks.wait("grok_app", value.task_id, timeout=5)
        assert task["state"] == "completed", task
        result = await result_for_conversation(bridge, "grok_app", task)
    returned = result["conversation_return"]
    assert not returned["final"] and returned["continue_required"]
    assert "Eine Antwort ist noch nicht bestätigt" in returned["text"]
    assert returned["scope"] == "terminal_input_delivery"
    assert returned["next_call"] == {
        "tool": "session_read",
        "arguments": {"pane_id": row["pane_id"], "expected_pid": 900},
    }
    assert returned["audio_playback"] == "not_observed_by_bridge"
    assert transport["calls"] == ["insert", "return"]


def hold_activation(bridge, state):
    now = time.time()
    bridge.store.db.execute(
        "INSERT INTO activation_runs VALUES('maintenance',?,?,?,?,NULL)",
        (state, now, now, "{}"),
    )


@pytest.mark.parametrize("sender", ["chatgpt", "grok_app", "codex", "grok"])
@pytest.mark.parametrize("state", ["draining", "verifying", "failed_blocked"])
async def test_maintenance_blocks_new_visible_work_for_all_senders(visible, sender, state):
    from kirabridge.bridge_core.config import ReceiverConfig

    bridge, transport = visible
    target = "codex" if sender == "grok" else "grok"
    transport["target"] = target
    transport["text"] = "› " if target == "codex" else "╭\n│ ❯ │\n╰"
    bridge.config.messaging.receivers[target] = ReceiverConfig(cwd="/tmp")
    hold_activation(bridge, state)
    args = AgentInput(agent=target, prompt="New work during maintenance", cwd="/tmp", timeout=1)
    with pytest.raises(BridgeError) as error:
        await bridge.agents.execute(
            {"id": "new-work", "principal": sender},
            args,
            bridge.config.principals[sender],
            callback,
            callback,
        )
    assert error.value.code == "service_maintenance"
    with pytest.raises(BridgeError) as error:
        bridge.messages.send(
            sender,
            MessageSend(
                recipient=target,
                conversation_id="new-public-work",
                idempotency_key="new",
                body="New public work",
                kind="work",
                dispatch=True,
            ),
        )
    assert error.value.code == "service_maintenance"
    assert transport["calls"] == []
    assert not bridge.store.db.execute("SELECT 1 FROM messages").fetchone()


@pytest.mark.parametrize("sender", ["chatgpt", "grok_app", "codex", "grok"])
async def test_already_claimed_visible_turn_and_return_complete_while_draining(visible, sender):
    from kirabridge.bridge_core.config import ReceiverConfig

    bridge, transport = visible
    target = "codex" if sender == "grok" else "grok"
    transport["target"] = target
    transport["text"] = "› " if target == "codex" else "╭\n│ ❯ │\n╰"
    bridge.config.messaging.receivers[target] = ReceiverConfig(cwd="/tmp")
    original = bridge.messages.send(
        sender,
        MessageSend(
            recipient=target,
            conversation_id="existing-work",
            idempotency_key="before-barrier",
            body="Already queued work",
            kind="work",
            dispatch=True,
        ),
    )
    _, run_id = bridge.message_receiver._claim(original["id"])
    hold_activation(bridge, "draining")
    with pytest.raises(BridgeError) as error:
        bridge.prepare(
            sender,
            request(
                "file.list", {"path": bridge.config.principals[sender].roots[0]}, task_id=run_id
            ),
        )
    assert error.value.code == "service_maintenance"
    args = AgentInput(agent=target, prompt=original["body"], cwd="/tmp", timeout=1)
    result = await bridge.agents.execute(
        {"id": run_id, "principal": sender, "visible_message_id": original["id"]},
        args,
        bridge.config.principals[sender],
        callback,
        callback,
    )
    assert result["success"]
    assert result["scope"] == "agent_turn"
    assert result["evidence"]["agent_confirmed"]
    reply = bridge.messages.get(sender, result["evidence"]["reply_id"])
    assert reply["recipient"] == sender and reply["sender"] == target
    assert reply["reply_to"] == original["id"]
    assert transport["calls"] == ["insert", "return"]
    assert bridge.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 2


@pytest.mark.parametrize("sender", ["chatgpt", "grok_app", "codex", "grok"])
async def test_four_senders_use_same_visible_route_and_distinct_confirmation(visible, sender):
    bridge, transport = visible
    target = "codex" if sender == "grok" else "grok"
    transport["target"] = target
    transport["text"] = "› " if target == "codex" else "╭\n│ ❯ │\n╰"
    args = AgentInput(agent=target, prompt="Read-only review", cwd="/tmp", timeout=1)
    task = {"id": "visible-test", "principal": sender}
    result = await bridge.agents.execute(
        task, args, bridge.config.principals[sender], callback, callback
    )
    assert result["success"] and result["evidence"]["agent_confirmed"]
    assert result["scope"] == "agent_turn" and result["text"] == "independent review"
    assert transport["inserted_body"] == args.prompt
    assert transport["calls"] == ["insert", "return"]
    bridge.visible_handoffs.transition(task["id"], "unknown", {"reason": "late_callback"})
    assert bridge.visible_handoffs.status(sender, task["id"])["state"] == "completed"
    status = bridge.visible_handoffs.status(sender, task["id"])
    states = [e["state"] for e in status["events"]]
    assert states == [
        "inserting",
        "inserted",
        "submitting",
        "return_sent",
        "sent",
        "confirmed",
        "completed",
    ]
    assert not status["events"][1]["evidence"]["return_sent"]
    assert not status["events"][4]["evidence"]["agent_confirmed"]
    assert len(bridge.messages.receive(target)["messages"]) == 0
    await bridge.visible_handoffs.execute(task, args, callback, callback)
    assert transport["calls"] == ["insert", "return"]


@pytest.mark.parametrize("failure", ["binding", "pid", "agent_pid", "ready"])
@pytest.mark.parametrize("sender", ["chatgpt", "grok_app", "codex", "grok"])
async def test_missing_changed_or_unready_target_never_spawns_or_sends(visible, failure, sender):
    bridge, transport = visible
    target = "codex" if sender == "grok" else "grok"
    transport["target"] = target
    transport["text"] = "› " if target == "codex" else "╭\n│ ❯ │\n╰"
    binding = bridge.config.visible_handoffs.bindings[target]
    if failure == "binding":
        del bridge.config.visible_handoffs.bindings[target]
    elif failure == "pid":
        binding.expected_pid = 999
    elif failure == "agent_pid":
        binding.agent_pid = 999
    else:
        transport["text"] = "Agent currently working"
    with pytest.raises(BridgeError):
        await bridge.visible_handoffs.execute(
            {"id": "blocked", "principal": sender},
            AgentInput(agent=target, prompt="test", cwd="/tmp"),
            callback,
            callback,
        )
    assert not transport["calls"]
    assert bridge.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0


@pytest.mark.parametrize("failure", ["return", "ack", "reply"])
async def test_unclear_transport_or_reply_is_never_repeated(visible, failure):
    bridge, transport = visible
    transport[{"return": "fail", "ack": "ack", "reply": "reply"}[failure]] = failure == "return"
    task = {"id": "unknown-test", "principal": "codex"}
    args = AgentInput(agent="grok", prompt="test", cwd="/tmp", timeout=0.02)
    with pytest.raises(UncertainExecution):
        await bridge.visible_handoffs.execute(task, args, callback, callback)
    assert bridge.visible_handoffs.status("codex", task["id"])["state"] == "unknown"
    with pytest.raises(UncertainExecution):
        await bridge.visible_handoffs.execute(task, args, callback, callback)
    assert transport["calls"] == ["insert", "return"]


async def test_in_flight_window_rejects_second_handoff(visible):
    bridge, transport = visible
    transport["reply"] = False
    args = AgentInput(agent="grok", prompt="test", cwd="/tmp", timeout=2)
    first = asyncio.create_task(
        bridge.visible_handoffs.execute(
            {"id": "first", "principal": "codex"}, args, callback, callback
        )
    )
    await asyncio.sleep(0.01)
    transport["text"] = "╭\nThinking… [stop]\n│ ❯ │\n╰"
    with pytest.raises(BridgeError) as error:
        await bridge.visible_handoffs.execute(
            {"id": "second", "principal": "chatgpt"},
            args,
            callback,
            callback,
        )
    assert error.value.code == "visible_target_working"
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert bridge.visible_handoffs.status("codex", "first")["state"] in {"sent", "confirmed"}
    assert transport["calls"] == ["insert", "return"]


async def test_prompt_limit_rejects_before_creating_inbox_or_pasting(visible):
    bridge, transport = visible
    with pytest.raises(BridgeError, match="input limit"):
        await bridge.visible_handoffs.execute(
            {"id": "oversized", "principal": "codex"},
            AgentInput(agent="grok", prompt="x" * 16385, cwd="/tmp"),
            callback,
            callback,
        )
    assert not transport["calls"]
    assert bridge.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
    assert bridge.store.db.execute("SELECT count(*) FROM visible_handoffs").fetchone()[0] == 0


async def test_late_authenticated_reply_reconciles_without_paste_or_return(visible):
    bridge, transport = visible
    transport["reply"] = False
    task = {"id": "late-reply", "principal": "codex"}
    args = AgentInput(agent="grok", prompt="test", cwd="/tmp", timeout=0.02)
    with pytest.raises(UncertainExecution):
        await bridge.visible_handoffs.execute(task, args, callback, callback)
    status = bridge.visible_handoffs.status("codex", task["id"])
    message = bridge.messages.get("codex", status["message_id"])
    bridge.messages.send(
        "grok",
        MessageSend(
            recipient="codex",
            conversation_id=message["conversation_id"],
            idempotency_key="late",
            reply_to=message["id"],
            body="late actual result",
            kind="result",
            request_reply=False,
            dispatch=False,
        ),
    )
    result = await bridge.visible_handoffs.execute(task, args, callback, callback)
    assert result["scope"] == "agent_turn" and result["text"] == "late actual result"
    assert bridge.messages.get("codex", message["id"])["acknowledged"]
    assert (
        bridge.store.db.execute(
            "SELECT body FROM messages WHERE reply_to=?", (message["id"],)
        ).fetchone()[0]
        == "late actual result"
    )
    assert bridge.visible_handoffs.status("codex", task["id"])["state"] == "completed"
    assert transport["calls"] == ["insert", "return"]


@pytest.mark.parametrize(
    "target,delta,observed",
    [
        ("codex", 0, True),
        ("codex", 1, False),
        ("grok", 0, False),
    ],
)
def test_real_codex_multiline_collapsed_paste_representation(target, delta, observed):
    from kirabridge.visible_handoff import VisibleHandoffs

    prompt = "First line\nSecond line with spaces and (punctuation)."
    view = f"› [Pasted Content {len(prompt) + delta} chars]\n"
    before = "› " if target == "codex" else "╭\n│ ❯ │\n╰"
    assert (
        bool(VisibleHandoffs.insertion_observed(target, view, prompt, "test", before=before))
        == observed
    )


@pytest.mark.parametrize("sender", ["chatgpt", "grok_app", "codex", "grok"])
@pytest.mark.parametrize("kind", ["codex", "grok_acp", "grok_api", "claude_code"])
async def test_no_adapter_can_spawn_fallback_for_any_sender(visible, monkeypatch, sender, kind):
    bridge, transport = visible
    target = "codex" if sender == "grok" else "grok"
    bridge.config.agents[target].kind = kind
    del bridge.config.visible_handoffs.bindings[target]

    async def forbidden(*args, **kwargs):
        raise AssertionError("A fallback attempted to create a process or window")

    monkeypatch.setattr(bridge.sessions, "open", forbidden)
    monkeypatch.setattr(bridge.agents.adapters[kind], "execute", forbidden)
    monkeypatch.setattr("kirabridge.agent_manager.spawn_process", forbidden)
    with pytest.raises(BridgeError) as exc:
        await bridge.agents.execute(
            {"id": "missing", "principal": sender},
            AgentInput(agent=target, prompt="test", cwd="/tmp"),
            bridge.config.principals[sender],
            callback,
            callback,
        )
    assert exc.value.code == "visible_target_missing"
    assert not transport["calls"]


@pytest.mark.parametrize("sender", ["codex", "grok"])
async def test_missing_reply_window_blocks_before_any_handoff(visible, sender):
    bridge, transport = visible
    target = "codex" if sender == "grok" else "grok"
    del bridge.config.visible_handoffs.bindings[sender]
    with pytest.raises(BridgeError) as exc:
        await bridge.visible_handoffs.execute(
            {"id": "no-reply-window", "principal": sender},
            AgentInput(agent=target, prompt="test", cwd="/tmp"),
            callback,
            callback,
        )
    assert exc.value.code == "visible_reply_target_missing"
    assert not transport["calls"]


def test_an_old_prompt_in_scrollback_does_not_prove_current_empty_input():
    from kirabridge.visible_handoff import VisibleHandoffs

    old_and_current = "╭\n│ ❯ │\n╰\nold history\n╭\n│ ❯ UNSENT PROMPT\n╰"
    field = VisibleHandoffs.input_view("grok", old_and_current)
    assert "old history" not in field and "UNSENT PROMPT" in field
    assert "│ ❯ │" not in field


def test_persisted_configuration_cannot_disable_visible_route():
    from pydantic import ValidationError

    from kirabridge.bridge_core.config import VisibleHandoffConfig

    with pytest.raises(ValidationError):
        VisibleHandoffConfig(enabled=False)


@pytest.mark.parametrize("sender", ["chatgpt", "grok_app", "codex", "grok"])
async def test_raw_cli_input_uses_the_literal_owner_for_every_sender(visible, monkeypatch, sender):
    bridge, transport = visible
    called = []

    async def literal(owner, task, args, target, binding, *callbacks):
        assert owner is bridge
        assert binding.pane_id == "terminal:100:ttys001"
        assert binding.agent_pid == 456
        called.append((task["id"], task["principal"], target, args.text))
        return {"submitted": True}

    monkeypatch.setattr("kirabridge.literal_session_input.execute", literal)
    task = {
        "id": "raw-input",
        "principal": sender,
        "operation": "session.input",
        "args": {
            "pane_id": "terminal:100:ttys001",
            "expected_pid": 123,
            "text": "explicit instruction",
        },
    }
    assert (await bridge.execute(task, callback, callback))["submitted"]
    assert called == [("raw-input", sender, "grok", "explicit instruction")]
    assert not transport["calls"]


async def test_team_style_self_turn_still_uses_existing_visible_window(visible):
    bridge, transport = visible
    result = await bridge.visible_handoffs.execute(
        {"id": "self-owned-team-task", "principal": "grok"},
        AgentInput(agent="grok", prompt="Assigned team work", cwd="/tmp"),
        callback,
        callback,
    )
    assert result["success"] and transport["calls"] == ["insert", "return"]


def test_old_marker_and_line_count_do_not_prove_a_literal_body():
    from kirabridge.bridge_core.models import digest
    from kirabridge.visible_handoff import VisibleHandoffs

    identifier, prompt = "grok-collapse", "First\nSecond\nThird"
    preview = "╭\nKB-END-" + digest(identifier)[:12] + "\n╰─ paste again or double-cli…"
    field = "\n╭\n│ ❯ [Pasted: 3 lines]\n╰"
    before = "╭\n│ ❯ │\n╰"
    assert not VisibleHandoffs.insertion_observed(
        "grok", preview + field, prompt, identifier, before=before
    )
    assert not VisibleHandoffs.insertion_observed("grok", field, prompt, identifier)
    assert not VisibleHandoffs.insertion_observed(
        "grok", preview + field, prompt + "\nMore", identifier
    )
    assert not VisibleHandoffs.insertion_observed(
        "grok", "Old history KB-END-" + digest(identifier)[:12] + field, prompt, identifier
    )


async def test_real_http_receiver_keeps_original_message_and_exactly_one_agent_reply(
    visible,
    http_bridge,  # noqa: F811
    config,
    monkeypatch,
):
    from kirabridge.bridge_core.config import ReceiverConfig
    from kirabridge.mcp_gateway.client import MCPClientPool, Peer

    bridge, transport = visible
    _, endpoint = http_bridge
    for identity in ["chatgpt", "grok"]:
        config.principals[identity].token_env = "VISIBLE_TEST_" + identity.upper()
        monkeypatch.setenv(config.principals[identity].token_env, identity + "-" + "x" * 48)
    config.messaging.receivers["grok"] = ReceiverConfig(
        cwd=config.principals["grok"].roots[0],
        timeout=3,
    )
    await bridge.message_receiver.start()
    async with MCPClientPool() as clients:
        await clients.connect(Peer("caller", url=endpoint, token="chatgpt-" + "x" * 48))
        sent = (
            await clients.call(
                "caller",
                "message_send",
                {
                    "completion_target": "visible-http-test",
                    "message": {
                        "recipient": "grok",
                        "conversation_id": "original-public-request",
                        "idempotency_key": "exactly-once",
                        "kind": "work",
                        "body": "Normal explicit user instruction",
                        "dispatch": False,
                    },
                },
            )
        ).structuredContent
        assert "message_buffer" not in sent and sent["processing"]
        assert sent["processing_route"] in {"pending_visible_terminal", "existing_visible_terminal"}
        async with asyncio.timeout(5):
            while True:
                current = bridge.messages.get("chatgpt", sent["id"])
                if current["processing"]["state"] not in {"queued", "running"}:
                    break
                await asyncio.sleep(0.02)
        assert current["processing"]["state"] == "completed", current
        reply = bridge.messages.get("chatgpt", current["processing"]["reply_id"])
        assert reply["reply_to"] == sent["id"] and reply["sender"] == "grok"
        assert reply["body"] == "independent review" and reply["processing"] is None
        assert current["processing_route"] == "existing_visible_terminal"
        assert bridge.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 2
        assert bridge.store.db.execute("SELECT count(*) FROM message_jobs").fetchone()[0] == 1
        assert transport["calls"] == ["insert", "return"]


def test_old_inbox_only_work_retry_does_not_retroactively_dispatch(visible):
    bridge, transport = visible
    value = MessageSend(
        recipient="grok",
        conversation_id="historical-inbox",
        idempotency_key="old",
        kind="work",
        body="old work",
        dispatch=False,
    )
    original = bridge.messages._send("codex", value, visible_internal=True)
    retry = bridge.messages.send("codex", value)
    assert retry["id"] == original["id"] and retry["processing"] is None
    assert not transport["calls"]


@pytest.mark.parametrize("sender", ["codex", "grok", "chatgpt", "grok_app"])
async def test_empty_field_with_active_agent_never_receives_a_new_handoff(visible, sender):
    bridge, transport = visible
    transport["text"] = "╭\nThinking… [stop]\n│ ❯ │\n╰"
    with pytest.raises(BridgeError) as exc:
        await bridge.visible_handoffs.execute(
            {"id": "busy-original", "principal": sender},
            AgentInput(agent="grok", prompt="new work", cwd="/tmp"),
            callback,
            callback,
        )
    assert exc.value.code == "visible_target_working" and not transport["calls"]


@pytest.mark.parametrize("sender", ["codex", "grok"])
async def test_reply_to_closed_original_requester_never_opens_another_window(
    visible, monkeypatch, sender
):
    bridge, transport = visible
    target = "codex" if sender == "grok" else "grok"
    transport["target"] = target
    transport["text"] = "› " if target == "codex" else "╭\n│ ❯ │\n╰"
    original_selected = bridge.sessions.selected
    requester = bridge.config.visible_handoffs.bindings[sender]

    async def selected(principal, pane, pid):
        if pane == requester.pane_id and "return" in transport["calls"]:
            raise BridgeError("session_selection_changed", "Original reply window closed")
        return await original_selected(principal, pane, pid)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Reply must not create a new window")

    monkeypatch.setattr(bridge.sessions, "selected", selected)
    monkeypatch.setattr(bridge.sessions, "open", forbidden)
    transport.update(ack=False, reply=False)
    result = await bridge.visible_handoffs.execute(
        {"id": "closed-reply-window", "principal": sender},
        AgentInput(agent=target, prompt="test", cwd="/tmp", wait_for_reply=False),
        callback,
        callback,
    )
    assert result["scope"] == "visible_input_delivery" and not result["agent_confirmed"]
    assert transport["calls"] == ["insert", "return"]


def grok_composer(content):
    width = 55
    row = " │ ❯ " + content + " " * (width - len(content)) + "│ "
    return (
        " ╭"
        + "─" * 56
        + "╮ \n"
        + row
        + "\n ╰"
        + "─" * 19
        + " Grok 4.7 (medium) · always-approve ─╯ \n"
        + " \n Ctrl+x:shortcuts\n"
    )


async def test_grok_placeholder_handoff_pastes_returns_once_and_releases_the_field(
    visible, monkeypatch
):
    bridge, transport = visible
    empty = grok_composer("Build anything")
    inserted = grok_composer("Only this exact body")
    transport.update(text=empty, target="grok", calls=[])

    async def read(*args):
        return {"text": transport["text"]}

    async def insert(principal, args, *, before_transport=None):
        assert before_transport is not None
        await before_transport()
        transport["calls"].append("insert")
        transport["text"] = inserted

    async def press_return(principal, pane, pid, *, expected_screen=None):
        assert expected_screen == inserted
        transport["calls"].append("return")
        # Grok paints the empty placeholder again after the field is cleared.
        transport["text"] = empty

    monkeypatch.setattr(bridge.sessions, "read", read)
    monkeypatch.setattr(bridge.sessions, "insert", insert)
    monkeypatch.setattr(bridge.sessions, "press_return", press_return)
    result = await bridge.visible_handoffs.execute(
        {"id": "grok-placeholder-once", "principal": "chatgpt"},
        AgentInput(
            agent="grok",
            prompt="Only this exact body",
            cwd="/tmp",
            wait_for_reply=False,
        ),
        callback,
        callback,
    )
    assert result["scope"] == "visible_input_delivery"
    assert result["return_sent"] and result["evidence"]["input_field_cleared"]
    # The placeholder is empty: neither a second paste nor a second Return.
    assert transport["calls"] == ["insert", "return"]
    status = bridge.visible_handoffs.status("chatgpt", "grok-placeholder-once")
    assert status["state"] == "sent"
