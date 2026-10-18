import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import AgentConfig, ThreadDeskConfig
from kirabridge.bridge_core.models import TaskRequest

pytestmark = pytest.mark.skipif(
    not os.environ.get("KIRABRIDGE_TEST_THREADDESK_SOURCE"),
    reason="Reviewed actual ThreadDesk M2 source required",
)

SESSION = "f0100000-0000-4000-8000-000000000001"


def configure(config, tmp_path, *, question=True, incomplete=False):
    workspace = tmp_path / "operator-profile"
    workspace.mkdir(mode=0o700)
    config.threaddesk = ThreadDeskConfig(
        enabled=True,
        command=sys.executable,
        args=["-m", "threaddesk.ui.mcp_stdio"],
        workspace=str(workspace),
        source_root=os.environ["KIRABRIDGE_TEST_THREADDESK_SOURCE"],
    )
    cli = tmp_path / "owned-codex"
    counter = tmp_path / "calls.jsonl"
    cli.write_text(
        f"#!{sys.executable}\n"
        "import json,sys,pathlib\n"
        "prompt=sys.stdin.read()\n"
        f"with open({str(counter)!r},'a') as out: out.write(json.dumps(sys.argv[1:])+'\\n')\n"
        f"print(json.dumps({{'type':'thread.started','thread_id':{SESSION!r}}}),flush=True)\n"
        "print(json.dumps({'type':'turn.started'}),flush=True)\n"
        f"if {question!r} and 'resume' not in sys.argv:\n"
        "    reply={'kind':'question','text':'Welche Farbe?','files':[],"
        "'test_results':[],'open_issues':[]}\n"
        "else:\n"
        "    if 'resume' in sys.argv:\n"
        f"        assert {SESSION!r} in sys.argv and 'blue' in prompt\n"
        "    pathlib.Path('synthetic-result.txt').write_text('blue')\n"
        "    reply={'kind':'result','text':'Synthetisches Ergebnis',"
        "'files':['synthetic-result.txt'],'test_results':['fixture check'], 'open_issues':[]}\n"
        "print(json.dumps({'type':'item.completed','item':{'type':'agent_message',"
        "'text':json.dumps(reply)}}),flush=True)\n"
        + ("" if incomplete else "print(json.dumps({'type':'turn.completed'}),flush=True)\n")
    )
    cli.chmod(0o700)
    config.agents["codex"] = AgentConfig(
        kind="codex", executable=str(cli), sandbox_mode="workspace-write"
    )
    for policy in config.principals.values():
        policy.approval_mode = "automatic"
    return counter


async def call(bridge, identity, operation, arguments, *, principal="local", expected="completed"):
    bridge.prepare(
        principal,
        TaskRequest(
            task_id=identity, idempotency_key=identity, operation=operation, arguments=arguments
        ),
    )
    result = await bridge.tasks.wait(principal, identity)
    assert result["state"] == expected, result
    assert result["attempt"] == 1
    return result


async def issued(bridge, suffix=""):
    created = await call(
        bridge,
        "create" + suffix,
        "threaddesk.manage",
        {
            "operation_id": "create" + suffix,
            "action": "create",
            "expected_revision": 0,
            "data": {"title": "Synthetic bounded workflow"},
        },
    )
    thread = created["result"]["value"]
    result = await call(
        bridge,
        "issue" + suffix,
        "handoff.issue",
        {
            "operation_id": "issue" + suffix,
            "thread_id": thread["thread_id"],
            "expected_revision": thread["revision"],
        },
    )
    record = result["result"]["value"]
    return thread, record["handoff"], record


