from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from kirabridge.agent_manager.openrouter import OpenRouterAdapter
from kirabridge.bridge_core.config import AgentConfig
from kirabridge.bridge_core.models import AgentInput, BridgeError
from kirabridge.openrouter_models import OPENROUTER_DEFAULT_MODEL


def _config(**kwargs):
    return AgentConfig(
        kind="openrouter_api",
        model=OPENROUTER_DEFAULT_MODEL,
        api_key_env="TEST_OPENROUTER_API_KEY",
        openrouter_credential_source="environment",
        **kwargs,
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
    monkeypatch.setenv("TEST_OPENROUTER_API_KEY", secret)
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
    monkeypatch.setenv("TEST_OPENROUTER_API_KEY", "synthetic-key")
    with pytest.raises(BridgeError, match="does not execute tools"):
        await OpenRouterAdapter().execute(
            {},
            _args(mcp_operations=["file.read"]),
            _config(),
            [],
            _callback,
            _callback,
        )


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
        api_key_env="TEST_OPENROUTER_API_KEY",
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
            api_key_env="TEST_OPENROUTER_API_KEY",
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
        api_key_env="TEST_OPENROUTER_API_KEY",
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
    monkeypatch.setenv("TEST_OPENROUTER_API_KEY", secret)

    def handler(request):
        return httpx.Response(429, json={"error": secret})

    _mock_client(monkeypatch, handler)
    with pytest.raises(BridgeError) as exc:
        await OpenRouterAdapter().execute({}, _args(), _config(), [], _callback, _callback)
    assert exc.value.code == "provider_rejected"
    assert exc.value.provider_error["category"] == "rate_limit"
    assert secret not in str(exc.value)
    assert secret not in repr(exc.value.provider_error)
