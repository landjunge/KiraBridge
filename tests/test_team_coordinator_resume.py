# ruff: noqa: F811
"""Finished delegated work -> durable notice -> exactly one coordinator resume work."""

import asyncio
import json
from pathlib import Path

import pytest
from test_agents import fake_cli
from test_mcp import http_bridge  # noqa: F401
from test_team_dispatcher import configure_team
from test_team_manager import core, create, domain, work  # noqa: F401,F811

from kirabridge.bridge_core.config import AgentConfig
from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.team_manager.models import TeamWorkComplete, TeamWorkCreate


def finish_grok_work(domain, key="order-1", result="Grok result"):
    """codex delegates to grok (the coordinator order), grok finishes it."""
    item = domain.delegate("codex", work(assignee="grok", title="Order A", idempotency_key=key))
    claimed = domain.claim(item["id"])
    domain.bind_task(item["id"], core(domain, claimed))
    domain.finish(item["id"], result, {"actions": []})
    return item["id"]


def notices(domain):
    return domain.store.db.execute(
        "SELECT * FROM completion_notices WHERE source='team' ORDER BY seq"
    ).fetchall()


def test_completion_is_bound_uniquely_to_the_original_order(domain):
    work_id = finish_grok_work(domain)
    (notice,) = notices(domain)
    payload = json.loads(notice["payload"])
    assert (notice["principal"], notice["target"], notice["source_id"]) == (
        "codex",
        "team:test-team",
        work_id,
    )
    assert payload["work_id"] == work_id and payload["delegation_key"] == "order-1"
    assert payload["assignee"] == "grok" and payload["outcome"] == "success"
    assert payload["project_completion_verified"] is False
    # Terminal state is idempotent: a repeated finish creates no second notice.
    domain.finish(work_id, "Grok result", {})
    assert len(notices(domain)) == 1


def test_failed_and_manual_completions_are_also_recorded(domain):
    failed = domain.delegate("codex", work(assignee="grok", idempotency_key="order-f"))
    domain.fail(failed["id"], "failed", "agent_timeout", {})
    manual = domain.delegate("codex", work(assignee="chatgpt", idempotency_key="order-m"))
    domain.work_complete(
        "chatgpt",
        TeamWorkComplete(
            team_id="test-team",
            work_id=manual["id"],
            success=True,
            result="done by hand",
            idempotency_key="done",
        ),
    )
    rows = [json.loads(n["payload"]) for n in notices(domain)]
    assert [r["outcome"] for r in rows] == ["failure", "success"]
    assert rows[0]["error_code"] == "agent_timeout"


def test_resume_is_opt_in(domain):
    finish_grok_work(domain)
    assert domain.resume_coordinators() == 0
    assert not domain.store.db.execute("SELECT 1 FROM team_coordinator_resumes").fetchall()


def test_codex_is_resumed_exactly_once_and_survives_restart(domain):
    domain.config.team.coordinator_resume = True
    work_id = finish_grok_work(domain)
    assert domain.resume_coordinators() == 1
    # A second pass, a second dispatcher loop or a restart must not start it again.
    assert domain.resume_coordinators() == 0
    (link,) = domain.store.db.execute("SELECT * FROM team_coordinator_resumes").fetchall()
    resume = domain.work_get("codex", "test-team", link["resume_work_id"])
    assert link["work_id"] == work_id
    assert resume["assignee"] == "codex" and resume["assigned_by"] == "codex"
    assert resume["state"] == "queued" and work_id in resume["body"]
    assert "Grok result" in resume["body"]
    assert notices(domain)[0]["acknowledged"] is not None


