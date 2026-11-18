"""Lost submit responses reconcile the original attempt, never submit a replacement."""

# ruff: noqa: F811 -- imported pytest fixtures are injected as test parameters.

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_mcp import http_bridge  # noqa: F401
from test_team_dispatcher import configure_team, make_http_team
from test_team_manager import core, domain, work  # noqa: F401

from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.mcp_gateway.client import MCPClientPool
from kirabridge.team_manager.dispatcher import TeamDispatcher
from kirabridge.team_manager.models import TeamWorkReprocess


@pytest.mark.parametrize("tool", ["task_submit", "task_get"])
@pytest.mark.parametrize("state", ["failed", "blocked", "unknown", "cancelled"])
async def test_durable_terminal_task_error_is_an_observation(tool, state):
    task = {
        "id": "team-original",
        "operation": "agent.execute",
        "state": state,
        "request_sha256": "a" * 64,
        "error": {"code": "peer_unknown"},
    }

    class Pool:
        async def call(self, *_):
            return SimpleNamespace(isError=False, structuredContent=task)

    arguments = (
        {"request": {"task_id": task["id"]}} if tool == "task_submit" else {"task_id": task["id"]}
    )
    dispatcher = TeamDispatcher(SimpleNamespace(teams=None))
    assert await dispatcher._call(Pool(), tool, arguments) == task


@pytest.mark.parametrize("change", ["error_envelope", "foreign_id", "wrong_operation", "no_seal"])
async def test_submission_error_cannot_masquerade_as_original_task(change):
    task = {
        "id": "team-original",
        "operation": "agent.execute",
        "state": "unknown",
        "request_sha256": "a" * 64,
        "error": {"code": "peer_unknown"},
    }
    if change == "error_envelope":
        task = {"error": task["error"]}
    elif change == "foreign_id":
        task["id"] = "foreign"
    elif change == "wrong_operation":
        task["operation"] = "file.write"
    else:
        del task["request_sha256"]

    class Pool:
        async def call(self, *_):
            return SimpleNamespace(isError=False, structuredContent=task)

    dispatcher = TeamDispatcher(SimpleNamespace(teams=None))
    with pytest.raises(BridgeError, match="Authenticated team call was rejected"):
        await dispatcher._call(Pool(), "task_submit", {"request": {"task_id": "team-original"}})


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
