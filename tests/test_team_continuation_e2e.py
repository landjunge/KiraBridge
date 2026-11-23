# ruff: noqa: F811
"""Real owner stdio / TeamWork / Core adapter acceptance with private fixtures."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_agents import fake_cli
from test_mcp import http_bridge  # noqa: F401
from test_team_dispatcher import configure_team

from kirabridge.audit_manager import verify
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import AgentConfig
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.team_manager.dispatcher import TeamDispatcher

TEAM = "ready-e2e"
SESSION = {
    "codex": "01a1ce14-57d2-75f3-85c9-7208392ce422",
    "grok": "01a1ce14-57d2-75f3-85c9-7208392ce423",
}
TOKENS = {
    "local": "local-test-" + "a" * 40,
    "codex": "codex-team-test-" + "x" * 40,
    "grok": "grok-team-test-" + "x" * 40,
}

# Create genuine owner records in a throwaway workspace. The bridge can only read it.
OWNER_FIXTURE = """
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from threaddesk.api.service import ThreadService
from threaddesk.services.commands import CommandApplication
from threaddesk.services.whiteboard_lifecycle import WhiteboardService
from threaddesk.storage.json_store import JsonStore
store=JsonStore(Path(sys.argv[2]))
svc=ThreadService(store)
owner=WhiteboardService(svc)
boards=json.loads(sys.argv[3]) if len(sys.argv)>3 else {
    label: owner.create(label)["thread"]["id"] for label in ("allowed","foreign")
}
entries=[]
for row in json.load(sys.stdin):
    board_id=boards[row["board"]]
    result=svc.append_whiteboard(board_id,actor="Fixture",actor_type="human",
                                 entry_type="task",content=row["content"])
    entry_id=result["entry"]["id"]
    if row["historical"]:
        owner.edit(board_id,entry_id=entry_id,content="Current replacement")
    entries.append({"board_id":board_id,"entry_id":entry_id})
print(json.dumps({"workspace_id":CommandApplication(svc).workspace_id,
                  "boards":boards,"entries":entries}))
"""


def card(task_id, *, board="allowed", state="READY", historical=False, assignee="grok"):
    content = json.dumps(
        {
            "schema": "kirabridge-team-ready.v1",
            "task_id": task_id,
            "state": state,
            "title": "Fixture " + task_id,
            "body": "Return the bounded deterministic fixture result.",
            "assignee": assignee,
        },
        sort_keys=True,
    )
    return {
        "content": content,
        "board": board,
        "task_id": task_id,
        "historical": historical,
        "assignee": assignee,
    }


@pytest.fixture
def owner_workspace(config, tmp_path):
    configured = os.environ.get("KIRABRIDGE_TEST_THREADDESK_SOURCE")
    if not configured:
        pytest.skip("Pinned ThreadDesk source required for real isolated owner stdio")
    source = Path(configured).resolve()
    root = tmp_path / "owner-ready-workspace"
    root.mkdir(mode=0o700)
    settings = config.threaddesk
    settings.enabled = settings.dynamic_read_proxy = True
    settings.command, settings.args = sys.executable, ["-m", "threaddesk.ui.mcp_stdio"]
    settings.workspace, settings.source_root = str(root), str(source)

    def seed(cards, *, boards=None):
        args = [sys.executable, "-IB", "-c", OWNER_FIXTURE, str(source), str(root)]
        if boards is not None:
            args.append(json.dumps(boards))
        result = subprocess.run(
            args,
            input=json.dumps(cards),
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        return root, json.loads(result.stdout)

    return seed


def worker_code(principal, *, accept_review):
    return f"""
import json,re,sys
from pathlib import Path
prompt=sys.stdin.read()
subject=""
if "peer content:" in prompt:
    metadata=json.loads(prompt.split("peer content:\\n",1)[1])
    work=metadata["current_work"]
    subject=work["title"]
handoff=re.search(r"ACCEPT COORDINATOR ([A-Za-z0-9_-]+)",prompt)
if handoff and "peer content:" not in prompt:
    answer="ACCEPT COORDINATOR "+handoff.group(1)
elif "REVIEW DATA (JSON):" in prompt:
    evidence=json.loads(prompt.split("REVIEW DATA (JSON):\\n",1)[1])
    assert evidence["state"]=="completed" and evidence["core_task_id"]
    assert evidence["result"]=="FIXTURE_DONE "+evidence["title"]
    answer="ACCEPT READY TASK "+evidence["work_id"] if {accept_review!r} else "HOLD"
