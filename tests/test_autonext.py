"""Isolated board + authenticated existing dispatcher + real deterministic CLI.

No provider/model/API call, native UI, installed profile or productive board.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from test_agents import fake_cli
from test_mcp import http_bridge  # noqa: F401
from test_team_dispatcher import configure_team

from kirabridge.autonext.manager import AutoNextManager, text_sha
from kirabridge.autonext.models import AutoNextConfig, AutoNextControl, ReadyCard
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import AgentConfig, ReceiverConfig
from kirabridge.bridge_core.models import BridgeError, TaskRequest, canonical
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.message_manager import MessageSend
from kirabridge.team_manager.models import (
    TeamCreate,
    TeamWorkClaim,
    TeamWorkComplete,
    TeamWorkCreate,
)
from kirabridge.whiteboard_read import append_whiteboard, read_whiteboard

CLI = """import json,sys,time,pathlib
prompt=sys.stdin.read()
card=json.loads(prompt.split("\\n",1)[1]);task=card["task_id"]
with open("autonext-invocations.jsonl","a") as f:
 f.write(json.dumps({"task_id":task,"prompt":prompt})+"\\n")
pathlib.Path(task+".effect").write_text("one authorized effect")
if card["instruction"]=="fixture-timeout":time.sleep(5)
answer={"kirabridge_team":"1","result":"DONE:"+task,"actions":[]}
if card["instruction"]=="fixture-delegate":
 answer["actions"]=[{"type":"task","assignee":"grok","title":"unapproved","body":"must not run"}]
for event in [{"type":"thread.started","thread_id":"fixture-"+task},
 {"type":"turn.started"},
 {"type":"item.completed","item":{"type":"agent_message","text":json.dumps(answer)}},
 {"type":"turn.completed"}]:print(json.dumps(event),flush=True)
