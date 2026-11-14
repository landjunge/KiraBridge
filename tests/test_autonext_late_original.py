"""Original result acceptance after a lost submit reply; real local Core/CLI only."""

# ruff: noqa: F811 -- imported pytest fixtures.
import asyncio
import hashlib
import json
import time

import pytest
from test_autonext import scenario, until  # noqa: F401
from test_autonext_coordinator import configure
from test_coordinator_runtime import runtime
from test_mcp import http_bridge  # noqa: F401

from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.team_manager.models import TeamWorkReprocess


async def original_boundary(s, tmp_path, monkeypatch, *, legacy=True):
    card = configure(s, tmp_path, monkeypatch)
    (s["root"] / ".git").write_text("isolated result-only fixture")
    b = s["bridge"]
    b.config.autonext.completion_target = "late-result-fixture"
    dispatcher = b.team_dispatcher
    original = dispatcher._call
    fail = b.teams.fail

    def original_failure(work_id, state, code, evidence):
        if legacy and code == "peer_unknown":
            evidence = {k: v for k, v in evidence.items() if k != "submission_observation_pending"}
        return fail(work_id, state, code, evidence)

    async def lost(pool, tool, args):
        result = await original(pool, tool, args)
        if tool == "task_submit" and args["request"]["arguments"]["agent"] == "codex_verify":
            dispatcher._defer[args["request"]["task_id"][5:]] = time.monotonic() + 3600
            raise BridgeError("peer_unknown", "Original admitted result, submit response lost")
        return result

    monkeypatch.setattr(b.teams, "fail", original_failure)
    monkeypatch.setattr(dispatcher, "_call", lost)
    await s["start"]()
    await until(
        lambda: b.store.db.execute("SELECT 1 FROM team_work WHERE state='unknown'").fetchone()
    )
    if legacy:
        await until(lambda: b.autonext.inspect()["state"] == "stopped")
    await b.autonext.stop()
    await dispatcher.stop()
    row = b.store.db.execute("SELECT * FROM autonext_coordinator").fetchone()
    item = b.store.db.execute("SELECT * FROM autonext_items").fetchone()
    work = b.teams._work(row["verify_work_id"])
    await until(lambda: b.store.get(work["core_task_id"])["state"] == "completed")
    core = b.store.get(work["core_task_id"])
    assert core["state"] == "completed" and core["finished"] <= item["lease_until"]
    request = TeamWorkReprocess(
        team_id=b.config.autonext.team_id,
        work_id=work["id"],
        core_task_id=core["id"],
        expected_result_sha256=hashlib.sha256(core["result"]["text"].encode()).hexdigest(),
        expected_request_sha256=core["request_sha256"],
        expected_core_attempt=1,
        expected_core_receipt=core["receipt"],
        idempotency_key="original-result-only",
    )
    lease = dict(b.store.db.execute("SELECT * FROM autonext_leases").fetchone())
    return card, item, work, core, request, lease


