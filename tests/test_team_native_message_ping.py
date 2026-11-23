"""Authenticated team-message pings into an already-active native Codex turn."""

import asyncio
import json
import time

import pytest
from test_mcp import http_bridge as live_http_fixture

from kirabridge.bridge_core.config import NativeCodexBinding, TeamWorkerConfig
from kirabridge.bridge_core.models import BridgeError, UncertainExecution, digest
from kirabridge.mcp_gateway.client import MCPClientPool, Peer

http_bridge = live_http_fixture


def test_native_ping_scan_uses_partial_event_indexes(bridge):
    sql = (
        "SELECT e.team_id,e.object_id,m.sender,m.recipient FROM team_events e "
        "JOIN team_messages m ON m.team_id=e.team_id AND m.id=e.object_id "
        "WHERE e.kind='team.message_native_ping_queued' AND NOT EXISTS ("
        "SELECT 1 FROM team_events done WHERE done.team_id=e.team_id "
        "AND done.object_id=e.object_id AND done.kind IN ("
        "'team.message_native_ping_idle_pending','team.message_native_ping_denied',"
        "'team.message_native_ping_failed','team.message_native_ping_submitting',"
        "'team.message_native_ping_submitted','team.message_native_ping_unknown')) "
        "ORDER BY e.seq LIMIT ?"
    )
    plan = " ".join(
        row["detail"]
        for row in bridge.store.db.execute("EXPLAIN QUERY PLAN " + sql, (1,)).fetchall()
    )
    assert "team_native_ping_queue" in plan
    assert "team_native_ping_outcomes" in plan
    indexes = {
        row["name"]: row["sql"]
        for row in bridge.store.db.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='index' "
            "AND name IN ('team_native_ping_outcomes','team_native_ping_defers',"
            "'team_native_ping_exhausted')"
        ).fetchall()
    }
    assert "team.message_native_ping_unknown'" in indexes["team_native_ping_outcomes"]
    assert "pre_attempt_exhausted" in indexes["team_native_ping_exhausted"]


class FakeNativeHost:
    def __init__(self, binding, *, operation="turn/steer", uncertain=False):
        self.binding = binding
        self.operation = operation
        self.uncertain = uncertain
        self.deliveries = []
        self.prepare_calls = 0

    async def prepare(self, binding):
        self.prepare_calls += 1
        return {
            "binding_sha256": digest(binding.model_dump()),
            "operation": self.operation,
            "expected_turn_id": "live-turn-1" if self.operation == "turn/steer" else None,
        }

    async def deliver(self, binding, prepared, message_id, body, before_send):
        await before_send({"expected_turn_id": prepared["expected_turn_id"]})
        self.deliveries.append((message_id, body, prepared["operation"]))
        if self.uncertain:
            raise UncertainExecution(
                "native_codex_delivery_unknown", "Reconcile the original native Codex attempt"
            )
        return {"turn_id": prepared["expected_turn_id"], "native_input_attempted": True}


class RacingNativeHost(FakeNativeHost):
    def __init__(self, binding):
        super().__init__(binding)
        self.prepared = 0
        self.both_prepared = asyncio.Event()

    async def prepare(self, binding):
        result = await super().prepare(binding)
        self.prepared += 1
        if self.prepared == 2:
            self.both_prepared.set()
        await self.both_prepared.wait()
        return result


class PreAttemptUnavailableHost(FakeNativeHost):
    async def deliver(self, binding, prepared, message_id, body, before_send):
        raise BridgeError("native_codex_host_unavailable", "synthetic host unavailable")


async def _setup(http_bridge, config, monkeypatch, tmp_path):
    bridge, endpoint = http_bridge
    token = "codex-team-test-" + "x" * 40
    monkeypatch.setenv("TEAM_TEST_CODEX", token)
    codex = config.principals["local"].model_copy(deep=True)
    codex.token_env = "TEAM_TEST_CODEX"
    codex.capabilities = list(
        set(codex.capabilities) | {"team.read", "team.write", "team.manage", "message.read"}
    )
    codex.approval_mode = "automatic"
    codex.message_peers = ["local", "other"]
    config.principals["codex"] = codex
    for name in ("local", "other"):
        policy = config.principals[name]
        policy.capabilities = list(
            set(policy.capabilities)
            | {
                "team.read",
                "team.write",
                "team.manage",
                "agent.execute",
                "message.send",
                "session.inspect",
                "session.input",
            }
        )
        policy.approval_mode = "automatic"
        policy.agents = ["codex"]
        policy.message_peers = ["codex"]
    config.team.enabled = True
    config.team.workers = {name: TeamWorkerConfig() for name in ("local", "other", "codex")}
    config.visible_handoffs.native_codex = NativeCodexBinding(
        thread_id="11111111-1111-7111-8111-111111111111",
        session_id="11111111-1111-7111-8111-111111111111",
        source="vscode",
        codex_home=str(tmp_path),
        host_executable="/opt/codex/bin/codex",
    )
    clients = MCPClientPool()
    await clients.__aenter__()
    for name, auth in (
        ("local", "local-test-" + "a" * 40),
        ("other", "other-test-" + "b" * 40),
        ("codex", token),
    ):
        await clients.connect(Peer(name, url=endpoint, token=auth))
    for team_id, coordinator in (("team-codex", "codex"), ("team-other", "other")):
        created = await clients.call(
            "local",
            "team_create",
            {
                "request": {
                    "team_id": team_id,
                    "name": team_id,
                    "coordinator": coordinator,
                    "members": {"local": "worker", "other": "worker", "codex": "worker"},
                    "idempotency_key": "create-" + team_id,
                }
            },
        )
        assert created.structuredContent["id"] == team_id
    return bridge, endpoint, clients


