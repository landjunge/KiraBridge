"""OpenRouter's OpenAI-compatible text API with a closed free-model route."""

from __future__ import annotations

import json
import os
from decimal import Decimal, InvalidOperation

import httpx

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.openrouter_models import (
    OPENROUTER_CHAT_API,
    OPENROUTER_FREE_MODELS,
    OPENROUTER_MODELS_API,
    OPENROUTER_PAID_MODELS,
)

_MAX_RESPONSE_BYTES = 1048576
_MAX_CATALOG_BYTES = 4194304
_FREE_RATE = Decimal("0")


def _credential(config) -> str:
    if config.openrouter_credential_source == "environment":
        key = os.environ.get(config.api_key_env)
        if key:
            return key
        raise BridgeError("agent_auth", "OpenRouter credential is unavailable")
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
    """Single bounded text request; no retries, local tools, or secret evidence."""

    interface_version = "1"

    async def execute(self, task, args, config, roots, running, progress) -> dict:
        if args.local_tools or args.mcp_grants or args.mcp_operations or args.mcp_read_roots:
            raise BridgeError("agent_tools_denied", "OpenRouter text mode does not execute tools")
        model = config.model
        fallbacks = list(config.openrouter_fallback_models)
        models = [model, *fallbacks]
        if len(set(models)) != len(models):
            raise BridgeError("agent_config", "OpenRouter model routes must be unique")
        if any(item not in OPENROUTER_FREE_MODELS for item in fallbacks):
            raise BridgeError("agent_config", "OpenRouter fallbacks must be verified free models")

        is_free = model in OPENROUTER_FREE_MODELS
        if not is_free and model not in OPENROUTER_PAID_MODELS:
            raise BridgeError(
                "provider_paid_disabled", "OpenRouter model is not explicitly enabled"
            )
        output_limit = config.openrouter_max_output_tokens
        input_limit = config.openrouter_max_prompt_bytes
        price_bound = None
        if not is_free:
            if not config.openrouter_allow_paid:
                raise BridgeError("provider_paid_disabled", "Paid OpenRouter models are disabled")
            if any(item not in OPENROUTER_FREE_MODELS for item in fallbacks):
                raise BridgeError("agent_config", "Paid model fallback routes are not enabled")
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
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
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
                    worst_cost = (
                        Decimal(prompt_bytes + 64) * input_rate
                        + Decimal(output_limit) * output_rate
                    )
                    if worst_cost > config.openrouter_paid_max_cost_usd:
                        raise BridgeError(
                            "provider_paid_budget", "OpenRouter request exceeds its cost limit"
                        )
                    price_bound = str(worst_cost)

                key = _credential(config)
                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                del key
                body = {
                    "models": models,
                    "messages": [{"role": "user", "content": args.prompt}],
                    "max_tokens": output_limit,
                    "stream": False,
                }
                if not is_free:
                    body["provider"] = {"allow_fallbacks": False, "sort": "price"}
                try:
                    await running(
                        {
                            "agent": args.agent,
                            "adapter": "openrouter_api",
                            "model": model,
                            "event": "provider_request_sent",
                            "provider_request_count": 1,
                        }
                    )
                    async with client.stream(
                        "POST",
                        OPENROUTER_CHAT_API,
                        headers=headers,
                        json=body,
                    ) as response:
                        if response.status_code != 200:
                            status = response.status_code
                            error = (
                                UncertainExecution(
                                    "provider_unknown", "OpenRouter request outcome is unknown"
                                )
                                if status >= 500 or status == 408
                                else BridgeError(
                                    "provider_rejected", "OpenRouter rejected the request"
                                )
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
                        raw = await _bounded_body(response, _MAX_RESPONSE_BYTES)
                finally:
                    headers.clear()
        except (httpx.HTTPError, OSError):
            raise UncertainExecution(
                "provider_disconnected", "OpenRouter response cannot be confirmed"
            ) from None

        try:
            result = json.loads(raw)
            choices = result.get("choices")
            choice = choices[0] if isinstance(choices, list) and choices else None
            message = choice.get("message") if isinstance(choice, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            finish = choice.get("finish_reason") if isinstance(choice, dict) else None
            if not isinstance(content, str) or not isinstance(finish, str):
                raise ValueError("completion missing")
            if len(content.encode("utf-8")) > 65536 or len(finish) > 64:
                raise ValueError("completion exceeded its limit")
            if message.get("tool_calls"):
                raise ValueError("unexpected tool call")
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError, IndexError):
            raise UncertainExecution(
                "provider_protocol", "OpenRouter completion could not be confirmed"
            ) from None

        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        selected = result.get("model")
        request_id = result.get("id")
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        actual_cost = None
        if "cost" in usage:
            try:
                parsed_cost = Decimal(str(usage["cost"]))
                if parsed_cost.is_finite() and parsed_cost >= 0:
                    actual_cost = str(parsed_cost)
            except (InvalidOperation, TypeError, ValueError):
                pass
        evidence = {
            "agent": args.agent,
            "adapter": "openrouter_api",
            "requested_models": models,
            "selected_model": selected[:256] if isinstance(selected, str) else None,
            "request_id": request_id[:256] if isinstance(request_id, str) else None,
            "finish_reason": finish,
            "provider_request_count": 1,
            "prompt_tokens": prompt_tokens
            if type(prompt_tokens) is int and prompt_tokens >= 0
            else None,
            "completion_tokens": completion_tokens
            if type(completion_tokens) is int and completion_tokens >= 0
            else None,
            "paid_cost_upper_bound_usd": price_bound,
            "reported_cost_usd": actual_cost,
            "tools_enabled": False,
        }
        return {
            "success": finish == "stop",
            "text": content,
            "evidence": evidence,
            "scope": "model_turn",
            "project_completion_verified": False,
        }
