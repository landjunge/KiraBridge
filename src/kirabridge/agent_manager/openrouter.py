"""OpenRouter's OpenAI-compatible text API with a closed free-model route."""

from __future__ import annotations

import asyncio
import json
import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

from kirabridge.agent_manager.openrouter_credentials import keychain_credential
from kirabridge.agent_manager.qwen_mcp import task_server
from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.openrouter_models import (
    OPENROUTER_CHAT_API,
    OPENROUTER_DEEPSEEK_MAX_PRICE,
    OPENROUTER_FREE_MODELS,
    OPENROUTER_MODELS_API,
    OPENROUTER_PAID_MODELS,
    OPENROUTER_TOOL_MODELS,
)
from kirabridge.terminal_manager import minimal_environment

_MAX_RESPONSE_BYTES = 1048576
_MAX_CATALOG_BYTES = 4194304
_MAX_TOOL_CATALOG_BYTES = 65536
_FREE_RATE = Decimal("0")


def _credential(config) -> str:
    if config.openrouter_credential_source == "environment":
        key = os.environ.get(config.api_key_env)
        if key:
            return key
        raise BridgeError("agent_auth", "OpenRouter credential is unavailable")
    if config.openrouter_credential_source == "macos_keychain":
        return keychain_credential()
    raise BridgeError("agent_auth", "OpenRouter credential source is unsupported")


async def _bounded_body(response: httpx.Response, limit: int) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes(chunk_size=8192):
        body.extend(chunk)
        if len(body) > limit:
            raise UncertainExecution("provider_protocol", "OpenRouter response exceeded its limit")
    return bytes(body)


def _decimal_price(value) -> Decimal:
    try:
        price = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise BridgeError("provider_metadata", "OpenRouter pricing metadata is invalid") from None
    if not price.is_finite() or price < 0:
        raise BridgeError("provider_metadata", "OpenRouter pricing metadata is invalid")
    return price


def _paid_prices(catalog: dict, model: str) -> tuple[Decimal, Decimal]:
    rows = catalog.get("data") if isinstance(catalog, dict) else None
    if not isinstance(rows, list):
        raise BridgeError("provider_metadata", "OpenRouter model metadata is unavailable")
    match = next((row for row in rows if isinstance(row, dict) and row.get("id") == model), None)
    pricing = match.get("pricing") if isinstance(match, dict) else None
    if not isinstance(pricing, dict):
        raise BridgeError("provider_metadata", "OpenRouter model pricing is unavailable")
    inputs = [_decimal_price(pricing.get("prompt"))]
    outputs = [_decimal_price(pricing.get("completion"))]
    overrides = pricing.get("overrides", [])
    if isinstance(overrides, list):
        for item in overrides:
            if isinstance(item, dict):
                if "prompt" in item:
                    inputs.append(_decimal_price(item["prompt"]))
                if "completion" in item:
                    outputs.append(_decimal_price(item["completion"]))
    return max(inputs), max(outputs)


