# ruff: noqa: F811
"""Automatic team status delivery through the authenticated TeamWork path."""

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from test_mcp import http_bridge  # noqa: F401
from test_team_continuation_e2e import (
    TEAM,
    authorize_sources,
    board_bytes,
    card,
    configure_workers,
    create_bound_coordinator,
    inspect_invocations,
    list_work,
    owner_workspace,  # noqa: F401
    rpc,
    wait_for_work,
)

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import TeamWorkerConfig
from kirabridge.mcp_gateway.client import MCPClientPool, Peer

CHATGPT_TOKEN = "fixture-chatgpt-" + "c" * 40
OTHER_TOKEN = "other-test-" + "b" * 40


def chatgpt_identity(config, monkeypatch):
    policy = config.principals["local"].model_copy(deep=True)
    policy.token_env = "TEAM_TEST_CHATGPT"
    policy.capabilities = ["team.read", "team.write"]
    policy.agents = []
    config.principals["chatgpt"] = policy
    config.team.workers["chatgpt"] = TeamWorkerConfig()
    monkeypatch.setenv(policy.token_env, CHATGPT_TOKEN)


async def create_work(clients, title):
    return await rpc(
        clients,
        "local",
        "team_work_create",
        {
            "request": {
                "team_id": TEAM,
                "assignee": "grok",
                "title": title,
                "body": "Return a deterministic test result.",
                "idempotency_key": "fixture-" + title,
            }
        },
    )


async def team_messages(clients, principal="chatgpt"):
    response = await rpc(clients, principal, "team_messages", {"team_id": TEAM, "limit": 100})
    return response["messages"]


async def wait_for_messages(clients, predicate):
    async with asyncio.timeout(15):
        while True:
            rows = await team_messages(clients)
            if predicate(rows):
                return rows
            await asyncio.sleep(0.05)


def published(bridge, work_id):
    rows = bridge.store.db.execute(
        "SELECT object_id,metadata FROM team_events "
        "WHERE team_id=? AND kind='team.chatgpt_status_published' ORDER BY seq",
        (TEAM,),
    ).fetchall()
    return [
        {"message_id": row["object_id"], **metadata}
        for row in rows
        if (metadata := json.loads(row["metadata"]))["work_id"] == work_id
    ]


def read_status_receipts(bridge):
    db_path = bridge.store.db.execute("PRAGMA database_list").fetchone()[2]
    with sqlite3.connect(Path(db_path).as_uri() + "?mode=ro", uri=True) as persisted:
        persisted.row_factory = sqlite3.Row
        rows = persisted.execute(
            "SELECT op.team_id,op.principal,op.idem,op.object_id,m.sender,m.recipient,"
            "m.kind,m.body,m.reply_to,m.acknowledged FROM team_operations op "
            "LEFT JOIN team_messages m ON m.team_id=op.team_id AND m.id=op.object_id "
            "WHERE op.operation='chatgpt_status' ORDER BY m.seq"
        ).fetchall()
    return [dict(row) for row in rows]


async def assert_error(clients, principal, tool, arguments, code):
    result = (await clients.call(principal, tool, arguments)).structuredContent
    assert result and result.get("error", {}).get("code") == code, result


def marked_events(bridge, work_id=None):
    rows = bridge.store.db.execute(
        "SELECT seq,kind,object_id,metadata FROM team_events WHERE team_id=? ORDER BY seq",
        (TEAM,),
    ).fetchall()
    return [
        {**dict(row), "metadata": json.loads(row["metadata"])}
        for row in rows
        if (work_id is None or row["object_id"] == work_id)
        and "chatgpt_status" in json.loads(row["metadata"])
    ]


def make_legacy_fixture(bridge):
    # Legacy stores have the same genuine event history without the new metadata marker.
    for row in marked_events(bridge):
        metadata = {
            key: value
            for key, value in row["metadata"].items()
            if not key.startswith("chatgpt_status")
        }
        bridge.store.db.execute(
            "UPDATE team_events SET metadata=? WHERE team_id=? AND seq=?",
            (json.dumps(metadata), TEAM, row["seq"]),
        )