async def test_actual_peer_question_answer_resume_inbox_decision_and_restart(config, tmp_path):
    counter = configure(config, tmp_path)
    first = Bridge(config)
    async with first:
        thread, packet, _ = await issued(first)
        assert packet["task_id"] == thread["thread_id"] + ":task"
        start = {
            "handoff_id": packet["handoff_id"],
            "revision": packet["revision"],
            "cwd": config.principals["local"].roots[0],
        }
        started = await call(first, "start", "handoff.start", start)
        waiting = started["result"]["value"]
        assert waiting["phase"] == "awaiting_answer"
        assert waiting["original_task_id"] == packet["task_id"]
        assert waiting["run_id"] == started["receipt"] and waiting["session_id"] == SESSION
        assert not waiting["project_completion_verified"]
        assert not (Path(start["cwd"]) / "synthetic-result.txt").exists()
    resumed = Bridge(config)
    async with resumed:
        replay = await call(resumed, "start-replay", "handoff.start", start)
        assert replay["result"]["value"]["duplicate"]
        assert replay["result"]["value"]["run_id"] == waiting["run_id"]
        foreign = await call(
            resumed,
            "foreign-read",
            "handoff.status",
            {"handoff_id": packet["handoff_id"], "revision": 1},
            principal="other",
            expected="failed",
        )
        assert foreign["result"]["value"]["error"]["code"] == "handoff_not_found"
        answer = {
            "handoff_id": packet["handoff_id"],
            "revision": 1,
            "question_id": waiting["question_id"],
            "answer_id": "human-answer",
            "text": "blue",
        }
        finished = await call(resumed, "answer", "handoff.answer", answer)
        value = finished["result"]["value"]
        assert value["phase"] == "delivered_unverified" and not value["decision"]
        assert value["run_id"] == waiting["run_id"] and value["session_id"] == SESSION
        assert (Path(start["cwd"]) / "synthetic-result.txt").read_text() == "blue"
        repeat = await call(resumed, "answer-replay", "handoff.answer", answer)
        assert repeat["result"]["value"]["duplicate"]
        await call(
            resumed,
            "answer-conflict",
            "handoff.answer",
            {**answer, "text": "red"},
            expected="failed",
        )
        inbox = await call(resumed, "inbox", "handoff.inbox", {})
        items = inbox["result"]["value"]["items"]
        assert len(items) == 1 and items[0]["return"]["task_id"] == packet["task_id"]
        assert items[0]["return"]["review_status"] == "unverified"
        decision = await call(
            resumed,
            "decision",
            "handoff.decide",
            {
                "handoff_id": packet["handoff_id"],
                "revision": 1,
                "return_id": value["return_id"],
                "choice": "accepted",
                "note": "Synthetic operator checked exact fixture artifact",
            },
        )
        assert decision["result"]["value"]["phase"] == "accepted"
        assert not decision["result"]["value"]["project_completion_verified"]
        audit = [row[0] for row in resumed.store.db.execute("SELECT metadata FROM audit")]
        assert not any("Welche Farbe" in item or '"blue"' in item for item in audit)
    invocations = [json.loads(line) for line in counter.read_text().splitlines()]
    assert len(invocations) == 2
    assert "resume" not in invocations[0] and "resume" in invocations[1]
    assert "--last" not in invocations[1] and SESSION in invocations[1]
    assert "--ignore-rules" not in invocations[1] and "--output-schema" in invocations[1]


async def test_unknown_original_turn_is_never_restarted_with_new_task_key(config, tmp_path):
    counter = configure(config, tmp_path, question=False, incomplete=True)
    original = Bridge(config)
    async with original:
        _, packet, _ = await issued(original)
        arguments = {
            "handoff_id": packet["handoff_id"],
            "revision": 1,
            "cwd": config.principals["local"].roots[0],
        }
        await call(original, "start", "handoff.start", arguments, expected="unknown")
    reopened = Bridge(config)
    async with reopened:
        replay = await call(reopened, "new-task-key", "handoff.start", arguments)
        assert replay["result"]["value"]["phase"] == "unknown"
        assert replay["result"]["value"]["first_task_id"] == "start"
    assert len(counter.read_text().splitlines()) == 1


async def test_actual_stale_source_cannot_bind_or_start_agent(config, tmp_path):
    counter = configure(config, tmp_path)
    bridge = Bridge(config)
    async with bridge:
        thread, packet, _ = await issued(bridge)
        await call(
            bridge,
            "change-source",
            "threaddesk.manage",
            {
                "operation_id": "changed",
                "action": "set_note",
                "id": thread["thread_id"],
                "expected_revision": thread["revision"],
                "data": {"text": "Changed after issue"},
            },
        )
        failed = await call(
            bridge,
            "start",
            "handoff.start",
            {
                "handoff_id": packet["handoff_id"],
                "revision": 1,
                "cwd": config.principals["local"].roots[0],
            },
            expected="failed",
        )
        assert failed["result"]["value"]["error"]["code"] == "revision_conflict"
    assert not counter.exists()


