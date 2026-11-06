"""Standing mandate intake through real Core/TeamWork; deterministic CLI fixtures."""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock

import pytest
from test_autonext import scenario, until  # noqa: F401
from test_autonext_coordinator import configure
from test_coordinator_runtime import runtime
from test_mcp import http_bridge  # noqa: F401

from kirabridge.autonext.continuation import (
    ContinuationPolicy,
    bind_scope,
    discover,
    restore,
    validate_source,
)
from kirabridge.autonext.manager import text_sha
from kirabridge.autonext.models import AutoNextConfig, ReadyCard
from kirabridge.bridge_core.models import BridgeError
from kirabridge.whiteboard_read import append_whiteboard, read_whiteboard


def append(s, content, entry_type="task", *, assign=True):
    text = content if isinstance(content, str) else json.dumps(content)
    result = append_whiteboard(
        str(s["desk"]),
        "board",
        actor="coordinator",
        actor_type="codex",
        entry_type=entry_type,
        content=text,
    )
    if assign and entry_type == "task" and isinstance(content, dict) and "task_id" in content:
        s["intake_profile"]["continuation"]["sources"].append(
            {
                "task_id": content["task_id"],
                "entry_id": result["id"],
                "content_sha256": text_sha(text),
            }
        )
    return result


def setup(s, tmp_path, monkeypatch):
    card = configure(s, tmp_path, monkeypatch)
    b, cfg = s["bridge"], s["config"]
    (s["root"] / ".git").write_text("isolated fixture worktree")
    team = b.teams.get("codex", "auto-team")
    anchor = b.teams.work_get("codex", "auto-team", cfg.autonext.after_work_id)
    cfg.autonext = AutoNextConfig(coordinator_mode=True, principal="codex")
    profile = {
        "enabled": True,
        "codex": "/bin/false",
        "workspace": str(s["desk"]),
        "board_id": "board",
        "sandbox": "workspace-write",
        "cards": [],
        "completion_target": "fixture-continuation",
        "continuation": {
            "authority_ref": "explicit user mandate fixture",
            "allowed_cwds": [str(s["root"])],
            "products": ["KiraBridge"],
            "checks": card["acceptance"]["checks"],
            "sources": [],
        },
    }
    entries = read_whiteboard(str(s["desk"]), "board")["entries"]
    source = read_whiteboard(str(s["desk"]), "board", entries[0]["id"])["entry"]
    profile["continuation"]["sources"].append(
        {
            "task_id": card["task_id"],
            "entry_id": source["id"],
            "content_sha256": text_sha(source["content"]),
        }
    )
    s["intake_profile"] = profile
    b.autonext.continuation_guard = lambda item: validate_source(b, profile, item)
    quota = AsyncMock(return_value={"observed_at": time.time(), "source": "fixture subscription"})
    monkeypatch.setattr(runtime, "quota", quota)
    return card, profile, team, anchor, quota


async def settled(b):
    await until(lambda: b.autonext.inspect()["state"] in {"complete", "stopped"})


async def test_standing_mandate_advances_existing_tasks_once_without_approve(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,  # noqa: F811
):
    s, b = scenario, scenario["bridge"]
    card, profile, team, anchor, quota = setup(s, tmp_path, monkeypatch)
    second = {**card, "task_id": "followup.two", "title": "Existing second task"}
    append(s, second)
    await s["start"]()
    active, _ = await runtime.advance(b, profile, team, anchor, None)
    await settled(b)
    first = b.autonext.receipt("codex", card["task_id"])
    assert first and b.autonext.inspect()["state"] == "complete"
    b.store.db.execute("UPDATE autonext_outbox SET verified=0 WHERE phase='completed'")
    assert runtime.process_completions(b, profile) == {"processed": [], "pending": 1}
    assert runtime.closure_status(b)["missing"]
    assert not runtime.closure_status(b)["closed"]
    b.store.db.execute("UPDATE autonext_outbox SET verified=1 WHERE phase='completed'")
    assert runtime.closure_status(b) == {"closed": [card["task_id"]], "missing": []}
    consumed = runtime.process_completions(b, profile)
    assert len(consumed["processed"]) == 1 and consumed["pending"] == 0
    assert runtime.process_completions(b, profile) == {"processed": [], "pending": 0}
    assert b.store.db.execute("SELECT count(*) FROM autonext_items").fetchone()[0] == 1
    active, _ = await runtime.advance(b, profile, team, anchor, active)
    await settled(b)
    second_receipt = b.autonext.receipt("codex", second["task_id"])
    assert second_receipt
    work = b.teams.work_get("codex", "auto-team", second_receipt["work_id"])
    assert work["started"] > first["accepted_at"]
    count = b.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0]
    for _ in range(3):
        active, intake = await runtime.advance(b, profile, team, anchor, active)
        assert intake["selected"] is None
    assert restore(b, profile) is None
    assert b.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == count
    assert quota.await_count == 2
    assert {item["reason"] for item in intake["held"]} == {"completed"}


