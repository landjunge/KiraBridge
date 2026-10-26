from types import SimpleNamespace

import pytest

from kirabridge.audit_manager import AuditReader
from kirabridge.operator_queries import OperatorQueries
from kirabridge.task_manager.store import Store


def processing_result_fixture(store):
    # A valid durable in-progress team result, without launching any worker.
    with store.transaction():
        store.db.execute("INSERT INTO teams VALUES('review','Review','local','local',1,1)")
        store.db.execute(
            "INSERT INTO team_work(id,team_id,assigned_by,assignee,title,body,"
            "root_id,depth,state,created) "
            "VALUES('work','review','local','local','Result','Test','work',0,'processing_result',1)"
        )


def queries(bridge):
    return OperatorQueries(
        bridge.store,
        bridge.messages,
        bridge.teams,
        AuditReader(bridge.store),
        bridge.visible_handoffs,
    )


def test_maintenance_queries_use_each_domain_owner_and_the_given_transaction():
    seen = []
    context = object()

    def owner(name, count):
        def query(*, active_only, context):
            seen.append((name, active_only, context))
            return count

        return SimpleNamespace(activation_work_count=query)

    service = OperatorQueries(
        owner("task", 1), owner("message", 2), owner("team", 3), None, owner("handoff", 4)
    )
    assert service.maintenance_counts(active_only=True, context=context) == {
        "tasks": 1,
        "message_jobs": 2,
        "team_work": 3,
        "visible_handoffs": 4,
    }
    assert seen == [(name, True, context) for name in ("task", "message", "team", "handoff")]


def test_processing_team_result_counts_as_work_during_activation_and_recovery(bridge):
    processing_result_fixture(bridge.store)
    for active_only in (False, True):
        assert queries(bridge).maintenance_counts(active_only=active_only)["team_work"] == 1
    bridge.store.db.execute("UPDATE team_work SET state='completed',result='Actual result'")
    assert queries(bridge).maintenance_counts()["team_work"] == 0


def test_owner_queries_observe_the_callers_shared_uncommitted_transaction(bridge):
    processing_result_fixture(bridge.store)
    bridge.store.db.execute("UPDATE team_work SET state='completed'")
    other = Store(bridge.config.state_path / "bridge.sqlite3")
    service = queries(bridge)
    try:
        with other.transaction():
            other.db.execute("UPDATE team_work SET state='processing_result'")
            # An independent connection sees the previous committed state.
            assert service.maintenance_counts()["team_work"] == 0
            # Domain-owned SQL participates in the actual caller's transaction.
            assert service.maintenance_counts(context=other)["team_work"] == 1
        assert service.maintenance_counts()["team_work"] == 1
    finally:
        other.close()


def authenticated_delivery(bridge):
    from kirabridge.message_manager import MessageSend

    for name, peer in (("local", "other"), ("other", "local")):
        policy = bridge.config.principals[name]
        policy.message_peers = [peer]
        policy.approval_mode = "automatic"
        policy.capabilities += ["message.send", "message.read", "message.ack"]
    original = bridge.messages.send(
        "local",
        MessageSend(
            recipient="other",
            conversation_id="activation-proof",
            body="original",
            idempotency_key="activation-original",
            dispatch=False,
        ),
    )
    delivered = bridge.messages.receive("other")["messages"][0]
    return original["id"], delivered["receipt"]


def test_activation_does_not_count_authenticated_final_reply_as_pending_handoff(bridge):
    from kirabridge.message_manager import MessageSend

    message_id, receipt = authenticated_delivery(bridge)
    bridge.messages.ack("other", message_id, receipt)
    bridge.messages.send(
        "other",
        MessageSend(
            recipient="local",
            conversation_id="activation-proof",
            reply_to=message_id,
            body="final result",
            kind="result",
            idempotency_key="activation-result",
            dispatch=False,
        ),
    )
    bridge.store.db.execute(
        "INSERT INTO visible_handoffs VALUES('proved','local','other','hash','{}',?,"
        "'confirmed',1,1,'{}')",
        (message_id,),
    )
    before = tuple(bridge.store.db.execute("SELECT * FROM visible_handoffs").fetchone())
    for active_only in (False, True):
        assert bridge.visible_handoffs.activation_work_count(active_only=active_only) == 0
    assert tuple(bridge.store.db.execute("SELECT * FROM visible_handoffs").fetchone()) == before


def test_activation_queued_ack_is_not_pending_delivery_but_running_stays_active(bridge):
    message_id, receipt = authenticated_delivery(bridge)
    bridge.store.db.execute(
        "INSERT INTO message_jobs(message_id,state) VALUES(?,'queued')",
        (message_id,),
    )
    assert bridge.messages.activation_work_count() == 1
    bridge.messages.ack("other", message_id, receipt)
    assert bridge.messages.activation_work_count() == 0
    assert bridge.store.db.execute("SELECT state FROM message_jobs").fetchone()[0] == "queued"
    bridge.store.db.execute("UPDATE message_jobs SET state='running'")
    for active_only in (False, True):
        assert bridge.messages.activation_work_count(active_only=active_only) == 1


@pytest.mark.parametrize("state", ["sent", "confirmed", "inserting", "submitting", "return_sent"])
@pytest.mark.parametrize("proof", ["ack-only", "reply-only", "ack-and-nonfinal"])
def test_activation_never_infers_finished_execution_from_incomplete_evidence(bridge, state, proof):
    from kirabridge.message_manager import MessageSend

    message_id, receipt = authenticated_delivery(bridge)
    if proof != "reply-only":
        bridge.messages.ack("other", message_id, receipt)
    if proof != "ack-only":
        bridge.messages.send(
            "other",
            MessageSend(
                recipient="local",
                conversation_id="activation-proof",
                reply_to=message_id,
                body="observed",
                kind="question" if proof == "ack-and-nonfinal" else "result",
                idempotency_key="activation-observation",
                dispatch=False,
            ),
        )
    bridge.store.db.execute(
        "INSERT INTO visible_handoffs VALUES('unproved','local','other','hash','{}',?,?,1,1,'{}')",
        (message_id, state),
    )
    for active_only in (False, True):
        assert bridge.visible_handoffs.activation_work_count(active_only=active_only) == 1