def drain_reopened(config):
    reopened = Bridge(config)
    try:
        reopened.teams.publish_chatgpt_status()
    finally:
        reopened.store.close()


def hold_worker_turn(config, principal, title):
    executable = Path(config.agents[principal].executable)
    code = executable.read_text()
    writer = " print(json.dumps(event),flush=True)"
    assert writer in code
    executable.write_text(
        code.replace(
            writer,
            f" if subject == {title!r} and event['type'] == 'item.completed':\n"
            "  import time\n"
            "  deadline=time.monotonic()+8\n"
            "  while not Path('finish-followup').exists() and time.monotonic()<deadline:\n"
            "   time.sleep(0.03)\n" + writer,
        )
    )
    config.team.workers[principal].timeout = 15


async def handoff(clients, bridge):
    snapshot = await rpc(clients, "local", "team_coordinator_status", {"team_id": TEAM})
    target = next(row for row in snapshot["candidates"] if row["principal"] == "grok")
    transfer = await rpc(
        clients,
        "local",
        "team_coordinator_handoff",
        {
            "request": {
                "team_id": TEAM,
                "principal": "grok",
                "session_id": target["session_id"],
                "generation": target["generation"],
                "expected_revision": snapshot["revision"],
                "idempotency_key": "e2e-status-handoff",
            }
        },
    )
    assert transfer["state"] == "pending"
    await bridge.team_dispatcher.start()
    await wait_for_work(
        clients,
        lambda rows: any(
            row["id"] == transfer["work_id"] and row["state"] == "completed" for row in rows
        ),
    )
    await bridge.team_dispatcher.stop()
    changed = await rpc(clients, "local", "team_coordinator_status", {"team_id": TEAM})
    assert changed["coordinator"] == "grok" and changed["revision"] > snapshot["revision"]
    return transfer["work_id"]


