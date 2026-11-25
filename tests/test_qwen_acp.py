"""Protocol/authority fixtures only; real provider evidence is recorded separately."""

import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import request, submit
from mcp.types import Tool, ToolAnnotations
from pydantic import ValidationError

from kirabridge.agent_manager.qwen_acp import QwenACPAdapter
from kirabridge.bridge_core.config import AgentConfig
from kirabridge.bridge_core.models import (
    AgentInput,
    AgentToolGrant,
    BridgeError,
    UncertainExecution,
    digest,
)
from kirabridge.mcp_gateway.agent_policy import AgentTaskPolicy

SERVER = """import json,sys,time,os
session='fixture-qwen'
mode=MODE
for line in sys.stdin:
 m=json.loads(line);method=m.get('method')
 if method=='initialize':
  assert m['params']['clientCapabilities']=={}
  version='0.27.2' if mode!='version' else '0.28.0'
  r={'protocolVersion':1,'agentInfo':{'name':'qwen-code','version':version}}
 elif method=='session/new':
  assert not m['params']['mcpServers']
  r={'sessionId':session}
 elif method=='session/prompt':
  assert m['params']['sessionId']==session
  if mode=='disconnect':sys.exit(0)
  if mode=='timeout':time.sleep(5)
  if mode=='permission':
   p={'sessionId':session,'toolCall':{'kind':'execute'},'options':[{'kind':'allow_once','optionId':'proceed_once'}]}
   print(json.dumps({'jsonrpc':'2.0','id':'permission','method':'session/request_permission','params':p}),flush=True)
   reply=json.loads(sys.stdin.readline());assert reply['result']['outcome']['outcome']=='cancelled'
  p={'sessionId':'foreign' if mode=='foreign' else session,
     'update':{'sessionUpdate':'agent_thought_chunk',
               'content':{'type':'text','text':'PRIVATE_THOUGHT'}}}
  print(json.dumps({'jsonrpc':'2.0','method':'session/update','params':p}),flush=True)
  p['update']={'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':'EXACT_QWEN_MARKER'}}
  print(json.dumps({'jsonrpc':'2.0','method':'session/update','params':p}),flush=True)
  if mode=='disconnect_after_text':sys.exit(0)
  if mode=='timeout_after_text':time.sleep(30)
  r={} if mode=='missing_stop' else {'stopReason':'cancelled' if mode=='cancelled' else 'end_turn'}
 else:continue
 print(json.dumps({'jsonrpc':'2.0','id':m['id'],'result':r}),flush=True)
"""


def profile(tmp_path, mode="ok", **changes):
    exe = tmp_path / "qwen-fixture"
    exe.write_text("#!" + sys.executable + "\n" + SERVER.replace("MODE", repr(mode)))
    exe.chmod(0o700)
    return AgentConfig(
        kind="qwen_acp",
        executable=str(exe),
        model="fixture-model",
        qwen_auth_type="qwen-subscription",
        **changes,
    )


async def turn(tmp_path, mode="ok", **changes):
    cfg = profile(tmp_path, mode)
    args = AgentInput(
        agent="qwen",
        prompt="public marker fixture",
        cwd=str(tmp_path),
        timeout=0.5 if mode == "timeout" else 3,
        **changes,
    )
    task = {"id": "qwen-task", "principal": "owner", "args": args.model_dump()}
    started, progress = AsyncMock(), AsyncMock()
    result = await QwenACPAdapter().execute(task, args, cfg, [str(tmp_path)], started, progress)
    return result, started, progress


@pytest.mark.parametrize("mode", ["ok", "permission", "cancelled"])
async def test_bound_turn_and_permission_denial(tmp_path, mode):
    result, started, progress = await turn(tmp_path, mode)
    assert result["success"] == (mode != "cancelled")
    assert result["text"] == "EXACT_QWEN_MARKER"
    assert not result["project_completion_verified"]
    assert "PRIVATE_THOUGHT" not in json.dumps(result)
    assert started.await_count == 1
    evidence = result["evidence"]
    assert (evidence["session_id"], evidence["task_id"], evidence["owner"], evidence["cwd"]) == (
        "fixture-qwen",
        "qwen-task",
        "owner",
        str(tmp_path),
    )
    events = [x.args[0]["event"] for x in progress.await_args_list]
    assert events[:3] == ["process_spawned", "acp_initialized", "session_created"]
    assert events[-1] == "agent_turn_observed"
    if mode == "permission":
        denial = next(
            x.args[0] for x in progress.await_args_list if x.args[0]["event"] == "permission_denied"
        )
        assert denial["permission_source"] == "adapter_policy"


