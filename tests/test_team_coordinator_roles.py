"""Exercise the persisted team role and its exact, sealed session transfer."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from test_team_manager import core, create, message, work
from test_team_manager import domain as imported_domain

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import AgentConfig, TeamWorkerConfig
from kirabridge.bridge_core.models import BridgeError
from kirabridge.team_manager.models import TeamCoordinatorHandoff

domain = imported_domain

TEAM = "auto-coordinator"


def setup_team(domain, coordinator=None):
    root = domain.config.principals["local"].roots[0]
    for principal in ("codex", "grok"):
        domain.config.principals[principal].agents = [principal]
        domain.config.team.workers[principal] = TeamWorkerConfig(
            agent=principal, cwd=root, execution_scope="separate_managed_session"
        )
    domain.create(
        "local",
        create(
            team_id=TEAM,
            coordinator=coordinator,
            members={"local": "worker", "grok": "worker", "codex": "worker"},
        ),
    )


def record(domain, principal, *, session=None, state="completed", key=None):
    session = session or principal + "-session"
    pending = domain.delegate(
        "local", work(team_id=TEAM, assignee=principal, idempotency_key=key or session)
    )
    claimed = domain.claim(pending["id"])
    evidence = {"adapter": domain.config.agents[principal].kind, "session_id": session}
    observed = core(domain, claimed, state=state, evidence=evidence)
    domain.bind_task(pending["id"], observed)
    if state == "completed":
        domain.finish(pending["id"], "Finished observation", {"session_id": session})
    return pending["id"]


def status(domain, principal="local"):
    return domain.coordinator_status(principal, TEAM)


def handoff(domain, principal="grok", *, key="handoff"):
    snapshot = status(domain)
    target = next(s for s in snapshot["candidates"] if s["principal"] == principal)
    return TeamCoordinatorHandoff(
        team_id=TEAM,
        principal=principal,
        session_id=target["session_id"],
        generation=target["generation"],
        expected_revision=snapshot["revision"],
        idempotency_key=key,
        work_state="Investigate and preserve the started project",
    )


def finish(domain, transfer, reply=None, session=None):
    claim = domain.claim(transfer["work_id"])
    assert claim["resume_session"] == transfer["session_id"]
    result = reply or "ACCEPT COORDINATOR " + transfer["id"]
    observed = core(
        domain,
        claim,
        evidence={"adapter": "codex", "session_id": session or transfer["session_id"]},
        result={"success": True, "text": result},
    )
    domain.bind_task(claim["id"], observed)
    return domain.finish(claim["id"], result, {"model_turn_completed": True})


def role_message(domain, key):
    return domain.send("local", message(team_id=TEAM, recipient="coordinator", idempotency_key=key))


def test_first_eligible_session_is_elected_once_under_concurrent_start_and_persists(domain):
    setup_team(domain)
    assert status(domain)["coordinator"] is None
    with pytest.raises(BridgeError) as caught:
        role_message(domain, "unassigned")
    assert caught.value.code == "team_coordinator_unassigned"

    def observe(principal):
        reopened = Bridge(domain.config)
        try:
            record(reopened.teams, principal)
        finally:
            reopened.store.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(observe, ("codex", "grok")))
    observed = status(domain)
    assert observed["coordinator"] in {"codex", "grok"}
    assert observed["session"]["principal"] == observed["coordinator"]
    assert observed["revision"] == 2
    actual = domain.get("local", TEAM)
    assert sum(member["role"] == "coordinator" for member in actual["members"].values()) == 1
    reopened = Bridge(domain.config)
    try:
        assert status(reopened.teams)["session"] == observed["session"]
    finally:
        reopened.store.close()


def test_confirmed_handoff_restarts_without_promoting_then_changes_role_route(domain):
    setup_team(domain, coordinator="codex")
    record(domain, "codex")
    record(domain, "grok")
    original = role_message(domain, "old")
    request = handoff(domain)
    transfer = domain.request_coordinator_handoff("local", request)
    assert transfer["state"] == "pending"
    assert status(domain)["pending"]["id"] == transfer["id"]
    assert role_message(domain, "during")["recipient"] == "codex"
    with pytest.raises(BridgeError) as foreign:
        domain.request_coordinator_handoff("grok", request)
    assert foreign.value.code == "team_role_denied"

    reopened = Bridge(domain.config)
    try:
        assert status(reopened.teams)["coordinator"] == "codex"
        assert status(reopened.teams)["pending"]["id"] == transfer["id"]
        finish(reopened.teams, transfer)
        active = status(reopened.teams)
        assert active["coordinator"] == "grok"
        assert active["session"]["session_id"] == "grok-session"
        assert active["pending"] is None
        assert active["last_handoff"]["state"] == "accepted"
        assert role_message(reopened.teams, "new")["recipient"] == "grok"
        assert role_message(reopened.teams, "old") == original
        assert reopened.teams.request_coordinator_handoff("local", request)["state"] == "accepted"
        roles = reopened.teams.get("local", TEAM)["members"]
        assert roles["codex"]["role"] == "worker"
        assert roles["grok"]["role"] == "coordinator"
    finally:
        reopened.store.close()


@pytest.mark.parametrize("mode", ["bare_ack", "foreign_session"])
def test_naked_ack_or_wrong_session_never_changes_role(domain, mode):
    setup_team(domain, coordinator="codex")
    record(domain, "codex")
    record(domain, "grok")
    transfer = domain.request_coordinator_handoff("local", handoff(domain))
    if mode == "bare_ack":
        finish(domain, transfer, reply="ACK")
    else:
        finish(domain, transfer, session="foreign")
    assert status(domain)["coordinator"] == "codex"
    assert status(domain)["last_handoff"]["state"] == "not_accepted"


def test_concurrent_handoffs_cannot_bypass_revision_or_replace_ongoing_handoff(domain):
    setup_team(domain, coordinator="codex")
    record(domain, "codex")
    record(domain, "grok")
    request = handoff(domain)
    transfer = domain.request_coordinator_handoff("local", request)
    with pytest.raises(BridgeError) as busy:
        domain.request_coordinator_handoff(
            "local", request.model_copy(update={"idempotency_key": "competing"})
        )
    assert busy.value.code == "team_coordinator_handoff_pending"
    with pytest.raises(BridgeError) as wrong:
        domain.request_coordinator_handoff(
            "local", request.model_copy(update={"idempotency_key": "stale", "expected_revision": 1})
        )
    assert wrong.value.code == "team_revision_conflict"
    # A legitimate role change invalidates the preserved handoff revision.
    team = domain.get("local", TEAM)
    from kirabridge.team_manager.models import TeamRoleSet

    domain.set_role(
        "local",
        TeamRoleSet(
            team_id=TEAM,
            member="grok",
            role="reviewer",
            expected_revision=team["revision"],
            idempotency_key="change-worker",
        ),
    )
    assert domain.claim(transfer["work_id"]) is None
    assert status(domain)["last_handoff"]["state"] == "not_accepted"
    assert status(domain)["coordinator"] == "codex"


def test_parallel_claude_sessions_are_distinct_without_provider_model_claim(domain):
    setup_team(domain)
    root = domain.config.principals["local"].roots[0]
    domain.config.agents["grok"] = AgentConfig(kind="claude_code", model="opus")
    domain.config.team.workers["grok"] = TeamWorkerConfig(
        agent="grok", cwd=root, execution_scope="separate_managed_session"
    )
    first = record(domain, "grok", session="claude-1", state="running")
    second = record(domain, "grok", session="claude-2", state="running")
    rows = {row["session_id"]: row for row in status(domain)["inventory"]}
    assert set(rows) == {"claude-1", "claude-2"}
    assert [rows[k]["work_id"] for k in ("claude-1", "claude-2")] == [first, second]
    for row in rows.values():
        assert row["state"] == "running"
        assert row["core_task_id"] and row["observed_at"]
        assert row["model"] is None and row["requested_model"] == "opus"
    domain.fail(first, "unknown", "provider_unknown", {})
    rows = {row["session_id"]: row for row in status(domain)["inventory"]}
    assert rows["claude-1"]["state"] == "unknown"
    assert rows["claude-2"]["state"] == "running"
    assert status(domain)["candidates"] == []


def test_managed_notification_uses_exact_session_and_records_real_ack(domain):
    setup_team(domain)
    record(domain, "grok")
    stored = role_message(domain, "once")
    duplicate = role_message(domain, "once")
    assert duplicate["id"] == stored["id"]
    notification = domain.store.db.execute(
        "SELECT work_id FROM team_coordinator_notifications WHERE message_id=?",
        (stored["id"],),
    ).fetchone()
    claim = domain.claim(notification["work_id"])
    assert claim["resume_session"] == "grok-session"
    assert domain._message(TEAM, stored["id"])["acknowledged"] is None
    result = "ACK COORDINATOR MESSAGE " + stored["id"] + "\nA completed reply."
    observed = core(
        domain,
        claim,
        evidence={"adapter": "codex", "session_id": "grok-session"},
        result={"success": True, "text": result},
    )
    domain.bind_task(claim["id"], observed)
    domain.finish(claim["id"], result, {"model_turn_completed": True})
    original = domain._message(TEAM, stored["id"])
    assert original["acknowledged"] is not None
    replies = [
        item
        for item in domain.messages("local", TEAM)["messages"]
        if item["reply_to"] == original["id"]
    ]
    assert len(replies) == 1
    assert replies[0]["recipient"] == "local" and replies[0]["body"] == "A completed reply."


def test_authorized_status_does_not_offer_write_controls_to_read_only_owner(domain):
    setup_team(domain)
    record(domain, "codex")
    owner = domain.config.principals["local"]
    owner.capabilities = ["team.read"]
    observed = status(domain)
    assert observed["coordinator"] == "codex"
    assert observed["can_manage"] is False
    assert observed["inventory"][0]["session_id"] == "codex-session"
