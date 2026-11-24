"""Existing native root delivery with isolated stores and 0.169/0.171 fixtures.

No host Codex socket, installed config, TTY or provider is touched by these tests.
"""

# Imported pytest fixtures.
# ruff: noqa: F811
import asyncio
import json
import socket
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_direct_delivery import delivery, job, new_message, settled  # noqa: F401
from test_visible_handoff import visible  # noqa: F401

from kirabridge.bridge_core.config import NativeCodexBinding
from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.platform_adapters.codex_host import CodexHost

ROOT = "11111111-1111-7111-8111-111111111111"
OTHER = "22222222-2222-7222-8222-222222222222"


@pytest.fixture
def binding(tmp_path):
    return NativeCodexBinding(
        thread_id=ROOT,
        session_id=ROOT,
        source="vscode",
        codex_home=str(tmp_path),
        host_executable="/opt/codex/bin/codex",
    )


class Protocol:
    """Captured protocol shapes, including steer.turnId."""

    def __init__(self, binding):
        self.binding = binding
        self.thread = {
            "id": ROOT,
            "sessionId": ROOT,
            "source": "vscode",
            "cwd": binding.codex_home,
            "parentThreadId": None,
            "attachedToThreadId": None,
            "canAcceptDirectInput": True,
            "status": {"type": "active", "activeFlags": []},
        }
        self.turn = "root-turn-1"
        self.generation = "host-generation-1"
        self.calls = []
        self.reads = 0
        self.read_hook = None
        self.on_input = None
        self.failure = None
        self.sockets = []
        self.reply_turns = []

    def response(self, request):
        method, params = request["method"], request.get("params", {})
        self.calls.append(request)
        if method == "initialize":
            return {
                "codexHome": self.binding.codex_home,
                "userAgent": f"codex-tui/{self.binding.protocol_version} fixture",
            }
        if method == "initialized":
            return None
        if method == "thread/read":
            self.reads += 1
            if self.read_hook:
                self.read_hook(self)
            assert params == {"threadId": ROOT, "includeTurns": False}
            return {"thread": self.thread}
        if method == "thread/turns/list":
            assert params["threadId"] == ROOT
            if params["limit"] == 8:
                assert params["itemsView"] == "full"
                return {"data": self.reply_turns}
            assert params["limit"] == 1
            active = self.thread["status"]["type"] == "active"
            return {"data": [{"id": self.turn, "status": "inProgress"}] if active else []}
        assert method in {"turn/steer", "turn/start"}
        assert params["threadId"] == ROOT
        if self.on_input:
            self.on_input(request)
        if self.failure == "disconnect":
            raise ConnectionError("after send; outcome unknown")
        if self.failure == "cancel":
            raise asyncio.CancelledError()
        if self.failure == "rejected":
            return {"error": {"code": -32600, "message": "turn changed"}}
        if method == "turn/steer":
            return {"turnId": OTHER if self.failure == "wrong_turn" else self.turn}
        return {"turn": {"id": "new-root-turn"}}

    @asynccontextmanager
    async def connector(self, *_args, **options):
        protocol = self

        class WS:
            async def send(self, payload):
                request = json.loads(payload)
                result = protocol.response(request)
                if "id" in request:
                    self.pending = json.dumps(
                        {"id": request["id"], **result}
                        if isinstance(result, dict) and "error" in result
                        else {"id": request["id"], "result": result}
                    )

            async def recv(self):
                return self.pending

        try:
            yield WS()
        finally:
            options["sock"].close()

    def socket_factory(self, binding):
        # socketpair has no listener and cannot reach a host service.
        left, right = socket.socketpair()
        right.close()
        self.sockets.append(left)
        return left, self.generation

    def host(self):
        return CodexHost(socket_factory=self.socket_factory, connector=self.connector)

    def inputs(self):
        return [r for r in self.calls if r["method"].startswith("turn/")]


async def test_two_concurrent_threads_route_only_assigned_root_without_any_tty(binding):
    p = Protocol(binding)
    host = p.host()
    prepared = await host.prepare(binding)
    attempts = []

    async def before_send(observation):
        attempts.append(observation)

    result = await host.deliver(binding, prepared, "original-id", "/literal body", before_send)
    assert p.inputs() == [
        {
            "id": 4,
            "method": "turn/steer",
            "params": {
                "threadId": ROOT,
                "expectedTurnId": "root-turn-1",
                "clientUserMessageId": "original-id",
                "input": [{"type": "text", "text": "/literal body", "text_elements": []}],
            },
        }
    ]
    assert len(attempts) == 1
    assert result["completion_scope"] == "native_input_delivery"
    assert result["native_input_attempted"] and not result["terminal_input_attempted"]
    assert not result["agent_confirmed"] and not result["request_reply_satisfied"]
    assert all(sock.fileno() == -1 for sock in p.sockets)


