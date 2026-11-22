"""Authenticated team-message pings into an already-active native Codex turn."""

import asyncio

import pytest
from test_mcp import http_bridge as live_http_fixture

from kirabridge.bridge_core.config import NativeCodexBinding, TeamWorkerConfig
from kirabridge.bridge_core.models import UncertainExecution, digest
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
async def test_idle_codex_keeps_ping_pending_without_start_or_ack(
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
                "AND kind='team.message_native_ping_idle_pending'",
                (result["id"],),
            ).fetchone():
                break
            await asyncio.sleep(0.02)
        assert host.deliveries == []
        assert bridge.teams._message("team-codex", result["id"])["acknowledged"] is None
        outcome = bridge.store.db.execute(
            "SELECT metadata FROM team_events WHERE team_id='team-codex' AND object_id=? "
            "AND kind='team.message_native_ping_idle_pending'",
            (result["id"],),
        ).fetchone()
        assert outcome is not None and '"native_input_attempted":false' in outcome["metadata"]
    finally:
        await bridge.team_dispatcher.stop()
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
