"""Only background health noise is coalesced; task and failure evidence remains."""

import asyncio
import copy
import json

import pytest
from mcp.types import CallToolResult, Tool

from kirabridge.audit_manager import verify
from kirabridge.bridge_core.models import BridgeError
from kirabridge.diagnostics import AuditObserver
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.proxy import DaemonConnection


class HealthSession:
    def __init__(self):
        self.data = {
            "name": "KiraBridge",
            "version": "0.8.0rc17",
            "dispatcher_active": True,
            "discovery": {"instance_id": "instance-one", "revision": "revision-one"},
        }
        self.error = None
        self.is_error = False
        self.calls = 0

    async def call_tool(self, tool, arguments):
        self.calls += 1
        if self.error:
            raise self.error
        return CallToolResult(
            content=[],
            structuredContent=self.data,
            isError=self.is_error,
        )


async def test_stable_background_health_preserves_diagnostic_budget(bridge, config):
    config.diagnostics.max_events_per_day = 10
    observer = AuditObserver(config, "local", bridge.runtime, bridge.store)
    pool = MCPClientPool(observer=observer)
    pool.sessions["daemon"] = HealthSession()
    pool.connection_ids["daemon"] = "connection-one"
    for _ in range(8):
        await pool.call("daemon", "bridge_health", {}, routine_health=True)
    report = observer.status()
    assert report["recording"] == "available", report
    # Successful routine polls go to the overflow archive, not the hot budget.
    assert report["today"] == 0 and observer.dropped == 0 and observer.archived == 2
    assert verify(bridge.store)["valid"]


def observed_pool():
    records = []
    pool = MCPClientPool(observer=lambda kind, metadata, **_: records.append(metadata))
    session = HealthSession()
    pool.sessions["daemon"] = session
    pool.connection_ids["daemon"] = "connection-one"
    return pool, session, records


async def test_poll_transitions_and_new_connections_are_not_coalesced():
    pool, session, records = observed_pool()
    await pool.call("daemon", "bridge_health", {}, routine_health=True)
    session.data["volatile_count"] = 123
    await pool.call("daemon", "bridge_health", {}, routine_health=True)
    assert len(records) == 2
    session.data["version"] = "0.8.0rc18"
    await pool.call("daemon", "bridge_health", {}, routine_health=True)
    session.data["discovery"]["instance_id"] = "instance-two"
    await pool.call("daemon", "bridge_health", {}, routine_health=True)
    session.data["discovery"]["revision"] = "new-grant-or-session-revision"
    await pool.call("daemon", "bridge_health", {}, routine_health=True)
    pool.connection_ids["daemon"] = "connection-two"
    await pool.call("daemon", "bridge_health", {}, routine_health=True)
    assert [entry["phase"] for entry in records] == ["call.started", "call.returned"] * 5
    assert session.calls == 6


@pytest.mark.parametrize("reply", ["is_error", "error_field", "inactive", "malformed"])
async def test_failed_health_replies_and_recovery_retain_diagnostics(reply):
    pool, session, records = observed_pool()
    original = copy.deepcopy(session.data)
    await pool.call("daemon", "bridge_health", {}, routine_health=True)
    if reply == "is_error":
        session.is_error = True
    elif reply == "error_field":
        session.data["error"] = {"message": "PRIVATE_REPLY_VALUE"}
    elif reply == "inactive":
        session.data["dispatcher_active"] = False
    else:
        session.data.pop("discovery")
    await pool.call("daemon", "bridge_health", {}, routine_health=True)
    session.is_error = False
    session.data = original
    await pool.call("daemon", "bridge_health", {}, routine_health=True)
    await pool.call("daemon", "bridge_health", {}, routine_health=True)
    assert [entry["phase"] for entry in records] == ["call.started", "call.returned"] * 3
    assert "PRIVATE_REPLY_VALUE" not in json.dumps(records)
    assert session.calls == 4


@pytest.mark.parametrize("error", [ValueError, TimeoutError, asyncio.CancelledError])
async def test_poll_exceptions_are_recorded_once_without_replay(error):
    pool, session, records = observed_pool()
    await pool.call("daemon", "bridge_health", {}, routine_health=True)
    session.error = error("PRIVATE_EXCEPTION_VALUE")
    with pytest.raises(asyncio.CancelledError if error is asyncio.CancelledError else BridgeError):
        await pool.call("daemon", "bridge_health", {}, routine_health=True)
    assert session.calls == 2
    assert records[-2]["phase"] == "call.started"
    assert records[-1]["phase"] == (
        "call.interrupted" if error is asyncio.CancelledError else "call.outcome_unknown"
    )
    assert "PRIVATE_EXCEPTION_VALUE" not in json.dumps(records)
    session.error = None
    await pool.call("daemon", "bridge_health", {}, routine_health=True)
    assert len(records) == 6


@pytest.mark.parametrize(
    "tool,args,routine",
    [
        ("bridge_health", {}, False),
        ("bridge_health", {"observe_terminals": True}, True),
        ("task_get", {"task_id": "original-task"}, True),
        ("completion_ack", {"notice_id": "original-notice", "receipt": "PRIVATE_RECEIPT"}, True),
    ],
)
async def test_explicit_health_and_evidence_calls_keep_every_observation(tool, args, routine):
    pool, session, records = observed_pool()
    for _ in range(3):
        await pool.call("daemon", tool, args, routine_health=routine)
    assert len(records) == 6 and session.calls == 3
    assert "PRIVATE_RECEIPT" not in json.dumps(records)


async def test_proxy_forwards_only_explicit_background_poll_context(monkeypatch):
    pool, _, records = observed_pool()
    listings = []
    schema_revision = "one"

    async def tools(_):
        listings.append(schema_revision)
        return [
            Tool(
                name="bridge_health",
                description=schema_revision,
                inputSchema={"type": "object"},
            )
        ]

    monkeypatch.setattr(pool, "list_tools", tools)
    connection = DaemonConnection(pool, Peer("daemon"))
    await connection.call_tool("bridge_health", {}, routine_health=True)
    await connection.call_tool("bridge_health", {}, routine_health=True)
    assert len(records) == 2
    await connection.call_tool("bridge_health", {})
    assert len(records) == 4
    assert listings == ["one"] * 3
    assert connection.change_generation == 0
    schema_revision = "two"
    await connection.call_tool("bridge_health", {}, routine_health=True)
    assert listings == ["one"] * 3 + ["two"]
    assert connection.change_generation == 1


async def test_explicit_health_failure_does_not_hide_background_recovery():
    pool, session, records = observed_pool()
    await pool.call("daemon", "bridge_health", {}, routine_health=True)
    session.is_error = True
    await pool.call("daemon", "bridge_health", {})
    session.is_error = False
    await pool.call("daemon", "bridge_health", {}, routine_health=True)
    assert len(records) == 6