async def test_0171_protocol_prepares_only_the_assigned_active_turn(binding):
    binding.protocol_version = "0.171.0"
    p = Protocol(binding)
    prepared = await p.host().prepare(binding)
    assert prepared["operation"] == "turn/steer"
    assert prepared["expected_turn_id"] == p.turn
    assert [call["method"] for call in p.calls] == [
        "initialize",
        "initialized",
        "thread/read",
        "thread/turns/list",
    ]


async def test_0171_protocol_rejects_a_different_patch_user_agent(binding):
    binding.protocol_version = "0.171.0"
    p = Protocol(binding)
    response = p.response

    def changed_patch(request):
        result = response(request)
        if request["method"] == "initialize":
            result["userAgent"] = "codex-tui/0.171.1 fixture"
        return result

    p.response = changed_patch
    with pytest.raises(BridgeError) as exc:
        await p.host().prepare(binding)
    assert exc.value.code == "native_codex_host_unverified"
    assert [call["method"] for call in p.calls] == ["initialize"]


async def test_0172_protocol_prepares_assigned_active_turn_without_broadening_identity(binding):
    binding.protocol_version = "0.172.0"
    p = Protocol(binding)
    prepared = await p.host().prepare(binding)
    assert prepared["operation"] == "turn/steer"
    assert prepared["expected_turn_id"] == p.turn
    assert [call["method"] for call in p.calls] == [
        "initialize",
        "initialized",
        "thread/read",
        "thread/turns/list",
    ]


async def test_0172_protocol_rejects_a_different_assigned_root_without_input(binding):
    binding.protocol_version = "0.172.0"
    p = Protocol(binding)
    p.thread["id"] = OTHER
    with pytest.raises(BridgeError):
        await p.host().prepare(binding)
    assert not p.inputs()


@pytest.mark.parametrize(
    "user_agent",
    ["codex-tui/0.172.1 fixture", "kirabridge/0.172.0 fixture", "codex-tui/0.173.0 fixture"],
)
async def test_0172_protocol_rejects_unexpected_user_agent(binding, user_agent):
    binding.protocol_version = "0.172.0"
    p = Protocol(binding)
    response = p.response

    def changed_user_agent(request):
        result = response(request)
        if request["method"] == "initialize":
            result["userAgent"] = user_agent
        return result

    p.response = changed_user_agent
    with pytest.raises(BridgeError) as exc:
        await p.host().prepare(binding)
    assert exc.value.code == "native_codex_host_unverified"
    assert [call["method"] for call in p.calls] == ["initialize"]


@pytest.mark.parametrize(
    "patch",
    [
        {"id": OTHER},
        {"sessionId": OTHER},
        {"parentThreadId": ROOT},
        {"attachedToThreadId": ROOT},
        {"source": {"subAgent": {"threadId": ROOT}}},
        {"canAcceptDirectInput": False},
        {"status": {"type": "notLoaded"}},
        {"status": {"type": "active", "activeFlags": ["waitingOnApproval"]}},
    ],
)
async def test_sibling_child_unloaded_and_ambiguous_targets_never_receive_input(binding, patch):
    p = Protocol(binding)
    p.thread.update(patch)
    with pytest.raises(BridgeError):
        await p.host().prepare(binding)
    assert not p.inputs()


async def test_restart_refreshes_host_generation_without_changing_logical_root(binding):
    p, attempts = Protocol(binding), []
    host = p.host()
    prepared = await host.prepare(binding)
    p.generation = "new-process-new-socket-inode"

    async def before_send(observation):
        attempts.append(observation)

    result = await host.deliver(binding, prepared, "restart-original", "body", before_send)
    assert result["host_generation"] == p.generation
    assert attempts[0]["thread_id"] == ROOT and len(p.inputs()) == 1


async def test_expected_turn_race_before_attempt_never_falls_back_to_start_or_sibling(binding):
    p = Protocol(binding)
    host = p.host()
    prepared = await host.prepare(binding)
    p.turn = "different-turn"

    async def forbidden(_):
        pytest.fail("No attempt should be persisted")

    with pytest.raises(BridgeError, match="freshly verified") as exc:
        await host.deliver(binding, prepared, "race-original", "body", forbidden)
    assert exc.value.code == "native_codex_target_changed" and not p.inputs()