"""


@pytest.fixture
async def scenario(http_bridge, config, tmp_path, monkeypatch):  # noqa: F811
    bridge, endpoint = http_bridge
    root = Path(configure_team(bridge, config, tmp_path, monkeypatch, answer="fixture"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    directory = tmp_path / "autonext-cli"
    directory.mkdir()
    config.agents["codex"] = AgentConfig(
        kind="codex", executable=fake_cli(directory, CLI), api_key_env="AUTONEXT_FIXTURE_API_KEY"
    )
    monkeypatch.delenv("AUTONEXT_FIXTURE_API_KEY", raising=False)
    desk = tmp_path / "desk"
    (desk / "threads").mkdir(parents=True)
    (desk / "whiteboard").mkdir()
    (desk / "threads/board.json").write_text(
        json.dumps({"id": "board", "title": "existing test board"})
    )
    config.threaddesk.enabled = True
    config.threaddesk.workspace = str(desk)
    bridge.teams.create(
        "local",
        TeamCreate(
            team_id="auto-team",
            name="isolated",
            coordinator="local",
            members={"local": "coordinator", "codex": "worker", "grok": "reviewer"},
            idempotency_key="create-team",
        ),
    )
    seed = bridge.teams.delegate(
        "local",
        TeamWorkCreate(
            team_id="auto-team",
            assignee="local",
            title="previous authorized task",
            body="operator-confirmed predecessor",
            idempotency_key="seed",
        ),
    )
    bridge.teams.work_claim(
        "local",
        TeamWorkClaim(team_id="auto-team", work_id=seed["id"], idempotency_key="claim-seed"),
    )
    bridge.teams.work_complete(
        "local",
        TeamWorkComplete(
            team_id="auto-team",
            work_id=seed["id"],
            result="PREDECESSOR",
            idempotency_key="finish-seed",
        ),
    )

    def source(
        task_id, *, state="READY", instruction="authorized fixture", acceptance="result_sha256"
    ):
        card = {
            "autonext": 1,
            "task_id": task_id,
            "state": state,
            "product": "KiraBridge",
            "cwd": str(root),
            "sandbox": "read-only",
            "title": task_id,
            "instruction": instruction,
            "acceptance": {"kind": acceptance},
        }
        if acceptance == "result_sha256":
            card["acceptance"]["expected_sha256"] = text_sha("DONE:" + task_id)
        content = json.dumps(card)
        entry = append_whiteboard(
            str(desk),
            "board",
            actor="operator",
            actor_type="human",
            entry_type="task",
            content=content,
            external_key="source-" + task_id,
        )
        return {"task_id": task_id, "entry_id": entry["id"], "content_sha256": text_sha(content)}

    def grant(cards):
        config.autonext = AutoNextConfig(
            enabled=True,
            grant_id="grant-v1",
            principal="local",
            team_id="auto-team",
            team_revision=bridge.teams.get("local", "auto-team")["revision"],
            board_id="board",
            after_work_id=seed["id"],
            after_result_sha256=text_sha("PREDECESSOR"),
            cards=cards,
            max_tasks=2,
            lease_seconds=30,
            budget_state="available",
            budget_observed_at=time.time(),
            budget_valid_until=time.time() + 120,
            budget_source_ref="isolated-fixture-budget",
            billing_evidence_ref="isolated-fixture-no-provider",
        )

    def calls():
        log = root / "autonext-invocations.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    async def start():
        await bridge.team_dispatcher.start()
        await bridge.autonext.start()

    yield {
        "bridge": bridge,
        "config": config,
        "root": root,
        "desk": desk,
        "source": source,
        "grant": grant,
        "calls": calls,
        "start": start,
        "endpoint": endpoint,
        "evidence": tmp_path / "autonext-evidence.json",
    }
    await bridge.autonext.stop()
    await bridge.team_dispatcher.stop()


async def until(predicate, timeout=12):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.025)


async def test_two_explicit_ready_cards_once_and_zero_unapproved_with_actual_receipts(scenario):
    s = scenario
    b = s["bridge"]
    s["source"]("intruder", instruction="UNAPPROVED_SECRET_DO_NOT_FORWARD")
    s["grant"]([s["source"]("old-idea", state="IDEA"), s["source"]("one"), s["source"]("two")])
    await s["start"]()
    await until(lambda: b.autonext.inspect()["state"] == "complete")
    assert [x["task_id"] for x in s["calls"]()] == ["one", "two"]
    assert not (s["root"] / "intruder.effect").exists()
    assert not (s["root"] / "old-idea.effect").exists()
    first = b.autonext.receipt("local", "one")
    second = b.autonext.receipt("local", "two")
    assert first["result_sha256"] == text_sha("DONE:one") and second["result_sha256"] == text_sha(
        "DONE:two"
    )
    assert first["accepted_at"] <= b.store.get(second["core_task_id"], "codex")["created"]
    for receipt in (first, second):
        core = b.store.get(receipt["core_task_id"], "codex")
        assert core["state"] == "completed" and core["attempt"] == 1
    outbox = b.store.db.execute("SELECT * FROM autonext_outbox").fetchall()
    assert len(outbox) == 4 and all(r["verified"] for r in outbox)
    for row in outbox:
        read = read_whiteboard(str(s["desk"]), "board", row["entry_id"])["entry"]
        assert read["content"] == row["content"] and not read["truncated"]
        assert "UNAPPROVED_SECRET" not in read["content"] and "DONE:" not in read["content"]
    assert all("UNAPPROVED_SECRET" not in x["prompt"] for x in s["calls"]())
    s["evidence"].write_text(
        json.dumps(
            {
                "scope": (
                    "isolated authenticated MCP/dispatcher plus deterministic CLI; "
                    "not production/provider acceptance"
                ),
                "executed_task_ids": [x["task_id"] for x in s["calls"]()],
                "unapproved_effects": 0,
                "acceptance_receipts": [first, second],
                "board_receipts": [
                    {
                        "entry_id": r["entry_id"],
                        "phase": r["phase"],
                        "verified": bool(r["verified"]),
                    }
                    for r in outbox
                ],
                "core_attempts": [
                    b.store.get(r["core_task_id"], "codex")["attempt"] for r in (first, second)
                ],
            },
            indent=2,
        )
        + "\n"
    )
    await b.autonext.stop()
    b.autonext = AutoNextManager(b)
    await b.autonext.tick()  # Restart reads original receipts, never reclaims.
    assert [x["task_id"] for x in s["calls"]()] == ["one", "two"]
    assert b.store.db.execute("SELECT count(*) FROM autonext_outbox").fetchone()[0] == 4


@pytest.mark.parametrize("where", ["child", "parent"])
async def test_overlapping_agent_cwd_cannot_bypass_worktree_lease(scenario, where):
    s = scenario
    b = s["bridge"]
    s["grant"]([s["source"]("one")])
    await b.autonext.tick()
    other = s["root"] / "subdir" if where == "child" else s["root"].parent
    with pytest.raises(BridgeError, match="lease"):
        b.autonext.authorize_execution({"id": "foreign", "args": {"cwd": str(other)}})
    assert s["calls"]() == []


@pytest.mark.parametrize("where", ["child", "parent"])
async def test_existing_overlapping_team_work_blocks_new_claim(scenario, where):
    s = scenario
    b = s["bridge"]
    s["grant"]([s["source"]("one")])
    other = s["root"] / "subdir" if where == "child" else s["root"].parent
    s["config"].team.workers["grok"].cwd = str(other)
    b.teams.delegate(
        "local",
        TeamWorkCreate(
            team_id="auto-team",
            assignee="grok",
            title="existing review",
            body="inert existing scoped fixture",
            idempotency_key="other-work",
        ),
    )
    await b.autonext.tick()
    assert b.autonext.inspect()["reason"] == "autonext_worktree_busy" and s["calls"]() == []


async def test_admission_fault_stops_autonext_without_killing_existing_dispatcher(
    scenario, monkeypatch
):
    s = scenario
    b = s["bridge"]
    s["grant"]([s["source"]("one")])
    await b.autonext.tick()
    legacy = b.teams.delegate(
        "local",
        TeamWorkCreate(
            team_id="auto-team",
            assignee="grok",
            title="legacy review",
            body="existing separately authorized work",
            idempotency_key="legacy-review",
        ),
    )
    monkeypatch.setattr(b.autonext, "_configuration_ref", Mock(side_effect=OSError("missing")))
    selected = []

    async def legacy_only(work, **kwargs):
        selected.append(work["id"])
        b.team_dispatcher.stopping = True

    monkeypatch.setattr(b.team_dispatcher, "_run", legacy_only)
    await b.team_dispatcher.start()
    await asyncio.wait_for(asyncio.gather(*b.team_dispatcher.workers), 2)
    assert selected == [legacy["id"]]
    assert b.autonext.inspect()["state"] == "stopped" and s["calls"]() == []
    assert (
        b.store.db.execute("SELECT reason FROM autonext_runs").fetchone()[0]
        == "autonext_state_unknown"
    )


@pytest.mark.parametrize("phase", ["agent_running", "unknown", "accepted"])
async def test_preexisting_handoff_reservation_blocks_overlapping_claim(scenario, phase):
    s = scenario
    b = s["bridge"]
    s["grant"]([s["source"]("one")])
    b.prepare(
        "local",
        TaskRequest(
            task_id="existing-handoff",
            idempotency_key="existing-handoff",
            operation="file.list",
            arguments={"path": str(s["root"])},
        ),
    )
    metadata = {
        "last_task_id": "existing-handoff",
        "principal": "local",
        "phase": phase,
        "cwd": str(s["root"]),
    }
    b.store.db.execute(
        "INSERT INTO handoff_bindings VALUES(?,?,?,?,?,?,?,?)",
        (
            "old-handoff",
            "local",
            "operator",
            "old",
            1,
            "existing-handoff",
            "hash",
            canonical(metadata),
        ),
    )
    await b.autonext.tick()
    assert s["calls"]() == []
    if phase == "accepted":
        assert b.store.db.execute("SELECT count(*) FROM autonext_items").fetchone()[0] == 1
    else:
        assert b.autonext.inspect()["reason"] == "autonext_worktree_busy"
        assert not b.store.db.execute("SELECT 1 FROM autonext_items").fetchone()


@pytest.mark.parametrize(
    "state,scope", [("running", "overlap"), ("unknown", "missing"), ("unknown", "other")]
)
async def test_preexisting_receiver_scope_is_persisted_and_not_guessed(scenario, state, scope):
    s = scenario
    b = s["bridge"]
    s["grant"]([s["source"]("one")])
    s["config"].messaging.receivers["codex"] = ReceiverConfig(cwd=str(s["root"]))
    for name, peer in (("local", "codex"), ("codex", "local")):
        policy = s["config"].principals[name]
        policy.capabilities += ["message.send", "message.read", "message.ack"]
        policy.message_peers = [peer]
    sent = b.messages.send(
        "local",
        MessageSend(
            recipient="codex",
            conversation_id="preexisting",
            idempotency_key="preexisting",
            body="inert prior authorized work",
            dispatch=True,
        ),
    )
    assert b.message_receiver._claim(sent["id"])
    pin = b.store.db.execute("SELECT execution_cwd FROM message_jobs").fetchone()[0]
    assert pin == str(s["root"])
    if scope == "missing":
        b.store.db.execute("UPDATE message_jobs SET execution_cwd=NULL")
    if scope == "other":
        elsewhere = s["root"].parent / "different-worktree"
        elsewhere.mkdir()
        b.store.db.execute("UPDATE message_jobs SET execution_cwd=?", (str(elsewhere),))
    b.store.db.execute("UPDATE message_jobs SET state=?", (state,))
    # A changed receiver configuration never rewrites an already claimed scope.
    s["config"].messaging.receivers["codex"].cwd = str(s["root"].parent / "changed")
    await b.autonext.tick()
    assert s["calls"]() == []
    if scope == "other":
        assert b.store.db.execute("SELECT 1 FROM autonext_items").fetchone()
    else:
        assert b.autonext.inspect()["reason"] == (
            "autonext_scope_unknown" if scope == "missing" else "autonext_worktree_busy"
        )


async def test_unconfirmed_visible_delivery_is_never_overlooked(scenario):
    s = scenario
    b = s["bridge"]
    s["grant"]([s["source"]("one")])
    b.store.db.execute(
        "INSERT INTO visible_handoffs VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            "old-visible",
            "local",
            "codex",
            "hash",
            "{}",
            "old-message",
            "unknown",
            1,
            1,
            "{}",
        ),
    )
    await b.autonext.tick()
    assert b.autonext.inspect()["reason"] == "autonext_scope_unknown"
    assert s["calls"]() == []


async def test_sibling_directories_of_same_git_worktree_share_one_writer_lease(scenario):
    s = scenario
    b = s["bridge"]
    (s["root"] / ".git").mkdir()
    first = s["root"] / "src"
    first.mkdir()
    second = s["root"] / "tests"
    second.mkdir()
    s["grant"]([s["source"]("one")])
    # The worker is deliberately scoped to a subdirectory, not a second worktree.
    ref = s["config"].autonext.cards[0]
    entry_path = s["desk"] / "whiteboard/board" / (ref.entry_id + ".json")
    entry = json.loads(entry_path.read_text())
    card = json.loads(entry["content"])
    card["cwd"] = str(first)
    entry["content"] = json.dumps(card)
    entry_path.write_text(json.dumps(entry))
    ref.content_sha256 = text_sha(entry["content"])
    s["config"].team.workers["codex"].cwd = str(first)
    await b.autonext.tick()
    with pytest.raises(BridgeError, match="lease"):
        b.autonext.authorize_execution({"id": "sibling-writer", "args": {"cwd": str(second)}})
    assert s["calls"]() == []


@pytest.mark.parametrize("change", ["model", "executable", "bytes", "timeout"])
async def test_restart_never_adopts_changed_executor_under_old_grant(scenario, change):
    s = scenario
    b = s["bridge"]
    s["grant"]([s["source"]("one")])
    await b.autonext.tick()
    agent = s["config"].agents["codex"]
    if change == "model":
        agent.model = "different-model"
    if change == "executable":
        agent.executable = sys.executable
    if change == "bytes":
        p = Path(agent.executable)
        p.write_text(p.read_text() + "\n# changed executor\n")
    if change == "timeout":
        s["config"].team.workers["codex"].timeout = 2
    b.autonext = AutoNextManager(b)
    await b.autonext.tick()
    assert b.autonext.inspect()["reason"] == "autonext_grant_changed"
    assert s["calls"]() == []


async def test_configured_effective_api_key_blocks_subscription_only_automation(
    scenario, monkeypatch
):
    s = scenario
    b = s["bridge"]
    s["grant"]([s["source"]("one")])
    monkeypatch.setenv("AUTONEXT_FIXTURE_API_KEY", "synthetic-not-a-real-secret")
    await b.autonext.tick()
    assert b.autonext.inspect()["reason"] == "autonext_billing_unknown" and s["calls"]() == []


async def test_budget_near_expiry_cannot_start_a_longer_turn(scenario):
    s = scenario
    b = s["bridge"]
    s["grant"]([s["source"]("one")])
    s["config"].autonext.budget_valid_until = time.time() + 1
    await b.autonext.tick()
    assert b.autonext.inspect()["reason"] == "autonext_budget_stop" and s["calls"]() == []
    assert not b.store.db.execute("SELECT 1 FROM autonext_items").fetchone()


async def test_remaining_lease_is_rechecked_immediately_before_executor(scenario):
    s = scenario
    b = s["bridge"]
    s["grant"]([s["source"]("one")])
    await b.autonext.tick()
    item = b.store.db.execute("SELECT * FROM autonext_items").fetchone()
    work = b.teams.claim(item["work_id"])
    b.store.db.execute("UPDATE autonext_items SET lease_until=?", (time.time() + 1,))
    with pytest.raises(BridgeError, match="Remaining lease"):
        b.autonext.authorize_execution(
            {"id": work["core_task_id"], "args": {"cwd": str(s["root"])}}
        )
    assert s["calls"]() == []


async def test_timeout_stops_chain_without_starting_second_task(scenario):
    s = scenario
    b = s["bridge"]
    s["grant"]([s["source"]("one", instruction="fixture-timeout"), s["source"]("two")])
    s["config"].team.workers["codex"].timeout = 1
    await s["start"]()
    await until(lambda: b.autonext.inspect()["state"] == "stopped")
    assert [x["task_id"] for x in s["calls"]()] == ["one"]
    assert not (s["root"] / "two.effect").exists()


async def test_turn_budget_does_not_execute_third_approved_task(scenario):
    s = scenario
    b = s["bridge"]
    s["grant"]([s["source"]("one"), s["source"]("two"), s["source"]("three")])
    await s["start"]()
    await until(lambda: b.autonext.inspect()["state"] == "stopped")
    assert b.autonext.inspect()["reason"] == "autonext_turn_budget_reached"
    assert [x["task_id"] for x in s["calls"]()] == ["one", "two"]
    approved = s["config"].autonext.cards[2]
    b.autonext._claim(approved, b.autonext._card(approved))  # Late preflight cannot reopen STOP.
    assert b.store.db.execute("SELECT count(*) FROM autonext_items").fetchone()[0] == 2


async def test_write_work_cannot_use_a_self_reported_result_as_project_completion(scenario):
    s = scenario
    ref = s["source"]("write-scope")
    raw = read_whiteboard(str(s["desk"]), "board", ref["entry_id"])["entry"]["content"]
    value = json.loads(raw)
    value["sandbox"] = "workspace-write"
    with pytest.raises(ValueError, match="independently confirmed"):
        ReadyCard.model_validate(value)
    value["acceptance"] = {"kind": "operator_receipt"}
    assert ReadyCard.model_validate(value).sandbox == "workspace-write"
    value["autonext"] = True
    with pytest.raises(ValueError, match="exact card version"):
        ReadyCard.model_validate(value)


async def test_lost_board_append_reply_reconciles_same_receipt_and_stops_input(
    scenario, monkeypatch
):
    import kirabridge.autonext.manager as module

    s = scenario
    b = s["bridge"]
    s["grant"]([s["source"]("one")])
    original = module.append_whiteboard
    lost = False

    def append(*args, **kwargs):
        nonlocal lost
        value = original(*args, **kwargs)
        if not lost:
            lost = True
            raise OSError("simulated lost board reply after append")
        return value

    monkeypatch.setattr(module, "append_whiteboard", append)
    await b.autonext.tick()
    assert b.autonext.inspect()["state"] == "stopped" and s["calls"]() == []
    rows = b.store.db.execute("SELECT * FROM autonext_outbox").fetchall()
    assert all(row["verified"] for row in rows)
    count = len(list((s["desk"] / "whiteboard/board").glob("*.json")))
    b.autonext = AutoNextManager(b)
    await b.autonext.tick()
    assert len(list((s["desk"] / "whiteboard/board").glob("*.json"))) == count


async def test_actual_controller_process_crash_after_claim_is_recovered_once(scenario, tmp_path):
    s = scenario
    b = s["bridge"]
    s["grant"]([s["source"]("one"), s["source"]("two")])
    config_file = tmp_path / "isolated-config.json"
    config_file.write_text(s["config"].model_dump_json())
    config_file.chmod(0o600)
    program = """import asyncio,json,os,pathlib,sys
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config
value=json.loads(pathlib.Path(sys.argv[1]).read_text());value.pop("visible_handoffs")
cfg=Config.model_validate(value);cfg.visible_handoffs.enabled=False
b=Bridge(cfg);original=b.autonext._flush
def crash():
 if b.store.db.execute("SELECT 1 FROM autonext_items").fetchone():os._exit(91)
 original()
