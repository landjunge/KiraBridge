"""team send is the one send path: it hands a ticket to the delivery machine, once."""

import time

import pytest
from test_team_manager import domain as imported_domain
from test_team_manager import message, role

from kirabridge.bridge_core.config import (
    AgentConfig,
    ReceiverConfig,
    VisibleHandoffConfig,
    VisibleTerminalBinding,
)
from kirabridge.bridge_core.models import BridgeError
from kirabridge.message_manager import MessageSend
from kirabridge.message_overview import inbox

domain = imported_domain


def wire(domain, *names):
    domain.config.visible_handoffs = VisibleHandoffConfig(
        bindings={
            name: VisibleTerminalBinding(
                pane_id="terminal:1:ttys001", expected_pid=1, agent_pid=2, ready_pattern="ready"
            )
            for name in names
        }
    )
    for name in ("codex", "grok", "local", "chatgpt"):
        domain.config.messaging.receivers[name] = ReceiverConfig(
            cwd=domain.config.principals["local"].roots[0], timeout=3
        )
        domain.config.agents.setdefault(name, AgentConfig(kind="codex"))
        policy = domain.config.principals[name]
        policy.agents = sorted(set(policy.agents) | {name})
        policy.capabilities = list(set(policy.capabilities) | {"message.send", "message.read"})
        policy.capabilities = list(set(policy.capabilities) | {"agent.execute"})
        policy.message_peers = ["chatgpt", "codex", "grok", "local"]


def tickets(domain):
    return domain.store.db.execute(
        "SELECT * FROM messages WHERE idem LIKE 'team:%' ORDER BY seq"
    ).fetchall()


def to_coordinator(domain, key, sender="grok"):
    return domain.send(sender, message(recipient="coordinator", idempotency_key=key))


def test_message_to_the_coordinator_creates_exactly_one_hidden_ticket(domain):
    wire(domain, "chatgpt")  # chatgpt is the coordinator of the test team
    sent = to_coordinator(domain, "k1")
    to_coordinator(domain, "k1")  # replay
    rows = tickets(domain)
    assert len(rows) == 1
    assert rows[0]["idem"] == "team:" + sent["id"] and rows[0]["recipient"] == "chatgpt"
    assert all(i["id"] != rows[0]["id"] for i in inbox(domain.bridge, "chatgpt")["items"])


def test_role_change_moves_the_delivery_target(domain):
    wire(domain, "chatgpt", "grok")
    to_coordinator(domain, "k2", sender="codex")
    role(domain, "grok", "coordinator")
    to_coordinator(domain, "k3", sender="codex")
    assert [r["recipient"] for r in tickets(domain)] == ["chatgpt", "grok"]


def test_coordinator_without_a_terminal_binding_keeps_the_message_in_the_inbox(domain):
    wire(domain, "grok")
    sent = to_coordinator(domain, "k4")
    assert tickets(domain) == []
    assert domain.messages("chatgpt", "test-team")["messages"][-1]["id"] == sent["id"]


def test_ticket_and_coordinator_notification_never_both_fire(domain, monkeypatch):
    wire(domain, "chatgpt")
    calls = []
    monkeypatch.setattr(
        type(domain.coordinator_roles), "queue_notification", lambda *a, **k: calls.append(a)
    )
    to_coordinator(domain, "k5")
    assert calls == [] and len(tickets(domain)) == 1


def test_non_members_get_no_message_and_no_ticket(domain):
    wire(domain, "chatgpt")
    with pytest.raises(BridgeError):
        domain.send("outsider", message(recipient="coordinator", idempotency_key="k6"))
    assert tickets(domain) == []


def test_message_to_a_bound_worker_creates_one_ticket_and_replay_none(domain):
    wire(domain, "grok")
    sent = domain.send("local", message(recipient="grok", idempotency_key="w1"))
    domain.send("local", message(recipient="grok", idempotency_key="w1"))
    rows = tickets(domain)
    assert [r["idem"] for r in rows] == ["team:" + sent["id"]]
    assert rows[0]["recipient"] == "grok"