async def test_empty_active_turn_is_not_an_input_precondition(binding):
    p = Protocol(binding)
    p.turn = ""
    with pytest.raises(BridgeError) as exc:
        await p.host().prepare(binding)
    assert exc.value.code == "native_codex_target_not_ready" and not p.inputs()


@pytest.mark.parametrize("failure", ["disconnect", "cancel", "rejected", "wrong_turn"])
async def test_after_attempt_outcomes_are_unknown_without_input_retry(binding, failure):
    p = Protocol(binding)
    host = p.host()
    prepared = await host.prepare(binding)
    p.failure = failure
    attempts = []

    async def before_send(observation):
        attempts.append(observation)

    with pytest.raises(UncertainExecution) as exc:
        await host.deliver(binding, prepared, "unknown-original", "body", before_send)
    assert exc.value.code == "native_codex_delivery_unknown"
    assert len(attempts) == len(p.inputs()) == 1


async def test_idle_start_uses_the_same_assigned_root_with_no_model_or_effort_override(binding):
    p = Protocol(binding)
    p.thread["status"] = {"type": "idle"}
    host = p.host()
    prepared = await host.prepare(binding)

    async def before_send(_):
        pass

    await host.deliver(binding, prepared, "idle-original", "body", before_send)
    request = p.inputs()[0]
    assert request["method"] == "turn/start" and request["params"]["threadId"] == ROOT
    assert set(request["params"]) == {"threadId", "clientUserMessageId", "input"}


async def test_framed_unix_websocket_protocol_fixture(binding):
    from websockets.asyncio.server import unix_serve

    p = Protocol(binding)
    with tempfile.TemporaryDirectory(prefix="kb-native-") as folder:
        path = str(Path(folder) / "fixture.sock")

        async def handler(ws):
            async for payload in ws:
                request = json.loads(payload)
                response = p.response(request)
                if "id" in request:
                    await ws.send(json.dumps({"id": request["id"], "result": response}))

        def connection(_):
            raw = socket.socket(socket.AF_UNIX)
            raw.connect(path)
            raw.setblocking(False)
            return raw, "fixture-generation"

        async with unix_serve(handler, path):
            host = CodexHost(socket_factory=connection)
            assert (await host.prepare(binding))["thread_id"] == ROOT
    assert not p.inputs()


async def test_direct_rebind_bypasses_dead_tty_and_preserves_original_receipts(delivery, binding):
    bridge, transport, direct, connected, _ = delivery
    p = Protocol(binding)
    direct.codex_host = p.host()
    bridge.config.visible_handoffs.native_codex = binding
    before = bridge.config.visible_handoffs.bindings["codex"].model_copy(deep=True)
    sent = new_message(bridge, key="native-root", recipient="codex")
    assert direct.submit("chatgpt", sent["id"])
    await settled(direct)
    outcome = job(bridge, sent)
    original = bridge.messages.get("chatgpt", sent["id"])
    assert outcome["state"] == "unknown"
    assert outcome["error"] == "native_codex_steer_reply_unverified"
    assert outcome["evidence"]["completion_scope"] == "native_input_delivery"
    assert original["processing_route"] == "existing_native_codex_root"
    assert outcome["completion_scope"] == "native_input_delivery"
    assert original["receipt"] is original["delivered"] is original["acknowledged"] is None
    assert bridge.config.visible_handoffs.bindings["codex"] == before
    assert not transport["calls"] and not connected
    assert len(p.inputs()) == 1
    assert not direct.submit("chatgpt", sent["id"])
    new_message(bridge, key="native-root", recipient="codex")
    await settled(direct)
    assert len(p.inputs()) == 1


async def test_direct_cold_host_retries_only_prepare_for_the_original(
    delivery, binding, monkeypatch
):
    bridge, transport, direct, _, _ = delivery
    protocol = Protocol(binding)
    host = protocol.host()
    prepare = host.prepare
    checked = []

    async def cold_then_ready(candidate):
        checked.append(candidate.thread_id)
        if len(checked) == 1:
            raise BridgeError("native_codex_host_unavailable", "Host is starting")
        return await prepare(candidate)

    monkeypatch.setattr(host, "prepare", cold_then_ready)
    monkeypatch.setattr(direct, "native_host_prepare_delays", (0,))
    direct.codex_host = host
    bridge.config.visible_handoffs.native_codex = binding
    sent = new_message(bridge, key="direct-cold-host", recipient="codex")
    assert direct.submit("chatgpt", sent["id"])
    await settled(direct)

    assert checked == [ROOT, ROOT]
    assert len(protocol.inputs()) == 1 and not transport["calls"]
    assert job(bridge, sent)["evidence"]["completion_scope"] == "native_input_delivery"
    assert bridge.messages.get("chatgpt", sent["id"])["acknowledged"] is None
    assert not direct.submit("chatgpt", sent["id"])