def test_crash_between_delegation_and_link_does_not_start_twice(domain):
    domain.config.team.coordinator_resume = True
    finish_grok_work(domain)
    (notice,) = notices(domain)
    original = domain.store.transaction
    calls = {"n": 0}

    class Boom(Exception):
        pass

    def exploding():
        calls["n"] += 1
        if calls["n"] == 1:  # the delegation commits ...
            return original()
        raise Boom  # ... the process dies before the link/ack transaction

    domain.store.transaction = exploding
    with pytest.raises(Boom):
        domain.resume_coordinators()
    domain.store.transaction = original
    # Work was delegated, link was not committed: the retry reuses the same work.
    assert not domain.store.db.execute("SELECT 1 FROM team_coordinator_resumes").fetchall()
    before = domain.store.db.execute("SELECT count(*) FROM team_work").fetchone()[0]
    assert domain.resume_coordinators() == 1
    after = domain.store.db.execute("SELECT count(*) FROM team_work").fetchone()[0]
    assert after == before
    assert notices(domain)[0]["id"] == notice["id"]


def test_a_resume_turn_never_wakes_itself(domain):
    domain.config.team.coordinator_resume = True
    finish_grok_work(domain)
    domain.resume_coordinators()
    link = domain.store.db.execute("SELECT * FROM team_coordinator_resumes").fetchone()
    claimed = domain.claim(link["resume_work_id"])
    domain.bind_task(claimed["id"], core(domain, claimed))
    domain.finish(claimed["id"], "Next decision: done", {"actions": []})
    assert len(notices(domain)) == 1  # only the original worker completion
    assert domain.resume_coordinators() == 0


def test_manual_delegator_is_not_resumed(domain):
    domain.config.team.coordinator_resume = True
    item = domain.delegate("chatgpt", work(assignee="grok", idempotency_key="by-chatgpt"))
    claimed = domain.claim(item["id"])
    domain.bind_task(item["id"], core(domain, claimed))
    domain.finish(item["id"], "result", {"actions": []})
    assert domain.resume_coordinators() == 0
    assert notices(domain)[0]["principal"] == "chatgpt"
    with pytest.raises(BridgeError):
        domain.work_get("outsider", "test-team", item["id"])


def test_receive_returns_team_notice_to_its_delegator(domain, bridge):
    work_id = finish_grok_work(domain)
    got = bridge.completions.receive("codex", "team:test-team")
    assert [n["payload"]["work_id"] for n in got["notices"]] == [work_id]


# --- Full chain with the real dispatcher and fake native CLIs -------------------------
CODEX = """import json,sys
prompt=sys.stdin.read()
open('coord-prompts','a').write(json.dumps(prompt)+'\\n')
n=len(open('coord-prompts').read().splitlines())
if n==1:
 answer={'kirabridge_team':'1','result':'ORDER_DELEGATED','actions':[
  {'type':'task','assignee':'grok','title':'Pruefen','body':'Harmlose Folgearbeit'}]}
else:
 answer={'kirabridge_team':'1','result':'COORDINATOR_FINAL_DECISION','actions':[]}
for event in [{'type':'thread.started','thread_id':'01a1ce14-57d2-75f3-85c9-7208392ce422'},
 {'type':'turn.started'},
 {'type':'item.completed','item':{'type':'agent_message','text':json.dumps(answer)}},
 {'type':'turn.completed'}]:
 print(json.dumps(event),flush=True)
"""


def coordinator(bridge, config, tmp_path, monkeypatch, body=CODEX):
    root = configure_team(bridge, config, tmp_path, monkeypatch)
    directory = tmp_path / "coordinator-cli"
    directory.mkdir()
    config.agents["codex"] = AgentConfig(kind="codex", executable=fake_cli(directory, body))
    config.team.coordinator_resume = True
    return Path(root)


async def rows(clients, count):
    async with asyncio.timeout(20):
        while True:
            listed = (
                await clients.call(
                    "local", "team_work_list", {"team_id": "e2e", "after": 0, "limit": 20}
                )
            ).structuredContent["work"]
            if len(listed) >= count and all(r["state"] == "completed" for r in listed):
                return listed
            await asyncio.sleep(0.05)