b.autonext._flush=crash
asyncio.run(b.autonext.tick())
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        program,
        str(config_file),
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(process.communicate(), 10)
    assert process.returncode == 91, (out, err)
    assert b.store.db.execute("SELECT claim_published FROM autonext_items").fetchone()[0] == 0
    b.autonext = AutoNextManager(b)
    await s["start"]()
    try:
        await until(lambda: b.autonext.inspect()["state"] == "complete")
    except TimeoutError:
        pytest.fail(
            json.dumps(
                {
                    "phase": "post_crash_recovery",
                    "child_returncode": process.returncode,
                    "run": b.autonext.inspect(),
                    "items": [
                        dict(row)
                        for row in b.store.db.execute(
                            "SELECT task_id,state,claim_published FROM autonext_items"
                        )
                    ],
                    "tasks": [
                        dict(row) for row in b.store.db.execute("SELECT id,state,error FROM tasks")
                    ],
                }
            )
        )
    assert [x["task_id"] for x in s["calls"]()] == ["one", "two"]


async def test_unexpected_worker_exception_stops_and_cleans_callback(scenario, monkeypatch):
    s = scenario
    b = s["bridge"]
    s["grant"]([s["source"]("one")])

    async def failure():
        raise RuntimeError("unexpected fixture failure")

    monkeypatch.setattr(b.autonext, "tick", failure)
    await b.autonext.start()
    await until(lambda: b.autonext.inspect()["state"] == "stopped")
    await b.autonext.stop()
    assert b.autonext.worker is None and b.autonext.loop is None and b.teams.on_change is None
    assert s["calls"]() == []


