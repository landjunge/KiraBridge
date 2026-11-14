"""Lost submit responses reconcile the original attempt, never submit a replacement."""

# ruff: noqa: F811 -- imported pytest fixtures are injected as test parameters.

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from test_mcp import http_bridge  # noqa: F401
from test_team_dispatcher import configure_team, make_http_team
from test_team_manager import core, domain, work  # noqa: F401

from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.mcp_gateway.client import MCPClientPool
from kirabridge.team_manager.models import TeamWorkReprocess


def lost_submission(domain, *, automatic=False, team_id="test-team"):
    created = domain.delegate("grok", work(team_id=team_id))
    claimed = domain.claim(created["id"])
    text = '{"kirabridge_team":"1","result":"original only","actions":[]}'
    native = core(domain, claimed, result={"success": True, "text": text})
    domain.store.db.execute(
        "UPDATE tasks SET result=?,started=1,finished=2,receipt='original-receipt' WHERE id=?",
        (canonical(native["result"]), native["id"]),
    )
    evidence = {"core_task_id": native["id"], "automatic_retry": False}
    if automatic:
        evidence["submission_observation_pending"] = True
    unknown = domain.fail(created["id"], "unknown", "peer_unknown", evidence)
    native = domain.store.get(native["id"])
    request = TeamWorkReprocess(
        team_id=created["team_id"],
        work_id=created["id"],
        core_task_id=native["id"],
        expected_result_sha256=hashlib.sha256(text.encode()).hexdigest(),
        expected_request_sha256=native["request_sha256"],
        expected_core_attempt=1,
        expected_core_receipt=native["receipt"],
        idempotency_key="recover-original",
    )
    return unknown, native, request


def test_explicit_historical_submission_recovery_preserves_original_and_is_idempotent(domain):
    old, native, request = lost_submission(domain)
    tasks = [tuple(r) for r in domain.store.db.execute("SELECT * FROM tasks")]
    assert domain.inflight() == []  # Historical UNKNOWNs are never automatically drained.
    recovered = domain.work_reprocess("local", request)
    assert recovered["state"] == "processing_result"
    history = dict(domain.store.db.execute("SELECT * FROM team_work_reprocess_history").fetchone())
    assert history["previous_state"] == "unknown"
    assert json.loads(history["previous_evidence"]) == old["evidence"]
    assert history["previous_error"] == "peer_unknown"
    assert domain.work_reprocess("local", request) == recovered
    domain.bind_task(old["id"], native)
    domain.finish(old["id"], "original only", {"actions": []})
    assert domain.work_reprocess("local", request)["state"] == "completed"
    assert tasks == [tuple(r) for r in domain.store.db.execute("SELECT * FROM tasks")]
    assert (
        domain.store.db.execute("SELECT count(*) FROM team_work_reprocess_history").fetchone()[0]
        == 1
    )


@pytest.mark.parametrize(
    "change",
    [
        "running",
        "unknown",
        "failed",
        "receipt",
        "attempt",
        "principal",
        "seal",
        "success",
        "finished",
    ],
)
def test_unproven_original_stays_unknown(domain, change):
    old, _, request = lost_submission(domain)
    if change in {"running", "unknown", "failed"}:
        domain.store.db.execute("UPDATE tasks SET state=?", (change,))
    elif change == "receipt":
        domain.store.db.execute("UPDATE tasks SET receipt=NULL")
    elif change == "attempt":
        domain.store.db.execute("UPDATE tasks SET attempt=2")
    elif change == "principal":
        domain.store.db.execute("UPDATE tasks SET principal='grok'")
    elif change == "seal":
        domain.store.db.execute("UPDATE tasks SET request_hash='different'")
    elif change == "finished":
        domain.store.db.execute("UPDATE tasks SET finished=NULL")
    else:
        domain.store.db.execute("UPDATE tasks SET result=?", (canonical({"success": False}),))
    with pytest.raises(BridgeError):
        domain.work_reprocess("local", request)
    assert domain.work_get("local", "test-team", old["id"]) == old
    assert (
        domain.store.db.execute("SELECT count(*) FROM team_work_reprocess_history").fetchone()[0]
        == 0
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_request_sha256", "0" * 64),
        ("expected_core_receipt", "foreign"),
        ("expected_core_attempt", 2),
        ("expected_result_sha256", "0" * 64),
    ],
)
def test_explicit_recovery_requires_exact_original_proof(domain, field, value):
    old, _, request = lost_submission(domain)
    with pytest.raises(BridgeError):
        domain.work_reprocess("local", request.model_copy(update={field: value}))
    assert domain.work_get("local", "test-team", old["id"]) == old


@pytest.mark.parametrize(
    "field", ["id", "principal", "request_sha256", "receipt", "attempt", "result"]
)
def test_foreign_observation_cannot_reconcile_new_submission(domain, field):
    old, native, _ = lost_submission(domain, automatic=True)
    bad = {**native, field: "foreign"}
    with pytest.raises(BridgeError):
        domain.reconcile_submission(old["id"], bad)
    assert domain.work_get("local", "test-team", old["id"]) == old


