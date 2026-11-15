"""Read-only workflow projection; never infer process cleanup or release a lease."""

import json
import sqlite3
from types import SimpleNamespace

import pytest
from test_autonext import scenario, until  # noqa: F401 -- private dispatcher fixture
from test_autonext_coordinator import configure
from test_mcp import http_bridge  # noqa: F401 -- private HTTP fixture

from kirabridge.autonext.manager import text_sha
from kirabridge.autonext.models import ApprovedCard
from kirabridge.autonext.status import coordinator_status
from kirabridge.team_manager.models import TeamWorkCreate


@pytest.fixture
async def projected(scenario, tmp_path, monkeypatch):  # noqa: F811
    s, b = scenario, scenario["bridge"]
    card = configure(s, tmp_path, monkeypatch)
    await b.autonext.tick()  # Claim only; the TeamDispatcher is not started.
    item = b.store.db.execute("SELECT * FROM autonext_items").fetchone()
    source = text_sha("PRIVATE_MODEL_RESULT")
    b.store.db.execute(
        "INSERT INTO autonext_coordinator(task_id,source_sha) VALUES(?,?)",
        (card["task_id"], source),
    )
    review = b.store.db.execute("SELECT * FROM autonext_coordinator").fetchone()
    verifier = b.autonext._delegate(item, review, "verify", "codex_verify")
    ids = {"worker": item["work_id"], "verifier": verifier}
    for role, work_id in ids.items():
        principal = "codex" if role == "worker" else "codex_verify"
        core = "status-core-" + role
        b.store.db.execute(
            "INSERT INTO tasks(id,principal,idem,request_hash,operation,args,state,created,updated,"
            "started,finished,result) VALUES(?,?,?,'fixture','agent.execute','{}','completed',"
            "1,4,2,3,?)",
            (core, principal, core, json.dumps({"PRIVATE_MODEL_RESULT": True})),
        )
        b.store.db.execute(
            "UPDATE team_work SET state='completed',core_task_id=?,result='PRIVATE_MODEL_RESULT' "
            "WHERE id=?",
            (core, work_id),
        )
    return s, card, ids


def view(b):
    previous = b.autonext.worker
    b.autonext.worker = SimpleNamespace(done=lambda: False)
    try:
        return coordinator_status(b, "codex")
    finally:
        b.autonext.worker = previous


def stop(b, task_id, reason):
    item = b.store.db.execute("SELECT * FROM autonext_items WHERE task_id=?", (task_id,)).fetchone()
    b.autonext._stop(reason, item)


async def test_original_rejected_review_has_truthful_counts_and_keeps_raw_ledger(projected):
    s, card, _ = projected
    b = s["bridge"]
    stop(b, card["task_id"], "autonext_review_rejected")
    before, changes = list(b.store.db.iterdump()), b.store.db.total_changes
    status = view(b)
    assert status["controller_running"] and status["autonext"]["state"] == "stopped"
    assert status["tasks"][0]["state"] == "rejected"
    assert status["tasks"][0]["ledger_state"] == "waiting"
    assert status["counts"] == {"rejected": 1}
    assert not status["project_completion_verified"] and status["read_only"]
    assert "PRIVATE_MODEL_RESULT" not in json.dumps(status)
    assert b.store.db.total_changes == changes and list(b.store.db.iterdump()) == before
    assert b.store.db.execute("SELECT count(*) FROM autonext_leases").fetchone()[0] == 1
    assert not any("release" in key or "lease_held" == key for key in status["tasks"][0])


@pytest.mark.parametrize("role", ["worker", "verifier"])
@pytest.mark.parametrize("layer", ["team", "core"])
@pytest.mark.parametrize("active", ["published", "running", "unknown", "processing_result"])
async def test_active_or_unknown_effects_are_not_projected_terminal(projected, role, layer, active):
    s, card, ids = projected
    b = s["bridge"]
    stop(b, card["task_id"], "autonext_review_rejected")
    if layer == "team":
        b.store.db.execute("UPDATE team_work SET state=? WHERE id=?", (active, ids[role]))
    else:
        b.store.db.execute("UPDATE tasks SET state=? WHERE id=?", (active, "status-core-" + role))
    row = view(b)["tasks"][0]
    assert row["state"] == row["ledger_state"] == "waiting"


@pytest.mark.parametrize("drift", ["parent", "source", "body", "assignee", "pin", "core", "note"])
async def test_rejection_requires_original_parent_source_and_core_binding(projected, drift):
    s, card, ids = projected
    b = s["bridge"]
    stop(b, card["task_id"], "autonext_review_rejected")
    if drift in {"parent", "body", "assignee"}:
        column = {"parent": "parent_id", "body": "body", "assignee": "assignee"}[drift]
        value = None if drift == "parent" else "foreign-binding"
        b.store.db.execute(f"UPDATE team_work SET {column}=? WHERE id=?", (value, ids["verifier"]))
    elif drift == "source":
        b.store.db.execute("UPDATE autonext_coordinator SET source_sha=?", (text_sha("other"),))
    elif drift == "pin":
        b.store.db.execute("UPDATE autonext_items SET source_ref=?", (text_sha("other card"),))
    elif drift == "core":
        b.store.db.execute("UPDATE team_work SET core_task_id=NULL WHERE id=?", (ids["verifier"],))
    else:
        b.store.db.execute("DELETE FROM autonext_outbox WHERE phase='verify_review'")
    assert view(b)["tasks"][0]["state"] == "waiting"