async def _send_codex_ping(clients, *, key="pre-attempt-ping"):
    result = await clients.call(
        "local",
        "team_message_send",
        {
            "request": {
                "team_id": "team-codex",
                "recipient": "codex",
                "body": "Retry this original inbox item only before any native input.",
                "kind": "question",
                "idempotency_key": key,
            }
        },
    )
    return result.structuredContent


def _record_pre_attempt_host_failure(bridge, message_id, **overrides):
    metadata = {
        "error_code": "native_codex_host_unavailable",
        "error_type": "BridgeError",
        "stage": "host_deliver",
        "native_input_attempted": False,
        "automatic_retry": False,
    }
    metadata.update(overrides)
    bridge.teams._event(
        "team-codex", "local", "team.message_native_ping_failed", message_id, **metadata
    )


def _make_latest_pre_attempt_retry_due(bridge, message_id):
    row = bridge.store.db.execute(
        "SELECT seq,metadata FROM team_events WHERE team_id='team-codex' AND object_id=? "
        "AND kind='team.message_native_ping_pre_attempt_deferred' ORDER BY seq DESC LIMIT 1",
        (message_id,),
    ).fetchone()
    assert row is not None
    metadata = json.loads(row["metadata"])
    metadata["retry_after"] = time.time() - 1
    bridge.store.db.execute(
        "UPDATE team_events SET metadata=? WHERE seq=?",
        (json.dumps(metadata, sort_keys=True, separators=(",", ":")), row["seq"]),
    )


@pytest.mark.asyncio
async def test_pre_attempt_host_unavailable_defers_then_retries_same_ping_id(
    http_bridge, config, monkeypatch, tmp_path
):
    bridge, _, clients = await _setup(http_bridge, config, monkeypatch, tmp_path)
    unavailable = PreAttemptUnavailableHost(config.visible_handoffs.native_codex)
    bridge.team_dispatcher.codex_host = unavailable
    try:
        message = await _send_codex_ping(clients)
        message_id = message["id"]
        item = bridge.teams.pending_native_pings(limit=1)[0]

        await bridge.team_dispatcher._run_native_ping(item)

        assert unavailable.prepare_calls == 1 and unavailable.deliveries == []
        assert bridge.teams.pending_native_pings(limit=1) == []
        event_kinds = [
            row["kind"]
            for row in bridge.store.db.execute(
                "SELECT kind FROM team_events WHERE team_id='team-codex' AND object_id=?",
                (message_id,),
            ).fetchall()
        ]
        assert event_kinds == [
            "team.message_queued",
            "team.message_native_ping_queued",
            "team.message_native_ping_pre_attempt_deferred",
        ]
        deferred = bridge.store.db.execute(
            "SELECT metadata FROM team_events WHERE team_id='team-codex' AND object_id=? "
            "AND kind='team.message_native_ping_pre_attempt_deferred'",
            (message_id,),
        ).fetchone()
        state = json.loads(deferred["metadata"])
        assert state["native_input_attempted"] is False
        assert state["retry_scheduled"] is True and state["retry_count"] == 1
        assert state["delay_seconds"] == 2 and state["retry_after"] > time.time()

        _make_latest_pre_attempt_retry_due(bridge, message_id)
        from kirabridge.team_manager.dispatcher import TeamDispatcher

        restarted = TeamDispatcher(bridge)
        recovered = FakeNativeHost(config.visible_handoffs.native_codex)
        restarted.codex_host = recovered
        item = bridge.teams.pending_native_pings(limit=1)[0]
        assert item["object_id"] == message_id
        await restarted._run_native_ping(item)

        assert len(recovered.deliveries) == 1 and recovered.deliveries[0][0] == message_id
        assert bridge.store.db.execute(
            "SELECT count(*) FROM team_events WHERE team_id='team-codex' AND object_id=? "
            "AND kind='team.message_native_ping_queued'",
            (message_id,),
        ).fetchone()[0] == 1
        assert bridge.store.db.execute(
            "SELECT count(*) FROM team_events WHERE team_id='team-codex' AND object_id=? "
            "AND kind='team.message_native_ping_submitting'",
            (message_id,),
        ).fetchone()[0] == 1
        assert bridge.teams.pending_native_pings() == []
        assert bridge.teams._message("team-codex", message_id)["acknowledged"] is None
    finally:
        await clients.__aexit__(None, None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["new_root", "expired"])