def test_worker_without_terminal_and_non_members_get_no_ticket(domain):
    wire(domain, "grok")
    domain.send("local", message(recipient="codex", idempotency_key="w2"))  # codex: own wake
    with pytest.raises(BridgeError):
        domain.send("outsider", message(recipient="grok", idempotency_key="w3"))
    assert tickets(domain) == []


def test_message_send_alias_lands_in_the_team_log_with_one_ticket(domain):
    wire(domain, "grok")
    request = MessageSend(
        recipient="grok", conversation_id="c", idempotency_key="a1", body="hi", kind="note"
    )
    stored = domain.alias_send("local", request)
    assert stored["deprecated"] and stored["team_id"] == "test-team"
    assert domain.alias_send("local", request)["id"] == stored["id"]
    assert len(tickets(domain)) == 1


def test_message_send_alias_keeps_the_legacy_path_where_no_ticket_delivers(domain):
    wire(domain, "grok")
    for recipient in ("codex", "unknown", "local"):
        request = MessageSend(
            recipient=recipient, conversation_id="c", idempotency_key="a2", body="hi"
        )
        assert domain.alias_send("local", request) is None


def test_delivery_outcome_is_written_back_to_the_team_log(domain):
    wire(domain, "chatgpt")
    sent = to_coordinator(domain, "k7")
    ticket = tickets(domain)[0]
    with domain.store.transaction():
        domain.bridge.message_receiver._finish(ticket["id"], "completed", {})
    event = domain.store.db.execute(
        "SELECT kind,object_id FROM team_events WHERE kind LIKE 'team.message_deliver%'"
    ).fetchone()
    assert tuple(event) == ("team.message_delivered", sent["id"])
    assert domain.messages("chatgpt", "test-team")["messages"][-1]["acknowledged"] is None


def test_the_local_binding_matches_the_claude_process(domain):
    from kirabridge.session_manager import SessionManager

    binding = VisibleTerminalBinding(
        pane_id="terminal:1:ttys001", expected_pid=10, agent_pid=11, ready_pattern="❯"
    )
    selected = {
        "pane_id": "terminal:1:ttys001",
        "expected_pid": 10,
        "processes": [{"pid": 11, "name": "claude"}],
    }
    assert SessionManager.binding_matches(selected, binding, "local")
    assert not SessionManager.binding_matches(selected, binding, "grok")


def test_ticket_to_the_coordinator_always_gets_a_job_even_when_presence_is_not_live(domain):
    from kirabridge.bridge_core.models import canonical

    wire(domain, "grok")
    domain.config.team.coordinator_only_senders = ["chatgpt"]
    role(domain, "grok", "coordinator")
    # Dead or unobserved pane: presence flaps, so the ticket still gets its job and waits
    # unsent in the receiver (it observes the exact binding itself before any input).
    domain.send("chatgpt", message(recipient="coordinator", idempotency_key="live0"))
    assert len(tickets(domain)) == 1
    assert domain.store.db.execute("SELECT count(*) FROM message_jobs").fetchone()[0] == 1
    binding = domain.config.visible_handoffs.bindings["grok"]
    domain.store.db.execute(
        "INSERT INTO receiver_presence VALUES(?,?,?,?,?)",
        ("grok", "available", canonical(binding.model_dump()), "{}", time.time()),
    )
    domain.send("chatgpt", message(recipient="coordinator", idempotency_key="live1"))
    assert len(tickets(domain)) == 2
    assert domain.store.db.execute("SELECT count(*) FROM message_jobs").fetchone()[0] == 2


def test_tickets_never_appear_in_message_receive_get_or_overview(domain):
    wire(domain, "chatgpt")
    sent = to_coordinator(domain, "r1")
    ticket = tickets(domain)[0]
    assert domain.bridge.messages.receive("chatgpt")["messages"] == []
    with pytest.raises(BridgeError):
        domain.alias_get("chatgpt", ticket["id"])
    assert all(i["id"] != ticket["id"] for i in inbox(domain.bridge, "chatgpt")["items"])
    assert domain.alias_get("chatgpt", sent["id"])["id"] == sent["id"]