async def test_bridge_shutdown_still_stops_dispatcher_receiver_after_continuation_error():
    fake = SimpleNamespace(
        autonext=SimpleNamespace(stop=AsyncMock(side_effect=RuntimeError("stop"))),
        team_dispatcher=SimpleNamespace(stop=AsyncMock()),
        message_receiver=SimpleNamespace(stop=AsyncMock()),
        tasks=SimpleNamespace(stop=AsyncMock()),
        system_modules=SimpleNamespace(close=AsyncMock()),
        threaddesk=SimpleNamespace(close=AsyncMock()),
        store=SimpleNamespace(close=Mock()),
    )
    with pytest.raises(RuntimeError):
        await Bridge.__aexit__(fake, None, None, None)
    for obj in (fake.team_dispatcher, fake.message_receiver, fake.tasks):
        obj.stop.assert_awaited_once()
    fake.store.close.assert_called_once()


async def test_empty_or_nonready_grant_never_dispatches(scenario):
    s = scenario
    s["source"]("not-approved")
    s["grant"]([s["source"]("hold", state="HOLD"), s["source"]("stale", state="STALE")])
    await s["start"]()
    await until(lambda: s["bridge"].autonext.inspect()["state"] == "complete")
    assert s["calls"]() == []


@pytest.mark.parametrize("fault", ["budget", "anchor", "source", "identity"])
async def test_preflight_failure_never_starts_cli(scenario, fault):
    s = scenario
    card = s["source"]("one")
    s["grant"]([card])
    cfg = s["config"]
    if fault == "budget":
        cfg.autonext.budget_state = "unknown"
    if fault == "anchor":
        cfg.autonext.after_result_sha256 = "0" * 64
    if fault == "identity":
        cfg.autonext.team_revision += 1
    if fault == "source":
        card["content_sha256"] = "0" * 64
        cfg.autonext.cards[0].content_sha256 = "0" * 64
    await s["start"]()
    await until(lambda: s["bridge"].autonext.inspect()["state"] == "stopped")
    assert (
        s["calls"]() == []
        and s["bridge"].store.db.execute("SELECT count(*) FROM autonext_items").fetchone()[0] == 0
    )


