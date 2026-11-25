"""The coordinator role reaches the registered member's inbox even without a bound session."""

import pytest
from test_team_manager import create, message
from test_team_manager import domain as imported_domain

from kirabridge.bridge_core.models import BridgeError
from kirabridge.message_manager import MessageSend
from kirabridge.team_manager.models import TeamRoleSet

domain = imported_domain
TEAM = "test-team"  # created by the fixture, coordinator chatgpt


def allow_direct(domain):
    for principal in ("chatgpt", "codex", "grok"):
        policy = domain.config.principals[principal]
        policy.capabilities = list(set(policy.capabilities) | {"message.send", "message.read"})
        policy.message_peers = ["chatgpt", "codex", "grok", "local"]


def send_direct(domain, key, recipient="coordinator", kind="work", sender="chatgpt"):
    return domain.bridge.messages.send(
        sender,
        MessageSend(
            recipient=recipient,
            conversation_id=key,
            idempotency_key=key,
            kind=kind,
            body="Bericht an den Koordinator",
        ),
    )


def stored(domain, key):
    return domain.store.db.execute(
        "SELECT id,recipient FROM messages WHERE idem=?", (key,)
    ).fetchone()


def set_coordinator(domain, principal, member, key, team_id=TEAM):
    return domain.set_role(
        principal,
        TeamRoleSet(
            team_id=team_id,
            member=member,
            role="coordinator",
            expected_revision=domain.get(principal, team_id)["revision"],
            idempotency_key=key,
        ),
    )


def test_role_message_is_stored_for_the_registered_coordinator_without_a_session(domain):
    set_coordinator(domain, "local", "codex", "to-codex")
    allow_direct(domain)
    send_direct(domain, "inbox-route")  # kind=work would normally start an agent job
    row = stored(domain, "inbox-route")
    assert row["recipient"] == "codex"
    assert (
        domain.store.db.execute(
            "SELECT count(*) FROM message_jobs WHERE message_id=?", (row["id"],)
        ).fetchone()[0]
        == 0
    ), "an inbox-only route must never drive an agent"


def test_switching_the_role_redirects_the_next_message_at_once(domain):
    set_coordinator(domain, "local", "codex", "to-codex")
    allow_direct(domain)
    send_direct(domain, "before-switch")
    set_coordinator(domain, "local", "grok", "to-grok")
    send_direct(domain, "after-switch")
    assert stored(domain, "before-switch")["recipient"] == "codex"
    assert stored(domain, "after-switch")["recipient"] == "grok"


def test_two_distinct_coordinators_stay_ambiguous(domain):
    allow_direct(domain)
    domain.create(
        "local",
        create(
            team_id="team-b",
            coordinator="grok",
            members={"local": "worker", "codex": "worker", "grok": "coordinator"},
            idempotency_key="create-b",
        ),
    )
    with pytest.raises(BridgeError) as caught:
        send_direct(domain, "two-holders", sender="codex")
    assert caught.value.code == "coordinator_ambiguous"


def test_member_with_team_manage_can_claim_the_role_only_when_listed_as_candidate(domain):
    with pytest.raises(BridgeError) as unlisted:
        set_coordinator(domain, "grok", "grok", "grok-unlisted")
    assert unlisted.value.code == "team_role_denied"  # team.manage alone is not enough
    domain.config.team.coordinator_candidates = ["grok"]
    view = set_coordinator(domain, "grok", "grok", "grok-claims")
    assert view["coordinator"] == "grok"
    with pytest.raises(BridgeError) as other_member:
        set_coordinator(domain, "codex", "codex", "codex-unlisted")
    assert other_member.value.code == "team_role_denied"


def test_claiming_needs_team_manage_and_only_works_for_oneself(domain):
    domain.config.team.coordinator_candidates = ["grok", "codex"]
    with pytest.raises(BridgeError) as for_other:
        set_coordinator(domain, "grok", "codex", "grok-claims-for-codex")  # not itself
    assert for_other.value.code == "team_role_denied"
    policy = domain.config.principals["grok"]
    policy.capabilities = [item for item in policy.capabilities if item != "team.manage"]
    with pytest.raises(BridgeError) as without_capability:
        set_coordinator(domain, "grok", "grok", "grok-without-manage")
    assert without_capability.value.code == "team_role_denied"
    assert domain.get("local", TEAM)["coordinator"] == "chatgpt"


def test_coordinator_only_sender_reaches_only_the_coordinator_by_direct_message(domain):
    set_coordinator(domain, "local", "codex", "to-codex")
    allow_direct(domain)
    domain.config.team.coordinator_only_senders = ["chatgpt"]
    send_direct(domain, "chatgpt-to-grok", recipient="grok", kind="note")
    assert stored(domain, "chatgpt-to-grok")["recipient"] == "codex"
    assert not domain.store.db.execute("SELECT 1 FROM messages WHERE recipient='grok'").fetchone()
    # Other senders keep addressing peers directly.
    send_direct(domain, "codex-to-grok", recipient="grok", kind="note", sender="codex")
    assert stored(domain, "codex-to-grok")["recipient"] == "grok"


def test_coordinator_only_sender_reaches_only_the_coordinator_by_team_message(domain):
    set_coordinator(domain, "local", "codex", "to-codex")
    domain.config.team.coordinator_only_senders = ["chatgpt"]
    domain.send("chatgpt", message(team_id=TEAM, recipient="grok", idempotency_key="team-1"))
    rows = domain.store.db.execute(
        "SELECT recipient FROM team_messages WHERE sender='chatgpt'"
    ).fetchall()
    assert [row["recipient"] for row in rows] == ["codex"]