@pytest.mark.parametrize("kind", ["claimed", "progress", "result", "problem"])
async def test_existing_foreign_activity_is_reserved_even_if_stale(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,
    kind,  # noqa: F811
):
    s = scenario
    card, profile, *_ = setup(s, tmp_path, monkeypatch)
    append(s, card["task_id"] + " delivered/assigned elsewhere", kind)
    append(s, {**card, "task_id": "independent", "title": "Independent"})
    intake = discover(s["bridge"], profile)
    assert intake["selected"]["card"].task_id == "independent"
    assert intake["held"][0]["reason"] == "external_activity"
    assert not s["bridge"].store.db.execute("SELECT 1 FROM autonext_items").fetchone()


async def test_conflicting_id_unapproved_check_and_idea_hold_only_affected_task(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,  # noqa: F811
):
    s = scenario
    card, profile, *_ = setup(s, tmp_path, monkeypatch)
    append(s, {**card, "instruction": "conflicting bytes"})
    append(s, {**card, "task_id": "idea", "state": "IDEA"})
    unapproved = {
        **card,
        "task_id": "unapproved",
        "acceptance": {
            "kind": "coordinator_checks",
            "checks": [{"argv": ["/bin/false"]}],
        },
    }
    append(s, unapproved)
    append(s, {**card, "task_id": "eligible"})
    append(s, "READY arbitrary prose and another coordinator name")
    intake = discover(s["bridge"], profile)
    assert intake["selected"]["card"].task_id == "eligible"
    assert {item["reason"] for item in intake["held"]} == {
        "conflicting_task_id",
        "card_idea",
        "outside_check_templates",
    }


async def test_restart_after_claim_restores_original_work_without_replay(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,  # noqa: F811
):
    s, b = scenario, scenario["bridge"]
    card, profile, team, anchor, quota = setup(s, tmp_path, monkeypatch)
    active, _ = await runtime.advance(b, profile, team, anchor, None)
    await until(lambda: b.autonext.inspect()["state"] == "waiting")
    await b.autonext.stop()
    work_id = b.store.db.execute("SELECT work_id FROM autonext_items").fetchone()[0]
    s["config"].autonext = AutoNextConfig(coordinator_mode=True, principal="codex")
    assert restore(b, profile) == active
    await s["start"]()
    await settled(b)
    receipt = b.autonext.receipt("codex", card["task_id"])
    assert receipt and receipt["work_id"] == work_id
    assert b.store.db.execute("SELECT count(*) FROM autonext_items").fetchone()[0] == 1
    assert quota.await_count == 1


async def test_unknown_retains_original_lease_but_other_worktree_can_start(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,  # noqa: F811
):
    s, b = scenario, scenario["bridge"]
    card, profile, team, anchor, _ = setup(s, tmp_path, monkeypatch)
    active, _ = await runtime.advance(b, profile, team, anchor, None)
    await until(lambda: b.autonext.inspect()["state"] == "waiting")
    await b.autonext.stop()
    original = dict(b.store.db.execute("SELECT * FROM autonext_items").fetchone())
    work_id = original["work_id"]
    b.teams.fail(work_id, "unknown", "fixture_unknown", {"automatic_retry": False})
    b.autonext._stop("autonext_work_unknown", original)
    b.autonext._flush()
    other = tmp_path / "independent-worktree"
    other.mkdir()
    (other / ".git").write_text("isolated second worktree")
    profile["continuation"]["allowed_cwds"].append(str(other))
    for policy in b.config.principals.values():
        policy.roots.append(str(other))
        policy.read_roots.append(str(other))
    append(s, {**card, "task_id": "independent.scope", "cwd": str(other)})
    await s["start"]()
    active, _ = await runtime.advance(b, profile, team, anchor, active)
    await settled(b)
    receipt = b.autonext.receipt("codex", "independent.scope")
    assert receipt, b.autonext.inspect()
    assert (
        dict(
            b.store.db.execute(
                "SELECT * FROM autonext_items WHERE task_id=?", (card["task_id"],)
            ).fetchone()
        )
        == original
    )
    assert b.store.db.execute("SELECT cwd FROM autonext_leases").fetchone()[0] == str(s["root"])
    scopes = [
        json.loads(row["args"])["cwd"]
        for row in b.store.db.execute("SELECT args FROM tasks WHERE operation='agent.execute'")
    ]
    assert scopes == [str(other), str(other)]  # Worker and verifier, original UNKNOWN never runs.