async def test_crash_after_durable_claim_before_board_receipt_recovers_original_once(
    scenario, monkeypatch
):
    s = scenario
    b = s["bridge"]
    s["grant"]([s["source"]("one"), s["source"]("two")])
    original = b.autonext._flush

    class Crash(BaseException):
        pass

    def flush():
        if b.store.db.execute("SELECT 1 FROM autonext_items").fetchone():
            raise Crash()
        return original()

    monkeypatch.setattr(b.autonext, "_flush", flush)
    with pytest.raises(Crash):
        await b.autonext.tick()
    item = b.store.db.execute("SELECT * FROM autonext_items").fetchone()
    assert item["claim_published"] == 0 and b.teams.claim(item["work_id"]) is None
    b.autonext = AutoNextManager(b)
    await s["start"]()
    await until(lambda: b.autonext.inspect()["state"] == "complete")
    assert [x["task_id"] for x in s["calls"]()] == ["one", "two"]


async def test_claimed_core_missing_after_restart_is_unknown_not_resubmitted(scenario):
    s = scenario
    b = s["bridge"]
    s["grant"]([s["source"]("one"), s["source"]("two")])
    await b.autonext.tick()
    item = b.store.db.execute("SELECT * FROM autonext_items").fetchone()
    claimed = b.teams.claim(item["work_id"])
    assert claimed["core_task_id"]
    b.autonext = AutoNextManager(b)
    await s["start"]()
    await until(lambda: b.autonext.inspect()["state"] == "stopped")
    assert b.teams.work_get("local", "auto-team", item["work_id"])["state"] == "unknown"
    assert s["calls"]() == []


