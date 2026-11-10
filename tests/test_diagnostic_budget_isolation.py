"""A full optional diagnostic budget never disables ordinary durable receipts."""

import json

from conftest import request, submit

from kirabridge.audit_manager import verify
from kirabridge.diagnostics import AuditObserver, task_report
from kirabridge.message_manager import MessageSend


async def test_full_diagnostic_budget_keeps_task_message_and_audit_evidence(bridge, config):
    config.diagnostics.max_records = config.diagnostics.max_events_per_day = 10
    config.principals["local"].message_peers = ["other"]
    config.principals["other"].message_peers = ["local"]
    for policy in config.principals.values():
        policy.capabilities += ["message.send", "message.read", "message.ack"]
        policy.approval_mode = "automatic"
    observer = AuditObserver(config, "local", bridge.runtime, bridge.store)
    for _ in range(10):
        assert observer("connection", {"phase": "connect.started"})
    assert observer("connection", {"phase": "call.started"}) and observer.archived == 1
    assert observer.status()["recording"] == "budget_exhausted"

    value = request("file.list", {"path": config.principals["local"].roots[0]})
    submit(bridge, value)
    async with bridge:
        task = await bridge.tasks.wait("local", value.task_id, 5)
        assert task["state"] == "completed" and task["result"]["entries"] == []
        states = [
            row["state"]
            for row in bridge.store.db.execute(
                "SELECT state FROM events WHERE task_id=? ORDER BY seq", (value.task_id,)
            )
        ]
        assert states[-1] == "completed" and "running" in states

        sent = bridge.messages.send(
            "local",
            MessageSend(
                recipient="other",
                conversation_id="diagnostic-boundary",
                idempotency_key="diagnostic-boundary",
                kind="note",
                dispatch=False,
                body="Ordinary durable receipt after diagnostic saturation",
            ),
        )
        incoming = bridge.messages.receive("other")["messages"]
        assert len(incoming) == 1 and incoming[0]["id"] == sent["id"]
        acknowledged = bridge.messages.ack("other", sent["id"], incoming[0]["receipt"])
        assert acknowledged["acknowledged"] is not None
        assert (
            bridge.store.db.execute(
                "SELECT count(*) FROM message_events WHERE message_id=?", (sent["id"],)
            ).fetchone()[0]
            >= 3
        )

        with bridge.store.transaction():
            bridge.store.audit("review.boundary", "local", value.task_id, {"ordinary": True})
        assert (
            bridge.store.db.execute(
                "SELECT count(*) FROM audit WHERE kind LIKE 'diagnostic.%'"
            ).fetchone()[0]
            == 10
        )
        task_audit = bridge.store.db.execute(
            "SELECT metadata FROM audit WHERE kind='task.transition' AND task_id=?",
            (value.task_id,),
        ).fetchall()
        assert {json.loads(row["metadata"])["to"] for row in task_audit} >= {"running", "completed"}
        assert (
            bridge.store.db.execute(
                "SELECT count(*) FROM audit WHERE kind='review.boundary'"
            ).fetchone()[0]
            == 1
        )
        assert verify(bridge.store)["valid"]
        health = bridge.health("local")
        assert health["dispatcher_active"] is True
        assert health["diagnostics_storage"]["recording"] == "budget_exhausted"
        assert (
            task_report(bridge, "local", value.task_id)["storage"]["recording"]
            == "budget_exhausted"
        )