async def test_foreign_claim_between_selection_and_claim_starts_nothing(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,  # noqa: F811
):
    s, b = scenario, scenario["bridge"]
    card, profile, team, anchor, quota = setup(s, tmp_path, monkeypatch)

    async def quota_then_foreign_claim(_):
        append(s, card["task_id"] + " claimed by another session", "claimed")
        return quota.return_value

    monkeypatch.setattr(runtime, "quota", quota_then_foreign_claim)
    await s["start"]()
    await runtime.advance(b, profile, team, anchor, None)
    await settled(b)
    assert b.autonext.inspect()["reason"] == "continuation_external_claim"
    assert not b.store.db.execute("SELECT 1 FROM autonext_items").fetchone()
    assert not b.store.db.execute("SELECT 1 FROM tasks WHERE operation='agent.execute'").fetchone()


def test_board_claim_external_key_is_atomic_across_concurrent_writers(tmp_path):
    (tmp_path / "threads").mkdir()
    (tmp_path / "whiteboard").mkdir()
    (tmp_path / "threads/board.json").write_text('{"id":"board"}')

    def reserve(owner):
        try:
            return append_whiteboard(
                str(tmp_path),
                "board",
                actor=owner,
                actor_type="codex",
                entry_type="claimed",
                content="task: shared",
                external_key="autonext-claim-shared",
            )
        except BridgeError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, ["first", "second"]))
    assert sum(isinstance(value, dict) for value in results) == 1
    assert "conflict" in results
    assert len(read_whiteboard(str(tmp_path), "board")["entries"]) == 1


async def test_scope_cannot_change_while_core_effect_running(scenario, tmp_path, monkeypatch):  # noqa: F811
    s, b = scenario, scenario["bridge"]
    card, profile, team, anchor, _ = setup(s, tmp_path, monkeypatch)
    await runtime.advance(b, profile, team, anchor, None)
    await until(lambda: b.autonext.inspect()["state"] == "waiting")
    # A real Core task record is sufficient; no process/provider is needed here.
    from kirabridge.bridge_core.models import TaskRequest

    b.tasks.enqueue(
        "codex",
        TaskRequest(
            operation="agent.execute",
            arguments={
                "agent": "codex",
                "prompt": "fixture",
                "cwd": card["cwd"],
                "timeout": 2,
            },
            task_id="running-scope-fixture",
            idempotency_key="running-scope-fixture",
        ),
        "",
    )
    assert not bind_scope(b, ReadyCard.model_validate({**card, "cwd": str(tmp_path)}))
    assert b.config.team.workers["codex"].cwd == card["cwd"]


def test_standing_mandate_requires_canonical_scope_without_global_liveness_gate(tmp_path):
    value = {
        "authority_ref": "user",
        "products": ["KiraBridge"],
        "checks": [{"argv": [sys.executable, "-c", "pass"]}],
        "allowed_cwds": [str(tmp_path / "missing-worktree")],
    }
    assert ContinuationPolicy.model_validate(value)
    value["allowed_cwds"] = ["relative/worktree"]
    with pytest.raises(ValueError, match="worktree"):
        ContinuationPolicy.model_validate(value)


async def test_ready_data_without_coordinator_assignment_cannot_self_authorize(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,  # noqa: F811
):
    s = scenario
    card, profile, *_ = setup(s, tmp_path, monkeypatch)
    append(s, {**card, "task_id": "untrusted.board.data"}, assign=False)
    intake = discover(s["bridge"], profile)
    assert intake["selected"]["card"].task_id == card["task_id"]
    assert intake["held"][0]["reason"] == "unassigned_source"


