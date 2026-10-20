import json
from types import SimpleNamespace

import pytest
from conftest import request
from starlette.requests import Request

from kirabridge.audit_manager import AuditReader
from kirabridge.bridge_core.models import BridgeError, State
from kirabridge.control_center import ControlCenter
from kirabridge.message_manager import MessageSend
from kirabridge.operator_queries import OperatorQueries


def test_operator_service_uses_owners_without_a_bridge_or_database():
    seen = []
    tasks = SimpleNamespace(
        operator_work_count=lambda: 2,
        operator_pending=lambda: [{"id": "pending"}],
        operator_snapshot_at=lambda identifier, at: (
            seen.append((identifier, at)) or {"state": "running", "result": None}
        ),
    )
    messages = SimpleNamespace(
        operator_work_count=lambda: 3,
        operator_protocol_snapshot=lambda identifier, at: {
            "body": identifier,
            "acknowledged": None,
        },
    )
    teams = SimpleNamespace(operator_work_count=lambda: 4)
    audit = SimpleNamespace(
        protocol_page=lambda after, before: [
            {
                "seq": 9,
                "at": 123.0,
                "kind": "task.progress",
                "principal": "local",
                "task_id": "owned",
                "metadata": {"message_id": "incoming"},
            }
        ],
        recent_connection_checks=lambda: [{"mode": "voice"}],
    )
    service = OperatorQueries(tasks, messages, teams, audit)
    assert service.busy() == {"tasks": 2, "message_jobs": 3, "team_work": 4}
    assert service.pending() == [{"id": "pending"}]
    assert service.recent_connection_checks() == [{"mode": "voice"}]
    page = service.protocol(after=8)
    assert page["last_seq"] == 9 and seen == [("owned", 123.0)]
    assert page["entries"][0]["task"]["result"] is None
    assert page["entries"][0]["message"]["body"] == "incoming"


def test_task_snapshot_does_not_attach_a_future_task_to_an_old_event(bridge, config):
    bridge.prepare("local", request(arguments={"path": config.principals["local"].roots[0]}))
    task = bridge.store.get("task-1")
    assert bridge.store.operator_snapshot_at("task-1", task["created"] - 1) is None


@pytest.mark.parametrize("final_state", [State.COMPLETED, State.FAILED])
def test_historical_running_task_hides_later_finished_timestamp(bridge, config, final_state):
    value = request(arguments={"path": config.principals["local"].roots[0]})
    bridge.prepare("local", value)
    bridge.tasks.approve(value.task_id)
    bridge.store.claim("history", 30)
    bridge.store.transition(value.task_id, State.RUNNING, {"started": True}, owner="history")
    at = bridge.store.get(value.task_id)["started"]
    bridge.store.transition(
        value.task_id,
        final_state,
        {"finished": True},
        result={"text": "later result"},
        error={"code": "later_error"} if final_state == State.FAILED else None,
        owner="history",
    )
    snapshot = bridge.store.operator_snapshot_at(value.task_id, at)
    assert snapshot["state"] == "running"
    assert snapshot["finished"] is None and snapshot["result"] is None and snapshot["error"] is None


def test_message_snapshot_does_not_project_later_delivery_or_ack_backwards(bridge, config):
    for name, peer in [("local", "other"), ("other", "local")]:
        config.principals[name].capabilities += ["message.send", "message.read", "message.ack"]
        config.principals[name].message_peers = [peer]
        config.principals[name].approval_mode = "automatic"
    message = bridge.messages.send(
        "local",
        MessageSend(
            recipient="other",
            conversation_id="history",
            idempotency_key="once",
            body="actual message",
            dispatch=False,
            request_reply=False,
        ),
    )
    delivered = bridge.messages.receive("other")["messages"][0]
    acknowledged = bridge.messages.ack("other", message["id"], delivered["receipt"])
    early = bridge.messages.operator_protocol_snapshot(message["id"], message["created"])
    assert (
        early["body"] == "actual message"
        and early["delivered"] is None
        and early["acknowledged"] is None
    )
    late = bridge.messages.operator_protocol_snapshot(message["id"], acknowledged["acknowledged"])
    assert late["delivered"] == delivered["delivered"] and late["acknowledged"] is not None
    assert bridge.messages.operator_protocol_snapshot(message["id"], message["created"] - 1) is None


async def test_http_protocol_only_needs_the_operator_query_port():
    control = object.__new__(ControlCenter)
    seen = []
    control.authenticate = lambda request: seen.append("authenticated")
    control.queries = SimpleNamespace(
        protocol=lambda after, before: {"after": after, "before": before}
    )
    response = await control.protocol(
        Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/control/protocol",
                "query_string": b"after=7&before=2",
            }
        )
    )
    assert json.loads(response.body) == {"after": 7, "before": 2}
    assert seen == ["authenticated"]


async def test_unauthenticated_surface_never_calls_operator_queries():
    control = object.__new__(ControlCenter)

    def deny(request):
        raise BridgeError("unauthorized", "Local operator required")

    def forbidden(*args):
        pytest.fail("Operator queries must remain behind local authentication")

    control.authenticate = deny
    control.queries = SimpleNamespace(protocol=forbidden)
    with pytest.raises(BridgeError) as error:
        await control.protocol(
            Request(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/api/control/protocol",
                    "query_string": b"",
                }
            )
        )
    assert error.value.code == "unauthorized"


def test_operator_reads_do_not_claim_or_mutate_work(bridge, config):
    bridge.prepare("local", request(arguments={"path": config.principals["local"].roots[0]}))
    queries = OperatorQueries(
        bridge.store, bridge.messages, bridge.teams, AuditReader(bridge.store)
    )
    before = bridge.store.db.total_changes
    queries.busy()
    assert queries.pending()[0]["id"] == "task-1"
    queries.protocol()
    queries.recent_connection_checks()
    assert bridge.store.db.total_changes == before
    assert bridge.store.get("task-1")["state"] == "created"
