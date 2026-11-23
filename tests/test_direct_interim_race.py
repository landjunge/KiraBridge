"""Recipient pull during the interim peer connect must win; the direct driver backs off.

Barrier: the fake MCP pool's ``connect`` lets the authenticated recipient pull the
same message (real SQLite receipt) before the direct driver resumes. On base
1c20236 the interim branch then reached ``_claim`` once (attempt count 1); the
shared pristine pre-claim check makes it 0, with no input and no record change.
The native effect itself is faked; this proves the claim, not a real double input.
"""

# ruff: noqa: F811
from test_codex_interim import arguments, setup_input
from test_direct_delivery import delivery, settled  # noqa: F401
from test_visible_handoff import callback, visible  # noqa: F401

from kirabridge.message_manager import MessageSend


def snapshot(bridge, message_id):
    db = bridge.store.db
    return (
        tuple(db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()),
        tuple(
            bridge.store.db.execute(
                "SELECT * FROM message_jobs WHERE message_id=?", (message_id,)
            ).fetchone()
        ),
    )


async def test_interim_recipient_pull_during_connect_prevents_direct_claim(delivery, monkeypatch):
    bridge, transport, direct, _, pool = delivery
    bridge.config.session_input_policy.enabled = False
    row = await setup_input(bridge, transport, monkeypatch)
    claims = []
    original_claim = bridge.message_receiver._claim

    def counting_claim(message_id, **options):
        claims.append(options)
        return original_claim(message_id, **options)

    monkeypatch.setattr(bridge.message_receiver, "_claim", counting_claim)
    message = MessageSend(
        recipient="codex",
        conversation_id="interim-race",
        idempotency_key="interim-race",
        body="Kurzer Zwischenstand?",
        kind="question",
        request_reply=False,
        interim_session={
            k: v
            for k, v in arguments(row).items()
            if k in {"pane_id", "expected_pid", "expected_agent_pid"}
        },
    )
    sent = bridge.messages.send("chatgpt", message)
    barrier = {}

    class RacingPool(pool):
        async def connect(self, recipient):
            await super().connect(recipient)
            pulled = bridge.messages.receive("codex")["messages"]
            barrier["pulled"] = [item["id"] for item in pulled]
            barrier["after_pull"] = snapshot(bridge, sent["id"])

    monkeypatch.setattr("kirabridge.message_manager.direct.MCPClientPool", RacingPool)
    assert direct.submit("chatgpt", sent["id"])
    await direct.wait_delivery(sent["id"])
    await settled(direct)

    # Precondition: the real recipient obtained the receipt inside the barrier.
    assert sent["id"] in barrier["pulled"]
    current = bridge.messages.get("chatgpt", sent["id"])
    assert current["delivered"] is not None and current["acknowledged"] is None
    # Outcome: zero direct claim attempts, zero input, durable record untouched.
    assert claims == []
    assert transport["literal_calls"] == []
    assert snapshot(bridge, sent["id"]) == barrier["after_pull"]
    # Idempotency: neither a resend nor a second submit re-admits it.
    assert bridge.messages.send("chatgpt", message)["id"] == sent["id"]
    assert not direct.submit("chatgpt", sent["id"])
    assert claims == [] and transport["literal_calls"] == []
