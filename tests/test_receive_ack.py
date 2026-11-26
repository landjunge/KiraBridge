"""Receive hook: a successful chatgpt read acknowledges exactly the returned addressed messages."""

from test_message_overview import direct, team
from test_team_manager import domain as imported_domain

from kirabridge.message_overview import OBSERVE_CAPABILITY, observe

domain = imported_domain


def kira(domain):
    domain.config.principals["chatgpt"].capabilities.append(OBSERVE_CAPABILITY)


def stamps(domain):
    return (
        domain.store.db.execute(
            "SELECT seq,delivered,receipt,acknowledged FROM messages ORDER BY seq"
        ).fetchall()[:],
        domain.store.db.execute(
            "SELECT seq,acknowledged FROM team_messages ORDER BY seq"
        ).fetchall()[:],
    )


def test_read_acks_exactly_the_returned_chatgpt_messages(domain):
    kira(domain)
    direct(domain, "codex", "chatgpt", "d-kira", body="Frage an Kira")
    direct(domain, "codex", "grok", "d-grok", body="Nur fuer grok")
    team(domain, "codex", "chatgpt", "t-kira")
    result = observe(domain.bridge, "chatgpt")
    assert result["read_only"] is False
    assert result["acknowledged_by_read"] == {"direct": [1], "team": [1]}
    kira_row = domain.store.db.execute(
        "SELECT delivered,receipt,acknowledged FROM messages WHERE idem='d-kira'"
    ).fetchone()
    assert kira_row["delivered"] is not None and kira_row["receipt"]
    assert kira_row["acknowledged"] is not None
    other = domain.store.db.execute(
        "SELECT delivered,receipt,acknowledged FROM messages WHERE idem='d-grok'"
    ).fetchone()
    assert (other["delivered"], other["receipt"], other["acknowledged"]) == (None, None, None)


def test_delivery_is_recorded_before_the_acknowledgement(domain):
    kira(domain)
    direct(domain, "codex", "chatgpt", "d-order", body="Reihenfolge")
    observe(domain.bridge, "chatgpt")
    kinds = [
        row["kind"]
        for row in domain.store.db.execute(
            "SELECT kind FROM message_events WHERE message_id="
            "(SELECT id FROM messages WHERE idem='d-order') ORDER BY rowid"
        ).fetchall()
    ]
    assert kinds == ["message.queued", "message.delivered", "message.auto_acknowledged"]
    assert (
        domain.store.db.execute(
            "SELECT count(*) FROM team_events WHERE kind='team.message_auto_acknowledged'"
        ).fetchone()[0]
        == 0
    )


def test_messages_beyond_the_limit_stay_unacknowledged(domain):
    kira(domain)
    for index in range(3):
        team(domain, "codex", "chatgpt", f"t-{index}")
    result = observe(domain.bridge, "chatgpt", limit=1)
    assert result["count"] == 1
    assert len(result["acknowledged_by_read"]["team"]) == 1
    assert (
        domain.store.db.execute(
            "SELECT count(*) FROM team_messages WHERE acknowledged IS NULL"
        ).fetchone()[0]
        == 2
    )


def test_second_read_changes_nothing(domain):
    kira(domain)
    team(domain, "codex", "chatgpt", "t-idem")
    direct(domain, "codex", "chatgpt", "d-idem")
    first = observe(domain.bridge, "chatgpt")
    assert first["acknowledged_by_read"] == {"direct": [1], "team": [1]}
    before = stamps(domain)
    counts = (
        domain.store.db.execute("SELECT count(*) FROM message_events").fetchone()[0],
        domain.store.db.execute("SELECT count(*) FROM team_events").fetchone()[0],
        domain.store.db.execute("SELECT count(*) FROM audit").fetchone()[0],
    )
    second = observe(domain.bridge, "chatgpt")
    assert second["acknowledged_by_read"] == {"direct": [], "team": []}
    assert second["read_only"] is True and "ack_error" not in second
    assert stamps(domain) == before
    assert domain.store.db.execute("SELECT count(*) FROM message_events").fetchone()[0] == counts[0]
    assert domain.store.db.execute("SELECT count(*) FROM team_events").fetchone()[0] == counts[1]
    assert domain.store.db.execute("SELECT count(*) FROM audit").fetchone()[0] == counts[2]


def test_failed_acknowledgement_keeps_the_page_without_partial_ack(domain, monkeypatch):
    kira(domain)
    direct(domain, "codex", "chatgpt", "d-fail-1")
    direct(domain, "codex", "chatgpt", "d-fail-2")
    import kirabridge.message_overview as module

    original = module._event
    attempts = []

    def explode(store, message_id, kind, principal, evidence):
        if kind == "message.auto_acknowledged":
            attempts.append(message_id)
            if len(attempts) == 2:
                raise RuntimeError("simulated store failure")
        return original(store, message_id, kind, principal, evidence)

    monkeypatch.setattr(module, "_event", explode)
    result = observe(domain.bridge, "chatgpt")
    assert result["count"] == 2 and result["items"]
    assert result["ack_error"] == "auto_ack_failed"
    assert result["acknowledged_by_read"] == {"direct": [], "team": []}
    assert result["read_only"] is True
    for key in ("d-fail-1", "d-fail-2"):
        row = domain.store.db.execute(
            "SELECT delivered,receipt,acknowledged FROM messages WHERE idem=?", (key,)
        ).fetchone()
        assert (row["delivered"], row["receipt"], row["acknowledged"]) == (None, None, None)
    assert (
        domain.store.db.execute(
            "SELECT count(*) FROM message_events WHERE kind != 'message.queued'"
        ).fetchone()[0]
        == 0
    )
    assert (
        domain.store.db.execute(
            "SELECT count(*) FROM audit WHERE kind='message.delivered'"
        ).fetchone()[0]
        == 0
    )


def test_message_body_never_reaches_events_or_audit(domain):
    kira(domain)
    secret = "Streng vertraulicher Text 42"
    direct(domain, "codex", "chatgpt", "d-body", body=secret)
    team(domain, "codex", "chatgpt", "t-body", body=secret)
    result = observe(domain.bridge, "chatgpt")
    assert result["acknowledged_by_read"] == {"direct": [1], "team": [1]}
    assert all(
        secret not in row["evidence"]
        for row in domain.store.db.execute("SELECT evidence FROM message_events")
    )
    assert all(
        secret not in row["metadata"]
        for row in domain.store.db.execute("SELECT metadata FROM team_events")
    )
    assert all(
        secret not in row["metadata"]
        for row in domain.store.db.execute("SELECT metadata FROM audit")
    )