@pytest.mark.parametrize("mode", ["disconnect", "foreign", "missing_stop", "timeout"])
async def test_unknown_never_reprompts(tmp_path, mode):
    with pytest.raises(BridgeError) as error:
        await turn(tmp_path, mode)
    if mode != "timeout":
        assert isinstance(error.value, UncertainExecution)
    else:
        assert (
            isinstance(error.value, UncertainExecution)
            or error.value.code == "qwen_handshake_failed"
        )


async def test_version_refuses_before_session_or_prompt(tmp_path):
    with pytest.raises(BridgeError) as error:
        await turn(tmp_path, "version")
    assert error.value.code == "agent_version"


async def test_resume_and_new_local_rights_refused_before_spawn(tmp_path):
    for changes in [{"resume_session": "existing-private-session"}, {"local_tools": True}]:
        with pytest.raises(BridgeError) as error:
            await turn(tmp_path, **changes)
        assert error.value.code in {"agent_resume_unsupported", "agent_tools_denied"}


async def test_manager_registers_and_keeps_owner_and_roots(bridge, config, tmp_path):
    config.agents["qwen"] = profile(tmp_path)
    config.principals["local"].agents.append("qwen")
    value = request(
        "agent.execute",
        {
            "agent": "qwen",
            "prompt": "marker fixture",
            "cwd": config.principals["local"].roots[0],
            "timeout": 3,
        },
    )
    submit(bridge, value)
    async with bridge:
        final = await bridge.tasks.wait("local", value.task_id)
    assert final["state"] == "completed"
    assert final["result"]["evidence"]["owner"] == "local"
    assert bridge.agents.inventory(["qwen"])["agents"][0]["supports_owned_resume"] is True
    assert not final["result"]["project_completion_verified"]


def binding(**changes):
    task = {
        "id": "task",
        "principal": "owner",
        "operation": "agent.execute",
        "state": "running",
        "args": {"agent": "qwen", "cwd": "/private-fixture", "prompt": "not exported"},
    }
    policy = AgentTaskPolicy(
        owner="owner",
        task_id="task",
        agent="qwen",
        cwd="/private-fixture",
        arguments_sha256=digest(task["args"]),
        expires_at=9999999999,
        tools=["bridge_epoch"],
        capabilities=["bridge.health"],
        grants=[AgentToolGrant(tool="bridge_epoch")],
    )
    return policy, {**task, **changes}


@pytest.mark.parametrize(
    "changes",
    [
        {"principal": "other"},
        {"id": "other"},
        {"state": "unknown"},
        {"state": "completed"},
        {"args": {"cwd": "/foreign", "agent": "qwen"}},
    ],
)
def test_mcp_binding_refuses_foreign_or_inactive_tasks(changes):
    policy, task = binding(**changes)
    with pytest.raises(BridgeError):
        policy.validate_task(task)


async def test_mcp_exact_grant_and_single_dispatch():
    policy, task = binding()
    connection = SimpleNamespace(
        call_tool=AsyncMock(return_value=SimpleNamespace(isError=False, structuredContent=task))
    )
    for name, args in [("task_request", {}), ("bridge_epoch", {"extra": True})]:
        with pytest.raises(BridgeError):
            await policy.authorize(connection, name, args)
    connection.call_tool.assert_not_awaited()
    await policy.authorize(
        connection,
        "bridge_epoch",
        {},
        definition=Tool(
            name="bridge_epoch",
            inputSchema={"type": "object"},
            annotations=ToolAnnotations(readOnlyHint=True),
        ),
    )
    with pytest.raises(BridgeError):
        await policy.authorize(
            connection,
            "bridge_epoch",
            {},
            definition=Tool(
                name="bridge_epoch",
                inputSchema={"type": "object"},
                annotations=ToolAnnotations(readOnlyHint=True),
            ),
        )
    assert connection.call_tool.await_count == 1