@pytest.mark.parametrize(
    "drift", ["absent", "foreign_task", "foreign_grant", "reason", "historical", "key"]
)
async def test_foreign_or_historical_stop_cannot_relabel_this_card(projected, drift):
    s, card, _ = projected
    b = s["bridge"]
    stop(b, card["task_id"], "autonext_review_rejected")
    if drift == "absent":
        b.store.db.execute("DELETE FROM autonext_outbox WHERE phase='stopped'")
    elif drift == "historical":
        b.store.db.execute(
            "UPDATE autonext_outbox SET grant_id='past-grant',key='past-stop' WHERE phase='stopped'"
        )
    elif drift == "key":
        b.store.db.execute("UPDATE autonext_outbox SET key='unbound-stop' WHERE phase='stopped'")
    else:
        row = b.store.db.execute(
            "SELECT key,content FROM autonext_outbox WHERE phase='stopped'"
        ).fetchone()
        content = json.loads(row["content"])
        content[
            {"foreign_task": "task_id", "foreign_grant": "grant_id", "reason": "reason"}[drift]
        ] = "old-or-foreign"
        b.store.db.execute(
            "UPDATE autonext_outbox SET content=? WHERE key=?", (json.dumps(content), row["key"])
        )
    assert view(b)["tasks"][0]["state"] == "waiting"


@pytest.mark.parametrize(
    "ledger", ["completed", "published", "running", "unknown", "failed", "waiting"]
)
async def test_existing_states_survive_without_a_matching_terminal_projection(projected, ledger):
    s, _, _ = projected
    b = s["bridge"]
    b.store.db.execute("UPDATE autonext_items SET state=?", (ledger,))
    row = view(b)["tasks"][0]
    assert row["state"] == row["ledger_state"] == ledger


@pytest.mark.parametrize(
    "reason,role,work_state,expected",
    [
        ("autonext_work_failed", "worker", "failed", "failed"),
        ("autonext_review_unknown", "verifier", "failed", "failed"),
        ("autonext_budget_stop", "worker", "completed", "stopped"),
        ("autonext_work_cancelled", "worker", "cancelled", "cancelled"),
    ],
)
async def test_bound_failure_and_stop_states_are_workflow_only(
    projected, reason, role, work_state, expected
):
    s, card, ids = projected
    b = s["bridge"]
    b.store.db.execute("UPDATE team_work SET state=? WHERE id=?", (work_state, ids[role]))
    stop(b, card["task_id"], reason)
    row = view(b)["tasks"][0]
    assert row["state"] == expected and row["ledger_state"] == "waiting"


async def test_neighbor_card_is_not_rejected_with_the_stopped_card(projected):
    s, card, ids = projected
    b = s["bridge"]
    stop(b, card["task_id"], "autonext_review_rejected")
    b.config.autonext.cards.append(
        ApprovedCard(task_id="neighbor", entry_id="neighbor", content_sha256=text_sha("neighbor"))
    )
    work = b.teams.delegate(
        "codex",
        TeamWorkCreate(
            team_id="auto-team",
            assignee="codex",
            title="Neighbor",
            body="Not the rejected source",
            idempotency_key="neighbor-status",
        ),
    )
    original = b.store.db.execute("SELECT * FROM autonext_items").fetchone()
    columns = list(original.keys())
    data = dict(original)
    data.update(task_id="neighbor", work_id=work["id"], source_ref=text_sha("neighbor"))
    b.store.db.execute(
        "INSERT INTO autonext_items("
        + ",".join(columns)
        + ") VALUES("
        + ",".join("?" for _ in columns)
        + ")",
        tuple(data[k] for k in columns),
    )
    rows = {item["task_id"]: item for item in view(b)["tasks"]}
    assert rows[card["task_id"]]["state"] == "rejected"
    assert rows["neighbor"]["state"] == "waiting"


async def test_real_controller_rejected_verdict_projects_without_ledger_or_lease_mutation(
    scenario,  # noqa: F811 -- imported fixture
    tmp_path,
    monkeypatch,
):
    s, b = scenario, scenario["bridge"]
    configure(s, tmp_path, monkeypatch, verdict="fail")
    await s["start"]()
    await until(lambda: b.autonext.inspect()["state"] == "stopped")
    before = list(b.store.db.iterdump())
    status = coordinator_status(b, "codex")
    assert status["autonext"]["reason"] == "autonext_review_rejected"
    assert status["tasks"][0]["state"] == "rejected"
    assert status["tasks"][0]["ledger_state"] == "waiting"
    assert status["counts"] == {"rejected": 1}
    assert list(b.store.db.iterdump()) == before