def test_message_ack_on_a_team_message_is_the_team_ack(domain):
    wire(domain, "chatgpt")
    sent = to_coordinator(domain, "r2")
    acked = domain.alias_ack("chatgpt", sent["id"])
    assert acked["acknowledged"] is not None
    assert domain.alias_ack("chatgpt", "legacy-uuid") is None


def test_terminal_bound_coordinator_route_validates_and_still_detects_a_change(domain):
    import json

    wire(domain, "grok")
    domain.config.team.coordinator_only_senders = ["chatgpt"]
    role(domain, "grok", "coordinator")
    domain.send("chatgpt", message(recipient="coordinator", idempotency_key="v1"))
    ticket = tickets(domain)[0]
    queued = json.loads(
        domain.store.db.execute(
            "SELECT evidence FROM message_events WHERE message_id=? AND kind='message.queued'",
            (ticket["id"],),
        ).fetchone()[0]
    )
    assert queued["recipient_role"] == "coordinator"
    assert queued["coordinator_session_sha256"] is None  # no session record: binding only
    current = {
        "principal": "grok",
        "session": None,
        "team_id": queued["coordinator_scope_team_id"],
        "revision": queued["coordinator_role_revision"],
    }
    direct = domain.bridge.message_receiver.direct
    domain.bridge.messages.coordinator_resolver = lambda: dict(current)
    direct._verify_coordinator_route(dict(ticket))  # unchanged: accepted
    for change in ({"principal": "codex"}, {"revision": current["revision"] + 1}):
        domain.bridge.messages.coordinator_resolver = lambda change=change: {**current, **change}
        with pytest.raises(BridgeError) as moved:
            direct._verify_coordinator_route(dict(ticket))
        assert moved.value.code == "coordinator_route_changed"


def test_team_ack_closes_the_delivery_ticket_so_it_is_never_typed_again(domain):
    """Ticket waits (no live presence); the agent reads+acks the team message; the ticket ends."""
    wire(domain, "chatgpt")
    sent = to_coordinator(domain, "ack-closes")
    ticket = tickets(domain)[0]
    assert ticket["acknowledged"] is None
    domain.alias_ack("chatgpt", sent["id"])
    row = domain.store.db.execute(
        "SELECT acknowledged FROM messages WHERE id=?", (ticket["id"],)
    ).fetchone()
    assert row["acknowledged"] is not None  # receiver._claim now finishes it as acknowledged


def test_auto_ack_by_inbox_read_closes_the_delivery_ticket(domain):
    wire(domain, "chatgpt")
    domain.config.team.auto_ack_on_observe = ["grok"]
    to_coordinator(domain, "auto-closes", sender="grok")
    ticket = tickets(domain)[0]
    from kirabridge.message_overview import auto_acknowledge

    items = inbox(domain.bridge, "chatgpt")["items"]
    assert items
    auto_acknowledge(domain.bridge, "chatgpt", items)
    row = domain.store.db.execute(
        "SELECT acknowledged FROM messages WHERE id=?", (ticket["id"],)
    ).fetchone()
    assert row["acknowledged"] is not None


def _fail_ticket_once(domain, monkeypatch):
    real = domain.bridge.messages.send

    def refuse(*args, **kwargs):
        raise BridgeError("receiver_unavailable", "draining")

    monkeypatch.setattr(domain.bridge.messages, "send", refuse)
    return real


def test_replay_restores_a_ticket_lost_in_the_install_or_drain_window(domain, monkeypatch):
    wire(domain, "chatgpt")
    real = _fail_ticket_once(domain, monkeypatch)
    first = to_coordinator(domain, "lost-ticket")
    assert tickets(domain) == []  # message stored, ticket refused (draining)
    monkeypatch.setattr(domain.bridge.messages, "send", real)
    again = to_coordinator(domain, "lost-ticket")  # the caller retries with the same key
    assert again["id"] == first["id"]
    assert len(tickets(domain)) == 1
    to_coordinator(domain, "lost-ticket")
    assert len(tickets(domain)) == 1  # never a second one


