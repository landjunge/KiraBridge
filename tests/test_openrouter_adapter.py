from __future__ import annotations

import json
import subprocess
import time
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from kirabridge.agent_manager import openrouter_credentials
from kirabridge.agent_manager.openrouter import OpenRouterAdapter
from kirabridge.bridge_core.config import AgentConfig
from kirabridge.bridge_core.models import AgentInput, BridgeError, TaskRequest, UncertainExecution
from kirabridge.mcp_gateway.agent_policy import AgentTaskPolicy
from kirabridge.openrouter_models import OPENROUTER_DEFAULT_MODEL


def _config(**kwargs):
    values = {
        "kind": "openrouter_api",
        "model": OPENROUTER_DEFAULT_MODEL,
        "api_key_env": "OPENROUTER_API_KEY",
        "openrouter_credential_source": "environment",
    }
    values.update(kwargs)
    return AgentConfig(
        **values,
    )


def _args(**kwargs):
    return AgentInput(
        agent="openrouter",
        prompt="Return the word synthetic.",
        cwd="/tmp",
        timeout=15,
        **kwargs,
    )


async def _callback(_):
    return None


def _mock_client(monkeypatch, handler):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def client(*args, **kwargs):
        return original(*args, transport=transport, **kwargs)

    monkeypatch.setattr("kirabridge.agent_manager.openrouter.httpx.AsyncClient", client)