async def test_review_status_survives_restart_and_role_change_without_duplicate_messages(
    http_bridge, config, tmp_path, monkeypatch, owner_workspace
):
    bridge, endpoint = http_bridge
    root = configure_workers(bridge, config, tmp_path, monkeypatch)
    chatgpt_identity(config, monkeypatch)
    first_card = card("status-first")
    owner_root, fixture = owner_workspace([first_card])
    before = board_bytes(owner_root)
    async with MCPClientPool() as clients:
        await clients.connect(Peer("chatgpt", url=endpoint, token=CHATGPT_TOKEN))
        await clients.connect(Peer("other", url=endpoint, token=OTHER_TOKEN))
        with monkeypatch.context() as pause:
            pause.setattr(bridge.teams, "publish_chatgpt_status", lambda *args, **kwargs: None)
            await create_bound_coordinator(
                bridge, clients, endpoint, seed_second=True, members={"chatgpt": "worker"}
            )
            make_legacy_fixture(bridge)
            assert not marked_events(bridge)
            authorize_sources(bridge, fixture, [first_card], (0,), root)
            await bridge.team_dispatcher.start()
            rows = await wait_for_work(
                clients,
                lambda rows: any(
                    str(row["result"]).startswith("ACCEPT READY TASK tw-") for row in rows
                ),
            )
            (first,) = [row for row in rows if row["title"] == "Fixture status-first"]
            await bridge.team_dispatcher.stop()
            assert first["state"] == "completed"
            assert bridge.store.get(first["core_task_id"])["started"] is not None
            assert any(
                event["kind"] == "team.work_accepted"
                for event in marked_events(bridge, first["id"])
            )
            assert await team_messages(clients) == []
            transfer_work_id = await handoff(clients, bridge)
            assert not marked_events(bridge, transfer_work_id)
            assert await team_messages(clients) == []

        # Force a DB failure immediately before recording a delivery receipt.
        # The original source event remains committed, and the message must roll back.
        bridge.store.db.execute(
            "CREATE TRIGGER test_status_receipt_failure BEFORE INSERT ON team_operations "
            "WHEN NEW.operation='chatgpt_status' "
            "BEGIN SELECT RAISE(ABORT, 'isolated receipt fault'); END"
        )
        try:
            try:
                drain_reopened(config)
            except sqlite3.IntegrityError as exc:
                assert "isolated receipt fault" in str(exc)
            assert not read_status_receipts(bridge)
            assert await team_messages(clients) == []
        finally:
            bridge.store.db.execute("DROP TRIGGER test_status_receipt_failure")

        await asyncio.gather(
            asyncio.to_thread(drain_reopened, config),
            asyncio.to_thread(drain_reopened, config),
        )
        first_delivery = await team_messages(clients)
        receipts = read_status_receipts(bridge)
        assert first_delivery
        assert [row["object_id"] for row in receipts] == [row["id"] for row in first_delivery]
        assert len({row["idem"] for row in receipts}) == len(first_delivery)
        assert all(
            row["sender"] == "grok"
            and row["recipient"] == "chatgpt"
            and row["acknowledged"] is None
            and row["reply_to"] is None
            for row in first_delivery
        )
        assert not any("Bootstrap" in row["body"] for row in first_delivery)
        (accepted,) = [
            event for event in published(bridge, first["id"]) if event["subject"] == "accepted"
        ]
        assert not accepted.get("followup_work_id")
        accepted_message = next(
            row for row in first_delivery if row["id"] == accepted["message_id"]
        )
        assert first["id"] in accepted_message["body"]
        assert "nächster schritt" in accepted_message["body"].lower()
        assert "gestartet" not in accepted_message["body"].lower()
        assert len(accepted_message["body"]) < 600
        await assert_error(clients, "other", "team_messages", {"team_id": TEAM}, "not_found")
        roles = await rpc(clients, "local", "team_coordinator_status", {"team_id": TEAM})
        assert roles["coordinator"] == "grok"
        ack = {"team_id": TEAM, "message_id": first_delivery[-1]["id"]}
        await assert_error(clients, "grok", "team_message_ack", ack, "not_found")
        await rpc(clients, "chatgpt", "team_message_ack", ack)
        drain_reopened(config)
        assert len(await team_messages(clients)) == len(first_delivery)
        assert read_status_receipts(bridge)[-1]["acknowledged"] is not None
        assert [row["id"] for row in await list_work(clients)] == [row["id"] for row in rows] + [
            transfer_work_id
        ]
        assert board_bytes(owner_root) == before

        next_card = card("status-next", assignee="codex")
        _, next_fixture = owner_workspace([next_card], boards=fixture["boards"])
        next_before = board_bytes(owner_root)
        authorize_sources(bridge, next_fixture, [next_card], (0,), root)
        hold_worker_turn(config, "codex", "Fixture status-next")
        await bridge.team_dispatcher.start()
        try:
            current_rows = await wait_for_work(
                clients,
                lambda current: any(
                    row["title"] == "Fixture status-next" and row["state"] == "running"
                    for row in current
                ),
            )
            (subsequent,) = [row for row in current_rows if row["title"] == "Fixture status-next"]
            assert subsequent["assigned_by"] == "grok"
            assert bridge.store.get(subsequent["core_task_id"])["started"] is not None
            delivered = await wait_for_messages(
                clients,
                lambda rows: any(
                    row["id"]
                    in {
                        event["message_id"]
                        for event in published(bridge, subsequent["id"])
                        if event["subject"] == "started"
                    }
                    for row in rows
                ),
            )
            (start,) = [
                event
                for event in published(bridge, subsequent["id"])
                if event["subject"] == "started"
            ]
            assert start["predecessor_work_id"] == first["id"]
            message = next(row for row in delivered if row["id"] == start["message_id"])
            assert message["recipient"] == "chatgpt" and message["sender"] == "grok"
            assert first["id"] in message["body"] and subsequent["id"] in message["body"]
        finally:
            (root / "finish-followup").touch()
        await wait_for_work(
            clients,
            lambda current: any(
                row["id"] == subsequent["id"] and row["state"] == "completed" for row in current
            ),
        )
        await bridge.team_dispatcher.stop()
        assert board_bytes(owner_root) == next_before


