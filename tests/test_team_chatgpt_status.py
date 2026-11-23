"""Durable, redacted per-work review and state reports in the normal team inbox."""

import sqlite3

import pytest
from test_team_continuation import Owner, finish, pinned, select
from test_team_coordinator_roles import TEAM, record, setup_team
from test_team_manager import core, role, work
from test_team_manager import domain as imported_domain

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.team_manager import continuation
from kirabridge.team_manager.models import TeamRoleSet, TeamWorkComplete

domain = imported_domain
TEAM_ID = "test-team"


def manual_completed(domain, key="manual-work"):
    pending = domain.delegate(
        "local", work(assignee="local", idempotency_key=key, body="PRIVATE PLAN")
    )
    original = domain.work_complete(
        "local",
        TeamWorkComplete(
            team_id=TEAM_ID,
            work_id=pending["id"],
            idempotency_key="finish-" + key,
            result="PRIVATE RESULT",
        ),
    )
    return original["id"]


def inbox(domain, team=TEAM_ID):
    return [
        row for row in domain.messages("chatgpt", team)["messages"] if row["recipient"] == "chatgpt"
    ]


def test_terminal_report_survives_crash_and_uses_current_authorized_role(domain, monkeypatch):
    role(domain, "codex", "coordinator")
    original = manual_completed(domain)
    before = domain.chatgpt_status._remember_status

    def stop_after_message(*_args):
        raise sqlite3.OperationalError("simulated interruption")

    monkeypatch.setattr(domain.chatgpt_status, "_remember_status", stop_after_message)
    with pytest.raises(sqlite3.OperationalError):
        domain.publish_chatgpt_status()
    assert not inbox(domain)
    # The event and Work state committed separately from the interrupted publish.
    assert domain._work(original)["state"] == "completed"
    monkeypatch.setattr(domain.chatgpt_status, "_remember_status", before)
    role(domain, "grok", "coordinator")
    reopened = Bridge(domain.config)
    try:
        assert reopened.teams.publish_chatgpt_status() == 1
        assert reopened.teams.publish_chatgpt_status() == 0
        (notice,) = inbox(reopened.teams)
        assert notice["sender"] == "grok" and notice["kind"] == "note"
        assert original in notice["body"]
        assert "Ergebnis liegt vor" in notice["body"]
        assert "Fachliche Prüfung steht aus" in notice["body"]
        assert "PRIVATE" not in notice["body"]
        assert notice["acknowledged"] is None
        receipt = reopened.store.db.execute(
            "SELECT object_id FROM team_operations WHERE operation='chatgpt_status'",
        ).fetchone()
        assert receipt["object_id"] == notice["id"]
    finally:
        reopened.store.close()


def test_no_report_to_own_role_or_when_audience_was_absent(domain):
    assert domain.get("local", TEAM_ID)["coordinator"] == "chatgpt"
    own = manual_completed(domain, "own")
    assert domain.publish_chatgpt_status() == 0
    role(domain, "codex", "coordinator")
    role(domain, "chatgpt", "worker", active=False)
    absent = manual_completed(domain, "absent")
    assert domain.publish_chatgpt_status() == 0
    role(domain, "chatgpt", "worker")
    assert domain.publish_chatgpt_status() == 0
    queued = manual_completed(domain, "queued")
    role(domain, "chatgpt", "worker", active=False, key="deactivate-again")
    assert domain.publish_chatgpt_status() == 0
    role(domain, "chatgpt", "worker", key="return")
    assert domain.publish_chatgpt_status() == 1
    (notice,) = inbox(domain)
    assert queued in notice["body"]
    assert own not in notice["body"] and absent not in notice["body"]


def test_historical_event_and_core_claim_without_start_are_silent(domain):
    role(domain, "codex", "coordinator")
    historic = manual_completed(domain, "historic")
    domain.store.db.execute(
        "UPDATE team_events SET metadata='{}' WHERE object_id=?",
        (historic,),
    )
    assert domain.publish_chatgpt_status() == 0
    pending = domain.delegate("local", work(assignee="codex"))
    claimed = domain.claim(pending["id"])
    assert domain.publish_chatgpt_status() == 0
    observed = core(domain, claimed, state="running", receipt="actual-receipt")
    observed["evidence"] = {"event": "thread.started", "session_id": "agent-session"}
    domain.bind_task(pending["id"], observed)
    assert domain.publish_chatgpt_status() == 0
    observed["evidence"]["event"] = "turn.started"
    domain.bind_task(pending["id"], observed)
    assert domain.publish_chatgpt_status() == 1
    assert domain.publish_chatgpt_status() == 0
    assert "nachweisbar gestartet" in inbox(domain)[0]["body"]


async def test_dispatcher_publishes_status_during_long_running_turn(domain, monkeypatch):
    role(domain, "codex", "coordinator")
    pending = domain.delegate("local", work(assignee="codex"))
    claimed = domain.claim(pending["id"])
    observed = core(
        domain,
        claimed,
        state="running",
        receipt="started-receipt",
        evidence={"event": "turn.started", "session_id": "codex-session"},
    )
    dispatcher = domain.bridge.team_dispatcher

    async def poll(_pool, task_id):
        assert task_id == claimed["core_task_id"]
        assert domain._work(claimed["id"])["state"] == "running"
        (started,) = inbox(domain)
        assert "nachweisbar gestartet" in started["body"]
        return {**observed, "state": "failed"}

    monkeypatch.setattr(dispatcher, "_task", poll)
    await dispatcher._observe(None, claimed, observed, 1)
    assert domain._work(claimed["id"])["state"] == "failed"


async def test_only_verified_review_claims_factual_success_and_links_followup(domain, monkeypatch):
    setup_team(domain, coordinator="codex")
    record(domain, "codex")
    domain.set_role(
        "local",
        TeamRoleSet(
            team_id=TEAM,
            member="chatgpt",
            role="worker",
            expected_revision=domain.get("local", TEAM)["revision"],
            idempotency_key="add-chatgpt",
        ),
    )
    owner = Owner()
    a, b = owner.entry("product-a", "first"), owner.entry("product-b", "second")
    pinned(domain, [a, b])
    monkeypatch.setattr(continuation, "read_thread_desk", owner.read)
    first = await select(domain)
    finish(domain, first["id"], "PRIVATE RESULT", "grok-session")
    assert domain.publish_chatgpt_status() == 1
    assert "Fachliche Prüfung steht aus" in inbox(domain, TEAM)[0]["body"]
    assert domain.resume_coordinators() == 1
    review = domain.store.db.execute(
        "SELECT resume_work_id FROM team_coordinator_resumes WHERE work_id=?", (first["id"],)
    ).fetchone()["resume_work_id"]
    finish(domain, review, continuation.TeamContinuation.marker(first["id"]), "codex-session")
    second = await select(domain)
    assert second
    assert domain.publish_chatgpt_status() == 1
    accepted = inbox(domain, TEAM)[-1]
    assert "fachlich abgenommen" in accepted["body"]
    assert first["id"] in accepted["body"] and second["id"] in accepted["body"]
    claimed = domain.claim(second["id"])
    observed = core(
        domain,
        claimed,
        state="running",
        receipt="started-receipt",
        evidence={"event": "turn.started", "session_id": "grok-session"},
    )
    domain.bind_task(second["id"], observed)
    assert domain.publish_chatgpt_status() == 1
    started = inbox(domain, TEAM)[-1]
    assert f"Folgeauftrag {second['id']} zu {first['id']}" in started["body"]
    assert all("PRIVATE" not in row["body"] for row in inbox(domain, TEAM))
