import asyncio
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

    async def insert(principal, args):
        assert not args.submit
        transport["calls"].append("insert")
        transport["text"] = (
            "› " + args.text
            if transport.get("target") == "codex"
            else "╭\n│ ❯ " + args.text + "\n╰"
        )

    async def submit(principal, pane, pid, *, expected_screen=None):
        transport["calls"].append("return")
        transport["text"] = "› " if transport.get("target") == "codex" else "╭\n│ ❯ │\n╰"
        if transport["fail"]:
            raise UncertainExecution("uncertain_return", "Unknown return delivery")
        target = transport.get("target", "grok")
        messages = bridge.messages.receive(target)["messages"]
        message = messages[0]
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


async def callback(evidence):
    pass


async def test_eve_session_input_returns_actual_confirmed_reply_in_conversation(visible, config):
    from kirabridge.bridge_core.config import GrokConnectorConfig
    from kirabridge.grok_connector.conversation import result_for_conversation

    bridge, transport = visible
    config.grok_connector = GrokConnectorConfig(enabled=True, public_origin="https://voice.example")
    value = request(
        "session.input",
        {"pane_id": "terminal:100:ttys001", "expected_pid": 123, "text": "First line\nSecond line"},
    )
    async with bridge:
        bridge.prepare("grok_app", value)
        task = await bridge.tasks.wait("grok_app", value.task_id, timeout=5)
        assert task["state"] == "completed", task
        result = await result_for_conversation(bridge, "grok_app", task)
    returned = result["conversation_return"]
    assert returned["final"] and not returned["continue_required"]
    assert returned["text"] == "independent review"
    assert returned["scope"] == "addressed_agent_reply" and returned["next_call"] is None
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
            {"id": "first", "principal": "codex"},
            args,
            callback,
            callback,
        )
    )
    await asyncio.sleep(0.01)
    transport["text"] = "› " if transport.get("target") == "codex" else "╭\n│ ❯ │\n╰"
    with pytest.raises(BridgeError, match="owns this terminal"):
        await bridge.visible_handoffs.execute(
            {"id": "second", "principal": "chatgpt"},
            args,
            callback,
            callback,
        )
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
            AgentInput(agent="grok", prompt="x" * 16384, cwd="/tmp"),
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
    assert result["text"] == "late actual result"
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
    assert bool(VisibleHandoffs.insertion_observed(target, view, prompt, "test")) == observed


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
async def test_raw_cli_input_also_enters_central_route(visible, monkeypatch, sender):
    bridge, transport = visible
    called = []

    async def central(task, args, *callbacks, binding_override=None):
        assert binding_override.pane_id == "terminal:100:ttys001"
        assert binding_override.agent_pid == 456
        called.append((task["id"], task["principal"], args.agent, args.prompt))
        return {"success": True}

    monkeypatch.setattr(bridge.visible_handoffs, "execute", central)
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
    assert (await bridge.execute(task, callback, callback))["success"]
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


def test_grok_collapsed_paste_requires_count_and_the_exact_preview_marker():
    from kirabridge.bridge_core.models import digest
    from kirabridge.visible_handoff import VisibleHandoffs

    identifier, prompt = "grok-collapse", "First\nSecond\nThird"
    preview = "╭\nKB-END-" + digest(identifier)[:12] + "\n╰─ paste again or double-cli…"
    field = "\n╭\n│ ❯ [Pasted: 3 lines]\n╰"
    assert VisibleHandoffs.insertion_observed("grok", preview + field, prompt, identifier)
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
    with pytest.raises(UncertainExecution):
        await bridge.visible_handoffs.execute(
            {"id": "closed-reply-window", "principal": sender},
            AgentInput(agent=target, prompt="test", cwd="/tmp"),
            callback,
            callback,
        )
    assert transport["calls"] == ["insert", "return"]