def test_config_never_inherits_xai_key_or_accepts_api_provider():
    assert AgentConfig(kind="qwen_acp").api_key_env == ""
    assert AgentConfig(kind="qwen_acp", qwen_auth_type="openai").qwen_auth_type == "openai"
    with pytest.raises(ValidationError):
        AgentConfig(kind="codex", qwen_auth_type="qwen-oauth")


async def test_effort_requires_native_set_and_independent_readback():
    offered = {
        "configOptions": [
            {
                "id": "reasoning_effort",
                "category": "thought_level",
                "options": [{"value": v} for v in ["none", "low", "medium", "xhigh"]],
            }
        ]
    }
    selected = {"configOptions": [{"id": "reasoning_effort", "currentValue": "xhigh"}]}
    client = SimpleNamespace(request=AsyncMock(side_effect=[selected, {"state": selected}]))
    adapter = QwenACPAdapter()
    assert await adapter._set_effort(client, "session", offered, "xhigh", 3) == "xhigh"
    assert [c.args[0] for c in client.request.await_args_list] == [
        "session/set_config_option",
        "qwen/status/session/context",
    ]
    client.request.reset_mock()
    with pytest.raises(BridgeError):
        await adapter._set_effort(client, "session", offered, "max", 3)
    client.request.assert_not_awaited()


async def test_mcp_readiness_uses_bound_session_catalog(tmp_path):
    client = SimpleNamespace(
        request=AsyncMock(
            side_effect=[
                {
                    "sessionId": "session",
                    "workspaceCwd": str(tmp_path),
                    "mcp": {
                        "discoveryState": "completed",
                        "servers": [{"name": "kirabridge", "mcpStatus": "connected"}],
                    },
                },
                {"usage": {"mcpTools": [{"name": "kirabridge__bridge_epoch", "tokens": 12}]}},
            ]
        )
    )
    progress = AsyncMock()
    await QwenACPAdapter()._mcp_ready(client, "session", str(tmp_path), 3, progress, {})
    assert progress.await_args.args[0]["mcp_tools"] == ["kirabridge__bridge_epoch"]
    assert [c.args[0] for c in client.request.await_args_list] == [
        "qwen/status/session/resources",
        "qwen/status/session/context_usage",
    ]


@pytest.mark.parametrize("mode", ["ok", "disconnect"])
async def test_cleanup_failure_preserves_original_observation(tmp_path, monkeypatch, mode):
    import os

    from kirabridge.agent_manager import qwen_acp

    reap = qwen_acp.reap_process
    pids = []

    async def uncertain_cleanup(process, **kwargs):
        pids.append(process.pid)
        await reap(process, **kwargs)
        raise UncertainExecution("process_cleanup_unknown", "fixture cleanup uncertainty")

    monkeypatch.setattr(qwen_acp, "reap_process", uncertain_cleanup)
    args = AgentInput(agent="qwen", prompt="fixture", cwd=str(tmp_path), timeout=3)
    progress = AsyncMock()
    with pytest.raises(UncertainExecution) as error:
        await QwenACPAdapter().execute(
            {"id": "task", "principal": "owner", "args": args.model_dump()},
            args,
            profile(tmp_path, mode),
            [str(tmp_path)],
            AsyncMock(),
            progress,
        )
    observation = progress.await_args.args[0]
    assert observation["event"] == "cleanup_unconfirmed"
    if mode == "ok":
        assert error.value.code == "process_cleanup_unknown"
        assert observation["observed_result"]["evidence"]["stop_reason"] == "end_turn"
        assert observation["observed_result"]["text"] == "EXACT_QWEN_MARKER"
        assert not observation["observed_result"]["project_completion_verified"]
    else:
        assert error.value.code == "agent_disconnected"
        assert observation["original_error_code"] == "agent_disconnected"
    with pytest.raises(ProcessLookupError):
        os.kill(pids[0], 0)


