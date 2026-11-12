"""OpenCode HTTP API adapter: a protected loopback server, one task per session."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

import httpx

from kirabridge.agent_manager.cli_support import BoundedText, bind_session
from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.filesystem_manager import PathScope

_FAILED_FINISH = {"length", "content-filter", "tool-calls", "error"}
_FAILED_STATUS = {408}
_ERROR_CATEGORIES = {
    "ProviderAuthError": "authentication",
    "APIError": "provider",
    "MessageOutputLengthError": "length",
    "MessageAbortedError": "aborted",
    "ContextOverflowError": "context_overflow",
    "StructuredOutputError": "structured_output",
    "UnknownError": "unknown",
}


def _model(config) -> dict[str, str]:
    provider, separator, model = (config.model or "").partition("/")
    if not separator or not provider or not model:
        raise BridgeError("agent_config", "OpenCode HTTP requires an explicit provider/model")
    return {"providerID": provider, "modelID": model}


def _credentials(config) -> httpx.BasicAuth:
    if not config.server_username_env or not config.server_password_env:
        raise BridgeError("agent_config", "OpenCode HTTP requires credential environment names")
    username = os.environ.get(config.server_username_env)
    password = os.environ.get(config.server_password_env)
    if not username or not password:
        raise BridgeError(
            "agent_config",
            "OpenCode HTTP credentials are not available in the configured environment",
        )
    return httpx.BasicAuth(username, password)


def _error_category(error: Any) -> str | None:
    if not isinstance(error, dict):
        return None
    name = error.get("name")
    return _ERROR_CATEGORIES.get(name, "provider") if isinstance(name, str) else "provider"


def _completed(message: dict[str, Any]) -> bool:
    time = message.get("time")
    if not isinstance(time, dict):
        return False
    return isinstance(time.get("completed"), (int, float))


class OpenCodeHTTPAdapter:
    """Task handoff, session binding and live status through a loopback HTTP API."""

    interface_version = "1"

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        poll_interval: float = 1.0,
    ):
        if not isinstance(poll_interval, (int, float)) or poll_interval <= 0:
            raise ValueError("invalid poll interval")
        self._transport = transport
        self._poll_interval = float(poll_interval)

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            response = await client.request(method, path, params=params, json=body)
        except httpx.TimeoutException:
            raise UncertainExecution(
                "agent_timeout", "OpenCode server response timed out"
            ) from None
        except httpx.HTTPError:
            raise UncertainExecution(
                "server_disconnected", "OpenCode server cannot be reached"
            ) from None
        status = response.status_code
        if status in {401, 403}:
            raise BridgeError("agent_auth", "OpenCode server rejected the configured credentials")
        if status == 404:
            raise UncertainExecution("session_unknown", "OpenCode session is no longer available")
        if status in _FAILED_STATUS or status >= 500:
            # Status only: response bodies can contain provider or authorization details.
            raise UncertainExecution(
                "server_unknown", f"OpenCode server outcome is unknown (HTTP {status})"
            )
        if status >= 400:
            raise BridgeError(
                "agent_rejected", f"OpenCode server rejected the request (HTTP {status})"
            )
        return response

    @staticmethod
    async def _json(response: httpx.Response, label: str) -> Any:
        try:
            return response.json()
        except ValueError:
            raise UncertainExecution(
                "provider_protocol", f"OpenCode server returned invalid {label} JSON"
            ) from None

    async def _status(
        self, client: httpx.AsyncClient, session: str, directory: str
    ) -> dict[str, Any]:
        response = await self._request(
            client, "GET", "/session/status", params={"directory": directory}
        )
        value = await self._json(response, "status")
        if not isinstance(value, dict):
            raise UncertainExecution("provider_protocol", "OpenCode status is not an object")
        status = value.get(session)
        return status if isinstance(status, dict) else {"type": "idle"}

    async def _messages(
        self, client: httpx.AsyncClient, session: str, directory: str
    ) -> list[dict[str, Any]]:
        response = await self._request(
            client,
            "GET",
            f"/session/{session}/message",
            params={"directory": directory, "limit": 20},
        )
        value = await self._json(response, "message")
        if not isinstance(value, list):
            raise UncertainExecution("provider_protocol", "OpenCode messages are not a list")
        return [item for item in value if isinstance(item, dict)]

    @staticmethod
    def _last_assistant(
        messages: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        for item in reversed(messages):
            info = item.get("info")
            if isinstance(info, dict) and info.get("role") == "assistant":
                parts = item.get("parts")
                return info, [part for part in parts or [] if isinstance(part, dict)]
        return None, []

    async def execute(
        self, task, args, config, roots, running, progress, *, resume_session=None, **extra
    ) -> dict:
        if not config.server_url:
            raise BridgeError("agent_config", "OpenCode HTTP requires a configured server URL")
        model = _model(config)
        auth = _credentials(config)
        PathScope(roots).split(args.cwd)
        directory = str(Path(args.cwd).absolute())

        statuses: list[str] = []
        started = False
        session = None
        text = BoundedText()
        timeout = httpx.Timeout(args.timeout, connect=min(5.0, args.timeout))
        async with httpx.AsyncClient(
            base_url=config.server_url.rstrip("/"),
            auth=auth,
            timeout=timeout,
            trust_env=False,
            follow_redirects=False,
            transport=self._transport,
        ) as client:
            if resume_session is not None:
                session = bind_session(session, resume_session)
                # Verify the exact session still exists in this directory before
                # any prompt is admitted; a 404 is unknown, never a silent retry.
                await self._request(
                    client,
                    "GET",
                    f"/session/{session}",
                    params={"directory": directory},
                )
                await progress(
                    {"agent": args.agent, "session_id": session, "event": "session_resumed"}
                )
            else:
                response = await self._request(
                    client,
                    "POST",
                    "/session",
                    params={"directory": directory},
                    body={
                        "title": "KiraBridge " + str(task["id"]),
                        "model": {
                            "providerID": model["providerID"],
                            "id": model["modelID"],
                        },
                        "metadata": {"kirabridge_task_id": str(task["id"])},
                        "permission": [
                            {
                                "permission": "*",
                                "pattern": "*",
                                "action": "allow" if args.local_tools else "deny",
                            }
                        ],
                    },
                )
                created = await self._json(response, "session")
                if not isinstance(created, dict):
                    raise UncertainExecution(
                        "provider_protocol", "OpenCode session is not an object"
                    )
                session = bind_session(session, created.get("id"))
                await progress(
                    {"agent": args.agent, "session_id": session, "event": "session_created"}
                )

            # Snapshot the newest assistant message before admitting the prompt, so
            # a completed idle baseline from a previous turn can never be mistaken
            # for this turn's new response. A genuine new turn must then differ in
            # id and parentID and still belong to the exact bound session.
            prior, _ = self._last_assistant(await self._messages(client, session, directory))
            prior_id = prior.get("id") if prior is not None else None
            prior_parent = prior.get("parentID") if prior is not None else None

            await self._request(
                client,
                "POST",
                f"/session/{session}/prompt_async",
                params={"directory": directory},
                body={
                    "model": model,
                    "parts": [{"type": "text", "text": args.prompt}],
                },
            )
            await progress({"agent": args.agent, "session_id": session, "event": "prompt_admitted"})

            deadline = time.monotonic() + args.timeout
            while True:
                status = await self._status(client, session, directory)
                kind = status.get("type")
                kind = kind if kind in {"idle", "busy", "retry"} else "unknown"
                if not statuses or statuses[-1] != kind:
                    statuses.append(kind)
                    event = {"agent": args.agent, "session_id": session, "event": "session_status"}
                    event["status"] = kind
                    if kind == "retry" and isinstance(status.get("attempt"), int):
                        event["attempt"] = status["attempt"]
                    await progress(event)
                if kind in {"busy", "retry"}:
                    if not started:
                        started = True
                        await running(
                            {"agent": args.agent, "session_id": session, "event": "session_busy"}
                        )
                elif kind == "idle" and started:
                    break
                elif kind == "idle":
                    message, _ = self._last_assistant(
                        await self._messages(client, session, directory)
                    )
                    if (
                        message is not None
                        and _completed(message)
                        and message.get("sessionID") == session
                        and message.get("id") != prior_id
                        and message.get("parentID") != prior_parent
                    ):
                        break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise UncertainExecution(
                        "agent_timeout", "OpenCode turn could not be confirmed in time"
                    )
                await asyncio.sleep(min(self._poll_interval, remaining))

            message, parts = self._last_assistant(await self._messages(client, session, directory))
            if (
                message is None
                or message.get("sessionID") != session
                or message.get("id") == prior_id
                or message.get("parentID") == prior_parent
            ):
                # Only a new assistant message for the bound session proves this
                # turn; a foreign or unchanged message is not this turn's result.
                raise UncertainExecution(
                    "agent_unconfirmed", "No new OpenCode turn response observed"
                )

        if message is None:
            raise UncertainExecution("agent_unconfirmed", "No OpenCode final response observed")
        if not _completed(message):
            raise UncertainExecution("agent_unconfirmed", "No OpenCode turn completion evidence")
        failed = message.get("error") is not None
        provider_error = None
        if failed:
            category = _error_category(message.get("error"))
            provider_error = {
                "provider": "opencode",
                "source": "assistant_message",
                "category": category,
            }
        finish = message.get("finish")
        if isinstance(finish, str) and finish in _FAILED_FINISH:
            failed = True
        for part in parts:
            if part.get("type") != "text" or part.get("synthetic") or part.get("ignored"):
                continue
            if isinstance(part.get("text"), str):
                text.append(part["text"])
        if not failed and finish != "stop":
            raise UncertainExecution(
                "agent_unconfirmed", "No OpenCode final turn completion evidence"
            )
        if not failed and not text.text.strip():
            raise UncertainExecution(
                "agent_unconfirmed", "No OpenCode final response text observed"
            )
        return {
            "success": not failed,
            "text": text.text,
            "final_message": text.text,
            "evidence": {
                "agent": args.agent,
                "adapter": "opencode_http",
                "session_id": session,
                "session_resumed": resume_session is not None,
                "session_directory": directory,
                "model": config.model,
                "status_events": statuses,
                "message_id": message.get("id"),
                "finish_reason": finish if isinstance(finish, str) else None,
                "turn_failed": failed,
                "provider_error": provider_error,
                "output_truncated": text.truncated,
                "local_tools_enabled": bool(args.local_tools),
                "server_authenticated": True,
                "cost": message.get("cost"),
                "tokens": message.get("tokens"),
                "execution_workspace": "opencode_server_session",
                "requested_cwd_validated": True,
            },
            "scope": "agent_turn",
            "project_completion_verified": False,
        }