async def test_lost_submission_reply_does_not_reexecute_or_advance(scenario, monkeypatch):
    s = scenario
    b = s["bridge"]
    s["grant"]([s["source"]("one"), s["source"]("two")])
    original = b.team_dispatcher._call

    async def lost(pool, tool, args):
        result = await original(pool, tool, args)
        if tool == "task_submit":
            raise BridgeError("peer_timeout", "lost response after submission")
        return result

    monkeypatch.setattr(b.team_dispatcher, "_call", lost)
    await s["start"]()
    await until(lambda: b.autonext.inspect()["state"] == "stopped")
    await until(lambda: len(s["calls"]()) == 1)
    await b.autonext.stop()
    b.autonext = AutoNextManager(b)
    await b.autonext.tick()
    assert [x["task_id"] for x in s["calls"]()] == ["one"]


async def test_unapproved_model_delegation_stops_before_followup(scenario):
    s = scenario
    b = s["bridge"]
    s["grant"]([s["source"]("one", instruction="fixture-delegate"), s["source"]("two")])
    await s["start"]()
    await until(lambda: b.autonext.inspect()["state"] == "stopped")
    assert [x["task_id"] for x in s["calls"]()] == ["one"]
    assert not b.store.db.execute("SELECT 1 FROM team_work WHERE title='unapproved'").fetchone()