async def connect(clients, endpoint):
    for name, token in (
        ("local", "local-test-" + "a" * 40),
        ("codex", "codex-team-test-" + "x" * 40),
        ("grok", "grok-team-test-" + "x" * 40),
    ):
        await clients.connect(Peer(name, url=endpoint, token=token))
    made = await clients.call(
        "local",
        "team_create",
        {
            "request": {
                "team_id": "e2e",
                "name": "E2E",
                "coordinator": "local",
                "members": {"local": "coordinator", "codex": "worker", "grok": "reviewer"},
                "idempotency_key": "e2e-create",
            }
        },
    )
    assert not made.structuredContent.get("error")


async def test_order_agent_result_coordinator_followup_and_completion_chain(
    http_bridge,  # noqa: F811
    config,
    tmp_path,
    monkeypatch,
):
    bridge, endpoint = http_bridge
    root = coordinator(bridge, config, tmp_path, monkeypatch)
    await bridge.team_dispatcher.start()
    async with MCPClientPool() as clients:
        await connect(clients, endpoint)
        await clients.call(
            "local",
            "team_work_create",
            {
                "request": {
                    "team_id": "e2e",
                    "assignee": "codex",
                    "title": "Auftrag",
                    "body": "Delegiere eine Prüfung und entscheide danach.",
                    "idempotency_key": "e2e-order",
                }
            },
        )
        listed = await rows(clients, 3)
    by_assignee = {(r["assignee"], r["assigned_by"]): r for r in listed}
    order = by_assignee[("codex", "local")]
    agent = by_assignee[("grok", "codex")]
    decision = by_assignee[("codex", "codex")]
    assert (order["result"], agent["result"]) == ("ORDER_DELEGATED", "GROK_CHILD_DONE")
    assert decision["result"] == "COORDINATOR_FINAL_DECISION"
    # The coordinator was woken by the exact finished order, once, with its result.
    prompts = [json.loads(line) for line in (root / "coord-prompts").read_text().splitlines()]
    assert len(prompts) == 2 and agent["id"] in prompts[1] and "GROK_CHILD_DONE" in prompts[1]
    (link,) = bridge.store.db.execute("SELECT * FROM team_coordinator_resumes").fetchall()
    assert (link["work_id"], link["resume_work_id"]) == (agent["id"], decision["id"])
    # Final decision had no actions: the chain ends here, nothing else starts.
    await asyncio.sleep(0.5)
    assert len((root / "coord-prompts").read_text().splitlines()) == 2
    assert bridge.store.db.execute("SELECT count(*) FROM team_work").fetchone()[0] == 3


async def test_interrupted_coordinator_is_resumed_after_restart_without_duplicate_start(
    http_bridge,  # noqa: F811
    config,
    tmp_path,
    monkeypatch,
):
    bridge, endpoint = http_bridge
    root = coordinator(
        bridge, config, tmp_path, monkeypatch, CODEX.replace("if n==1:", "if False:")
    )
    teams = bridge.teams
    # The agent finished while no dispatcher was running (bridge down / interrupted).
    teams.create(
        "local",
        create(
            team_id="e2e",
            members={"local": "coordinator", "codex": "worker", "grok": "reviewer"},
            coordinator="local",
            idempotency_key="e2e-create",
        ),
    )
    item = teams.delegate(
        "codex",
        TeamWorkCreate(
            team_id="e2e", assignee="grok", title="Order", body="x", idempotency_key="order"
        ),
    )
    claimed = teams.claim(item["id"])
    teams.bind_task(item["id"], core(teams, claimed))
    teams.finish(item["id"], "RESULT_BEFORE_RESTART", {"actions": []})
    for _ in range(2):  # first start resumes; a restart must not resume again
        await bridge.team_dispatcher.start()
        async with asyncio.timeout(20):
            while not (root / "coord-prompts").exists():
                await asyncio.sleep(0.05)
            while teams.pending() or teams.inflight():
                await asyncio.sleep(0.05)
        await bridge.team_dispatcher.stop()
    prompts = (root / "coord-prompts").read_text().splitlines()
    assert len(prompts) == 1 and "RESULT_BEFORE_RESTART" in json.loads(prompts[0])
    assert (
        bridge.store.db.execute("SELECT count(*) FROM team_coordinator_resumes").fetchone()[0] == 1
    )