@pytest.mark.parametrize("scenario", ["different-recipient", "observer", "unauthorized-role"])
async def test_status_needs_the_correct_active_recipient_and_authorized_role(
    http_bridge, config, tmp_path, monkeypatch, scenario
):
    bridge, endpoint = http_bridge
    configure_workers(bridge, config, tmp_path, monkeypatch)
    chatgpt_identity(config, monkeypatch)
    members = {
        "different-recipient": {"other": "worker"},
        "observer": {"chatgpt": "observer"},
        "unauthorized-role": {"chatgpt": "worker"},
    }[scenario]
    async with MCPClientPool() as clients:
        await create_bound_coordinator(bridge, clients, endpoint, members=members)
        before = await team_messages(clients, "local")
        if scenario == "unauthorized-role":
            config.principals["codex"].capabilities.remove("team.write")
        work = await create_work(clients, "Recipient authorization")
        await bridge.team_dispatcher.start()
        await wait_for_work(
            clients,
            lambda rows: any(
                row["id"] == work["id"] and row["state"] == "completed" for row in rows
            ),
        )
        await bridge.team_dispatcher.stop()
        assert await team_messages(clients, "local") == before
        assert len(read_status_receipts(bridge)) == len(before)


async def test_technical_completion_blockage_and_unknown_have_distinct_status(
    http_bridge, config, tmp_path, monkeypatch
):
    bridge, endpoint = http_bridge
    root = configure_workers(bridge, config, tmp_path, monkeypatch)
    chatgpt_identity(config, monkeypatch)
    async with MCPClientPool() as clients:
        await clients.connect(Peer("chatgpt", url=endpoint, token=CHATGPT_TOKEN))
        await create_bound_coordinator(bridge, clients, endpoint, members={"chatgpt": "worker"})
        technical = await create_work(clients, "Technical only")
        unknown = await create_work(clients, "Interrupted submission")
        blocked = await create_work(clients, "Blocked source")
        claimed = bridge.teams.claim(unknown["id"])
        assert claimed["core_task_id"]
        await assert_error(
            clients, "grok", "task_get", {"task_id": claimed["core_task_id"]}, "not_found"
        )
        bridge.teams.fail(
            blocked["id"],
            "blocked",
            "continuation_source_unverified",
            {"native_input_attempted": False},
        )
        expected = {
            technical["id"]: "completed",
            unknown["id"]: "unknown",
            blocked["id"]: "blocked",
        }
        await bridge.team_dispatcher.start()
        rows = await wait_for_work(
            clients,
            lambda listing: (
                {row["id"]: row["state"] for row in listing if row["id"] in expected} == expected
            ),
        )
        await wait_for_messages(
            clients,
            lambda _: all(
                any(event["subject"] == "terminal" for event in published(bridge, work_id))
                for work_id in expected
            ),
        )
        await bridge.team_dispatcher.stop()
        by_id = {row["id"]: row for row in rows}
        assert by_id[technical["id"]]["evidence"]["project_completion_verified"] is False
        assert by_id[unknown["id"]]["error"] == "team_core_missing_after_claim"
        assert by_id[unknown["id"]]["evidence"]["automatic_retry"] is False
        assert by_id[blocked["id"]]["core_task_id"] is None
        messages = {row["id"]: row for row in await team_messages(clients)}
        expected_next_steps = {
            "completed": ("ergebnis liegt vor", "fachliche prüfung steht aus"),
            "unknown": ("ausgang ungeklärt", "prüfung des originalbelegs"),
            "blocked": ("ausführung blockiert", "prüfung der ursache"),
        }
        for work_id in expected:
            (event,) = [
                row for row in published(bridge, work_id) if row["subject"] == expected[work_id]
            ]
            assert not event.get("followup_work_id")
            assert not any(row["subject"] == "accepted" for row in published(bridge, work_id))
            message = messages[event["message_id"]]
            assert message["recipient"] == "chatgpt" and work_id in message["body"]
            assert all(
                part in message["body"].lower() for part in expected_next_steps[expected[work_id]]
            )
            assert "FIXTURE_DONE" not in message["body"]
        assert [turn["subject"] for turn in inspect_invocations(root)] == [
            "Bootstrap codex",
            "Technical only",
        ]
        assert not any(
            row["subject"] == "started"
            for work_id in (unknown["id"], blocked["id"])
            for row in published(bridge, work_id)
        )
