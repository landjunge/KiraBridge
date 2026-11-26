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


async def test_the_overview_is_published_as_a_receiving_mcp_tool(domain):
    from kirabridge.mcp_gateway.server import create_server

    tools = {tool.name: tool for tool in await create_server(domain.bridge).list_tools()}
    tool = tools["messages_overview"]
    # The receive hook acknowledges on read, so the tool no longer claims to be read-only.
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.idempotentHint is True
    assert OBSERVE_CAPABILITY in tool.description
    assert "acknowledges" in tool.description
    assert {"after_direct", "after_team", "limit", "body_chars"} <= set(
        tool.inputSchema["properties"]
    )


def test_observe_by_a_principal_outside_the_hook_list_changes_nothing(domain):
    direct(domain, "codex", "chatgpt", "d-other")
    team(domain, "codex", "chatgpt", "t-other")
    domain.config.principals["local"].capabilities.append(OBSERVE_CAPABILITY)
    result = observe(domain.bridge, "local")
    assert result["read_only"] is True and "ack_error" not in result
    assert result["acknowledged_by_read"] == {"direct": [], "team": []}
    assert (
        domain.store.db.execute(
            "SELECT count(*) FROM messages WHERE acknowledged IS NULL"
        ).fetchone()[0]
        == 1
    )
    assert (
        domain.store.db.execute(
            "SELECT count(*) FROM team_messages WHERE acknowledged IS NULL"
        ).fetchone()[0]
        == 1
    )


def test_one_inbox_shows_only_the_own_mailbox_over_both_stores(domain):
    from kirabridge.message_overview import inbox

    direct(domain, "codex", "grok", "d-box")
    team(domain, "codex", "grok", "t-box")
    team(domain, "grok", "codex", "t-back")
    result = inbox(domain.bridge, "grok")
    assert result["read_only"] is True
    assert {item["source"] for item in result["items"]} == {"direct", "team"}
    assert all(item["to"] == "grok" for item in result["items"])
    assert "team_messages" in result["notice"]


def test_reading_the_inbox_acknowledges_exactly_what_the_caller_received(domain):
    from kirabridge.message_overview import inbox, team_read

    direct(domain, "codex", "chatgpt", "d-ack")
    team(domain, "codex", "chatgpt", "t-ack")
    team(domain, "codex", "grok", "t-other")  # someone else's mail stays untouched
    first = inbox(domain.bridge, "chatgpt")
    assert {i["source"] for i in first["items"]} == {"direct", "team"}
    assert all(i["new"] and not i["read"] for i in first["items"])
    assert first["new_count"] == 2 and first["total"] == 2 and first["unread_count"] == 0
    second = inbox(domain.bridge, "chatgpt")
    assert all(i["read"] and not i["new"] and i["acknowledged_at"] for i in second["items"])
    assert second["new_count"] == 0
    other = domain.store.db.execute(
        "SELECT acknowledged FROM team_messages WHERE recipient='grok'"
    ).fetchone()
    assert other["acknowledged"] is None
    # The team-id path obeys the same rule and marks its rows.
    team(domain, "codex", "chatgpt", "t-ack2")
    page = team_read(domain.bridge, "chatgpt", "test-team")
    fresh = [m for m in page["messages"] if m["recipient"] == "chatgpt" and m["new"]]
    assert len(fresh) == 1 and page["new_count"] == 1 and page["unread_count"] == 0
    assert team_read(domain.bridge, "chatgpt", "test-team")["new_count"] == 0


def test_a_worker_reading_its_inbox_acknowledges_nothing(domain):
    from kirabridge.message_overview import inbox

    team(domain, "codex", "grok", "t-worker")
    result = inbox(domain.bridge, "grok")
    assert result["items"][0]["new"] and result["unread_count"] == 1
    assert inbox(domain.bridge, "grok")["items"][0]["new"]