async def test_operator_confirmation_is_bound_and_retrievable_over_existing_task_api(scenario):
    s = scenario
    b = s["bridge"]
    s["grant"]([s["source"]("one", acceptance="operator_receipt"), s["source"]("two")])
    await s["start"]()
    await until(
        lambda: b.store.db.execute(
            "SELECT 1 FROM team_work WHERE assignee='codex' AND state='completed'"
        ).fetchone()
    )
    assert b.autonext.receipt("local", "one") is None and len(s["calls"]()) == 1
    args = AutoNextControl(
        action="confirm",
        grant_id="grant-v1",
        task_id="one",
        result_sha256=text_sha("DONE:one"),
        evidence_ref="independent-test-receipt",
    )
    with pytest.raises(BridgeError):
        b.autonext.control("codex", args)
    async with MCPClientPool() as pool:
        await pool.connect(Peer("local", url=s["endpoint"], token="local-test-" + "a" * 40))
        submitted = await pool.call(
            "local",
            "action_request",
            {
                "request": {
                    "task_id": "confirm-one",
                    "idempotency_key": "confirm-one",
                    "operation": "autonext.control",
                    "arguments": args.model_dump(),
                }
            },
        )
        assert not submitted.isError
    await until(lambda: b.autonext.inspect()["state"] == "complete")
    assert b.autonext.receipt("local", "one")["acceptance"] == "operator_receipt"
    assert b.store.get("confirm-one", "local")["state"] == "completed"
    assert [x["task_id"] for x in s["calls"]()] == ["one", "two"]


@pytest.mark.parametrize("disposition", ["unheld", "withdrawn", "retired"])
async def test_existing_queue_retirement_releases_only_proven_delivery_reservations(
    scenario, monkeypatch, disposition
):
    from kirabridge.bridge_core.config import VisibleTerminalBinding
    from kirabridge.queue_management.models import QueueControl

    s, b = scenario, scenario["bridge"]
    s["grant"]([s["source"]("one")])
    policy = s["config"].principals["local"]
    policy.capabilities += ["message.send", "message.read", "message.ack", "task.cancel"]
    policy.message_peers = ["codex"]
    s["config"].principals["codex"].message_peers = ["local"]
    s["config"].principals["codex"].capabilities += ["message.read", "message.ack"]
    s["config"].messaging.receivers["codex"] = ReceiverConfig(cwd=str(s["root"]))
    sent = b.messages.send(
        "local",
        MessageSend(
            recipient="codex",
            conversation_id="old-delivery",
            idempotency_key="old-delivery",
            body="An old uncertain delivery, never replay",
            dispatch=True,
        ),
    )
    b.store.db.execute(
        "UPDATE message_jobs SET state='unknown',execution_cwd=NULL WHERE message_id=?",
        (sent["id"],),
    )
    binding = VisibleTerminalBinding(
        pane_id="terminal:1:ttys001", expected_pid=123, agent_pid=124, ready_pattern="ready"
    )
    s["config"].visible_handoffs.bindings["codex"] = binding
    b.store.db.execute(
        "INSERT INTO visible_handoffs VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            "retired-visible",
            "local",
            "codex",
            "hash",
            canonical(binding.model_dump()),
            sent["id"],
            "unknown",
            1,
            1,
            canonical({"reason": "visible_paste_unconfirmed"}),
        ),
    )
    if disposition != "unheld":
        if disposition == "retired":

            async def idle(*args, **kwargs):
                assert kwargs["ready"] is True
                return {"fresh_idle": True}

            monkeypatch.setattr(b.visible_handoffs, "check_target", idle)
        entry = b.queues.get("local", "handoffs", "retired-visible")
        await b.queues.control(
            "local",
            QueueControl(
                queue_id="handoffs",
                item_id=entry["id"],
                revision=entry["revision"],
                action="retire" if disposition == "retired" else "withdraw",
                reason="Explicit fixture retirement, no completed execution claimed",
                acknowledge_execution_unknown=disposition == "withdrawn",
            ),
        )
    old_handoff = tuple(b.store.db.execute("SELECT * FROM visible_handoffs").fetchone())
    old_job = tuple(b.store.db.execute("SELECT * FROM message_jobs").fetchone())
    await b.autonext.tick()
    assert s["calls"]() == []
    assert tuple(b.store.db.execute("SELECT * FROM visible_handoffs").fetchone()) == old_handoff
    assert tuple(b.store.db.execute("SELECT * FROM message_jobs").fetchone()) == old_job
    assert old_handoff[6] == "unknown"
    if disposition == "retired":
        assert b.store.db.execute("SELECT count(*) FROM autonext_items").fetchone()[0] == 1
        assert {r[0] for r in b.store.db.execute("SELECT queue_id FROM queue_holds")} == {
            "handoffs",
            "messages",
        }
    else:
        assert b.autonext.inspect()["reason"] == "autonext_scope_unknown"
        assert not b.store.db.execute("SELECT 1 FROM autonext_items").fetchone()