async def test_stopped_expired_original_reaches_receipt_outbox_ack_without_new_turn(
    scenario,
    tmp_path,
    monkeypatch,
):
    b = scenario["bridge"]
    card, item, work, core, request, lease = await original_boundary(
        scenario, tmp_path, monkeypatch
    )
    for index in range(5):
        b.store.db.execute(
            "INSERT INTO tasks(id,principal,idem,request_hash,operation,args,state,"
            "created,updated) "
            "VALUES(?, 'codex', ?, 'old-seal','agent.execute','{}','unknown',1,2)",
            (f"historical-{index}", f"historical-{index}"),
        )
    for index in range(6):
        b.store.db.execute(
            "INSERT INTO autonext_leases VALUES(?,?,?,?)",
            (str(tmp_path / f"old-scope-{index}"), f"old-{index}", "old-owner", 1),
        )
    old_leases = [
        tuple(r)
        for r in b.store.db.execute("SELECT * FROM autonext_leases WHERE owner='old-owner'")
    ]
    before = [tuple(r) for r in b.store.db.execute("SELECT * FROM tasks")]
    unknowns = [tuple(r) for r in b.store.db.execute("SELECT * FROM tasks WHERE state='unknown'")]
    monkeypatch.setattr(time, "time", lambda: item["lease_until"] + 10)
    receipt = await b.autonext.accept_original_result(
        "codex", request, expected_lease_owner=lease["owner"]
    )
    assert receipt["task_id"] == card["task_id"]
    assert receipt["accepted_at"] > item["lease_until"]
    assert receipt["coordinator"]["verify_work_id"] == work["id"]
    assert receipt["coordinator"]["checks"]["passed"] is True
    assert b.autonext.inspect()["state"] == "complete"
    assert [tuple(r) for r in b.store.db.execute("SELECT * FROM tasks")] == before
    assert [
        tuple(r) for r in b.store.db.execute("SELECT * FROM tasks WHERE state='unknown'")
    ] == unknowns
    assert (
        b.store.db.execute("SELECT lease_until FROM autonext_items").fetchone()[0]
        == item["lease_until"]
    )
    assert b.store.db.execute("SELECT count(*) FROM autonext_runs").fetchone()[0] == 1
    assert old_leases == [
        tuple(r)
        for r in b.store.db.execute("SELECT * FROM autonext_leases WHERE owner='old-owner'")
    ]
    assert all(r[0] for r in b.store.db.execute("SELECT verified FROM autonext_outbox"))
    consumed = runtime.process_completions(b, {"completion_target": "late-result-fixture"})
    assert consumed["processed"] and consumed["pending"] == 0
    count = b.store.db.execute("SELECT count(*) FROM autonext_outbox").fetchone()[0]
    assert (
        await b.autonext.accept_original_result(
            "codex", request, expected_lease_owner=lease["owner"]
        )
        == receipt
    )
    assert b.store.db.execute("SELECT count(*) FROM autonext_outbox").fetchone()[0] == count
    assert (
        runtime.process_completions(b, {"completion_target": "late-result-fixture"})["processed"]
        == []
    )


async def test_other_stops_and_unproven_originals_cannot_accept(scenario, tmp_path, monkeypatch):
    b = scenario["bridge"]
    _, item, work, core, request, lease = await original_boundary(scenario, tmp_path, monkeypatch)
    monkeypatch.setattr(time, "time", lambda: item["lease_until"] + 10)
    for reason in ["operator_stop", "autonext_budget_stop", "autonext_check_unknown"]:
        b.store.db.execute("UPDATE autonext_runs SET reason=?", (reason,))
        with pytest.raises(BridgeError):
            await b.autonext.accept_original_result(
                "codex", request, expected_lease_owner=lease["owner"]
            )
    b.store.db.execute("UPDATE autonext_runs SET reason='autonext_review_unknown'")
    for state in ["running", "unknown", "failed"]:
        b.store.db.execute("UPDATE tasks SET state=? WHERE id=?", (state, core["id"]))
        with pytest.raises(BridgeError):
            await b.autonext.accept_original_result(
                "codex", request, expected_lease_owner=lease["owner"]
            )
    b.store.db.execute("UPDATE tasks SET state='completed' WHERE id=?", (core["id"],))
    b.store.db.execute("UPDATE tasks SET result=NULL WHERE id=?", (core["id"],))
    with pytest.raises(BridgeError):
        await b.autonext.accept_original_result(
            "codex", request, expected_lease_owner=lease["owner"]
        )
    b.store.db.execute(
        "UPDATE tasks SET result=?,finished=? WHERE id=?",
        (canonical(core["result"]), item["lease_until"] + 1, core["id"]),
    )
    with pytest.raises(BridgeError):
        await b.autonext.accept_original_result(
            "codex", request, expected_lease_owner=lease["owner"]
        )
    b.store.db.execute("UPDATE tasks SET finished=? WHERE id=?", (core["finished"], core["id"]))
    with pytest.raises(BridgeError):
        await b.autonext.accept_original_result("codex", request, expected_lease_owner="foreign")
    for field, value in [
        ("expected_request_sha256", "0" * 64),
        ("expected_core_attempt", 2),
        ("expected_core_receipt", "foreign"),
        ("expected_result_sha256", "0" * 64),
    ]:
        with pytest.raises(BridgeError):
            await b.autonext.accept_original_result(
                "codex",
                request.model_copy(update={field: value}),
                expected_lease_owner=lease["owner"],
            )
    changed = {
        **core["result"],
        "final_message": json.dumps(
            {
                "kirabridge_team": "1",
                "result": "x",
                "actions": [{"type": "message", "recipient": "codex", "body": "forbidden"}],
            }
        ),
    }
    b.store.db.execute("UPDATE tasks SET result=? WHERE id=?", (canonical(changed), core["id"]))
    with pytest.raises(BridgeError):
        await b.autonext.accept_original_result(
            "codex", request, expected_lease_owner=lease["owner"]
        )
    assert b.teams._work(work["id"])["state"] == "unknown"
    assert b.store.db.execute("SELECT receipt FROM autonext_items").fetchone()[0] is None
    assert b.store.db.execute("SELECT count(*) FROM team_work_reprocess_history").fetchone()[0] == 0


