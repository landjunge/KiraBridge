from types import SimpleNamespace

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
