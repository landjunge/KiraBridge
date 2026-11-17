"""Review tw-aef4c7fe: visible success branches must be bound to the claiming run_id."""
# ruff: noqa: F811

import json

import pytest
from test_body_only_receiver import local_result
from test_direct_delivery import delivery  # noqa: F401
from test_visible_handoff import visible  # noqa: F401

from kirabridge.message_manager import MessageSend

OTHER = "channel-new-owner"


@pytest.mark.parametrize("scope", ["local_agent_turn", "visible_input_delivery"])
async def test_old_visible_success_after_handoff_keeps_foreign_job(delivery, monkeypatch, scope):
    bridge, transport, _, _, Pool = delivery
    sent = bridge.messages.send(
        "chatgpt",
        MessageSend(
            recipient="codex",
            conversation_id="vis-handoff-" + scope,
            idempotency_key="vis-handoff-" + scope,
            body="Current task",
            kind="work",
            dispatch=True,
            request_reply=True,
        ),
    )

    async def execute(task, args, policy, running, progress, **kwargs):
        await running({"return_sent": True})
        with bridge.store.transaction():  # new owner takes the running job mid-adapter
            bridge.store.db.execute(
                "UPDATE message_jobs SET run_id=?,evidence=? WHERE message_id=?",
                (OTHER, json.dumps({"owner": "new"}), sent["id"]),
            )
        if scope == "local_agent_turn":
            return local_result(bridge, sent, task["id"], "old run final")
        return {"success": True, "scope": scope, "evidence": {"agent_confirmed": False}}

    monkeypatch.setattr(bridge.agents, "execute", execute)
    message, run_id = bridge.message_receiver._claim(sent["id"], direct=True)
    events_before = bridge.store.db.execute(
        "SELECT coalesce(max(seq),0) FROM message_events WHERE message_id=?", (sent["id"],)
    ).fetchone()[0]
    pool = Pool()
    await pool.connect("codex")
    await bridge.message_receiver._process(pool, message, run_id)
    row = bridge.store.db.execute(
        "SELECT state,run_id,evidence,finished,reply_id FROM message_jobs WHERE message_id=?",
        (sent["id"],),
    ).fetchone()
    assert (row["state"], row["run_id"], row["finished"], row["reply_id"]) == (
        "running", OTHER, None, None,
    )
    assert json.loads(row["evidence"]) == {"owner": "new"}
    finished = bridge.store.db.execute(
        "SELECT count(*) FROM message_events WHERE message_id=? AND seq>? "
        "AND kind LIKE 'message.processing_%'",
        (sent["id"], events_before),
    ).fetchone()[0]
    assert finished == 0
    assert bridge.completions.receive("chatgpt")["notices"] == []