async def test_deferred_native_ping_does_not_follow_new_root_or_exceed_worker_timeout(
    http_bridge, config, monkeypatch, tmp_path, change
):
    from kirabridge.team_manager.dispatcher import TeamDispatcher

    bridge, _, clients = await _setup(http_bridge, config, monkeypatch, tmp_path)
    bridge.team_dispatcher.codex_host = PreAttemptUnavailableHost(
        config.visible_handoffs.native_codex
    )
    try:
        message = await _send_codex_ping(clients, key="defer-scope-" + change)
        original = bridge.teams.pending_native_pings(limit=1)[0]
        await bridge.team_dispatcher._run_native_ping(original)
        _make_latest_pre_attempt_retry_due(bridge, message["id"])
        if change == "new_root":
            replacement = "22222222-2222-7222-8222-222222222222"
            config.visible_handoffs.native_codex = config.visible_handoffs.native_codex.model_copy(
                update={"thread_id": replacement, "session_id": replacement}
            )
        else:
            bridge.store.db.execute(
                "UPDATE team_messages SET created=? WHERE id=?",
                (time.time() - config.team.workers["codex"].timeout - 1, message["id"]),
            )
        restarted = TeamDispatcher(bridge)
        host = FakeNativeHost(config.visible_handoffs.native_codex)
        restarted.codex_host = host
        await restarted._run_native_ping(bridge.teams.pending_native_pings(limit=1)[0])

        assert host.prepare_calls == 0 and not host.deliveries
        denied = bridge.store.db.execute(
            "SELECT metadata FROM team_events WHERE object_id=? "
            "AND kind='team.message_native_ping_denied'",
            (message["id"],),
        ).fetchone()
        assert json.loads(denied["metadata"])["error_code"] == (
            "native_codex_scope_changed" if change == "new_root" else "native_codex_ping_expired"
        )
        assert bridge.teams.pending_native_pings() == []
    finally:
        await clients.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_native_ping_restart_does_not_reissue_durable_submitting(
    http_bridge, config, monkeypatch, tmp_path
):
    from kirabridge.team_manager.dispatcher import TeamDispatcher

    bridge, _, clients = await _setup(http_bridge, config, monkeypatch, tmp_path)
    try:
        message = await _send_codex_ping(clients, key="crash-after-submitting")
        original = bridge.teams.pending_native_pings(limit=1)[0]
        bridge.teams._event(
            "team-codex", "local", "team.message_native_ping_submitting", message["id"],
            native_input_attempted=True,
        )
        restarted = TeamDispatcher(bridge)
        host = FakeNativeHost(config.visible_handoffs.native_codex)
        restarted.codex_host = host
        assert bridge.teams.pending_native_pings() == []
        await restarted._run_native_ping(original)
        assert host.prepare_calls == 0 and not host.deliveries
        assert bridge.teams._message("team-codex", message["id"])["acknowledged"] is None
    finally:
        await clients.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_restart_recovers_only_exact_durable_pre_attempt_host_failure(
    http_bridge, config, monkeypatch, tmp_path
):
    bridge, _, clients = await _setup(http_bridge, config, monkeypatch, tmp_path)
    try:
        message = await _send_codex_ping(clients, key="historical-pre-attempt")
        message_id = message["id"]
        _record_pre_attempt_host_failure(bridge, message_id)

        # A new dispatcher represents the process restart; the same persisted
        # queue item is rediscovered from the original event and exact ID.
        from kirabridge.team_manager.dispatcher import TeamDispatcher

        restarted = TeamDispatcher(bridge)
        recovered = FakeNativeHost(config.visible_handoffs.native_codex)
        restarted.codex_host = recovered
        assert bridge.teams.pending_native_pings(limit=1) == []
        assert recovered.deliveries == [] and recovered.prepare_calls == 0
        events = bridge.store.db.execute(
            "SELECT kind FROM team_events WHERE team_id='team-codex' AND object_id=?",
            (message_id,),
        ).fetchall()
        kinds = [row["kind"] for row in events]
        assert kinds.count("team.message_native_ping_queued") == 1
        assert kinds.count("team.message_native_ping_failed") == 1
        assert "team.message_native_ping_submitting" not in kinds
        assert "team.message_native_ping_submitted" not in kinds
    finally:
        await clients.__aexit__(None, None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "metadata"),
    [
        ("attempted", {"native_input_attempted": True}),
        ("wrong_code", {"error_code": "native_codex_rpc_rejected"}),
        ("wrong_stage", {"stage": "before_send"}),
        ("retry_flag", {"automatic_retry": True}),
        ("wrong_delay", {"delay_seconds": 99}),
        ("malformed", None),
        ("json_null", "json_null"),
        ("missing_fields", "missing_fields"),
    ],
)
async def test_malformed_or_incomplete_defer_is_never_retryable(
    http_bridge, config, monkeypatch, tmp_path, case, metadata
):
    bridge, _, clients = await _setup(http_bridge, config, monkeypatch, tmp_path)
    try:
        message = await _send_codex_ping(clients, key="bad-metadata-" + case)
        assert bridge.teams.defer_native_ping_before_attempt(
            "team-codex", "local", message["id"], "host_deliver"
        )
        row = bridge.store.db.execute(
            "SELECT seq,metadata FROM team_events WHERE team_id='team-codex' AND object_id=? "
            "AND kind='team.message_native_ping_pre_attempt_deferred'",
            (message["id"],),
        ).fetchone()
        value = json.loads(row["metadata"])
        if metadata is None:
            bridge.store.db.execute(
                "UPDATE team_events SET metadata='not-json' WHERE seq=?", (row["seq"],)
            )
        elif metadata == "json_null":
            bridge.store.db.execute(
                "UPDATE team_events SET metadata='null' WHERE seq=?", (row["seq"],)
            )
        elif metadata == "missing_fields":
            bridge.store.db.execute(
                "UPDATE team_events SET metadata='{}' WHERE seq=?", (row["seq"],)
            )
        else:
            value.update(metadata)
            bridge.store.db.execute(
                "UPDATE team_events SET metadata=? WHERE seq=?",
                (json.dumps(value, sort_keys=True, separators=(",", ":")), row["seq"]),
            )
        assert bridge.teams.pending_native_pings(limit=1) == []
    finally:
        await clients.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_pre_attempt_retries_are_bounded_across_restarts(
    http_bridge, config, monkeypatch, tmp_path
):
    bridge, _, clients = await _setup(http_bridge, config, monkeypatch, tmp_path)
    message = await _send_codex_ping(clients, key="bounded-pre-attempt")
    message_id = message["id"]
    host = PreAttemptUnavailableHost(config.visible_handoffs.native_codex)
    bridge.team_dispatcher.codex_host = host
    try:
        from kirabridge.team_manager.dispatcher import TeamDispatcher

        dispatcher = bridge.team_dispatcher
        for retry_count in range(1, 5):
            pending = bridge.teams.pending_native_pings(limit=1)
            assert len(pending) == 1 and pending[0]["object_id"] == message_id
            await dispatcher._run_native_ping(pending[0])
            if retry_count < 4:
                defer = bridge.store.db.execute(
                    "SELECT metadata FROM team_events WHERE team_id='team-codex' AND object_id=? "
                    "AND kind='team.message_native_ping_pre_attempt_deferred' "
                    "ORDER BY seq DESC LIMIT 1",
                    (message_id,),
                ).fetchone()
                state = json.loads(defer["metadata"])
                assert state["retry_count"] == retry_count
                assert state["delay_seconds"] == min(2**retry_count, 8)
                _make_latest_pre_attempt_retry_due(bridge, message_id)
                # Recreate the dispatcher to prove the bounded state is durable.
                dispatcher = TeamDispatcher(bridge)
                dispatcher.codex_host = host
            else:
                assert bridge.teams.pending_native_pings() == []

        assert host.prepare_calls == 4 and host.deliveries == []
        events = bridge.store.db.execute(
            "SELECT kind,metadata FROM team_events WHERE team_id='team-codex' "
            "AND object_id=? ORDER BY seq",
            (message_id,),
        ).fetchall()
        deferred = [
            row
            for row in events
            if row["kind"] == "team.message_native_ping_pre_attempt_deferred"
        ]
        exhausted = [
            row
            for row in events
            if row["kind"] == "team.message_native_ping_pre_attempt_exhausted"
        ]
        assert len(deferred) == 3 and len(exhausted) == 1
        assert json.loads(exhausted[0]["metadata"])["retry_count"] == 4
        assert not any(
            row["kind"]
            in {"team.message_native_ping_submitting", "team.message_native_ping_submitted"}
            for row in events
        )
    finally:
        await clients.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_invalid_old_ping_does_not_starve_later_queued_ping(
    http_bridge, config, monkeypatch, tmp_path
):
    bridge, _, clients = await _setup(http_bridge, config, monkeypatch, tmp_path)
    try:
        old = await _send_codex_ping(clients, key="old-terminal")
        _record_pre_attempt_host_failure(bridge, old["id"])
        later = await _send_codex_ping(clients, key="later-eligible")

        pending = bridge.teams.pending_native_pings(limit=1)
        assert len(pending) == 1
        assert pending[0]["object_id"] == later["id"]
    finally:
        await clients.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_malformed_defer_does_not_spin_or_starve_later_queued_ping(
    http_bridge, config, monkeypatch, tmp_path
):
    bridge, _, clients = await _setup(http_bridge, config, monkeypatch, tmp_path)
    try:
        malformed = await _send_codex_ping(clients, key="malformed-defer-first")
        assert bridge.teams.defer_native_ping_before_attempt(
            "team-codex", "local", malformed["id"], "host_deliver"
        )
        defer = bridge.store.db.execute(
            "SELECT seq,metadata FROM team_events WHERE team_id='team-codex' AND object_id=? "
            "AND kind='team.message_native_ping_pre_attempt_deferred'",
            (malformed["id"],),
        ).fetchone()
        state = json.loads(defer["metadata"])
        state["delay_seconds"] = 99
        state["retry_after"] = time.time() - 1
        bridge.store.db.execute(
            "UPDATE team_events SET metadata=? WHERE seq=?",
            (json.dumps(state, sort_keys=True, separators=(",", ":")), defer["seq"]),
        )
        later = await _send_codex_ping(clients, key="after-malformed-defer")

        pending = bridge.teams.pending_native_pings(limit=1)
        assert len(pending) == 1 and pending[0]["object_id"] == later["id"]
        assert bridge.teams._native_ping_pre_attempt_defer_state(
            json.dumps(state)
        ) is None
    finally:
        await clients.__aexit__(None, None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_state", ["acknowledged", "held", "authorization_revoked"])
async def test_scheduled_pre_attempt_ping_still_respects_terminal_message_guards(
    http_bridge, config, monkeypatch, tmp_path, terminal_state
):
    bridge, _, clients = await _setup(http_bridge, config, monkeypatch, tmp_path)
    try:
        message = await _send_codex_ping(clients, key="terminal-" + terminal_state)
        message_id = message["id"]
        assert bridge.teams.defer_native_ping_before_attempt(
            "team-codex", "local", message_id, "host_deliver"
        )
        host = FakeNativeHost(config.visible_handoffs.native_codex)
        bridge.team_dispatcher.codex_host = host

        if terminal_state == "acknowledged":
            bridge.teams.ack("codex", "team-codex", message_id)
            assert bridge.teams.pending_native_pings() == []
        else:
            if terminal_state == "held":
                bridge.queues._place_hold(
                    "local", "team-messages", message_id, "recoverable-ping-test-hold"
                )
            else:
                config.principals["local"].capabilities.remove("session.input")
            _make_latest_pre_attempt_retry_due(bridge, message_id)
            item = bridge.teams.pending_native_pings(limit=1)[0]
            await bridge.team_dispatcher._run_native_ping(item)
            assert bridge.store.db.execute(
                "SELECT 1 FROM team_events WHERE team_id='team-codex' AND object_id=? "
                "AND kind='team.message_native_ping_denied'",
                (message_id,),
            ).fetchone()
            assert bridge.teams.pending_native_pings() == []

        assert host.prepare_calls == 0 and host.deliveries == []
        acknowledged = bridge.teams._message("team-codex", message_id)["acknowledged"]
        assert (acknowledged is not None) is (terminal_state == "acknowledged")
    finally:
        await clients.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_http_team_send_steers_only_exact_active_coordinator_and_never_replays(
    http_bridge, config, monkeypatch, tmp_path
):
    bridge, endpoint, clients = await _setup(http_bridge, config, monkeypatch, tmp_path)
    assert bridge.config is config and bridge.teams.config is config
    assert bridge.config.visible_handoffs.native_codex is not None
    assert bridge.config.team.enabled
    host = FakeNativeHost(config.visible_handoffs.native_codex, uncertain=True)
    bridge.team_dispatcher.codex_host = host

    async def unexpected_budget_call(agent):
        raise AssertionError(f"busy steering must not call the budget gate for {agent}")

    monkeypatch.setattr(bridge.agents, "budget_note", unexpected_budget_call)
    await bridge.team_dispatcher.start()
    try:
        request = {
            "team_id": "team-codex",
            "recipient": "codex",
            "body": "Please inspect this exact team message.",
            "kind": "question",
            "idempotency_key": "ping-one",
        }
        first = (
            await clients.call("local", "team_message_send", {"request": request})
        ).structuredContent
        replay = (
            await clients.call("local", "team_message_send", {"request": request})
        ).structuredContent
        assert first["id"] == replay["id"]

        other_team = (
            await clients.call(
                "local",
                "team_message_send",
                {
                    "request": {
                        **request,
                        "team_id": "team-other",
                        "idempotency_key": "not-coordinator-ping",
                    }
                },
            )
        ).structuredContent
        assert other_team["id"] != first["id"]
        for _ in range(100):
            if bridge.store.db.execute(
                "SELECT 1 FROM team_events WHERE team_id='team-codex' AND object_id=? "
                "AND kind='team.message_native_ping_unknown'",
                (first["id"],),
            ).fetchone():
                break
            await asyncio.sleep(0.02)

        assert len(host.deliveries) == 1
        delivered_id, native_body, operation = host.deliveries[0]
        assert delivered_id == first["id"] and operation == "turn/steer"
        assert "team_id: team-codex" in native_body
        assert f"message_id: {first['id']}" in native_body
        assert "sender: local" in native_body
        assert native_body.count(request["body"]) == 1
        assert "team_id: team-other" not in native_body
        assert bridge.teams.pending_native_pings() == []
        assert (
            bridge.store.db.execute(
                "SELECT count(*) FROM team_events WHERE team_id='team-codex' AND object_id=? "
                "AND kind='team.message_native_ping_queued'",
                (first["id"],),
            ).fetchone()[0]
            == 1
        )
        assert (
            bridge.store.db.execute(
                "SELECT count(*) FROM team_events WHERE team_id='team-other' "
                "AND object_id=? AND kind='team.message_native_ping_queued'",
                (other_team["id"],),
            ).fetchone()[0]
            == 0
        )
        assert bridge.teams._message("team-codex", first["id"])["acknowledged"] is None
        assert (
            bridge.store.db.execute(
                "SELECT count(*) FROM team_events WHERE team_id='team-codex' AND object_id=? "
                "AND kind='team.message_acknowledged'",
                (first["id"],),
            ).fetchone()[0]
            == 0
        )

        # The actual authenticated recipient ACKs the original ID, and replies
        # remain bound to that same team. Native acceptance itself was no ACK.
        ack = await clients.call(
            "codex", "team_message_ack", {"team_id": "team-codex", "message_id": first["id"]}
        )
        assert ack.structuredContent["acknowledged"] is not None
        wrong_scope = await clients.call(
            "codex",
            "team_message_send",
            {
                "request": {
                    "team_id": "team-other",
                    "recipient": "local",
                    "body": "cross-team reply must fail",
                    "kind": "answer",
                    "reply_to": first["id"],
                    "idempotency_key": "cross-team-reply",
                }
            },
        )
        assert wrong_scope.structuredContent["error"]["code"] == "not_found"
        reply = await clients.call(
            "codex",
            "team_message_send",
            {
                "request": {
                    "team_id": "team-codex",
                    "recipient": "local",
                    "body": "Processed the original team message.",
                    "kind": "answer",
                    "reply_to": first["id"],
                    "idempotency_key": "same-team-reply",
                }
            },
        )
        assert reply.structuredContent["reply_to"] == first["id"]
    finally:
        await bridge.team_dispatcher.stop()
        await clients.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_idle_codex_starts_exact_root_for_ping_without_ack(
    http_bridge, config, monkeypatch, tmp_path
):
    bridge, endpoint, clients = await _setup(http_bridge, config, monkeypatch, tmp_path)
    host = FakeNativeHost(config.visible_handoffs.native_codex, operation="turn/start")
    bridge.team_dispatcher.codex_host = host
    try:
        result = (
            await clients.call(
                "local",
                "team_message_send",
                {
                    "request": {
                        "team_id": "team-codex",
                        "recipient": "codex",
                        "body": "Remain pending while coordinator is idle.",
                        "kind": "question",
                        "idempotency_key": "idle-ping",
                    }
                },
            )
        ).structuredContent
        work = (
            await clients.call(
                "local",
                "team_work_create",
                {
                    "request": {
                        "team_id": "team-codex",
                        "assignee": "codex",
                        "title": "read exact inbox item",
                        "body": "Use existing work only after the inbox item is read.",
                        "idempotency_key": "idle-work",
                    }
                },
            )
        ).structuredContent
        await clients.connect(Peer("daemon", url=endpoint, token="codex-team-test-" + "x" * 40))
        prompt = await bridge.team_dispatcher._prompt(clients, work)
        assert result["id"] in prompt
        assert bridge.teams._message("team-codex", result["id"])["acknowledged"] is None

        await bridge.team_dispatcher.start()
        for _ in range(100):
            if bridge.store.db.execute(
                "SELECT 1 FROM team_events WHERE team_id='team-codex' AND object_id=? "
                "AND kind='team.message_native_ping_submitted'",
                (result["id"],),
            ).fetchone():
                break
            await asyncio.sleep(0.02)
        assert len(host.deliveries) == 1
        assert host.deliveries[0][0] == result["id"]
        assert host.deliveries[0][2] == "turn/start"
        assert bridge.teams._message("team-codex", result["id"])["acknowledged"] is None
        outcome = bridge.store.db.execute(
            "SELECT metadata FROM team_events WHERE team_id='team-codex' AND object_id=? "
            "AND kind='team.message_native_ping_submitted'",
            (result["id"],),
        ).fetchone()
        assert outcome is not None and '"operation":"turn/start"' in outcome["metadata"]
        assert '"native_input_attempted":true' in outcome["metadata"]
        # The test fixture has no pinned TollGate, so the shared model-work
        # budget gate fails open and records that fact in the durable outcome.
        assert '"tollgate_unavailable":true' in outcome["metadata"]
        assert '"tollgate_decision":"unavailable"' in outcome["metadata"]
        assert '"reason"' not in outcome["metadata"] and '"limit_source"' not in outcome["metadata"]
        assert bridge.store.db.execute(
            "SELECT 1 FROM team_events WHERE team_id='team-codex' AND object_id=? "
            "AND kind='team.message_native_ping_idle_pending'",
            (result["id"],),
        ).fetchone() is None
    finally:
        await bridge.team_dispatcher.stop()
        await clients.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_native_ping_steer_respects_disabled_interim_messages(
    http_bridge, config, monkeypatch, tmp_path
):
    bridge, _, clients = await _setup(http_bridge, config, monkeypatch, tmp_path)
    bridge.config.visible_handoffs.allow_interim_messages = False
    host = FakeNativeHost(config.visible_handoffs.native_codex, operation="turn/steer")
    bridge.team_dispatcher.codex_host = host
    try:
        result = (
            await clients.call(
                "local",
                "team_message_send",
                {
                    "request": {
                        "team_id": "team-codex",
                        "recipient": "codex",
                        "body": "Do not interrupt the active coordinator turn.",
                        "kind": "question",
                        "idempotency_key": "interim-disabled",
                    }
                },
            )
        ).structuredContent
        queued = bridge.teams.pending_native_pings(limit=1)[0]
        await bridge.team_dispatcher._run_native_ping(queued)

        assert host.prepare_calls == 1 and host.deliveries == []
        assert bridge.teams._message("team-codex", result["id"])["acknowledged"] is None
        outcome = bridge.store.db.execute(
            "SELECT metadata FROM team_events WHERE team_id='team-codex' AND object_id=? "
            "AND kind='team.message_native_ping_denied'",
            (result["id"],),
        ).fetchone()
        assert outcome is not None
        assert '"error_code":"interim_messages_disabled"' in outcome["metadata"]
    finally:
        await clients.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_idle_native_ping_user_budget_denial_prevents_start(
    http_bridge, config, monkeypatch, tmp_path
):
    bridge, _, clients = await _setup(http_bridge, config, monkeypatch, tmp_path)
    host = FakeNativeHost(config.visible_handoffs.native_codex, operation="turn/start")
    bridge.team_dispatcher.codex_host = host
    budget_calls = []

    async def denied_budget(agent):
        budget_calls.append(agent)
        raise BridgeError("tollgate_budget_reached", "user-set budget reached")

    monkeypatch.setattr(bridge.agents, "budget_note", denied_budget)
    try:
        result = (
            await clients.call(
                "local",
                "team_message_send",
                {
                    "request": {
                        "team_id": "team-codex",
                        "recipient": "codex",
                        "body": "The user-set budget must gate a new idle turn.",
                        "kind": "question",
                        "idempotency_key": "idle-budget-denied",
                    }
                },
            )
        ).structuredContent
        queued = bridge.teams.pending_native_pings(limit=1)[0]
        await bridge.team_dispatcher._run_native_ping(queued)

        assert budget_calls == ["codex"]
        assert host.prepare_calls == 1 and host.deliveries == []
        assert bridge.teams._message("team-codex", result["id"])["acknowledged"] is None
        denied = bridge.store.db.execute(
            "SELECT metadata FROM team_events WHERE team_id='team-codex' AND object_id=? "
            "AND kind='team.message_native_ping_denied'",
            (result["id"],),
        ).fetchone()
        assert denied is not None and '"error_code":"tollgate_budget_reached"' in denied["metadata"]
        assert bridge.store.db.execute(
            "SELECT 1 FROM team_events WHERE team_id='team-codex' AND object_id=? "
            "AND kind='team.message_native_ping_submitting'",
            (result["id"],),
        ).fetchone() is None
    finally:
        await clients.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_idle_native_ping_unknown_is_attempted_once_without_replay(
    http_bridge, config, monkeypatch, tmp_path
):
    bridge, _, clients = await _setup(http_bridge, config, monkeypatch, tmp_path)
    host = FakeNativeHost(
        config.visible_handoffs.native_codex, operation="turn/start", uncertain=True
    )
    bridge.team_dispatcher.codex_host = host
    try:
        result = (
            await clients.call(
                "local",
                "team_message_send",
                {
                    "request": {
                        "team_id": "team-codex",
                        "recipient": "codex",
                        "body": "An uncertain native start must never be replayed.",
                        "kind": "question",
                        "idempotency_key": "idle-unknown-once",
                    }
                },
            )
        ).structuredContent
        queued = bridge.teams.pending_native_pings(limit=1)[0]
        await bridge.team_dispatcher._run_native_ping(queued)
        await bridge.team_dispatcher._run_native_ping(queued)

        assert host.prepare_calls == 1
        assert len(host.deliveries) == 1 and host.deliveries[0][2] == "turn/start"
        assert bridge.teams._message("team-codex", result["id"])["acknowledged"] is None
        assert bridge.store.db.execute(
            "SELECT count(*) FROM team_events WHERE team_id='team-codex' AND object_id=? "
            "AND kind='team.message_native_ping_submitting'",
            (result["id"],),
        ).fetchone()[0] == 1
        unknown = bridge.store.db.execute(
            "SELECT metadata FROM team_events WHERE team_id='team-codex' AND object_id=? "
            "AND kind='team.message_native_ping_unknown'",
            (result["id"],),
        ).fetchone()
        assert unknown is not None and '"automatic_retry":false' in unknown["metadata"]
    finally:
        await clients.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_competing_lanes_cannot_claim_or_finalize_each_others_ping(
    http_bridge, config, monkeypatch, tmp_path
):
    bridge, _, clients = await _setup(http_bridge, config, monkeypatch, tmp_path)
    host = RacingNativeHost(config.visible_handoffs.native_codex)
    bridge.team_dispatcher.codex_host = host
    try:
        result = (
            await clients.call(
                "local",
                "team_message_send",
                {
                    "request": {
                        "team_id": "team-codex",
                        "recipient": "codex",
                        "body": "Only one lane may submit this exact message.",
                        "kind": "question",
                        "idempotency_key": "race-ping",
                    }
                },
            )
        ).structuredContent
        queued = bridge.teams.pending_native_pings(limit=1)[0]
        await asyncio.gather(
            bridge.team_dispatcher._run_native_ping(queued),
            bridge.team_dispatcher._run_native_ping(queued),
        )

        assert len(host.deliveries) == 1
        events = bridge.store.db.execute(
            "SELECT kind FROM team_events WHERE team_id='team-codex' AND object_id=?",
            (result["id"],),
        ).fetchall()
        kinds = [row["kind"] for row in events]
        assert kinds.count("team.message_native_ping_submitting") == 1
        assert kinds.count("team.message_native_ping_submitted") == 1
        assert "team.message_native_ping_unknown" not in kinds
        assert bridge.teams._message("team-codex", result["id"])["acknowledged"] is None
    finally:
        await clients.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_held_team_message_never_reaches_native_host(
    http_bridge, config, monkeypatch, tmp_path
):
    bridge, _, clients = await _setup(http_bridge, config, monkeypatch, tmp_path)
    host = FakeNativeHost(config.visible_handoffs.native_codex)
    bridge.team_dispatcher.codex_host = host
    try:
        result = (
            await clients.call(
                "local",
                "team_message_send",
                {
                    "request": {
                        "team_id": "team-codex",
                        "recipient": "codex",
                        "body": "This held item must not be submitted.",
                        "kind": "question",
                        "idempotency_key": "held-ping",
                    }
                },
            )
        ).structuredContent
        bridge.queues._place_hold("local", "team-messages", result["id"], "isolated_test_hold")
        queued = bridge.teams.pending_native_pings(limit=1)[0]
        await bridge.team_dispatcher._run_native_ping(queued)

        assert host.prepare_calls == 0 and host.deliveries == []
        assert bridge.teams._message("team-codex", result["id"])["acknowledged"] is None
        assert bridge.store.db.execute(
            "SELECT 1 FROM team_events WHERE team_id='team-codex' AND object_id=? "
            "AND kind='team.message_native_ping_denied'",
            (result["id"],),
        ).fetchone()
    finally:
        await clients.__aexit__(None, None, None)