@pytest.mark.parametrize("route", ["running-message", "inserting-visible"])
async def test_a_delivery_hold_never_proves_active_execution_has_ended(scenario, route):
    s, b = scenario, scenario["bridge"]
    s["grant"]([s["source"]("one")])
    if route == "running-message":
        policy = s["config"].principals["local"]
        policy.capabilities += ["message.send", "message.read"]
        policy.message_peers = ["codex"]
        s["config"].principals["codex"].message_peers = ["local"]
        s["config"].principals["codex"].capabilities += ["message.read"]
        s["config"].messaging.receivers["codex"] = ReceiverConfig(cwd=str(s["root"]))
        sent = b.messages.send(
            "local",
            MessageSend(
                recipient="codex",
                conversation_id="running-old",
                idempotency_key="running-old",
                body="Execution is still active",
                dispatch=True,
            ),
        )
        b.store.db.execute(
            "UPDATE message_jobs SET state='running',execution_cwd=? WHERE message_id=?",
            (str(s["root"]), sent["id"]),
        )
        family, identifier = "messages", sent["id"]
    else:
        identifier, family = "still-inserting", "handoffs"
        b.store.db.execute(
            "INSERT INTO visible_handoffs VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                identifier,
                "local",
                "codex",
                "hash",
                "{}",
                "old",
                "inserting",
                1,
                1,
                "{}",
            ),
        )
    b.store.db.execute(
        "INSERT INTO queue_holds VALUES(?,?,?,?,?)",
        (
            family,
            identifier,
            "local",
            time.time(),
            "Old hold is not a process completion proof",
        ),
    )
    await b.autonext.tick()
    assert b.autonext.inspect()["reason"] == (
        "autonext_worktree_busy" if route == "running-message" else "autonext_scope_unknown"
    )
    assert s["calls"]() == []
    assert not b.store.db.execute("SELECT 1 FROM autonext_items").fetchone()


async def test_never_started_cancelled_message_delivery_does_not_own_worktree(scenario):
    from kirabridge.queue_management.models import QueueControl

    s, b = scenario, scenario["bridge"]
    s["grant"]([s["source"]("one")])
    for name, peer in (("local", "codex"), ("codex", "local")):
        s["config"].principals[name].capabilities += ["message.send", "message.read"]
        s["config"].principals[name].message_peers = [peer]
    s["config"].messaging.receivers["codex"] = ReceiverConfig(cwd=str(s["root"]))
    sent = b.messages.send(
        "local",
        MessageSend(
            recipient="codex",
            conversation_id="cancelled-old",
            idempotency_key="cancelled-old",
            body="Never started old delivery",
            dispatch=True,
        ),
    )
    entry = b.queues.get("local", "messages", sent["id"])
    await b.queues.control(
        "local",
        QueueControl(
            queue_id="messages",
            item_id=entry["id"],
            revision=entry["revision"],
            action="cancel",
            reason="Operator cancels this never-started delivery",
        ),
    )
    old_job = tuple(b.store.db.execute("SELECT * FROM message_jobs").fetchone())
    assert b.message_receiver._claim(sent["id"]) is None
    await s["start"]()
    await until(lambda: b.autonext.inspect()["state"] == "complete")
    assert [c["task_id"] for c in s["calls"]()] == ["one"]
    assert tuple(b.store.db.execute("SELECT * FROM message_jobs").fetchone()) == old_job
    assert b.messages.get("local", sent["id"])["acknowledged"] is None


async def test_unknown_team_work_cannot_be_released_by_delivery_hold(scenario):
    s, b = scenario, scenario["bridge"]
    s["grant"]([s["source"]("one")])
    s["config"].team.workers["grok"].cwd = str(s["root"])
    work = b.teams.delegate(
        "local",
        TeamWorkCreate(
            team_id="auto-team",
            assignee="grok",
            title="unconfirmed old execution",
            body="A delivery hold cannot stop this execution",
            idempotency_key="old-unknown-work",
        ),
    )
    b.store.db.execute("UPDATE team_work SET state='unknown' WHERE id=?", (work["id"],))
    b.store.db.execute(
        "INSERT INTO queue_holds VALUES(?,?,?,?,?)",
        (
            "team-work",
            work["id"],
            "local",
            time.time(),
            "No process termination proof",
        ),
    )
    await b.autonext.tick()
    assert b.autonext.inspect()["reason"] == "autonext_worktree_busy"
    assert not b.store.db.execute("SELECT 1 FROM autonext_items").fetchone()
    assert b.teams.work_get("local", "auto-team", work["id"])["state"] == "unknown"
    assert s["calls"]() == []