async def test_first_return_after_source_change_is_rejected_without_inbox_write(config, tmp_path):
    counter = configure(config, tmp_path, question=False)
    bridge = Bridge(config)
    async with bridge:
        thread, packet, _ = await issued(bridge)
        original = bridge.agents.execute

        async def change_after_actual_turn(*args, **kwargs):
            result = await original(*args, **kwargs)
            await call(
                bridge,
                "changed-during-turn",
                "threaddesk.manage",
                {
                    "operation_id": "changed-during-turn",
                    "action": "set_note",
                    "id": thread["thread_id"],
                    "expected_revision": thread["revision"],
                    "data": {"text": "Actual source changed before first delivery"},
                },
            )
            return result

        bridge.agents.execute = change_after_actual_turn
        arguments = {
            "handoff_id": packet["handoff_id"],
            "revision": 1,
            "cwd": config.principals["local"].roots[0],
        }
        rejected = await call(bridge, "start", "handoff.start", arguments, expected="failed")
        assert rejected["result"]["value"]["error"]["code"] == "return_stale"
        inbox = await call(bridge, "inbox", "handoff.inbox", {})
        assert inbox["result"]["value"]["items"] == []
        replay = await call(bridge, "new-key", "handoff.start", arguments)
        assert replay["result"]["value"]["duplicate"]
        assert replay["result"]["value"]["phase"] == "failed"
    assert len(counter.read_text().splitlines()) == 1


@pytest.mark.parametrize(
    "corrupt_tool", ["bind_handoff_run", "record_handoff_question", "import_return"]
)
async def test_foreign_mutation_receipts_remain_unknown_and_do_not_restart(
    config, tmp_path, corrupt_tool
):
    counter = configure(config, tmp_path, question=corrupt_tool != "import_return")
    bridge = Bridge(config)
    async with bridge:
        _, packet, _ = await issued(bridge)
        original = bridge.handoffs.rpc

        async def foreign_receipt(task, tool, arguments):
            result = await original(task, tool, arguments)
            if tool == corrupt_tool:
                result = json.loads(json.dumps(result))
                if tool == "bind_handoff_run":
                    result["binding"]["run_id"] = "foreign-run"
                elif tool == "record_handoff_question":
                    result["question"]["question_id"] = "foreign-question"
                else:
                    result["return"]["run_id"] = "foreign-run"
            return result

        bridge.handoffs.rpc = foreign_receipt
        arguments = {
            "handoff_id": packet["handoff_id"],
            "revision": 1,
            "cwd": config.principals["local"].roots[0],
        }
        await call(bridge, "start", "handoff.start", arguments, expected="unknown")
        replay = await call(bridge, "new-key", "handoff.start", arguments)
        assert replay["result"]["value"]["phase"] == "unknown"
    assert (len(counter.read_text().splitlines()) if counter.exists() else 0) == (
        0 if corrupt_tool == "bind_handoff_run" else 1
    )


@pytest.mark.parametrize("lost_tool", ["import_return", "review_return"])
async def test_lost_write_receipt_is_read_back_without_repeating_dispatch_or_write(
    config, tmp_path, lost_tool
):
    from kirabridge.bridge_core.models import UncertainExecution

    counter = configure(config, tmp_path, question=False)
    bridge = Bridge(config)
    async with bridge:
        _, packet, _ = await issued(bridge)
        original = bridge.handoffs.rpc
        writes = []

        async def lose_after_actual_write(task, tool, arguments):
            result = await original(task, tool, arguments)
            if tool == lost_tool:
                writes.append(tool)
                raise UncertainExecution("simulated_lost_receipt", "Synthetic lost reply")
            return result

        bridge.handoffs.rpc = lose_after_actual_write
        reference = {"handoff_id": packet["handoff_id"], "revision": 1}
        start = {**reference, "cwd": config.principals["local"].roots[0]}
        result = await call(
            bridge,
            "start",
            "handoff.start",
            start,
            expected="unknown" if lost_tool == "import_return" else "completed",
        )
        if lost_tool == "review_return":
            await call(
                bridge,
                "decision",
                "handoff.decide",
                {
                    **reference,
                    "return_id": result["result"]["value"]["return_id"],
                    "choice": "accepted",
                    "note": "Synthetic deliberate decision",
                },
                expected="unknown",
            )
        status = await call(bridge, "status-before", "handoff.status", reference)
        assert status["result"]["value"]["phase"] == "unknown"
        assert status["result"]["value"]["last_task_id"] == (
            "start" if lost_tool == "import_return" else "decision"
        )
        reconciled = await call(bridge, "receipt-read", "handoff.reconcile", reference)
        value = reconciled["result"]["value"]
        assert value["phase"] == (
            "delivered_unverified" if lost_tool == "import_return" else "accepted"
        )
        assert value["last_task_state"] == "unknown" and value["receipt_confirmed_for_task"]
        await call(bridge, "duplicate-start", "handoff.start", start)
        assert len(writes) == 1
    assert len(counter.read_text().splitlines()) == 1


