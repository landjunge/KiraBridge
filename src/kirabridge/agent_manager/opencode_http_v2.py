"""OpenCode V2 HTTP adapter for the installed shared 2.2.7 app ``/api`` surface.

V2 assistant messages carry no ``parentID``/``sessionID``, so this adapter binds
its own admitted prompt (a stable client-assigned ``msg_`` id plus metadata) and
correlates the reply causally through the ordered message timeline and idle
boundary. Foreign interleaved inputs and any ambiguity fail closed as UNKNOWN.
The legacy V1 ``OpenCodeHTTPAdapter`` stays separate; there is no protocol or
POST fallback after an unclear start.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from kirabridge.agent_manager.cli_support import BoundedText, bind_session
from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.filesystem_manager import PathScope

# A final failed finish reason. "tool-calls" is an intermediate step, not a
# terminal failure: a multi-step turn keeps going until a non-tool finish.
_FAILED_FINISH = {"length", "content-filter", "error", "unknown"}
_FINISH_CATEGORY = {
    "length": "length",
    "content-filter": "content_filter",
    "error": "error",
    "unknown": "unknown",
    "tool-calls": "tool_calls",
}
_SESSION = re.compile(r"^ses_")
_MESSAGE = re.compile(r"^msg_")
# Bounded window for the reply search: the admitted prompt is the newest user
# message, so reading the newest pages first finds it without walking the whole
# history. Exceeding the window fails closed instead of silently timing out.
_MESSAGE_PAGES_MAX = 4
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


def _assistant_done(message: dict[str, Any]) -> bool:
    """A turn ends only on a final finish reason; ``time.completed`` alone or an
    intermediate ``tool-calls`` step is never promoted to completion."""
    finish = message.get("finish")
    return finish is not None and finish != "tool-calls"


def _assistant_text(message: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    for item in message.get("content", []):
        if (
            isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        ):
            parts.append(item["text"])
    return parts


class OpenCodeHTTPV2Adapter:
    """OpenCode V2 ``/api`` turn: one task per session, causal reply correlation."""

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
        if status == 409:
            raise UncertainExecution("session_busy", "OpenCode session is already running a turn")
        if status >= 500:
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

    async def _session(self, client: httpx.AsyncClient, session: str) -> dict[str, Any]:
        response = await self._request(client, "GET", f"/api/session/{session}")
        value = await self._json(response, "session")
        data = value.get("data") if isinstance(value, dict) else None
        if not isinstance(data, dict):
            raise UncertainExecution("provider_protocol", "OpenCode session data is not an object")
        return data

    async def _create(
        self,
        client: httpx.AsyncClient,
        session_id: str,
        directory: str,
        model: dict[str, str],
        task: dict,
    ) -> dict[str, Any]:
        response = await self._request(
            client,
            "POST",
            "/api/session",
            body={
                "id": session_id,
                "title": "KiraBridge " + str(task["id"]),
                "model": {"id": model["modelID"], "providerID": model["providerID"]},
                "location": {"directory": directory},
                "metadata": {"kirabridge_task_id": str(task["id"])},
            },
        )
        value = await self._json(response, "session")
        data = value.get("data") if isinstance(value, dict) else None
        if not isinstance(data, dict):
            raise UncertainExecution("provider_protocol", "OpenCode session data is not an object")
        return data

    async def _prompt(
        self, client: httpx.AsyncClient, session: str, message_id: str, prompt: str
    ) -> dict[str, Any]:
        response = await self._request(
            client,
            "POST",
            f"/api/session/{session}/prompt",
            body={
                "id": message_id,
                "text": prompt,
                "metadata": {"kirabridge_message_id": message_id},
            },
        )
        value = await self._json(response, "prompt")
        data = value.get("data") if isinstance(value, dict) else None
        if not isinstance(data, dict):
            raise UncertainExecution("provider_protocol", "OpenCode prompt data is not an object")
        return data

    async def _messages(self, client: httpx.AsyncClient, session: str) -> list[dict[str, Any]]:
        """Return the recent message window in ascending order, bounded and fail-closed.

        Reads newest-first so the just-admitted prompt is on the first page; a
        bounded page ceiling that does not reach the end of history fails closed
        instead of silently returning a truncated list and timing out.
        """
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(_MESSAGE_PAGES_MAX):
            params: dict[str, Any] = {"order": "desc", "limit": "100"}
            if cursor is not None:
                params["cursor"] = cursor
            response = await self._request(
                client, "GET", f"/api/session/{session}/message", params=params
            )
            value = await self._json(response, "message")
            if not isinstance(value, dict):
                raise UncertainExecution("provider_protocol", "OpenCode messages are not an object")
            data = value.get("data")
            if not isinstance(data, list):
                raise UncertainExecution("provider_protocol", "OpenCode message data is not a list")
            items.extend(item for item in data if isinstance(item, dict))
            next_cursor = (value.get("cursor") or {}).get("next")
            if not next_cursor:
                break
            cursor = next_cursor
        else:
            raise UncertainExecution(
                "agent_unconfirmed",
                "OpenCode message history exceeded the bounded read window",
            )
        items.reverse()
        return items

    @staticmethod
    def _reply_after(
        messages: list[dict[str, Any]], admitted_id: str
    ) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
        """Locate this turn's terminal state after our admitted user message.

        Returns ``(state, assistant, idle)`` where state is ``foreign`` (a real
        user input interleaved), ``idle`` (the idle boundary, with the last
        assistant before it), ``assistant`` (still streaming; the last assistant
        so far) or ``pending`` (our user message not yet projected).
        """
        seen = False
        assistant: dict[str, Any] | None = None
        idle: dict[str, Any] | None = None
        for message in messages:
            typ = message.get("type")
            if not seen:
                if message.get("id") == admitted_id:
                    seen = True
                continue
            if typ == "user":
                return "foreign", None, None
            if typ == "assistant":
                assistant = message
            elif typ == "idle":
                idle = message
        if idle is not None:
            return "idle", assistant, idle
        if assistant is not None:
            return "assistant", assistant, None
        return "pending", None, None

    async def execute(
        self, task, args, config, roots, running, progress, *, resume_session=None, **extra
    ) -> dict:
        if not config.server_url:
            raise BridgeError("agent_config", "OpenCode HTTP requires a configured server URL")
        model = _model(config)
        auth = _credentials(config)
        PathScope(roots).split(args.cwd)
        directory = str(Path(args.cwd).absolute())

        started = False
        session: str | None = None
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
                if not isinstance(resume_session, str) or not _SESSION.match(resume_session):
                    raise BridgeError(
                        "agent_identity", "An exact OpenCode V2 session id is required"
                    )
                session = bind_session(None, resume_session)
                info = await self._session(client, session)
                if (info.get("location") or {}).get("directory") != directory:
                    raise UncertainExecution(
                        "session_unknown", "OpenCode session location no longer matches the task"
                    )
                await progress(
                    {"agent": args.agent, "session_id": session, "event": "session_resumed"}
                )
            else:
                session_id = "ses_" + uuid4().hex
                created = await self._create(client, session_id, directory, model, task)
                returned_id = created.get("id")
                if not isinstance(returned_id, str) or not _SESSION.match(returned_id):
                    raise UncertainExecution(
                        "agent_identity", "OpenCode returned an invalid session id"
                    )
                if returned_id != session_id:
                    raise UncertainExecution("agent_identity", "OpenCode changed the session id")
                session = returned_id
                # Emitted before the prompt: the caller's durable recovery marker
                # for this exact session, never a second independent data trace.
                await progress(
                    {"agent": args.agent, "session_id": session, "event": "session_created"}
                )

            message_id = "msg_" + uuid4().hex
            admitted = await self._prompt(client, session, message_id, args.prompt)
            admitted_id = admitted.get("id")
            if not isinstance(admitted_id, str) or not _MESSAGE.match(admitted_id):
                raise UncertainExecution("agent_protocol", "OpenCode prompt returned no message id")
            if admitted_id != message_id:
                raise UncertainExecution(
                    "agent_identity", "OpenCode changed the admitted message id"
                )
            await progress({"agent": args.agent, "session_id": session, "event": "prompt_admitted"})

            deadline = time.monotonic() + args.timeout
            assistant: dict[str, Any] | None = None
            idle: dict[str, Any] | None = None
            while True:
                messages = await self._messages(client, session)
                state, assistant, idle = self._reply_after(messages, message_id)
                if state == "foreign":
                    raise UncertainExecution(
                        "agent_unconfirmed",
                        "A foreign input interleaved before this turn's reply",
                    )
                if assistant is not None and not started:
                    started = True
                    await running(
                        {"agent": args.agent, "session_id": session, "event": "session_busy"}
                    )
                if state == "assistant":
                    if _assistant_done(assistant):
                        break
                elif state == "idle":
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise UncertainExecution(
                        "agent_timeout", "OpenCode turn could not be confirmed in time"
                    )
                await asyncio.sleep(min(self._poll_interval, remaining))

        if assistant is None:
            if idle is not None and idle.get("outcome") in {"failed", "interrupted"}:
                raise UncertainExecution("agent_unconfirmed", "OpenCode turn did not complete")
            raise UncertainExecution("agent_unconfirmed", "No OpenCode assistant reply observed")
        if not _assistant_done(assistant):
            raise UncertainExecution("agent_unconfirmed", "No OpenCode turn completion evidence")

        finish = assistant.get("finish")
        failed = assistant.get("error") is not None or (
            isinstance(finish, str) and finish in _FAILED_FINISH
        )
        for part in _assistant_text(assistant):
            text.append(part)
        if not failed and finish != "stop":
            raise UncertainExecution(
                "agent_unconfirmed", "No OpenCode final turn completion evidence"
            )
        if not failed and not text.text.strip():
            raise UncertainExecution(
                "agent_unconfirmed", "No OpenCode final response text observed"
            )
        provider_error = None
        if failed:
            category = _error_category(assistant.get("error"))
            if category is None and isinstance(finish, str):
                category = _FINISH_CATEGORY.get(finish, "provider")
            provider_error = {
                "provider": "opencode",
                "source": "assistant_message",
                "category": category,
            }
        return {
            "success": not failed,
            "text": text.text,
            "final_message": text.text,
            "evidence": {
                "agent": args.agent,
                "adapter": "opencode_http_v2",
                "session_id": session,
                "session_resumed": resume_session is not None,
                "session_directory": directory,
                "model": config.model,
                "observed_model": assistant.get("model"),
                "observed_agent": assistant.get("agent"),
                "message_id": assistant.get("id"),
                "finish_reason": finish if isinstance(finish, str) else None,
                "turn_failed": failed,
                "provider_error": provider_error,
                "output_truncated": text.truncated,
                "local_tools_enabled": bool(args.local_tools),
                "server_authenticated": True,
                "cost": assistant.get("cost"),
                "tokens": assistant.get("tokens"),
                "execution_workspace": "opencode_server_session",
                "requested_cwd_validated": True,
            },
            "scope": "agent_turn",
            "project_completion_verified": False,
        }