async def test_read_only_adaptive_grants_cannot_write_or_escape(tmp_path):
    parent, task = binding()
    policy = parent.model_copy(
        update={
            "tools": ["task_request"],
            "operations": ["file.read", "file.write"],
            "capabilities": ["file.read", "file.write"],
            "read_only": True,
            "cwd": str(tmp_path),
            "max_calls": 5,
        }
    )
    task["args"]["cwd"] = str(tmp_path)
    policy = policy.model_copy(update={"arguments_sha256": digest(task["args"])})
    connection = SimpleNamespace(
        call_tool=AsyncMock(return_value=SimpleNamespace(isError=False, structuredContent=task))
    )
    definition = Tool(
        name="task_request",
        inputSchema={"type": "object"},
        annotations=ToolAnnotations(readOnlyHint=False),
    )
    for operation, path in [
        ("file.write", str(tmp_path / "a")),
        ("file.read", str(tmp_path.parent / "foreign")),
    ]:
        with pytest.raises(BridgeError):
            await policy.authorize(
                connection,
                "task_request",
                {
                    "request": {
                        "task_id": "child",
                        "idempotency_key": "child",
                        "operation": operation,
                        "arguments": {"path": path},
                        "parent_id": "task",
                    }
                },
                definition=definition,
            )
    await policy.authorize(
        connection,
        "task_request",
        {
            "request": {
                "task_id": "child",
                "idempotency_key": "child",
                "operation": "file.read",
                "arguments": {"path": str(tmp_path / "a")},
                "parent_id": "task",
            }
        },
        definition=definition,
    )
    with pytest.raises(BridgeError):
        await policy.authorize(
            connection,
            "task_request",
            {
                "request": {
                    "task_id": "child",
                    "idempotency_key": "child",
                    "operation": "file.read",
                    "arguments": {"path": str(tmp_path / "a")},
                    "parent_id": "task",
                }
            },
            definition=definition,
        )


async def test_read_pages_require_observed_matching_native_result():
    from mcp.types import CallToolResult

    parent, task = binding()
    base = {
        "version": 1,
        "workspace_id": "ws-fixture",
        "catalog_revision": "cat",
        "command": "get_thread",
        "arguments": {"id": "plan", "max_chars": 100000, "offset": 0},
    }
    grant = AgentToolGrant(tool="td_command_query", arguments=base)
    policy = parent.model_copy(
        update={
            "tools": ["td_command_query"],
            "capabilities": ["threaddesk.read"],
            "grants": [grant],
            "max_calls": 8,
        }
    )
    connection = SimpleNamespace(
        call_tool=AsyncMock(return_value=SimpleNamespace(isError=False, structuredContent=task))
    )
    definition = Tool(
        name="td_command_query",
        inputSchema={"type": "object"},
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
    )
    next_args = {**base, "result_digest": "a" * 64, "result_offset": 4}
    with pytest.raises(BridgeError):
        await policy.authorize(connection, "td_command_query", next_args, definition=definition)
    await policy.authorize(connection, "td_command_query", base, definition=definition)
    result = CallToolResult(
        content=[],
        structuredContent={
            "success": True,
            "value": {
                "schema": "threaddesk.command-result.v1",
                "encoding": "json-text-codepoint-pages",
                "workspace_id": "ws-fixture",
                "catalog_revision": "cat",
                "command": "get_thread",
                "result_digest": "a" * 64,
                "offset": 0,
                "total": 8,
                "next_offset": 4,
                "result_page": "abcd",
            },
        },
    )
    policy.observe_result("td_command_query", base, result)
    for changed in [
        {"result_digest": "b" * 64},
        {"result_offset": 5},
        {"workspace_id": "foreign"},
        {"arguments": {**base["arguments"], "offset": 100000}},
    ]:
        with pytest.raises(BridgeError):
            await policy.authorize(
                connection, "td_command_query", {**next_args, **changed}, definition=definition
            )
    await policy.authorize(connection, "td_command_query", next_args, definition=definition)
    assert policy._calls == 2
    with pytest.raises(BridgeError):
        await policy.authorize(connection, "td_command_query", next_args, definition=definition)
    assert policy._used[digest({"tool": "td_command_query", "arguments": base})] == 1
    task["state"] = "completed"
    with pytest.raises(BridgeError):
        await policy.authorize(connection, "td_command_query", next_args, definition=definition)