def test_restore_tickets_at_start_is_idempotent_and_skips_acknowledged_and_old(domain, monkeypatch):
    wire(domain, "chatgpt")
    real = _fail_ticket_once(domain, monkeypatch)
    open_one = to_coordinator(domain, "r-open")
    acked = to_coordinator(domain, "r-acked")
    old = to_coordinator(domain, "r-old")
    monkeypatch.setattr(domain.bridge.messages, "send", real)
    domain.alias_ack("chatgpt", acked["id"])
    domain.store.db.execute(
        "UPDATE team_messages SET created=? WHERE id=?", (time.time() - 10**6, old["id"])
    )
    domain.restore_tickets()
    domain.restore_tickets()
    assert [t["idem"] for t in tickets(domain)] == ["team:" + open_one["id"]]


def test_start_admits_a_pristine_queued_ticket_once_not_a_waiting_one(domain, monkeypatch):
    wire(domain, "chatgpt")
    to_coordinator(domain, "pristine")
    to_coordinator(domain, "waiting")
    pristine, waiting = tickets(domain)
    domain.store.db.execute(
        "INSERT OR IGNORE INTO message_jobs(message_id,state) VALUES(?,'queued')", (pristine["id"],)
    )
    domain.store.db.execute(
        "INSERT OR REPLACE INTO message_jobs(message_id,state,evidence) VALUES(?,'queued',?)",
        (waiting["id"], '{"waiting_for_visible_target": true}'),
    )
    submitted = []
    receiver = domain.bridge.message_receiver
    monkeypatch.setattr(receiver, "_submit_new", lambda p, m: submitted.append(m))
    receiver._admit_pristine_tickets()
    assert submitted == [pristine["id"]]


def test_team_prefix_idempotency_key_is_reserved_for_internal_tickets(domain):
    with pytest.raises(ValueError):
        MessageSend(
            recipient="grok", conversation_id="c", idempotency_key="team:x", body="b", kind="note"
        )
    # the internal ticket path still works
    wire(domain, "chatgpt")
    to_coordinator(domain, "reserved-ok")
    assert len(tickets(domain)) == 1


def test_restore_tickets_failure_is_visible_not_swallowed(domain, monkeypatch):
    wire(domain, "chatgpt")
    _fail_ticket_once(domain, monkeypatch)
    sent = to_coordinator(domain, "restore-boom")

    def boom(*args, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(domain, "_delivery_ticket", boom)
    domain.restore_tickets()
    event = domain.store.db.execute(
        "SELECT metadata FROM team_events WHERE kind='team.message_delivery_failed' "
        "AND object_id=?",
        (sent["id"],),
    ).fetchone()
    assert event is not None and "disk on fire" in event["metadata"]


def test_double_start_restores_exactly_one_ticket_and_one_job(domain, monkeypatch):
    wire(domain, "chatgpt")
    real = _fail_ticket_once(domain, monkeypatch)
    to_coordinator(domain, "double")
    monkeypatch.setattr(domain.bridge.messages, "send", real)
    domain.restore_tickets()
    domain.restore_tickets()
    assert len(tickets(domain)) == 1
    assert domain.store.db.execute("SELECT count(*) FROM message_jobs").fetchone()[0] == 1


def test_ack_closes_only_the_ticket_of_that_sender_and_recipient(domain):
    wire(domain, "chatgpt")
    sent = to_coordinator(domain, "scoped")
    ticket = tickets(domain)[0]
    # a legacy message that merely uses the same idem text from another sender stays untouched
    domain.store.db.execute("UPDATE messages SET sender='codex' WHERE id=?", (ticket["id"],))
    domain.alias_ack("chatgpt", sent["id"])
    row = domain.store.db.execute(
        "SELECT acknowledged FROM messages WHERE id=?", (ticket["id"],)
    ).fetchone()
    assert row["acknowledged"] is None