async def test_free_text_request_uses_only_pinned_free_models_and_no_tools(monkeypatch):
    secret = "synthetic-request-key"
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    observed = {}

    def handler(request):
        observed["headers"] = request.headers
        observed["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "req-synthetic",
                "model": OPENROUTER_DEFAULT_MODEL,
                "choices": [
                    {
                        "message": {"content": "synthetic", "role": "assistant"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 2, "cost": 0},
            },
        )

    _mock_client(monkeypatch, handler)
    events = []

    result = await OpenRouterAdapter().execute(
        {},
        _args(),
        _config(),
        [],
        lambda value: _record(events, value),
        _callback,
    )

    assert result["success"] is True
    assert result["text"] == "synthetic"
    assert observed["headers"]["Authorization"] == f"Bearer {secret}"
    assert observed["body"]["models"] == [
        OPENROUTER_DEFAULT_MODEL,
        "baidu/ernie-5.5-flash-preview:free",
    ]
    assert observed["body"]["max_tokens"] == 1024
    assert "tools" not in observed["body"]
    assert result["evidence"]["tools_enabled"] is False
    assert result["evidence"]["provider_request_count"] == 1
    assert result["evidence"]["reported_cost_usd"] == "0"
    assert secret not in json.dumps(result)
    assert secret not in json.dumps(events)


async def _record(events, value):
    events.append(value)


async def test_openrouter_task_tool_grants_are_rejected(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-key")
    with pytest.raises(BridgeError, match="MCP profile is not configured"):
        await OpenRouterAdapter().execute(
            {},
            _args(mcp_operations=["file.read"]),
            _config(),
            [],
            _callback,
            _callback,
        )


def _function_response(name="task_request", arguments='{"request":{}}', *, call_id="call_1"):
    return {
        "id": "req-tool",
        "model": OPENROUTER_DEFAULT_MODEL,
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 5, "cost": 0},
    }


def _tool_enabled_config(**overrides):
    values = {
        "bridge_tools": True,
        "allow_local_tools": True,
        "openrouter_mcp_tools": ["task_request"],
        "openrouter_mcp_operations": ["file.write"],
    }
    values.update(overrides)
    return _config(**values)


def _fake_task_proxy(monkeypatch, tool_result=None, error=None, *, tool_name="task_request"):
    observed = {"calls": [], "server_options": None, "disconnected": False}

    class Pool:
        def __init__(self, **kwargs):
            observed["pool_options"] = kwargs

        async def connect(self, peer):
            observed["peer"] = peer

        async def list_tools(self, peer_id):
            assert peer_id == "kirabridge-openrouter-task"
            return [
                SimpleNamespace(
                    name=tool_name,
                    description="Use one explicitly scoped KiraBridge tool",
                    inputSchema={"type": "object", "properties": {}},
                )
            ]

        async def call(self, peer_id, name, arguments, *, task_id=None):
            observed["calls"].append((peer_id, name, arguments, task_id))
            if error:
                raise error
            return tool_result or SimpleNamespace(
                isError=False,
                structuredContent={"accepted": True, "task_id": "child_1"},
                content=[],
            )

        async def disconnect(self, peer_id):
            observed["disconnected"] = True

    @contextmanager
    def scope(*args, **kwargs):
        observed["server_options"] = kwargs
        yield {"command": "/python", "args": ["-m", "kirabridge.cli", "connect"], "env": []}

    monkeypatch.setattr("kirabridge.agent_manager.openrouter.MCPClientPool", Pool)
    monkeypatch.setattr("kirabridge.agent_manager.openrouter.task_server", scope)
    return observed


async def test_openrouter_tool_round_trip_uses_filtered_task_proxy(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-tool-key")
    args_object = {"request": {"task_id": "child_1", "parent_id": "task_1"}}
    calls = 0
    observed_requests = []

    def handler(request):
        nonlocal calls
        calls += 1
        body = json.loads(request.content)
        observed_requests.append(body)
        if calls == 1:
            return httpx.Response(200, json=_function_response(arguments=json.dumps(args_object)))
        assert body["messages"][1]["tool_calls"][0]["function"]["arguments"] == json.dumps(
            args_object, separators=(",", ":")
        )
        assert body["messages"][2]["role"] == "tool"
        return httpx.Response(
            200,
            json={
                "id": "req-final",
                "model": OPENROUTER_DEFAULT_MODEL,
                "choices": [
                    {
                        "message": {"content": "wrote the file", "role": "assistant"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 30, "completion_tokens": 4, "cost": 0},
            },
        )

    _mock_client(monkeypatch, handler)
    proxy = _fake_task_proxy(monkeypatch)
    args = _args(local_tools=True, mcp_operations=["file.write"])
    task = {"id": "task_1", "principal": "local", "args": {"agent": "openrouter", "cwd": "/tmp"}}
    result = await OpenRouterAdapter(bridge_config=object()).execute(
        task, args, _tool_enabled_config(), ["/tmp"], _callback, _callback
    )
    assert result["success"]
    assert result["text"] == "wrote the file"
    assert result["evidence"]["tool_call_count"] == 1
    assert result["evidence"]["provider_request_count"] == 2
    assert observed_requests[0]["tools"][0]["function"]["name"] == "task_request"
    assert observed_requests[0]["parallel_tool_calls"] is False
    assert proxy["server_options"]["operator_tools"] == ["task_request"]
    assert proxy["server_options"]["operator_operations"] == ["file.write"]
    assert proxy["calls"] == [("kirabridge-openrouter-task", "task_request", args_object, "task_1")]
    assert proxy["disconnected"]


async def test_openrouter_tool_loop_supports_authorized_read_query(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-read-key")
    query = {"query": {"operation": "file.read", "path": "/tmp/source.py"}}
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json=_function_response("read_query", json.dumps(query)),
            )
        return httpx.Response(
            200,
            json={
                "id": "read-final",
                "model": OPENROUTER_DEFAULT_MODEL,
                "choices": [
                    {
                        "message": {"content": "read completed", "role": "assistant"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 3},
            },
        )

    _mock_client(monkeypatch, handler)
    proxy = _fake_task_proxy(monkeypatch, tool_name="read_query")
    config = _tool_enabled_config(
        allow_local_tools=False,
        openrouter_mcp_tools=["read_query"],
        openrouter_mcp_operations=["file.read"],
    )
    result = await OpenRouterAdapter(bridge_config=object()).execute(
        {"id": "task_1", "principal": "local", "args": {"agent": "openrouter", "cwd": "/tmp"}},
        _args(mcp_operations=["file.read"]),
        config,
        ["/tmp"],
        _callback,
        _callback,
    )
    assert result["success"]
    assert result["evidence"]["tool_call_count"] == 1
    assert proxy["calls"][0][1:3] == ("read_query", query)


@pytest.mark.parametrize(
    ("name", "arguments", "max_calls", "expected_code"),
    [
        ("terminal_execute", "{}", 8, "provider_protocol"),
        ("task_request", "{bad-json", 8, "provider_protocol"),
        ("task_request", "[]", 8, "provider_protocol"),
    ],
)
async def test_openrouter_malformed_or_ungranted_calls_never_dispatch(
    monkeypatch, name, arguments, max_calls, expected_code
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-tool-key")
    _mock_client(
        monkeypatch, lambda _: httpx.Response(200, json=_function_response(name, arguments))
    )
    proxy = _fake_task_proxy(monkeypatch)
    config = _tool_enabled_config(openrouter_max_tool_calls=max_calls)
    with pytest.raises(UncertainExecution) as exc:
        await OpenRouterAdapter(bridge_config=object()).execute(
            {"id": "task_1", "principal": "local", "args": {"agent": "openrouter", "cwd": "/tmp"}},
            _args(local_tools=True, mcp_operations=["file.write"]),
            config,
            ["/tmp"],
            _callback,
            _callback,
        )
    assert exc.value.code == expected_code
    assert proxy["calls"] == []


async def test_openrouter_tool_call_budget_rejects_batch_before_dispatch(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-tool-key")
    response = _function_response()
    response["choices"][0]["message"]["tool_calls"].append(
        {
            "id": "call_2",
            "type": "function",
            "function": {"name": "task_request", "arguments": "{}"},
        }
    )
    _mock_client(monkeypatch, lambda _: httpx.Response(200, json=response))
    proxy = _fake_task_proxy(monkeypatch)
    with pytest.raises(BridgeError) as exc:
        await OpenRouterAdapter(bridge_config=object()).execute(
            {"id": "task_1", "principal": "local", "args": {"agent": "openrouter", "cwd": "/tmp"}},
            _args(local_tools=True, mcp_operations=["file.write"]),
            _tool_enabled_config(openrouter_max_tool_calls=1),
            ["/tmp"],
            _callback,
            _callback,
        )
    assert exc.value.code == "provider_tool_call_budget"
    assert proxy["calls"] == []


async def test_openrouter_tool_turn_budget_rejects_before_first_dispatch(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-tool-key")
    _mock_client(monkeypatch, lambda _: httpx.Response(200, json=_function_response()))
    proxy = _fake_task_proxy(monkeypatch)
    with pytest.raises(BridgeError) as exc:
        await OpenRouterAdapter(bridge_config=object()).execute(
            {"id": "task_1", "principal": "local", "args": {"agent": "openrouter", "cwd": "/tmp"}},
            _args(local_tools=True, mcp_operations=["file.write"]),
            _tool_enabled_config(openrouter_max_turns=1),
            ["/tmp"],
            _callback,
            _callback,
        )
    assert exc.value.code == "provider_tool_turn_budget"
    assert proxy["calls"] == []


async def test_openrouter_oversized_tool_result_is_terminal_and_not_replayed(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-tool-key")
    request_count = 0

    def handler(_request):
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, json=_function_response())

    _mock_client(monkeypatch, handler)
    result = SimpleNamespace(isError=False, structuredContent={"payload": "x" * 2048}, content=[])
    proxy = _fake_task_proxy(monkeypatch, tool_result=result)
    with pytest.raises(BridgeError) as exc:
        await OpenRouterAdapter(bridge_config=object()).execute(
            {"id": "task_1", "principal": "local", "args": {"agent": "openrouter", "cwd": "/tmp"}},
            _args(local_tools=True, mcp_operations=["file.write"]),
            _tool_enabled_config(openrouter_max_tool_result_bytes=1024),
            ["/tmp"],
            _callback,
            _callback,
        )
    assert exc.value.code == "provider_tool_result"
    assert request_count == 1
    assert len(proxy["calls"]) == 1


async def test_openrouter_unknown_mcp_mutation_is_never_replayed(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-tool-key")
    provider_requests = []

    def provider(_):
        provider_requests.append("request")
        return httpx.Response(200, json=_function_response())

    _mock_client(monkeypatch, provider)
    proxy = _fake_task_proxy(monkeypatch, error=UncertainExecution("peer_unknown", "unknown"))
    with pytest.raises(UncertainExecution) as exc:
        await OpenRouterAdapter(bridge_config=object()).execute(
            {"id": "task_1", "principal": "local", "args": {"agent": "openrouter", "cwd": "/tmp"}},
            _args(local_tools=True, mcp_operations=["file.write"]),
            _tool_enabled_config(),
            ["/tmp"],
            _callback,
            _callback,
        )
    assert exc.value.code == "peer_unknown"
    assert len(proxy["calls"]) == 1
    assert len(provider_requests) == 1


async def test_openrouter_task_server_policy_binds_task_owner_args_cwd_and_read_only():
    from kirabridge.agent_manager.qwen_mcp import task_server
    from kirabridge.bridge_core.config import Config

    bridge_config = Config()
    bridge_config._source_path = "/tmp/openrouter-test-config.toml"
    principal = bridge_config.principals["local"]
    principal.capabilities = ["bridge.health", "task.read", "file.write"]
    principal.roots = [str(Path("/tmp").resolve())]
    bridge_config.agents["openrouter"] = _tool_enabled_config(sandbox_mode="workspace-write")
    args = _args(local_tools=True, mcp_operations=["file.write"])
    args.cwd = str(Path("/tmp").resolve())
    task = {
        "id": "bound_task",
        "principal": "local",
        "state": "running",
        "operation": "agent.execute",
        "args": args.model_dump(),
    }
    with task_server(
        bridge_config,
        task,
        args,
        30,
        operator_tools=bridge_config.agents["openrouter"].openrouter_mcp_tools,
        operator_operations=bridge_config.agents["openrouter"].openrouter_mcp_operations,
        operator_read_roots=[],
        max_calls=1,
        prefix="openrouter-test",
    ) as spec:
        policy_path = spec["args"][-1]
        policy = AgentTaskPolicy.load(policy_path, "local")
        assert policy.tools == ["task_request"]
        assert policy.operations == ["file.write"]
        assert policy.read_only is False
        assert policy.full_access is False
        policy.validate_task(task)
        with pytest.raises(BridgeError):
            policy.validate_task({**task, "principal": "foreign"})
        changed = {**task, "args": {**task["args"], "cwd": "/tmp/elsewhere"}}
        with pytest.raises(BridgeError):
            policy.validate_task(changed)
        expired = policy.model_copy(update={"expires_at": time.time() - 1})
        with pytest.raises(BridgeError):
            expired.validate_task(task)
        outside_child = TaskRequest(
            task_id="child_outside",
            idempotency_key="child_outside",
            parent_id="bound_task",
            operation="file.write",
            arguments={"path": "/etc/kirabridge-outside", "text": "synthetic"},
        )
        with pytest.raises(BridgeError, match="outside task cwd"):
            policy._child({"request": outside_child.model_dump()})
        shell_child = outside_child.model_copy(
            update={
                "task_id": "child_shell",
                "idempotency_key": "child_shell",
                "operation": "terminal.execute",
            }
        )
        with pytest.raises(BridgeError, match="outside the task operation grant"):
            policy._child({"request": shell_child.model_dump()})
        connection = SimpleNamespace(
            call_tool=lambda *_args: None,
        )

        async def owner_task(_name, _arguments):
            return SimpleNamespace(isError=False, structuredContent=task)

        connection.call_tool = owner_task
        definition = SimpleNamespace(name="task_request", annotations=None)
        good_request = TaskRequest(
            task_id="child_good",
            idempotency_key="child_good",
            parent_id="bound_task",
            operation="file.write",
            arguments={"path": str(Path(args.cwd) / "in-scope"), "text": "synthetic"},
        ).model_dump()
        more_request = TaskRequest(
            task_id="child_more",
            idempotency_key="child_more",
            parent_id="bound_task",
            operation="file.write",
            arguments={"path": str(Path(args.cwd) / "in-scope-2"), "text": "synthetic"},
        ).model_dump()
        await policy.authorize(
            connection,
            "task_request",
            {"request": good_request},
            definition=definition,
        )
        with pytest.raises(BridgeError, match="call budget"):
            await policy.authorize(
                connection,
                "task_request",
                {"request": more_request},
                definition=definition,
            )

    read_only_args = _args(local_tools=False, mcp_operations=["file.write"])
    read_only_task = {**task, "args": read_only_args.model_dump()}
    with pytest.raises(BridgeError, match="existing principal grant"):
        with task_server(
            bridge_config,
            read_only_task,
            read_only_args,
            30,
            operator_tools=["task_request"],
            operator_operations=["file.write"],
            operator_read_roots=[],
            max_calls=1,
        ):
            pytest.fail("read-only task must not receive a write operation")


async def test_paid_openrouter_loop_sends_provider_unit_price_ceiling_each_turn(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-paid-key")
    api_calls = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "deepseek/deepseek-v4.1-flash",
                            "pricing": {"prompt": "0.0000000498", "completion": "0.0000001992"},
                        }
                    ]
                },
            )
        body = json.loads(request.content)
        api_calls.append(body)
        response = (
            _function_response(arguments='{"request":{"task_id":"child_1"}}')
            if len(api_calls) == 1
            else {
                "id": "paid-final",
                "model": "deepseek/deepseek-v4.1-flash",
                "choices": [
                    {"message": {"content": "done", "role": "assistant"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 3, "cost": "0.0000001"},
            }
        )
        response["model"] = "deepseek/deepseek-v4.1-flash"
        return httpx.Response(200, json=response)

    _mock_client(monkeypatch, handler)
    proxy = _fake_task_proxy(monkeypatch)
    config = _tool_enabled_config(
        model="deepseek/deepseek-v4.1-flash",
        openrouter_fallback_models=[],
        openrouter_allow_paid=True,
        openrouter_max_output_tokens=16,
        openrouter_max_turns=2,
        openrouter_paid_max_prompt_bytes=1024,
        openrouter_paid_max_output_tokens=16,
        openrouter_paid_max_cost_usd=Decimal("0.0001"),
    )
    result = await OpenRouterAdapter(bridge_config=object()).execute(
        {"id": "task_1", "principal": "local", "args": {"agent": "openrouter", "cwd": "/tmp"}},
        _args(local_tools=True, mcp_operations=["file.write"]),
        config,
        ["/tmp"],
        _callback,
        _callback,
    )
    assert result["success"]
    assert len(api_calls) == 2
    assert all(body["models"] == ["deepseek/deepseek-v4.1-flash"] for body in api_calls)
    assert all(body["provider"]["allow_fallbacks"] is False for body in api_calls)
    assert all(
        body["provider"]["max_price"] == {"prompt": 0.0498, "completion": 0.1992}
        for body in api_calls
    )
    assert result["evidence"]["reported_cost_usd"] == "1E-7"
    assert result["evidence"]["paid_cost_upper_bound_usd"] is not None
    assert len(proxy["calls"]) == 1


def test_paid_model_requires_explicit_opt_in_and_bounded_prompt_output_cost():
    with pytest.raises(ValidationError):
        AgentConfig(
            kind="openrouter_api",
            executable="/absolute/path/opencode",
            model="deepseek/deepseek-v4.1-flash",
            openrouter_credential_source="environment",
        )

    config = AgentConfig(
        kind="openrouter_api",
        model="deepseek/deepseek-v4.1-flash",
        openrouter_fallback_models=[],
        api_key_env="OPENROUTER_API_KEY",
        openrouter_credential_source="environment",
        openrouter_allow_paid=True,
        openrouter_max_output_tokens=50,
        openrouter_paid_max_prompt_bytes=100,
        openrouter_paid_max_output_tokens=50,
        openrouter_paid_max_cost_usd=Decimal("0.00001"),
    )
    assert config.openrouter_allow_paid is True
    with pytest.raises(ValidationError, match="explicitly reviewed set"):
        AgentConfig(
            kind="openrouter_api",
            model="vendor/arbitrary-paid-model",
            api_key_env="OPENROUTER_API_KEY",
            openrouter_credential_source="environment",
            openrouter_allow_paid=True,
            openrouter_max_output_tokens=50,
            openrouter_paid_max_prompt_bytes=100,
            openrouter_paid_max_output_tokens=50,
            openrouter_paid_max_cost_usd=Decimal("0.00001"),
        )


def test_openrouter_config_defaults_free_and_omits_settings_for_other_agents():
    config = AgentConfig(kind="openrouter_api", executable="/absolute/path/opencode")
    assert config.openrouter_credential_source == "environment"
    assert config.model == OPENROUTER_DEFAULT_MODEL
    assert config.openrouter_fallback_models == ["baidu/ernie-5.5-flash-preview:free"]
    assert config.openrouter_allow_paid is False
    config_dump = config.model_dump()
    assert config_dump["api_key_env"] == "OPENROUTER_API_KEY"
    assert not any(key.lower() in {"api_key", "credential_value"} for key in config_dump)
    assert not any(
        key.startswith("openrouter_") for key in AgentConfig(kind="grok_api").model_dump()
    )


def test_openrouter_api_key_environment_name_is_fixed():
    with pytest.raises(ValidationError, match="OPENROUTER_API_KEY"):
        AgentConfig(
            kind="openrouter_api",
            api_key_env="OTHER_SECRET",
            openrouter_credential_source="environment",
        )


@pytest.mark.parametrize(
    "values",
    [
        {"openrouter_mcp_tools": ["terminal_execute"], "bridge_tools": True},
        {"openrouter_mcp_operations": ["terminal.execute"], "bridge_tools": True},
        {"openrouter_mcp_tools": ["task_request"]},
    ],
)
def test_openrouter_tool_profile_rejects_shell_or_unwired_tools(values):
    with pytest.raises(ValidationError):
        AgentConfig(kind="openrouter_api", **values)


@pytest.mark.parametrize("response_body", [[], "not-an-object", 42, None])
async def test_malformed_json_200_is_sanitized_protocol_error(monkeypatch, response_body):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-malformed-key")
    _mock_client(monkeypatch, lambda _: httpx.Response(200, json=response_body))
    with pytest.raises(UncertainExecution) as exc:
        await OpenRouterAdapter().execute({}, _args(), _config(), [], _callback, _callback)
    assert getattr(exc.value, "code", None) == "provider_protocol"


def test_keychain_reader_is_exact_and_never_prints_secret(monkeypatch):
    secret = "synthetic-keychain-secret"
    observed = {}
    monkeypatch.setattr(openrouter_credentials.sys, "platform", "darwin")

    def run(argv, **kwargs):
        observed.update(argv=argv, kwargs=kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout=(secret + "\n").encode())

    monkeypatch.setattr(openrouter_credentials.subprocess, "run", run)
    assert openrouter_credentials.keychain_credential() == secret
    assert observed["argv"] == [
        "/usr/bin/security",
        "find-generic-password",
        "-s",
        "KiraBridge.OpenRouter",
        "-a",
        "openrouter",
        "-w",
    ]
    assert observed["kwargs"]["stdout"] == subprocess.PIPE
    assert secret not in repr(observed)


def test_keychain_import_uses_native_hidden_tty_prompt_without_secret_argv(monkeypatch):
    seen = {}
    monkeypatch.setattr(openrouter_credentials.sys, "platform", "darwin")

    class TTY:
        def isatty(self):
            return True

    monkeypatch.setattr(openrouter_credentials.sys, "stdin", TTY())
    monkeypatch.setattr(openrouter_credentials.sys, "stdout", TTY())

    def run(argv, **kwargs):
        seen.update(argv=argv, kwargs=kwargs)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(openrouter_credentials.subprocess, "run", run)
    assert openrouter_credentials.import_from_hidden_tty() is True
    assert seen["argv"][-1] == "-w"
    assert seen["kwargs"]["stdin"] is None
    assert seen["kwargs"]["stderr"] is None
    assert not any("synthetic" in str(arg) for arg in seen["argv"])


def test_keychain_status_checks_presence_without_reading_value(monkeypatch):
    seen = {}
    monkeypatch.setattr(openrouter_credentials.sys, "platform", "darwin")

    def run(argv, **kwargs):
        seen.update(argv=argv, kwargs=kwargs)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(openrouter_credentials.subprocess, "run", run)
    assert openrouter_credentials.keychain_status() is True
    assert "-w" not in seen["argv"]
    assert seen["kwargs"]["stdout"] == subprocess.DEVNULL
    assert seen["kwargs"]["stderr"] == subprocess.DEVNULL


async def test_agent_manager_routes_openrouter_api_without_visible_terminal(tmp_path):
    from kirabridge.agent_manager import AgentManager
    from kirabridge.bridge_core.config import Config
    from kirabridge.terminal_manager import TerminalManager

    manager = AgentManager(Config(), TerminalManager())
    manager.config.visible_handoffs.enabled = True
    manager.config.agents["openrouter"] = _config()

    class Visible:
        called = False

        async def execute(self, *args, **kwargs):
            self.called = True
            raise AssertionError("OpenRouter API must not use a visible terminal")

    class Adapter:
        interface_version = "1"

        async def execute(self, task, args, config, roots, running, progress):
            return {"success": True, "text": "ok", "evidence": {"adapter": "openrouter_api"}}

    visible = Visible()
    manager.visible_handoffs = visible
    manager.adapters["openrouter_api"] = Adapter()
    principal = SimpleNamespace(
        agents=["openrouter"], permission_level=None, roots=[str(tmp_path)], capabilities=[]
    )
    result = await manager.execute(
        {"id": "task-openrouter", "principal": "local"},
        AgentInput(agent="openrouter", prompt="hello", cwd=str(tmp_path), timeout=1),
        principal,
        AsyncMock(),
        AsyncMock(),
    )
    assert result["text"] == "ok"
    assert visible.called is False


async def test_paid_cost_guard_checks_live_metadata_before_chat_request(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request.method)
        assert "Authorization" not in request.headers
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "deepseek/deepseek-v4.1-flash",
                        "pricing": {"prompt": "0.000001", "completion": "0.000001"},
                    }
                ]
            },
        )

    _mock_client(monkeypatch, handler)
    config = AgentConfig(
        kind="openrouter_api",
        model="deepseek/deepseek-v4.1-flash",
        openrouter_fallback_models=[],
        api_key_env="OPENROUTER_API_KEY",
        openrouter_credential_source="environment",
        openrouter_allow_paid=True,
        openrouter_max_output_tokens=50,
        openrouter_paid_max_prompt_bytes=100,
        openrouter_paid_max_output_tokens=50,
        openrouter_paid_max_cost_usd=Decimal("0.00001"),
    )

    with pytest.raises(BridgeError) as exc:
        await OpenRouterAdapter().execute({}, _args(), config, [], _callback, _callback)
    assert exc.value.code == "provider_paid_budget"
    assert calls == ["GET"]


async def test_provider_error_body_and_key_are_never_returned(monkeypatch):
    secret = "synthetic-api-key-never-echo"
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)

    def handler(request):
        return httpx.Response(429, json={"error": secret})

    _mock_client(monkeypatch, handler)
    with pytest.raises(BridgeError) as exc:
        await OpenRouterAdapter().execute({}, _args(), _config(), [], _callback, _callback)
    assert exc.value.code == "provider_rejected"
    assert exc.value.provider_error["category"] == "rate_limit"
    assert secret not in str(exc.value)
    assert secret not in repr(exc.value.provider_error)