async def test_direct_cold_host_watchdog_does_not_fall_back_to_terminal(
    delivery, binding, monkeypatch
):
    bridge, transport, direct, _, _ = delivery
    protocol = Protocol(binding)
    host = protocol.host()

    async def unavailable(_):
        raise BridgeError("native_codex_host_unavailable", "Host is starting")

    monkeypatch.setattr(host, "prepare", unavailable)
    monkeypatch.setattr(direct, "delivery_timeout", 0.03)
    direct.codex_host = host
    bridge.config.visible_handoffs.native_codex = binding
    sent = new_message(bridge, key="direct-cold-host-timeout", recipient="codex")
    assert direct.submit("chatgpt", sent["id"])
    await settled(direct)

    result = job(bridge, sent)
    assert result["state"] == "failed" and result["error"] == "delivery_timeout"
    assert result["evidence"]["terminal_input_attempted"] is False
    assert not protocol.inputs() and not transport["calls"]


async def test_unverified_native_host_fails_without_fallback_or_ack(
    delivery, binding, monkeypatch
):
    bridge, transport, direct, connected, _ = delivery
    attempts = []

    async def reject_unverified(_binding):
        attempts.append("prepare")
        raise BridgeError("native_codex_host_unverified", "Identity did not verify")

    monkeypatch.setattr(direct.codex_host, "prepare", reject_unverified)
    bridge.config.visible_handoffs.native_codex = binding
    sent = new_message(bridge, key="native-unverified-no-fallback", recipient="codex")
    assert direct.submit("chatgpt", sent["id"])
    await settled(direct)

    result = job(bridge, sent)
    stored = bridge.messages.get("chatgpt", sent["id"])
    assert result["state"] == "failed"
    assert result["error"] == "native_codex_host_unverified"
    assert result["evidence"]["phase"] == "native_direct_delivery"
    assert result["evidence"]["native_input_attempted"] is False
    assert result["evidence"]["terminal_input_attempted"] is False
    assert result["evidence"]["automatic_retry"] is False
    assert stored["delivered"] is stored["receipt"] is stored["acknowledged"] is None
    assert not bridge.store.db.execute(
        "SELECT 1 FROM message_events WHERE message_id=? AND kind='message.acknowledged'",
        (sent["id"],),
    ).fetchone()
    assert attempts == ["prepare"]
    assert not transport["calls"] and not connected
    assert not direct.submit("chatgpt", sent["id"])


async def test_role_routed_delivery_refuses_a_coordinator_change_before_any_input(
    delivery, binding
):
    from kirabridge.message_manager import MessageSend

    bridge, transport, direct, connected, _ = delivery
    protocol = Protocol(binding)
    direct.codex_host = protocol.host()
    bridge.config.visible_handoffs.native_codex = binding
    current = {
        "principal": "codex",
        "session": {"principal": "codex", "session_id": ROOT},
        "team_id": "team-one",
        "revision": 4,
    }
    bridge.messages.coordinator_resolver = lambda: current
    sent = bridge.messages.send(
        "chatgpt",
        MessageSend(
            recipient="coordinator",
            conversation_id="coordinator-route-change",
            idempotency_key="coordinator-route-change",
            body="This must not reach a replaced coordinator",
            kind="work",
            dispatch=True,
        ),
    )
    assert sent["recipient"] == "codex"
    current.update(
        {
            "principal": "grok",
            "session": {"principal": "grok", "session_id": "grok-new"},
            "team_id": "team-one",
            "revision": 5,
        }
    )

    assert direct.submit("chatgpt", sent["id"])
    await settled(direct)
    result = job(bridge, sent)
    stored = bridge.messages.get("chatgpt", sent["id"])
    assert result["state"] == "failed" and result["error"] == "coordinator_route_changed"
    assert result["evidence"]["terminal_input_attempted"] is False
    assert stored["delivered"] is stored["receipt"] is stored["acknowledged"] is None
    assert not protocol.inputs() and not transport["calls"] and not connected