class OpenRouterAdapter:
    """Bounded text/tool turns through KiraBridge's task-scoped stdio MCP proxy."""

    interface_version = "1"

    def __init__(self, bridge_config=None, *, client_factory=None, pool_factory=None):
        self.bridge_config = bridge_config
        self.client_factory = client_factory or httpx.AsyncClient
        self.pool_factory = pool_factory or MCPClientPool

    async def execute(self, task, args, config, roots, running, progress) -> dict:
        try:
            async with asyncio.timeout(args.timeout):
                return await self._execute_bounded(task, args, config, roots, running, progress)
        except TimeoutError:
            raise UncertainExecution(
                "provider_timeout", "OpenRouter task deadline elapsed"
            ) from None

    async def _execute_bounded(self, task, args, config, roots, running, progress) -> dict:
        model = config.model
        fallbacks = list(config.openrouter_fallback_models)
        if len(set([model, *fallbacks])) != 1 + len(fallbacks):
            raise BridgeError("agent_config", "OpenRouter model routes must be unique")
        if any(item not in OPENROUTER_FREE_MODELS for item in fallbacks):
            raise BridgeError("agent_config", "OpenRouter fallbacks must be verified free models")

        is_free = model in OPENROUTER_FREE_MODELS
        if not is_free and model not in OPENROUTER_PAID_MODELS:
            raise BridgeError(
                "provider_paid_disabled", "OpenRouter model is not explicitly enabled"
            )
        has_tool_scope = bool(args.mcp_grants or args.mcp_operations or args.mcp_read_roots)
        if has_tool_scope and model not in OPENROUTER_TOOL_MODELS:
            raise BridgeError("agent_tools_denied", "Selected model is not approved for tool calls")
        output_limit = config.openrouter_max_output_tokens
        input_limit = config.openrouter_max_prompt_bytes
        input_rate = output_rate = None
        if not is_free:
            if not config.openrouter_allow_paid:
                raise BridgeError("provider_paid_disabled", "Paid OpenRouter models are disabled")
            if fallbacks:
                raise BridgeError("agent_config", "Paid model fallbacks are disabled")
            input_limit = config.openrouter_paid_max_prompt_bytes
            output_limit = config.openrouter_paid_max_output_tokens
            if (
                input_limit is None
                or output_limit is None
                or config.openrouter_paid_max_cost_usd is None
            ):
                raise BridgeError(
                    "agent_config", "Paid OpenRouter requests require explicit limits"
                )

        prompt_bytes = len(args.prompt.encode("utf-8"))
        if prompt_bytes > input_limit:
            raise BridgeError(
                "provider_input_limit", "OpenRouter prompt exceeds the configured limit"
            )

        timeout = httpx.Timeout(args.timeout)
        try:
            async with self.client_factory(timeout=timeout, trust_env=False) as client:
                if not is_free:
                    async with client.stream("GET", OPENROUTER_MODELS_API) as meta_response:
                        if meta_response.status_code != 200:
                            raise BridgeError(
                                "provider_metadata", "OpenRouter pricing metadata is unavailable"
                            )
                        raw_catalog = await _bounded_body(meta_response, _MAX_CATALOG_BYTES)
                    try:
                        input_rate, output_rate = _paid_prices(json.loads(raw_catalog), model)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        raise BridgeError(
                            "provider_metadata", "OpenRouter pricing metadata is invalid"
                        ) from None
                    # A UTF-8 byte is a conservative upper bound for a text token;
                    # reserve framing overhead, and budget the full completion cap.
                    ceiling = OPENROUTER_DEEPSEEK_MAX_PRICE
                    if input_rate > Decimal(str(ceiling["prompt"])) or output_rate > Decimal(
                        str(ceiling["completion"])
                    ):
                        raise BridgeError(
                            "provider_paid_budget", "DeepSeek price exceeds the approved ceiling"
                        )
                tool_context = None
                if has_tool_scope:
                    if self.bridge_config is None or not config.openrouter_mcp_tools:
                        raise BridgeError(
                            "agent_tools_denied", "OpenRouter MCP profile is not configured"
                        )
                    tool_context = task_server(
                        self.bridge_config,
                        task,
                        args,
                        args.timeout,
                        operator_tools=config.openrouter_mcp_tools,
                        operator_operations=config.openrouter_mcp_operations,
                        operator_read_roots=config.openrouter_mcp_read_roots,
                        max_calls=config.openrouter_max_tool_calls,
                        prefix="openrouter",
                    )
                if tool_context is None:
                    return await self._conversation(
                        client,
                        task,
                        args,
                        config,
                        model,
                        fallbacks,
                        is_free,
                        input_limit,
                        output_limit,
                        input_rate,
                        output_rate,
                        None,
                        running,
                        progress,
                    )
                with tool_context as spec:
                    return await self._conversation(
                        client,
                        task,
                        args,
                        config,
                        model,
                        fallbacks,
                        is_free,
                        input_limit,
                        output_limit,
                        input_rate,
                        output_rate,
                        spec,
                        running,
                        progress,
                    )
        except (httpx.HTTPError, OSError):
            raise UncertainExecution(
                "provider_disconnected", "OpenRouter response cannot be confirmed"
            ) from None

    async def _conversation(
        self,
        client,
        task,
        args,
        config,
        model,
        fallbacks,
        is_free,
        input_limit,
        output_limit,
        input_rate,
        output_rate,
        server_spec,
        running,
        progress,
    ):
        pool = peer_id = None
        tool_catalog = []
        if server_spec is not None:
            pool, peer_id, tool_catalog = await self._connect_task_proxy(server_spec, args, config)
        messages = [{"role": "user", "content": args.prompt}]
        models = [model] if not is_free else [model, *fallbacks]
        request_count = tool_call_count = 0
        spent_bound = Decimal(0)
        reported_cost_total = Decimal(0)
        reported_cost_known = False
        final_text = ""
        final_result = None
        choice = None
        try:
            for turn in range(config.openrouter_max_turns):
                definitions = self._openai_tools(tool_catalog)
                request_bytes = len(
                    json.dumps(
                        {"messages": messages, "tools": definitions},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode()
                )
                if request_bytes > input_limit:
                    raise BridgeError(
                        "provider_input_limit", "OpenRouter context exceeds its limit"
                    )
                if not is_free:
                    turn_bound = (
                        Decimal(request_bytes + 64) * input_rate
                        + Decimal(output_limit) * output_rate
                    )
                    if spent_bound + turn_bound > config.openrouter_paid_max_cost_usd:
                        raise BridgeError(
                            "provider_paid_budget", "OpenRouter task exceeds its cost limit"
                        )
                    spent_bound += turn_bound
                body = {
                    "models": models,
                    "messages": messages,
                    "max_tokens": output_limit,
                    "stream": False,
                }
                if definitions:
                    body.update(tools=definitions, tool_choice="auto", parallel_tool_calls=False)
                if not is_free:
                    body["provider"] = {
                        "allow_fallbacks": False,
                        "max_price": OPENROUTER_DEEPSEEK_MAX_PRICE,
                    }
                request_count += 1
                request_evidence = {
                    "agent": args.agent,
                    "adapter": "openrouter_api",
                    "model": model,
                    "event": "provider_request_sent",
                    "provider_request_count": request_count,
                }
                await (running if request_count == 1 else progress)(request_evidence)
                raw = await self._post_chat(client, body, config)
                final_result, choice, message = self._parse_completion(raw)
                usage = final_result.get("usage")
                if isinstance(usage, dict):
                    call_cost = self._reported_cost(usage)
                    if call_cost is not None:
                        reported_cost_total += Decimal(call_cost)
                        reported_cost_known = True
                final_text = message.get("content") or ""
                calls = message.get("tool_calls") or []
                if choice["finish_reason"] != "tool_calls":
                    if calls:
                        raise UncertainExecution(
                            "provider_protocol", "OpenRouter tool response was malformed"
                        )
                    break
                if not isinstance(calls, list) or not calls or pool is None:
                    raise BridgeError("agent_tools_denied", "OpenRouter requested ungranted tools")
                if turn + 1 >= config.openrouter_max_turns:
                    raise BridgeError(
                        "provider_tool_turn_budget", "OpenRouter tool turn budget is exhausted"
                    )
                if tool_call_count + len(calls) > config.openrouter_max_tool_calls:
                    raise BridgeError(
                        "provider_tool_call_budget", "OpenRouter tool call budget is exhausted"
                    )
                normalized = self._validate_tool_calls(calls, tool_catalog)
                messages.append(
                    {
                        "role": "assistant",
                        "content": message.get("content"),
                        "tool_calls": [
                            {
                                "id": item["id"],
                                "type": "function",
                                "function": {
                                    "name": item["function"]["name"],
                                    "arguments": json.dumps(
                                        item["function"]["arguments"],
                                        ensure_ascii=False,
                                        separators=(",", ":"),
                                    ),
                                },
                            }
                            for item in normalized
                        ],
                    }
                )
                for item in normalized:
                    function = item["function"]
                    tool_call_count += 1
                    await progress(
                        {
                            "agent": args.agent,
                            "adapter": "openrouter_api",
                            "event": "mcp_tool_dispatch",
                            "tool": function["name"],
                            "tool_call_count": tool_call_count,
                        }
                    )
                    # The stdio proxy rechecks task owner/args/permissions and consumes
                    # its one-shot call budget before dispatch. Never replay exceptions.
                    result = await pool.call(
                        peer_id, function["name"], function["arguments"], task_id=task["id"]
                    )
                    if result.isError:
                        raise BridgeError(
                            "agent_tool_rejected", "Task-scoped MCP tool returned an error"
                        )
                    content = self._serialize_tool_result(
                        result, config.openrouter_max_tool_result_bytes
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": item["id"],
                            "content": content,
                        }
                    )
            else:
                raise BridgeError("provider_tool_turn_budget", "OpenRouter turn budget exhausted")
        finally:
            if pool is not None:
                await pool.disconnect(peer_id)
        if final_result is None:
            raise UncertainExecution("provider_protocol", "OpenRouter returned no completion")
        usage = final_result.get("usage") if isinstance(final_result.get("usage"), dict) else {}
        evidence = {
            "agent": args.agent,
            "adapter": "openrouter_api",
            "requested_models": models,
            "selected_model": self._bounded_string(final_result.get("model"), 256),
            "request_id": self._bounded_string(final_result.get("id"), 256),
            "finish_reason": choice["finish_reason"],
            "provider_request_count": request_count,
            "tool_call_count": tool_call_count,
            "prompt_tokens": self._token_count(usage.get("prompt_tokens")),
            "completion_tokens": self._token_count(usage.get("completion_tokens")),
            "paid_cost_upper_bound_usd": str(spent_bound) if not is_free else None,
            "reported_cost_usd": str(reported_cost_total) if reported_cost_known else None,
            "tools_enabled": bool(tool_catalog),
        }
        return {
            "success": choice["finish_reason"] == "stop",
            "text": final_text,
            "evidence": evidence,
            "scope": "agent_turn",
            "project_completion_verified": False,
        }

    async def _connect_task_proxy(self, server_spec, args, config):
        env = minimal_environment()
        env["HOME"] = str(Path.home())
        env.update({item["name"]: item["value"] for item in server_spec.get("env", [])})
        peer_id = "kirabridge-openrouter-task"
        pool = self.pool_factory(
            max_connections=1,
            call_timeout=min(args.timeout, 30),
            max_catalog_bytes=_MAX_TOOL_CATALOG_BYTES,
        )
        peer = Peer(
            id=peer_id,
            command=server_spec["command"],
            args=tuple(server_spec["args"]),
            env=env,
            cwd=args.cwd,
        )
        try:
            await pool.connect(peer)
            tools = await pool.list_tools(peer_id)
        except BaseException:
            await pool.disconnect(peer_id)
            raise
        if any(tool.name not in set(config.openrouter_mcp_tools) for tool in tools):
            await pool.disconnect(peer_id)
            raise BridgeError("agent_tools_denied", "MCP proxy exposed an unapproved tool")
        if len(tools) > 16:
            await pool.disconnect(peer_id)
            raise BridgeError("agent_tools_denied", "MCP tool catalog exceeds its bound")
        return pool, peer_id, tools

    @staticmethod
    def _openai_tools(catalog):
        definitions = []
        total = 0
        for tool in catalog:
            name = getattr(tool, "name", None)
            description = getattr(tool, "description", "") or ""
            schema = getattr(tool, "inputSchema", None)
            if (
                not isinstance(name, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name)
                or not isinstance(schema, dict)
                or not isinstance(description, str)
                or len(description.encode()) > 2048
            ):
                raise BridgeError("agent_tools_denied", "MCP tool schema is invalid")
            schema_bytes = len(
                json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode()
            )
            total += schema_bytes + len(description.encode()) + len(name)
            if schema_bytes > 16384 or total > _MAX_TOOL_CATALOG_BYTES:
                raise BridgeError("agent_tools_denied", "MCP tool catalog exceeds its byte budget")
            definitions.append(
                {
                    "type": "function",
                    "function": {"name": name, "description": description, "parameters": schema},
                }
            )
        return definitions

    @staticmethod
    def _validate_tool_calls(calls, catalog):
        allowed = {tool.name for tool in catalog}
        validated, seen = [], set()
        for call in calls:
            function = call.get("function") if isinstance(call, dict) else None
            call_id = call.get("id") if isinstance(call, dict) else None
            raw_args = function.get("arguments") if isinstance(function, dict) else None
            name = function.get("name") if isinstance(function, dict) else None
            if (
                not isinstance(call, dict)
                or call.get("type") != "function"
                or not isinstance(call_id, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", call_id)
                or call_id in seen
                or name not in allowed
                or not isinstance(raw_args, str)
                or len(raw_args.encode()) > 32768
            ):
                raise UncertainExecution("provider_protocol", "OpenRouter tool call is malformed")
            seen.add(call_id)
            try:
                arguments = json.loads(
                    raw_args,
                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
                )
            except (json.JSONDecodeError, ValueError):
                raise UncertainExecution(
                    "provider_protocol", "OpenRouter tool arguments are malformed"
                ) from None
            if not isinstance(arguments, dict):
                raise UncertainExecution(
                    "provider_protocol", "OpenRouter tool arguments must be an object"
                )
            validated.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }
            )
        return validated

    @staticmethod
    def _serialize_tool_result(result, max_bytes):
        value = result.structuredContent
        if value is None:
            value = [
                {"type": getattr(item, "type", "text"), "text": getattr(item, "text", "")}
                for item in result.content
            ]
        try:
            content = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError, RecursionError):
            raise BridgeError(
                "provider_tool_result", "MCP tool result is not serializable"
            ) from None
        if len(content.encode()) > max_bytes:
            raise BridgeError("provider_tool_result", "MCP tool result exceeds its byte limit")
        return content

    @staticmethod
    def _parse_completion(raw):
        try:
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("completion must be an object")
            choices = result.get("choices")
            choice = choices[0] if isinstance(choices, list) and choices else None
            message = choice.get("message") if isinstance(choice, dict) else None
            finish = choice.get("finish_reason") if isinstance(choice, dict) else None
            if (
                not isinstance(message, dict)
                or finish not in {"stop", "tool_calls", "length"}
                or (
                    message.get("content") is not None
                    and not isinstance(message.get("content"), str)
                )
            ):
                raise ValueError("completion missing")
            return result, choice, message
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError, IndexError):
            raise UncertainExecution(
                "provider_protocol", "OpenRouter completion could not be confirmed"
            ) from None

    @staticmethod
    def _reported_cost(usage):
        if "cost" not in usage:
            return None
        try:
            value = Decimal(str(usage["cost"]))
            return str(value) if value.is_finite() and value >= 0 else None
        except (InvalidOperation, TypeError, ValueError):
            return None

    @staticmethod
    def _token_count(value):
        return value if type(value) is int and value >= 0 else None

    @staticmethod
    def _bounded_string(value, limit):
        return value[:limit] if isinstance(value, str) else None

    async def _post_chat(self, client, body, config):
        key = _credential(config)
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        del key
        try:
            async with client.stream(
                "POST", OPENROUTER_CHAT_API, headers=headers, json=body
            ) as response:
                if response.status_code != 200:
                    status = response.status_code
                    error = (
                        UncertainExecution(
                            "provider_unknown", "OpenRouter request outcome is unknown"
                        )
                        if status >= 500 or status == 408
                        else BridgeError("provider_rejected", "OpenRouter rejected the request")
                    )
                    error.provider_error = {
                        "provider": "openrouter",
                        "source": "provider_http_status",
                        "http_status": status,
                        "category": {
                            401: "authentication",
                            403: "authentication",
                            402: "payment",
                            429: "rate_limit",
                        }.get(status, "provider"),
                    }
                    raise error
                return await _bounded_body(response, _MAX_RESPONSE_BYTES)
        finally:
            headers.clear()