async def test_structured_foreign_claim_survives_reader_projection(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    s = scenario
    card, profile, *_ = setup(s, tmp_path, monkeypatch)
    claim = append(s, "Analyse gestartet", "claimed")
    # A normal ThreadDesk entry can bind its task structurally, with no ID in prose.
    path = s["desk"] / "whiteboard/board" / (claim["id"] + ".json")
    stored = json.loads(path.read_text())
    stored["task_id"] = card["task_id"]
    path.write_text(json.dumps(stored))
    intake = discover(s["bridge"], profile)
    assert intake["selected"] is None
    assert intake["held"][0]["reason"] == "external_activity"


async def test_disabled_restart_restores_identity_without_starting_published_claim(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    s, b = scenario, scenario["bridge"]
    _, profile, team, anchor, _ = setup(s, tmp_path, monkeypatch)
    active, _ = await runtime.advance(b, profile, team, anchor, None)
    await until(lambda: b.autonext.inspect()["state"] == "waiting")
    await b.autonext.stop()
    profile["enabled"] = False
    s["config"].autonext = AutoNextConfig(coordinator_mode=True, principal="codex")
    assert restore(b, profile) == active
    assert not b.config.autonext.enabled
    await s["start"]()
    assert b.autonext.worker is None
    assert not b.store.db.execute("SELECT 1 FROM tasks WHERE operation='agent.execute'").fetchone()


async def test_missing_unrelated_worktree_does_not_stop_eligible_task(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    s = scenario
    card, profile, *_ = setup(s, tmp_path, monkeypatch)
    missing = str(tmp_path / "retired-worktree")
    profile["continuation"]["allowed_cwds"].append(missing)
    append(s, {**card, "task_id": "retired.scope", "cwd": missing})
    intake = discover(s["bridge"], profile)
    assert intake["selected"]["card"].task_id == card["task_id"]
    assert intake["held"][0]["reason"] == "worktree_unavailable"


async def test_revoked_assignment_blocks_pinned_checks(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    s, b = scenario, scenario["bridge"]
    card, profile, team, anchor, _ = setup(s, tmp_path, monkeypatch)
    await runtime.advance(b, profile, team, anchor, None)
    await until(lambda: b.autonext.inspect()["state"] == "waiting")
    await b.autonext.stop()
    profile["continuation"]["sources"] = []
    runner = AsyncMock()
    monkeypatch.setattr(b.autonext, "_run_checks", runner)
    with pytest.raises(BridgeError, match="not assigned"):
        await b.autonext._guarded_checks(ReadyCard.model_validate(card))
    runner.assert_not_awaited()


def test_whiteboard_append_supports_platform_without_nofollow_flag(tmp_path, monkeypatch):
    (tmp_path / "threads").mkdir()
    (tmp_path / "whiteboard").mkdir()
    (tmp_path / "threads/board.json").write_text('{"id":"board"}')
    import os

    monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)
    result = append_whiteboard(
        str(tmp_path),
        "board",
        actor="fixture",
        actor_type="codex",
        entry_type="note",
        content="portable append",
    )
    assert read_whiteboard(str(tmp_path), "board", result["id"])["entry"]["content"] == (
        "portable append"
    )


async def test_source_revoked_between_checks_prevents_the_second_spawn(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    s, b = scenario, scenario["bridge"]
    card, profile, team, anchor, _ = setup(s, tmp_path, monkeypatch)
    await runtime.advance(b, profile, team, anchor, None)
    await until(lambda: b.autonext.inspect()["state"] == "waiting")
    await b.autonext.stop()
    marker = tmp_path / "must-not-exist"
    first = {"argv": [sys.executable, "-c", "pass"]}
    second = {"argv": [sys.executable, "-c", f"open({str(marker)!r},'w').write('bad')"]}
    calls = []

    def revoke_after_first():
        calls.append(True)
        if len(calls) == 2:
            raise BridgeError("continuation_source_changed", "source revoked")

    changed = ReadyCard.model_validate(
        {
            **card,
            "acceptance": {
                "kind": "coordinator_checks",
                "checks": [first, second],
            },
        }
    )
    with pytest.raises(BridgeError, match="source revoked"):
        await b.autonext._run_checks(changed, before_check=revoke_after_first)
    assert len(calls) == 2 and not marker.exists()


async def test_lost_claim_readback_reuses_the_shared_reservation(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    s, b = scenario, scenario["bridge"]
    _, profile, team, anchor, _ = setup(s, tmp_path, monkeypatch)
    import kirabridge.whiteboard_read as board

    touch = board._touch_thread

    def fail_after_append(_):
        raise OSError("fixture lost append confirmation")

    monkeypatch.setattr(board, "_touch_thread", fail_after_append)
    await runtime.advance(b, profile, team, anchor, None)
    await until(lambda: b.autonext.inspect()["state"] == "stopped")
    await b.autonext.stop()
    assert not b.store.db.execute("SELECT 1 FROM tasks WHERE operation='agent.execute'").fetchone()
    monkeypatch.setattr(board, "_touch_thread", touch)
    b.autonext._flush()
    claims = [
        row
        for row in board.read_whiteboard(str(s["desk"]), "board")["entries"]
        if row["entry_type"] == "progress"
    ]
    assert len(claims) == 1
    assert b.store.db.execute("SELECT claim_published FROM autonext_items").fetchone()[0] == 1
    assert b.autonext.inspect()["state"] == "stopped"  # Readback never restarts the original work.


async def test_unavailable_subscription_observation_does_not_crash_or_repeat_model_work(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    s, b = scenario, scenario["bridge"]
    _, profile, team, anchor, quota = setup(s, tmp_path, monkeypatch)
    quota.side_effect = TimeoutError
    active, intake = await runtime.advance(b, profile, team, anchor, None)
    assert intake["resource_stop"]["reason"] == "subscription_observation_unavailable"
    for _ in range(2):
        _, again = await runtime.advance(b, profile, team, anchor, active)
        assert again["resource_stop"] == intake["resource_stop"]
    assert quota.await_count == 1
    assert not b.store.db.execute("SELECT 1 FROM autonext_items").fetchone()
    assert not b.store.db.execute("SELECT 1 FROM tasks WHERE operation='agent.execute'").fetchone()