def test_scalar_const_annotation_preserves_native_validation():
    from jsonschema import Draft202012Validator

    from kirabridge.mcp_gateway.schema_validation import explicit_scalar_const_types

    original = {
        "type": "object",
        "properties": {
            "version": {"const": 1},
            "payload": {"const": {"properties": {"x": {"const": True}}}},
        },
    }
    annotated = explicit_scalar_const_types(original)
    assert "type" not in original["properties"]["version"]
    assert annotated["properties"]["version"] == {"const": 1, "type": "integer"}
    assert annotated["properties"]["payload"] == original["properties"]["payload"]
    for version in [1, 1.0, "1", True, None]:
        data = {"version": version, "payload": original["properties"]["payload"]["const"]}
        assert Draft202012Validator(annotated).is_valid(data) == Draft202012Validator(
            original
        ).is_valid(data)


async def test_direct_read_query_keeps_native_scope(tmp_path):
    parent, task = binding()
    task["args"]["cwd"] = str(tmp_path)
    policy = parent.model_copy(
        update={
            "tools": ["read_query"],
            "operations": ["file.read"],
            "capabilities": ["file.read"],
            "cwd": str(tmp_path),
            "arguments_sha256": digest(task["args"]),
        }
    )
    connection = SimpleNamespace(
        call_tool=AsyncMock(return_value=SimpleNamespace(isError=False, structuredContent=task))
    )
    definition = Tool(
        name="read_query",
        inputSchema={"type": "object"},
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
    )
    await policy.authorize(
        connection,
        "read_query",
        {"query": {"operation": "file.read", "path": str(tmp_path / "source")}},
        definition=definition,
    )
    for query in [
        {"operation": "file.read", "path": str(tmp_path.parent / "foreign")},
        {"operation": "file.write", "path": str(tmp_path / "source"), "text": "not granted"},
    ]:
        with pytest.raises(BridgeError):
            await policy.authorize(
                connection, "read_query", {"query": query}, definition=definition
            )


async def test_legacy_thread_read_is_exact_and_requires_existing_right():
    parent, task = binding()
    args = {"id": "plan", "max_chars": 100000, "offset": 100000}
    policy = parent.model_copy(
        update={
            "tools": ["td_get_thread"],
            "capabilities": ["threaddesk.read"],
            "grants": [AgentToolGrant(tool="td_get_thread", arguments=args)],
            "max_calls": 8,
        }
    )
    connection = SimpleNamespace(
        call_tool=AsyncMock(return_value=SimpleNamespace(isError=False, structuredContent=task))
    )
    tool = Tool(
        name="td_get_thread",
        inputSchema={"type": "object"},
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
    )
    assert policy.permits_tool(tool)
    for changed in [{"id": "foreign"}, {"offset": 200000}, {"max_chars": 200000}]:
        with pytest.raises(BridgeError):
            await policy.authorize(
                connection, "td_get_thread", {**args, **changed}, definition=tool
            )
    await policy.authorize(connection, "td_get_thread", args, definition=tool)
    with pytest.raises(BridgeError):
        await policy.authorize(connection, "td_get_thread", args, definition=tool)
    assert not policy.model_copy(update={"capabilities": []}).permits_tool(tool)


@pytest.mark.parametrize("mode", ["missing_stop", "disconnect_after_text", "timeout_after_text"])
async def test_unknown_preserves_non_thought_text_without_completion(tmp_path, mode):
    args = AgentInput(agent="qwen", prompt="fixture", cwd=str(tmp_path), timeout=1)
    progress = AsyncMock()
    with pytest.raises(UncertainExecution):
        await QwenACPAdapter().execute(
            {"id": "task", "principal": "owner", "args": args.model_dump()},
            args,
            profile(tmp_path, mode),
            [str(tmp_path)],
            AsyncMock(),
            progress,
        )
    partial = next(
        c.args[0]["unconfirmed_observation"]
        for c in progress.await_args_list
        if c.args[0]["event"] == "agent_partial_observation"
    )
    assert partial["text"] == "EXACT_QWEN_MARKER"
    assert partial["completion_verified"] is False and partial["stop_reason"] is None
    assert "PRIVATE_THOUGHT" not in json.dumps(partial)
    assert all(c.args[0]["event"] != "agent_turn_observed" for c in progress.await_args_list)