async def test_role_handoff_during_native_revalidation_is_refused_at_send_boundary(
    delivery, binding
):
    """A role change during awaited host observation must be caught before RPC input."""
    from kirabridge.message_manager import MessageSend

    bridge, transport, direct, connected, _ = delivery
    protocol = Protocol(binding)
    direct.codex_host = protocol.host()
    bridge.config.visible_handoffs.native_codex = binding
    current = {
        "principal": "codex",
        "session": {"principal": "codex", "session_id": ROOT},
        "team_id": "team-one",
        "revision": 4,
    }
    bridge.messages.coordinator_resolver = lambda: current
    sent = bridge.messages.send(
        "chatgpt",
        MessageSend(
            recipient="coordinator",
            conversation_id="coordinator-final-boundary-race",
            idempotency_key="coordinator-final-boundary-race",
            body="Must stop if the role changes during final host observation",
            kind="work",
            dispatch=True,
        ),
    )

    def handoff_during_delivery_observation(host):
        if host.reads == 2:
            current.update(
                principal="grok",
                session={"principal": "grok", "session_id": "grok-new"},
                revision=5,
            )

    protocol.read_hook = handoff_during_delivery_observation
    assert direct.submit("chatgpt", sent["id"])
    await settled(direct)

    result = job(bridge, sent)
    stored = bridge.messages.get("chatgpt", sent["id"])
    assert result["state"] == "failed"
    assert result["error"] == "coordinator_route_changed"
    assert result["evidence"]["terminal_input_attempted"] is False
    assert stored["delivered"] is stored["receipt"] is stored["acknowledged"] is None
    assert not protocol.inputs() and not transport["calls"] and not connected


@pytest.mark.parametrize(
    "change",
    [
        "binding",
        "receiver",
        "grant",
        "hold",
        "withdrawal",
        "interim_disabled",
    ],
)
async def test_late_scope_changes_prevent_native_io(delivery, binding, change):
    bridge, transport, direct, _, _ = delivery
    p = Protocol(binding)
    direct.codex_host = p.host()
    bridge.config.visible_handoffs.native_codex = binding
    sent = new_message(bridge, key="native-late-" + change, recipient="codex")

    def late(protocol):
        if protocol.reads != 2:
            return
        if change == "binding":
            bridge.config.visible_handoffs.native_codex = binding.model_copy(
                update={"thread_id": OTHER}
            )
        elif change == "receiver":
            bridge.config.messaging.receivers["codex"].cwd = "/changed"
        elif change == "grant":
            bridge.config.principals["chatgpt"].agents.remove("codex")
        elif change == "hold":
            bridge.queues._place_hold("chatgpt", "messages", sent["id"], "test-owner")
        elif change == "interim_disabled":
            bridge.config.visible_handoffs.allow_interim_messages = False
        else:
            bridge.store.db.execute(
                "INSERT INTO queue_withdrawals(queue_id,item_id,actor,created,reason_sha256) "
                "VALUES('messages',?,'chatgpt',1,'test-owner')",
                (sent["id"],),
            )

    p.read_hook = late
    assert direct.submit("chatgpt", sent["id"])
    await settled(direct)
    assert not p.inputs() and not transport["calls"]
    assert job(bridge, sent)["state"] == "failed"


async def test_native_unknown_survives_duplicate_and_new_driver(delivery, binding):
    bridge, transport, direct, _, _ = delivery
    p = Protocol(binding)
    direct.codex_host = p.host()
    bridge.config.visible_handoffs.native_codex = binding
    p.failure = "disconnect"
    sent = new_message(bridge, key="native-unknown", recipient="codex")
    assert direct.submit("chatgpt", sent["id"])
    await settled(direct)
    result = job(bridge, sent)
    assert result["state"] == "unknown" and result["evidence"]["native_input_attempted"]
    assert result["evidence"]["terminal_input_attempted"] is False
    from kirabridge.message_manager.direct import DirectDelivery

    replacement = DirectDelivery(bridge.message_receiver)
    replacement.accepting = True
    assert not replacement.submit("chatgpt", sent["id"])
    new_message(bridge, key="native-unknown", recipient="codex")
    await settled(direct)
    assert len(p.inputs()) == 1 and not transport["calls"]


