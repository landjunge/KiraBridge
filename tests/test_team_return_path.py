"""Team return path: passive pull is reported truthfully; only real recipient ACK counts.

#369/#370 shape: a stored, directed reply is retrievable by its authenticated recipient,
but neither storage, retrieval nor a status read is an ACK, and no push exists.
"""

# ruff: noqa: F811
import pytest
from test_direct_delivery import delivery, new_message  # noqa: F401
from test_team_coordinator_roles import TEAM, finish, handoff, record, role_message, setup_team
from test_team_coordinator_roles import domain as roles_domain
from test_team_gateway import http_bridge  # noqa: F401
from test_team_gateway import setup_team as gateway_team
from test_visible_handoff import callback, visible  # noqa: F401

from kirabridge.bridge_core.models import BridgeError
from kirabridge.message_manager.receiver import MessageReceiver

domain = roles_domain


async def channel(pool, peer):
    result = await pool.call(peer, "message_channel_status", {})
    assert not result.isError, result
    return result.structuredContent["team_return_path"]


def grant_message_read(bridge):
    for policy in bridge.config.principals.values():
        if "message.read" not in policy.capabilities:
            policy.capabilities.append("message.read")


async def test_directed_reply_is_pull_only_and_counts_only_real_recipient_ack(http_bridge):
    bridge, _, pool = await gateway_team(http_bridge)
    grant_message_read(bridge)
    try:
        question = await pool.call(
            "peer",
            "team_message_send",
            {
                "request": {
                    "team_id": "gateway",
                    "recipient": "local",
                    "body": "Question #369 shape",
                    "kind": "question",
                    "idempotency_key": "rp-question",
                }
            },
        )
        question_id = question.structuredContent["id"]
        owner = await channel(pool, "owner")
        assert owner["delivery_mode"] == "passive_pull"
        assert owner["push"]["team_reply_push"] == "not_supported"
        assert owner["incoming"]["unacknowledged"] == 1
        reference = owner["incoming"]["references"][0]
        assert reference["message_id"] == question_id and "body" not in reference
        assert (await channel(pool, "peer"))["outgoing"]["awaiting_recipient_ack"] == 1

        # Retrieval and status reads are not acknowledgement.
        pulled = await pool.call("owner", "team_messages", {"team_id": "gateway"})
        assert any(m["id"] == question_id for m in pulled.structuredContent["messages"])
        assert (await channel(pool, "owner"))["incoming"]["unacknowledged"] == 1
        # The sender cannot acknowledge on the recipient's behalf.
        forged = await pool.call(
            "peer", "team_message_ack", {"team_id": "gateway", "message_id": question_id}
        )
        assert forged.structuredContent["error"]["code"] == "not_found"
        assert (await channel(pool, "peer"))["outgoing"]["recipient_acknowledged"] == 0

        # Real recipient ACK, then a directed reply (#370 shape) stays unacknowledged.
        acked = await pool.call(
            "owner", "team_message_ack", {"team_id": "gateway", "message_id": question_id}
        )
        assert acked.structuredContent["acknowledged"] is not None
        assert (await channel(pool, "peer"))["outgoing"]["recipient_acknowledged"] == 1
        reply = await pool.call(
            "owner",
            "team_message_send",
            {
                "request": {
                    "team_id": "gateway",
                    "recipient": "other",
                    "body": "Directed reply #370 shape",
                    "kind": "answer",
                    "reply_to": question_id,
                    "idempotency_key": "rp-reply",
                }
            },
        )
        reply_id = reply.structuredContent["id"]
        peer = await channel(pool, "peer")
        assert peer["incoming"]["unacknowledged_replies"] == 1
        assert peer["incoming"]["references"][0]["reply_to"] == question_id
        stored = bridge.store.db.execute(
            "SELECT acknowledged FROM team_messages WHERE id=?", (reply_id,)
        ).fetchone()
        assert stored["acknowledged"] is None  # no synthetic ACK anywhere
    finally:
        await pool.__aexit__(None, None, None)


async def test_coordinator_status_alias_matches_canonical_tool_and_errors(http_bridge):
    bridge, _, pool = await gateway_team(http_bridge)
    try:
        for peer in ("owner", "peer"):
            canonical = await pool.call(peer, "team_coordinator_status", {"team_id": "gateway"})
            alias = await pool.call(peer, "coordinator_status", {"team_id": "gateway"})
            assert alias.structuredContent == canonical.structuredContent
        missing = await pool.call("peer", "coordinator_status", {"team_id": "absent"})
        expected = await pool.call("peer", "team_coordinator_status", {"team_id": "absent"})
        assert missing.structuredContent == expected.structuredContent
        assert missing.structuredContent["error"]["code"] == "not_found"
    finally:
        await pool.__aexit__(None, None, None)


def test_role_handoff_never_lets_the_new_coordinator_ack_old_role_mail(domain):
    setup_team(domain, coordinator="codex")
    record(domain, "codex")
    record(domain, "grok")
    original = role_message(domain, "before-handoff")
    assert original["recipient"] == "codex"
    finish(domain, domain.request_coordinator_handoff("local", handoff(domain)))
    assert domain.coordinator_status("local", TEAM)["coordinator"] == "grok"
    with pytest.raises(BridgeError) as error:
        domain.ack("grok", TEAM, original["id"])
    assert error.value.code == "not_found"
    acked = domain.ack("codex", TEAM, original["id"])
    assert acked["recipient"] == "codex" and acked["acknowledged"] is not None
    # An ACK is a message fact; it never moves the role.
    assert domain.coordinator_status("local", TEAM)["coordinator"] == "grok"
    assert role_message(domain, "after-handoff")["recipient"] == "grok"


async def test_public_pull_after_direct_claim_has_no_second_automatic_effect(delivery):
    """Characterization: same ID and receipt on pull; no re-claim, no second input."""
    bridge, transport, direct, _, _ = delivery
    sent = new_message(bridge, "after-claim")
    claimed = bridge.message_receiver._claim(sent["id"], direct=True)
    assert claimed is not None
    first = bridge.messages.receive("grok")["messages"]
    second = bridge.messages.receive("grok")["messages"]
    mine = [m for m in first if m["id"] == sent["id"]]
    again = [m for m in second if m["id"] == sent["id"]]
    assert mine and again and mine[0]["receipt"] == again[0]["receipt"]
    assert bridge.messages.get("chatgpt", sent["id"])["acknowledged"] is None
    assert not direct.submit("chatgpt", sent["id"])
    assert not await MessageReceiver(bridge)._dispatch_next("grok", include_visible=False)
    assert transport["calls"] == []