async def test_lost_submit_response_late_core_completes_once_without_second_turn(
    http_bridge, config, tmp_path, monkeypatch
):
    bridge, endpoint = http_bridge
    root = configure_team(
        bridge,
        config,
        tmp_path,
        monkeypatch,
        answer='{"kirabridge_team":"1","result":"late original","actions":[]}',
    )
    dispatcher = bridge.team_dispatcher
    original = dispatcher._call
    submissions = []

    async def lost(pool, tool, arguments):
        if tool == "task_submit":
            submissions.append(asyncio.create_task(original(pool, tool, arguments)))
            async with asyncio.timeout(10):
                while not bridge.store.db.execute("SELECT 1 FROM tasks").fetchone():
                    await asyncio.sleep(0.01)
            raise BridgeError("peer_unknown", "Response lost after original admission")
        return await original(pool, tool, arguments)

    dispatcher._call = lost
    async with MCPClientPool() as clients:
        created = await make_http_team(clients, endpoint)
        await dispatcher._run(created, existing=False)
        unknown = bridge.teams.work_get("local", "restart-team", created["id"])
        assert unknown["state"] == "unknown"
        # The peer pool may close before its admitted task finishes; Core continues independently.
        await asyncio.gather(*submissions, return_exceptions=True)
        async with asyncio.timeout(10):
            while bridge.store.get(unknown["core_task_id"])["state"] != "completed":
                await asyncio.sleep(0.02)
        assert dispatcher._next()[0]["id"] == created["id"]
        dispatcher._active.clear()
        await dispatcher._run(unknown, existing=True)
        result = bridge.teams.work_get("local", "restart-team", created["id"])
        assert result["state"] == "completed" and result["result"] == "late original"
        await dispatcher._run(unknown, existing=True)  # stale duplicate observation
        assert bridge.teams.inflight() == []
        assert len(submissions) == 1
        assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
        assert len((Path(root) / "team-codex-invocations").read_text().splitlines()) == 1


def owner_fixture(domain, tmp_path, monkeypatch):
    from test_coordinator_runtime import runtime
    from test_team_manager import create

    members = {**create().members, "codex": "coordinator", "chatgpt": "worker"}
    domain.create(
        "local", create(team_id="bigplan-codex-loop", coordinator="codex", members=members)
    )
    old, native, request = lost_submission(domain, team_id="bigplan-codex-loop")
    state = domain.config.state_path
    profile = {
        "instance": "owned-loop",
        "cwd": str(tmp_path),
        "workspace": str(tmp_path),
        "state_dir": str(state),
        "enabled": False,
    }
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile))
    marker = {k: profile[k] for k in ("instance", "cwd", "workspace")}
    (state / "coordinator-profile.json").write_text(json.dumps(marker))
    (state / "coordinator.lock").touch()
    status = {
        "reporting_scope": runtime.digest(runtime.fixed_profile(profile)),
        "reporting": {"coordinator": None, "workers": {}, "unresolved": {}},
    }
    (state / "status.json").write_text(json.dumps(status))
    domain.store.db.execute(
        "INSERT INTO autonext_items(task_id,grant_id,source_ref,card,work_id,cwd,cwd_ref,"
        "state,lease_until) "
        "VALUES('pilot','grant','sha','{}',?,'fixture','fixture','waiting',0)",
        (old["id"],),
    )
    domain.store.db.execute(
        "CREATE TABLE IF NOT EXISTS autonext_coordinator (grok_work_id TEXT,verify_work_id TEXT)"
    )
    monkeypatch.setattr(runtime, "load_profile", lambda _: profile)
    monkeypatch.setattr(runtime, "configuration", lambda _: domain.config)
    monkeypatch.setattr(runtime, "Bridge", lambda _: pytest.fail("No Bridge may be constructed"))
    return runtime, path, request, native


def test_reconcile_owner_cli_reuses_stopped_state_without_starting_bridge(
    domain, tmp_path, monkeypatch
):
    runtime, path, request, _ = owner_fixture(domain, tmp_path, monkeypatch)
    state = domain.config.state_path
    before_status = (state / "status.json").read_bytes()
    before_tasks = [tuple(r) for r in domain.store.db.execute("SELECT * FROM tasks")]
    result = runtime.reconcile_result(
        path,
        request.model_dump(),
        expected_profile_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    assert result["state"] == "processing_result" and result["provider_started"] is False
    assert (state / "status.json").read_bytes() == before_status
    assert before_tasks == [tuple(r) for r in domain.store.db.execute("SELECT * FROM tasks")]


@pytest.mark.parametrize("guard", ["lock", "identity", "profile", "ownership"])
def test_reconcile_owner_cli_refuses_wrong_or_running_state(domain, tmp_path, monkeypatch, guard):
    import fcntl

    runtime, path, request, _ = owner_fixture(domain, tmp_path, monkeypatch)
    state = domain.config.state_path
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    if guard == "identity":
        (state / "coordinator-profile.json").write_text("{}")
    elif guard == "profile":
        expected = "0" * 64
    elif guard == "ownership":
        domain.store.db.execute("DELETE FROM autonext_items")
    with (state / "coordinator.lock").open("r+") as lock:
        if guard == "lock":
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises((BlockingIOError, RuntimeError)):
            runtime.reconcile_result(path, request.model_dump(), expected_profile_sha256=expected)
    assert domain.work_get("local", request.team_id, request.work_id)["state"] == "unknown"
    assert (
        domain.store.db.execute("SELECT count(*) FROM team_work_reprocess_history").fetchone()[0]
        == 0
    )