async def test_new_submit_marker_automatically_finishes_original_after_lease(
    scenario, tmp_path, monkeypatch
):
    b = scenario["bridge"]
    _, item, work, _, _, _ = await original_boundary(scenario, tmp_path, monkeypatch, legacy=False)
    assert b.autonext.inspect()["state"] == "waiting"
    before = b.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0]
    monkeypatch.setattr(time, "time", lambda: item["lease_until"] + 10)
    assert b.autonext.work_ready(work["id"])
    # A receiver may stop after reopening the original but before parsing it.
    b.teams.reconcile_submission(work["id"], b.store.get(work["core_task_id"]))
    assert b.autonext.work_ready(work["id"])
    work = b.teams._work(work["id"])
    await b.team_dispatcher._run(work, existing=True)
    assert b.teams._work(work["id"])["state"] == "completed"
    await b.autonext.tick()
    task = b.autonext._check_tasks[item["task_id"]]
    await task
    await b.autonext.tick()
    assert b.autonext.receipt("codex", item["task_id"])
    assert b.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == before
    assert (
        runtime.process_completions(b, {"completion_target": "late-result-fixture"})["pending"] == 0
    )


async def test_locked_cli_accepts_original_grant_and_processes_completion(
    scenario, tmp_path, monkeypatch
):
    b = scenario["bridge"]
    card, item, _, _, request, lease = await original_boundary(scenario, tmp_path, monkeypatch)
    cfg, state = b.config, b.config.state_path
    profile = {
        "instance": "original-owner",
        "cwd": str(scenario["root"]),
        "workspace": str(scenario["desk"]),
        "state_dir": str(state),
        "enabled": True,
        "board_id": "board",
        "completion_target": "late-result-fixture",
        "continuation": {
            "authority_ref": "original mandate",
            "allowed_cwds": [card["cwd"]],
            "products": ["KiraBridge"],
            "checks": card["acceptance"]["checks"],
            "sources": [p.model_dump() for p in cfg.autonext.cards],
        },
    }
    path = tmp_path / "owner-profile.json"
    path.write_text(json.dumps(profile))
    (state / "coordinator-profile.json").write_text(
        json.dumps({k: profile[k] for k in ["instance", "cwd", "workspace"]})
    )
    (state / "coordinator.lock").touch()
    (state / "status.json").write_text(
        json.dumps(
            {
                "reporting_scope": runtime.digest(runtime.fixed_profile(profile)),
                "reporting": {"coordinator": None, "workers": {}, "unresolved": {}},
            }
        )
    )
    grant = state / ("grant-" + item["grant_id"] + ".json")
    grant.write_text(cfg.autonext.model_dump_json())
    monkeypatch.setattr(runtime, "load_profile", lambda _: profile)
    monkeypatch.setattr(runtime, "configuration", lambda _: cfg)
    monkeypatch.setattr(runtime, "Bridge", lambda _: pytest.fail("No Bridge construction"))
    before_tasks = [tuple(r) for r in b.store.db.execute("SELECT * FROM tasks")]
    before_status = (state / "status.json").read_bytes()
    monkeypatch.setattr(time, "time", lambda: item["lease_until"] + 10)
    result = await asyncio.to_thread(
        runtime.reconcile_result,
        path,
        request.model_dump(),
        expected_profile_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        accept_original=True,
        expected_grant_sha256=hashlib.sha256(grant.read_bytes()).hexdigest(),
        expected_lease_owner=lease["owner"],
    )
    assert result["state"] == "accepted" and result["provider_started"] is False
    assert result["completions"]["processed"] and result["completions"]["pending"] == 0
    assert result["receipt"]["task_id"] == card["task_id"]
    assert before_status == (state / "status.json").read_bytes()
    assert before_tasks == [tuple(r) for r in b.store.db.execute("SELECT * FROM tasks")]