async def test_restart_preserves_original_native_attempt_and_never_replays(delivery, binding):
    bridge, transport, direct, _, _ = delivery
    bridge.config.visible_handoffs.native_codex = binding
    p = Protocol(binding)
    direct.codex_host = p.host()
    sent = new_message(bridge, key="native-crash-after-ledger", recipient="codex")
    claimed = bridge.message_receiver._claim(sent["id"], direct=True, interim=True, native=True)
    evidence = {
        "session_scope": "existing_native_codex_root",
        "run_id": claimed[1],
        "native_input_attempted": True,
        "terminal_input_attempted": False,
        "thread_id": ROOT,
        "automatic_retry": False,
    }
    bridge.store.db.execute(
        "UPDATE message_jobs SET started=1,evidence=? WHERE message_id=?",
        (json.dumps(evidence), sent["id"]),
    )
    bridge.messages._event(sent["id"], "message.native_submitting", "chatgpt", evidence)
    await bridge.message_receiver.start()
    try:
        await asyncio.sleep(0)
        outcome = job(bridge, sent)
        assert outcome["state"] == "unknown"
        assert outcome["evidence"]["native_input_attempted"] is True
        assert outcome["evidence"]["terminal_input_attempted"] is False
        assert outcome["evidence"]["last_observation"] == evidence
        assert not direct.submit("chatgpt", sent["id"])
        assert not p.calls and not transport["calls"]
    finally:
        await bridge.message_receiver.stop()


async def test_shutdown_during_reply_observation_preserves_accepted_turn(delivery, binding):
    bridge, transport, direct, _, _ = delivery
    p = Protocol(binding)
    p.thread["status"] = {"type": "idle"}
    bridge.config.visible_handoffs.native_codex = binding
    direct.codex_host = p.host()
    sent = new_message(bridge, key="native-shutdown-with-unfinished-reply", recipient="codex")
    assert sent["request_reply"] is True
    assert direct.submit("chatgpt", sent["id"])
    await direct.wait_delivery(sent["id"])
    assert job(bridge, sent)["state"] == "running"
    assert job(bridge, sent)["evidence"]["turn_id"] == "new-root-turn"
    await direct.stop()
    result = job(bridge, sent)
    assert result["state"] == "running" and result["error"] is None
    assert result["evidence"]["turn_id"] == "new-root-turn"
    bridge.config.messaging.receivers["codex"].timeout = 0.05
    await bridge.message_receiver.start()
    try:
        await settled(direct)
        assert job(bridge, sent)["state"] == "unknown"
        assert job(bridge, sent)["error"] == "native_codex_reply_timeout"
        assert job(bridge, sent)["evidence"]["turn_id"] == "new-root-turn"
        assert not direct.submit("chatgpt", sent["id"])
        assert len(p.inputs()) == 1 and not transport["calls"]
    finally:
        await bridge.message_receiver.stop()


async def test_explicit_interim_handle_keeps_its_own_target_when_native_root_is_configured(
    delivery, binding, monkeypatch
):
    bridge, transport, direct, _, _ = delivery
    bridge.config.visible_handoffs.native_codex = binding
    p = Protocol(binding)
    direct.codex_host = p.host()
    named = bridge.config.visible_handoffs.bindings["codex"]
    monkeypatch.setattr(
        bridge.messages,
        "interim_target",
        lambda _: SimpleNamespace(
            pane_id=named.pane_id,
            expected_pid=named.expected_pid,
            expected_agent_pid=named.agent_pid,
        ),
    )

    async def process(_pool, message, _run_id, **options):
        assert options["delivery_binding"].pane_id == named.pane_id
        assert options["interim"].expected_agent_pid == named.agent_pid
        bridge.message_receiver._finish(message["id"], "completed", {})

    monkeypatch.setattr(bridge.message_receiver, "_process", process)
    sent = new_message(bridge, key="explicit-interim-owned", recipient="codex")
    direct.submit("chatgpt", sent["id"])
    await settled(direct)
    assert job(bridge, sent)["state"] == "completed"
    assert not p.calls and not transport["calls"]


async def test_disabled_interim_messages_prevent_native_busy_admission(delivery, binding):
    bridge, transport, direct, _, _ = delivery
    bridge.config.visible_handoffs.native_codex = binding
    bridge.config.visible_handoffs.allow_interim_messages = False
    p = Protocol(binding)
    direct.codex_host = p.host()
    sent = new_message(bridge, key="native-busy-disabled", recipient="codex")
    direct.submit("chatgpt", sent["id"])
    await settled(direct)
    outcome = job(bridge, sent)
    assert outcome["state"] == "failed" and outcome["error"] == "interim_messages_disabled"
    assert not p.inputs() and not transport["calls"]