@pytest.mark.parametrize("checks", ["running", "unknown", "interrupted"])
async def test_active_or_unknown_native_checks_remain_unprojected(projected, checks):
    s, card, _ = projected
    b = s["bridge"]
    stop(b, card["task_id"], "autonext_budget_stop")
    b.store.db.execute("UPDATE autonext_coordinator SET checks_state=?", (checks,))
    assert view(b)["tasks"][0]["state"] == "waiting"


async def test_projection_reads_no_model_result_audit_or_lease_control_rows(projected):
    s, card, _ = projected
    b = s["bridge"]
    stop(b, card["task_id"], "autonext_review_rejected")

    def allowed(action, table, column, database, origin):
        if action == sqlite3.SQLITE_READ and (
            table in {"audit", "autonext_leases", "team_work_reprocess_history"}
            or table in {"tasks", "team_work"}
            and column == "result"
        ):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    b.store.db.set_authorizer(allowed)
    try:
        assert view(b)["tasks"][0]["state"] == "rejected"
    finally:
        b.store.db.set_authorizer(None)


@pytest.mark.parametrize("ledger", ["completed", "published", "running", "unknown", "failed"])
async def test_terminal_run_never_overwrites_other_stored_states(projected, ledger):
    s, card, _ = projected
    b = s["bridge"]
    stop(b, card["task_id"], "autonext_review_rejected")
    b.store.db.execute("UPDATE autonext_items SET state=?", (ledger,))
    row = view(b)["tasks"][0]
    assert row["state"] == row["ledger_state"] == ledger


async def test_verifier_failure_with_wrong_source_stays_unprojected(projected):
    s, card, ids = projected
    b = s["bridge"]
    b.store.db.execute("UPDATE team_work SET state='failed' WHERE id=?", (ids["verifier"],))
    b.store.db.execute("UPDATE autonext_coordinator SET source_sha=?", (text_sha("other"),))
    stop(b, card["task_id"], "autonext_review_unknown")
    assert view(b)["tasks"][0]["state"] == "waiting"


@pytest.mark.parametrize("drift", ["principal", "operation"])
async def test_core_identity_mismatch_never_becomes_terminal_projection(projected, drift):
    s, card, _ = projected
    b = s["bridge"]
    stop(b, card["task_id"], "autonext_review_rejected")
    b.store.db.execute(f"UPDATE tasks SET {drift}='foreign-core' WHERE id='status-core-verifier'")
    assert view(b)["tasks"][0]["state"] == "waiting"


async def test_finished_failed_acceptance_check_projects_failed_without_reading_its_output(
    projected,
):
    s, card, _ = projected
    b = s["bridge"]
    b.store.db.execute("UPDATE autonext_coordinator SET checks_state='completed'")
    stop(b, card["task_id"], "autonext_check_failed")
    assert view(b)["tasks"][0]["state"] == "failed"


async def test_recorded_blocked_work_is_projected_without_acceptance_or_release(projected):
    s, card, ids = projected
    b = s["bridge"]
    b.store.db.execute("UPDATE team_work SET state='blocked' WHERE id=?", (ids["worker"],))
    stop(b, card["task_id"], "autonext_work_blocked")
    assert view(b)["tasks"][0]["state"] == "blocked"


async def test_malformed_source_metadata_stays_unprojected(projected):
    s, card, _ = projected
    b = s["bridge"]
    b.store.db.execute(
        "UPDATE autonext_coordinator SET source_sha=?", (sqlite3.Binary(b"not-a-source-hash"),)
    )
    stop(b, card["task_id"], "autonext_review_rejected")
    assert view(b)["tasks"][0]["state"] == "waiting"


async def test_verified_ack_controller_rejection_has_no_false_waiting_or_pending_completion(
    scenario,  # noqa: F811 -- imported fixture
    tmp_path,
    monkeypatch,
):
    s, b = scenario, scenario["bridge"]
    configure(s, tmp_path, monkeypatch, verdict="fail")
    b.config.autonext.completion_target = "status-projection-fixture"
    b.config.autonext.completion_mode = "verified_ack"
    await s["start"]()
    await until(lambda: b.autonext.inspect()["state"] == "stopped")
    before = list(b.store.db.iterdump())
    status = coordinator_status(b, "codex")
    assert status["controller_running"]
    assert status["autonext"]["reason"] == "autonext_review_rejected"
    assert status["autonext"]["completion_processing"]["pending"] == {}
    assert status["tasks"][0]["state"] == "rejected"
    assert status["tasks"][0]["ledger_state"] == "waiting"
    assert status["counts"] == {"rejected": 1}
    assert list(b.store.db.iterdump()) == before