else:
    answer="FIXTURE_DONE "+subject
with Path("verified-worker-invocations.jsonl").open("a") as ledger:
    ledger.write(json.dumps({{"principal":{principal!r},"subject":subject,"result":answer}})+"\\n")
for event in [
    {{"type":"thread.started","thread_id":{SESSION[principal]!r}}},
    {{"type":"turn.started"}},
    {{"type":"item.completed","item":{{"type":"agent_message","text":answer}}}},
    {{"type":"turn.completed"}}
]:
    print(json.dumps(event),flush=True)
"""


def configure_workers(bridge, config, tmp_path, monkeypatch, *, accept_review=True):
    root = Path(configure_team(bridge, config, tmp_path, monkeypatch))
    config.team.coordinator_resume = True
    # Both deterministic workers go through the existing Codex CLI adapter.
    for principal in ("codex", "grok"):
        directory = tmp_path / (principal + "-acceptance")
        directory.mkdir()
        config.agents[principal] = AgentConfig(
            kind="codex",
            executable=fake_cli(directory, worker_code(principal, accept_review=accept_review)),
        )
        config.team.workers[principal].execution_scope = "separate_managed_session"
        config.principals[principal].capabilities.append("threaddesk.read")
    return root


def inspect_invocations(root):
    ledger = root / "verified-worker-invocations.jsonl"
    return [json.loads(line) for line in ledger.read_text().splitlines()] if ledger.exists() else []


def board_bytes(root):
    return {
        path.relative_to(root): hashlib.sha256(path.read_bytes()).hexdigest()
        for directory in ("threads", "whiteboard")
        for path in (root / directory).rglob("*.json")
    }


async def rpc(clients, principal, name, arguments):
    response = (await clients.call(principal, name, arguments)).structuredContent
    assert response is not None and not response.get("error"), response
    return response


async def list_work(clients):
    response = await rpc(clients, "local", "team_work_list", {"team_id": TEAM, "limit": 30})
    return response["work"]


async def wait_for_work(clients, predicate):
    async with asyncio.timeout(15):
        while True:
            rows = await list_work(clients)
            if predicate(rows):
                return rows
            await asyncio.sleep(0.05)


async def create_bound_coordinator(bridge, clients, endpoint, *, seed_second=False, members=None):
    for principal, token in TOKENS.items():
        await clients.connect(Peer(principal, url=endpoint, token=token))
    await rpc(
        clients,
        "local",
        "team_create",
        {
            "request": {
                "team_id": TEAM,
                "name": "Continuation fixture",
                "coordinator": "codex",
                "members": {
                    "local": "worker",
                    "codex": "coordinator",
                    "grok": "worker",
                    **(members or {}),
                },
                "idempotency_key": "fixture-team",
            }
        },
    )
    await bridge.team_dispatcher.start()
    workers = ("codex", "grok") if seed_second else ("codex",)
    for principal in workers:
        created = await rpc(
            clients,
            "local",
            "team_work_create",
            {
                "request": {
                    "team_id": TEAM,
                    "assignee": principal,
                    "title": "Bootstrap " + principal,
                    "body": "Provide a completed synthetic provider session.",
                    "idempotency_key": "fixture-bootstrap-" + principal,
                }
            },
        )
        await wait_for_work(
            clients,
            lambda rows, work_id=created["id"]: any(
                row["id"] == work_id and row["state"] == "completed" for row in rows
            ),
        )
    await bridge.team_dispatcher.stop()
    bound = bridge.teams.coordinator_status("local", TEAM)
    assert bound["coordinator"] == "codex"
    assert bound["session"]["session_id"] == SESSION["codex"]


async def test_acceptance_fixture_uses_a_real_managed_coordinator_binding(
    http_bridge,
    config,
    tmp_path,
    monkeypatch,
    owner_workspace,
):
    bridge, endpoint = http_bridge
    root = configure_workers(bridge, config, tmp_path, monkeypatch)
    owner_root, fixture = owner_workspace([card("fixture"), card("foreign", board="foreign")])
    assert fixture["entries"][0]["board_id"] != fixture["entries"][1]["board_id"]
    before = board_bytes(owner_root)
    async with MCPClientPool() as clients:
        await create_bound_coordinator(bridge, clients, endpoint, seed_second=True)
    assert [turn["subject"] for turn in inspect_invocations(root)] == [
        "Bootstrap codex",
        "Bootstrap grok",
    ]
    assert board_bytes(owner_root) == before
    assert verify(bridge.store)["valid"]


def authorize_sources(bridge, fixture, cards, indices, root, *, mismatched=()):
    from kirabridge.bridge_core.config import TeamContinuationConfig, TeamContinuationSource

    sources = []
    for index in indices:
        value = cards[index]
        entry = fixture["entries"][index]
        content = value["content"] if index not in mismatched else "Different reviewed bytes"
        sources.append(
            TeamContinuationSource(
                entry_id=entry["entry_id"],
                board_id=entry["board_id"],
                task_id=value["task_id"],
                content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                assignee=value["assignee"],
                cwd=str(root),
            )
        )
    bridge.config.team.continuation = TeamContinuationConfig(
        team_id=TEAM,
        workspace_id=fixture["workspace_id"],
        board_id=fixture["boards"]["allowed"],
        authority_ref="user-fixture-authorization",
        sources=sources,
    )
    bridge.team_dispatcher = TeamDispatcher(bridge)


def selected(rows):
    return [row for row in rows if row["title"].startswith("Fixture ")]


def completed(rows, count):
    chosen = selected(rows)
    return len(chosen) >= count and all(row["state"] == "completed" for row in chosen)


def resume_links(bridge, work_id):
    return bridge.store.db.execute(
        "SELECT r.resume_work_id,n.acknowledged,n.principal,n.payload "
        "FROM team_coordinator_resumes r "
        "JOIN completion_notices n ON n.id=r.notice_id WHERE r.work_id=?",
        (work_id,),
    ).fetchall()


async def test_continuation_parallel_selection_restart_and_exactly_one_acknowledged_followup(
    http_bridge,
    config,
    tmp_path,
    monkeypatch,
    owner_workspace,
):
    bridge, endpoint = http_bridge
    root = configure_workers(bridge, config, tmp_path, monkeypatch)
    cards = [card("first"), card("not-authorized", board="foreign"), card("next", board="foreign")]
    owner_root, fixture = owner_workspace(cards)
    before = board_bytes(owner_root)
    async with MCPClientPool() as clients:
        await create_bound_coordinator(bridge, clients, endpoint)
        authorize_sources(bridge, fixture, cards, (0, 2), root)
        # Both triggers can read the peer, but only one Work can be committed.
        contender = Bridge(config)
        try:
            await asyncio.gather(
                bridge.team_dispatcher.continuation.select(),
                contender.team_dispatcher.continuation.select(),
            )
        finally:
            await contender.threaddesk.close()
            contender.store.close()
        (first,) = selected(await list_work(clients))
        assert first["title"] == "Fixture first" and first["state"] == "queued"
        assert first["assigned_by"] == "codex" and first["assignee"] == "grok"
        assert first["core_task_id"] is None
        assert [turn["subject"] for turn in inspect_invocations(root)] == ["Bootstrap codex"]

        # New dispatcher has to adopt the durable unstarted Work with the same ID.
        reopened = Bridge(config)
        try:
            durable = reopened.teams.work_get("local", TEAM, first["id"])
            assert durable["state"] == "queued" and durable["core_task_id"] is None
        finally:
            reopened.store.close()
        bridge.team_dispatcher = TeamDispatcher(bridge)
        await bridge.team_dispatcher.start()
        rows = await wait_for_work(clients, lambda rows: completed(rows, 2))
        first_result, second = selected(rows)
        assert first_result["id"] == first["id"]
        assert second["title"] == "Fixture next"
        assert second["assigned_by"] == "codex" and second["assignee"] == "grok"
        for row in (first_result, second):
            core = bridge.store.get(row["core_task_id"])
            assert core["principal"] == "grok" and core["started"] is not None
            assert core["state"] == "completed"
            assert row["result"] == "FIXTURE_DONE " + row["title"]
        (ack,) = resume_links(bridge, first["id"])
        assert ack["acknowledged"] is not None and ack["principal"] == "codex"
        assert json.loads(ack["payload"])["work_id"] == first["id"]
        resume = bridge.teams.work_get("local", TEAM, ack["resume_work_id"])
        assert resume["result"] == "ACCEPT READY TASK " + first["id"]
        await bridge.team_dispatcher.stop()
        await bridge.team_dispatcher.continuation.select()
        assert [row["id"] for row in selected(await list_work(clients))] == [
            first["id"],
            second["id"],
        ]
    invocations = inspect_invocations(root)
    assert [turn["subject"] for turn in invocations if turn["principal"] == "grok"] == [
        "Fixture first",
        "Fixture next",
    ]
    assert board_bytes(owner_root) == before
    assert verify(bridge.store)["valid"]


@pytest.mark.parametrize("scenario", ["empty", "unapproved", "changed_hash", "historical", "hold"])
async def test_continuation_without_a_current_authorized_source_creates_no_agent_work(
    http_bridge,
    config,
    tmp_path,
    monkeypatch,
    owner_workspace,
    scenario,
):
    bridge, endpoint = http_bridge
    root = configure_workers(bridge, config, tmp_path, monkeypatch)
    cards = [
        card(
            "candidate",
            historical=scenario == "historical",
            state="HOLD" if scenario == "hold" else "READY",
        )
    ]
    if scenario == "empty":
        owner_root, fixture = owner_workspace([])
        fixture["entries"] = [
            {"board_id": fixture["boards"]["allowed"], "entry_id": "missing-empty"}
        ]
    elif scenario == "unapproved":
        owner_root, fixture = owner_workspace([card("unapproved", board="foreign")])
        fixture["entries"] = [
            {"board_id": fixture["boards"]["allowed"], "entry_id": "missing-approved"}
        ]
    else:
        owner_root, fixture = owner_workspace(cards)
    before = board_bytes(owner_root)
    async with MCPClientPool() as clients:
        await create_bound_coordinator(bridge, clients, endpoint)
        authorize_sources(
            bridge,
            fixture,
            cards,
            (0,),
            root,
            mismatched=(0,) if scenario == "changed_hash" else (),
        )
        await bridge.team_dispatcher.continuation.select()
        assert not selected(await list_work(clients))
    assert [turn["subject"] for turn in inspect_invocations(root)] == ["Bootstrap codex"]
    assert board_bytes(owner_root) == before


async def test_continuation_does_not_advance_past_an_active_or_unknown_work(
    http_bridge,
    config,
    tmp_path,
    monkeypatch,
    owner_workspace,
):
    bridge, endpoint = http_bridge
    root = configure_workers(bridge, config, tmp_path, monkeypatch)
    cards = [card("interrupted"), card("would-be-next")]
    owner_root, fixture = owner_workspace(cards)
    before = board_bytes(owner_root)
    async with MCPClientPool() as clients:
        await create_bound_coordinator(bridge, clients, endpoint)
        authorize_sources(bridge, fixture, cards, (0, 1), root)
        await bridge.team_dispatcher.continuation.select()
        (first,) = selected(await list_work(clients))
        claim = bridge.teams.claim(first["id"])
        assert claim["state"] == "dispatching" and claim["core_task_id"]
        await bridge.team_dispatcher.continuation.select()
        assert [row["id"] for row in selected(await list_work(clients))] == [first["id"]]
        bridge.team_dispatcher = TeamDispatcher(bridge)
        await bridge.team_dispatcher.start()
        await wait_for_work(
            clients,
            lambda rows: any(
                row["id"] == first["id"] and row["state"] == "unknown" for row in rows
            ),
        )
        await bridge.team_dispatcher.stop()
        await bridge.team_dispatcher.continuation.select()
        final = await list_work(clients)
        (original,) = selected(final)
        assert original["id"] == first["id"]
        assert original["error"] == "team_core_missing_after_claim"
        assert sorted(row["title"] for row in final) == [
            "Bootstrap codex",
            "Fixture interrupted",
        ]
        assert (
            bridge.store.db.execute(
                "SELECT count(*) FROM tasks WHERE started IS NOT NULL"
            ).fetchone()[0]
            == 1
        )
    assert [turn["subject"] for turn in inspect_invocations(root)] == ["Bootstrap codex"]
    assert board_bytes(owner_root) == before


async def test_continuation_preserves_logical_claim_through_revision_and_coordinator_change(
    http_bridge,
    config,
    tmp_path,
    monkeypatch,
    owner_workspace,
):
    bridge, endpoint = http_bridge
    root = configure_workers(bridge, config, tmp_path, monkeypatch)
    cards = [card("first")]
    owner_root, fixture = owner_workspace(cards)
    async with MCPClientPool() as clients:
        await create_bound_coordinator(bridge, clients, endpoint, seed_second=True)
        authorize_sources(bridge, fixture, cards, (0,), root)
        await bridge.team_dispatcher.start()
        first_rows = await wait_for_work(clients, lambda rows: completed(rows, 1))
        (first,) = selected(first_rows)
        assert first["assigned_by"] == "codex"
        await wait_for_work(
            clients,
            lambda rows: any(row["result"] == "ACCEPT READY TASK " + first["id"] for row in rows),
        )
        await bridge.team_dispatcher.stop()

        # An ordinary owner append changes the board revision, not a logical claim's identity.
        owner_workspace([card("outside-authorization")], boards=fixture["boards"])
        after_append = board_bytes(owner_root)
        await bridge.team_dispatcher.continuation.select()
        assert [work["id"] for work in selected(await list_work(clients))] == [first["id"]]
        assert board_bytes(owner_root) == after_append

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
                    "idempotency_key": "fixture-transfer",
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
        new_role = await rpc(clients, "local", "team_coordinator_status", {"team_id": TEAM})
        assert new_role["coordinator"] == "grok"
        assert new_role["session"]["session_id"] == SESSION["grok"]
        await bridge.team_dispatcher.stop()

        # A replacement has a new physical entry and an independently approved content hash.
        replacement = card("first")
        changed = json.loads(replacement["content"])
        changed["title"] = "Fixture first revised"
        replacement["content"] = json.dumps(changed, sort_keys=True)
        new_cards = [replacement, card("new", board="foreign", assignee="codex")]
        _, new_fixture = owner_workspace(new_cards, boards=fixture["boards"])
        assert new_fixture["entries"][0]["entry_id"] != fixture["entries"][0]["entry_id"]
        after_replacement = board_bytes(owner_root)
        authorize_sources(bridge, new_fixture, new_cards, (0, 1), root)
        await bridge.team_dispatcher.start()
        rows = await wait_for_work(clients, lambda rows: completed(rows, 2))
        previous, subsequent = selected(rows)
        assert previous["id"] == first["id"] and previous["assigned_by"] == "codex"
        assert subsequent["assigned_by"] == "grok" and subsequent["assignee"] == "codex"
        assert subsequent["title"] == "Fixture new"
        claims = bridge.store.db.execute(
            "SELECT principal,object_id FROM team_operations WHERE operation='continuation'"
        ).fetchall()
        assert {(claim["principal"], claim["object_id"]) for claim in claims} == {
            ("local", previous["id"]),
            ("local", subsequent["id"]),
        }
        assert len(claims) == 2
        assert board_bytes(owner_root) == after_replacement
        await bridge.team_dispatcher.stop()
    attempts = [turn["subject"] for turn in inspect_invocations(root)]
    assert attempts.count("Fixture first") == 1
    assert "Fixture first revised" not in attempts
    assert attempts.count("Fixture new") == 1


async def test_transport_ack_without_coordinator_acceptance_does_not_select_followup(
    http_bridge,
    config,
    tmp_path,
    monkeypatch,
    owner_workspace,
):
    bridge, endpoint = http_bridge
    root = configure_workers(bridge, config, tmp_path, monkeypatch, accept_review=False)
    cards = [card("first"), card("not-after-hold")]
    owner_root, fixture = owner_workspace(cards)
    before = board_bytes(owner_root)
    async with MCPClientPool() as clients:
        await create_bound_coordinator(bridge, clients, endpoint)
        authorize_sources(bridge, fixture, cards, (0, 1), root)
        await bridge.team_dispatcher.start()
        rows = await wait_for_work(
            clients,
            lambda rows: any(
                row["state"] == "completed" and row["result"] == "HOLD" for row in rows
            ),
        )
        (first,) = selected(rows)
        assert first["title"] == "Fixture first" and first["state"] == "completed"
        (receipt,) = resume_links(bridge, first["id"])
        assert receipt["acknowledged"] is not None
        await bridge.team_dispatcher.stop()
        bridge.team_dispatcher = TeamDispatcher(bridge)
        bridge.team_dispatcher.continuation.next_scan = 0
        await bridge.team_dispatcher.continuation.select()
        assert [work["id"] for work in selected(await list_work(clients))] == [first["id"]]
    turns = inspect_invocations(root)
    assert [turn["subject"] for turn in turns if turn["principal"] == "grok"] == ["Fixture first"]
    assert board_bytes(owner_root) == before
