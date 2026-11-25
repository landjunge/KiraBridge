"""ChatGPT can read everything, read-only, whenever the operator wants it read aloud."""

import pytest
from test_team_manager import domain as imported_domain
from test_team_manager import message

from kirabridge.bridge_core.models import BridgeError
from kirabridge.message_manager import MessageSend
from kirabridge.message_overview import OBSERVE_CAPABILITY, observe, overview

domain = imported_domain


def grant(domain, *principals):
    for principal in principals:
        policy = domain.config.principals[principal]
        policy.capabilities = list(
            set(policy.capabilities) | {"message.send", "message.read", "agent.execute"}
        )
        policy.message_peers = ["chatgpt", "codex", "grok", "local"]


def direct(domain, sender, recipient, key, body="Direkte Nachricht"):
    grant(domain, sender, recipient)
    return domain.bridge.messages.send(
        sender,
        MessageSend(
            recipient=recipient,
            conversation_id=key,
            idempotency_key=key,
            kind="note",
            body=body,
            dispatch=False,
        ),
    )


def team(domain, sender, recipient, key, body=None):
    request = message(team_id="test-team", recipient=recipient, idempotency_key=key)
    if body:
        request = request.model_copy(update={"body": body})
    return domain.send(sender, request)


def test_overview_contains_direct_and_team_messages_between_other_agents(domain):
    direct(domain, "codex", "grok", "d1")
    team(domain, "codex", "grok", "t1")
    result = overview(domain.store.db)
    assert result["read_only"] is True
    assert {item["source"] for item in result["items"]} == {"direct", "team"}
    assert all(item["from"] == "codex" and item["to"] == "grok" for item in result["items"])
    assert all(item["untrusted_content"] for item in result["items"])
    assert result["items"][0]["at"] <= result["items"][-1]["at"]


def test_every_item_has_a_sentence_to_read_aloud(domain):
    direct(domain, "codex", "grok", "d-speech", body="Release-Gate bestanden")
    item = overview(domain.store.db)["items"][0]
    assert (
        item["speech"].startswith("Um ")
        and "hat codex an grok eine Notiz geschickt" in item["speech"]
    )
    assert "Release-Gate bestanden" in item["speech"]


def test_long_bodies_are_cut_and_flagged(domain):
    direct(domain, "codex", "grok", "d-long", body="x" * 2000)
    item = overview(domain.store.db, body_chars=100)["items"][0]
    assert len(item["body"]) == 100 and item["body_truncated"] is True
    assert overview(domain.store.db, body_chars=4000)["items"][0]["body_truncated"] is False


def test_cursors_page_through_without_skipping_or_repeating(domain):
    for index in range(3):
        direct(domain, "codex", "grok", f"d{index}")
        team(domain, "codex", "grok", f"t{index}")
    seen, cursor = [], {"after_direct": 0, "after_team": 0}
    for _ in range(10):
        page = overview(domain.store.db, limit=2, **cursor)
        seen += [(item["source"], item["seq"]) for item in page["items"]]
        cursor = page["next"]
        if not page["more"] and not page["items"]:
            break
    assert len(seen) == 6 and len(set(seen)) == 6
    assert overview(domain.store.db, **cursor)["items"] == []


def test_reading_changes_nothing(domain):
    direct(domain, "codex", "grok", "d-ro")
    team(domain, "codex", "grok", "t-ro")
    before = (
        domain.store.db.execute("SELECT count(*), count(acknowledged) FROM messages").fetchone()[:],
        domain.store.db.execute(
            "SELECT count(*), count(acknowledged) FROM team_messages"
        ).fetchone()[:],
    )
    overview(domain.store.db)
    after = (
        domain.store.db.execute("SELECT count(*), count(acknowledged) FROM messages").fetchone()[:],
        domain.store.db.execute(
            "SELECT count(*), count(acknowledged) FROM team_messages"
        ).fetchone()[:],
    )
    assert before == after and after[0][1] == 0 and after[1][1] == 0


def test_only_principals_with_the_observe_capability_may_read_everything(domain):
    direct(domain, "codex", "grok", "d-cap")
    with pytest.raises(BridgeError) as denied:
        observe(domain.bridge, "chatgpt")
    assert denied.value.code == "forbidden"
    domain.config.principals["chatgpt"].capabilities.append(OBSERVE_CAPABILITY)
    assert observe(domain.bridge, "chatgpt")["count"] >= 1


async def test_the_overview_is_published_as_a_read_only_mcp_tool(domain):
    from kirabridge.mcp_gateway.server import create_server

    tools = {tool.name: tool for tool in await create_server(domain.bridge).list_tools()}
    tool = tools["messages_overview"]
    assert tool.annotations.readOnlyHint is True
    assert OBSERVE_CAPABILITY in tool.description
    assert {"after_direct", "after_team", "limit", "body_chars"} <= set(
        tool.inputSchema["properties"]
    )