async def test_native_board_index_grants_only_observed_entries_once():
    from mcp.types import CallToolResult

    parent, task = binding()
    policy = parent.model_copy(
        update={
            "tools": ["whiteboard_read"],
            "capabilities": ["threaddesk.read"],
            "grants": [AgentToolGrant(tool="whiteboard_read", arguments={"thread_id": "known"})],
            "max_calls": 8,
        }
    )
    conn = SimpleNamespace(
        call_tool=AsyncMock(return_value=SimpleNamespace(isError=False, structuredContent=task))
    )
    tool = Tool(
        name="whiteboard_read",
        inputSchema={"type": "object"},
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    entry = {"thread_id": "known", "entry_id": "entry-1"}
    with pytest.raises(BridgeError):
        await policy.authorize(conn, "whiteboard_read", entry, definition=tool)
    await policy.authorize(conn, "whiteboard_read", {"thread_id": "known"}, definition=tool)
    policy.observe_result(
        "whiteboard_read",
        {"thread_id": "known"},
        CallToolResult(
            content=[], structuredContent={"thread_id": "known", "entries": [{"id": "entry-1"}]}
        ),
    )
    for changed in [{"thread_id": "foreign"}, {"entry_id": "unseen"}]:
        with pytest.raises(BridgeError):
            await policy.authorize(conn, "whiteboard_read", {**entry, **changed}, definition=tool)
    await policy.authorize(conn, "whiteboard_read", entry, definition=tool)
    with pytest.raises(BridgeError):
        await policy.authorize(conn, "whiteboard_read", entry, definition=tool)


async def test_direct_note_pages_follow_only_observed_next_offset():
    from mcp.types import CallToolResult

    parent, task = binding()
    args = {"id": "known", "max_chars": 12000, "offset": 100000}
    policy = parent.model_copy(
        update={
            "tools": ["td_get_thread"],
            "capabilities": ["threaddesk.read"],
            "grants": [AgentToolGrant(tool="td_get_thread", arguments=args)],
            "max_calls": 8,
        }
    )
    conn = SimpleNamespace(
        call_tool=AsyncMock(return_value=SimpleNamespace(isError=False, structuredContent=task))
    )
    tool = Tool(
        name="td_get_thread",
        inputSchema={"type": "object"},
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    next_args = {**args, "offset": 112000}
    with pytest.raises(BridgeError):
        await policy.authorize(conn, "td_get_thread", next_args, definition=tool)
    await policy.authorize(conn, "td_get_thread", args, definition=tool)
    policy.observe_result(
        "td_get_thread",
        args,
        CallToolResult(
            content=[],
            structuredContent={
                "success": True,
                "value": {
                    "id": "known",
                    "offset": 100000,
                    "next_offset": 112000,
                    "total_chars": 413560,
                    "truncated": True,
                },
            },
        ),
    )
    for changed in [{"offset": 124000}, {"id": "foreign"}, {"max_chars": 24000}]:
        with pytest.raises(BridgeError):
            await policy.authorize(conn, "td_get_thread", {**next_args, **changed}, definition=tool)
    await policy.authorize(conn, "td_get_thread", next_args, definition=tool)
    with pytest.raises(BridgeError):
        await policy.authorize(conn, "td_get_thread", next_args, definition=tool)


@pytest.mark.parametrize(
    "change", [None, {"generation": 1}, {"work_id": "other"}, {"session_id": "foreign"}]
)
async def test_proxy_rechecks_current_team_lease_before_each_call(change):
    parent, task = binding()
    scope = {"team_id": "team", "work_id": "work", "session_id": "session", "generation": 0}
    policy = AgentTaskPolicy.model_validate({**parent.model_dump(), "team_scope": scope})
    slot = {
        **scope,
        "principal": parent.owner,
        "agent": parent.agent,
        "cwd": parent.cwd,
        "state": "active",
    }
    if change is None:
        slot = None
    else:
        slot.update(change)

    async def call(name, args):
        return SimpleNamespace(
            isError=False, structuredContent=task if name == "task_get" else {"session": slot}
        )

    tool = Tool(
        name="bridge_epoch",
        inputSchema={"type": "object"},
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    with pytest.raises(BridgeError):
        await policy.authorize(SimpleNamespace(call_tool=call), "bridge_epoch", {}, definition=tool)
    assert policy._calls == 0