async def test_actual_preflight_denies_missing_agent_right_before_peer_binding(config, tmp_path):
    counter = configure(config, tmp_path)
    bridge = Bridge(config)
    async with bridge:
        _, packet, _ = await issued(bridge)
        config.principals["local"].capabilities.remove("agent.execute")
        result = await call(
            bridge,
            "start",
            "handoff.start",
            {
                "handoff_id": packet["handoff_id"],
                "revision": 1,
                "cwd": config.principals["local"].roots[0],
            },
            expected="failed",
        )
        assert result["started"] is None and result["error"]["code"] == "forbidden"
        assert bridge.store.db.execute("SELECT COUNT(*) FROM handoff_bindings").fetchone()[0] == 0
    assert not counter.exists()


async def test_concurrent_starts_claim_one_run_and_changed_cwd_conflicts(config, tmp_path):
    counter = configure(config, tmp_path)
    bridge = Bridge(config)
    async with bridge:
        _, packet, _ = await issued(bridge)
        arguments = {
            "handoff_id": packet["handoff_id"],
            "revision": 1,
            "cwd": config.principals["local"].roots[0],
        }
        for identity in ["start-a", "start-b"]:
            bridge.prepare(
                "local",
                TaskRequest(
                    task_id=identity,
                    idempotency_key=identity,
                    operation="handoff.start",
                    arguments=arguments,
                ),
            )
        results = await asyncio.gather(
            *(bridge.tasks.wait("local", identity) for identity in ["start-a", "start-b"])
        )
        assert all(item["state"] == "completed" for item in results), results
        values = [item["result"]["value"] for item in results]
        assert len({item["run_id"] for item in values}) == 1
        assert sum(bool(item.get("duplicate")) for item in values) == 1
        different = Path(arguments["cwd"]) / "another-cwd"
        different.mkdir()
        conflict = await call(
            bridge,
            "changed-cwd",
            "handoff.start",
            {**arguments, "cwd": str(different)},
            expected="failed",
        )
        assert conflict["result"]["value"]["error"]["code"] == "handoff_conflict"
        config.agents["codex"].sandbox_mode = "read-only"
        conflict = await call(
            bridge, "changed-profile", "handoff.start", arguments, expected="failed"
        )
        assert conflict["result"]["value"]["error"]["code"] == "handoff_conflict"
    assert len(counter.read_text().splitlines()) == 1


async def test_question_answer_receipt_loss_never_resumes_the_session(config, tmp_path):
    from kirabridge.bridge_core.models import UncertainExecution

    counter = configure(config, tmp_path)
    bridge = Bridge(config)
    async with bridge:
        _, packet, _ = await issued(bridge)
        reference = {"handoff_id": packet["handoff_id"], "revision": 1}
        start = await call(
            bridge,
            "start",
            "handoff.start",
            {**reference, "cwd": config.principals["local"].roots[0]},
        )
        question = start["result"]["value"]
        original = bridge.handoffs.rpc
        writes = []

        async def lose_recorded_answer(task, tool, arguments):
            result = await original(task, tool, arguments)
            if tool == "answer_handoff_question":
                writes.append(tool)
                raise UncertainExecution("simulated_lost_reply", "Synthetic interruption")
            return result

        bridge.handoffs.rpc = lose_recorded_answer
        answer = {
            **reference,
            "question_id": question["question_id"],
            "answer_id": "answer",
            "text": "blue",
        }
        await call(bridge, "answer", "handoff.answer", answer, expected="unknown")
        failed = await call(bridge, "new-answer-key", "handoff.answer", answer, expected="failed")
        assert failed["result"]["value"]["error"]["code"] == "handoff_unknown"
        assert len(writes) == 1
    assert len(counter.read_text().splitlines()) == 1
