"""Reusable Agent Client Protocol (ACP) v1 client over a single stdio subprocess.

One client owns exactly one process and one JSON-RPC request stream. Requests are
matched strictly by the id this client assigned; an unknown response id is a protocol
failure, never a replay trigger. Session-scoped updates are accepted only for the
single negotiated session id. Content is bounded and identical deliveries are deduped
only by the protocol's own ``messageId``/``chunkIndex`` identity; identity-less updates
are never speculatively dropped. Timeout and disconnect surface as bounded failures
without automatic retry.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

from kirabridge.agent_manager.cli_support import BoundedText, bind_session
from kirabridge.bridge_core.models import UncertainExecution

_MESSAGE_KINDS = {"agent_message_chunk", "agent_thought_chunk", "tool_call"}


class ACPClient:
    """ACP v1 stdio client bound to one process and, after negotiation, one session."""

    def __init__(
        self,
        process,
        *,
        max_message_bytes: int = 1048576,
        max_text_bytes: int = 65536,
    ):
        self.process = process
        self.max_message_bytes = max_message_bytes
        self._counter = 0
        self._session_id: str | None = None
        self._text = BoundedText(max_text_bytes)
        self._seen_chunks: set[tuple[str, int]] = set()
        self._started = False
        self._failure: UncertainExecution | None = None
        self._response_events: dict[int, tuple[asyncio.Future, str]] = {}
        self._reader: asyncio.Task | None = None
        # Optional collaboration hooks, wired by the owning adapter.
        self.on_activity: Callable[[str], Awaitable[None]] | None = None
        self.on_request: Callable[[str, dict], Awaitable[dict | None]] | None = None

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        if self._reader is None:
            self._reader = asyncio.create_task(self._read_loop())

    async def aclose(self) -> None:
        if self._reader is None:
            return
        if not self._reader.done():
            self._reader.cancel()
        try:
            await self._reader
        except (asyncio.CancelledError, Exception):  # noqa: B014 - reader owns its errors
            pass
        self._reader = None

    # -- session binding -----------------------------------------------------

    def bind_session(self, identifier: str) -> str:
        self._session_id = bind_session(self._session_id, identifier)
        return self._session_id

    def reset_text(self) -> None:
        """Drop replayed history after session/load so only the new turn is kept.

        Keep the one-time activity/running flag: a replayed thought chunk has
        already marked the task running, and a second running transition would
        be rejected by the task store.
        """
        self._text = BoundedText(self._text.max_bytes)

    def begin_turn(self) -> None:
        """Start a new Core turn after verified history replay; replay is not execution."""
        self._text = BoundedText(self._text.max_bytes)
        self._seen_chunks.clear()
        self._started = False

    # -- transport -----------------------------------------------------------

    async def send(self, message: dict) -> None:
        payload = (json.dumps(message) + "\n").encode("utf-8")
        if len(payload) > self.max_message_bytes:
            raise UncertainExecution("provider_protocol", "ACP message exceeds byte limit")
        self.process.stdin.write(payload)
        await self.process.stdin.drain()

    async def request(self, method: str, params: dict, timeout: float) -> dict:
        if self._failure is not None:
            raise self._failure
        self._counter += 1
        identifier = self._counter
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._response_events[identifier] = (future, method)
        await self.send({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params})
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            raise UncertainExecution("agent_interrupted", "ACP request timed out") from None
        except UncertainExecution as exc:
            if getattr(exc, "provider_error", None) is None:
                exc.provider_error = {"adapter": "acp", "reason": str(exc)[:160]}
            raise
        finally:
            self._response_events.pop(identifier, None)

    async def cancel(self) -> None:
        """Best-effort ``session/cancel``; never blocks past a short bound."""
        if self._session_id is None or self._failure is not None:
            return
        try:
            async with asyncio.timeout(1):
                await self.send(
                    {
                        "jsonrpc": "2.0",
                        "method": "session/cancel",
                        "params": {"sessionId": self._session_id},
                    }
                )
        except Exception:
            pass

    # -- reader loop ---------------------------------------------------------

    async def _read_loop(self) -> None:
        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    break
                await self._dispatch(line)
        except asyncio.CancelledError:
            raise
        except UncertainExecution as exc:
            self._fail_pending(exc)
        except Exception as exc:  # noqa: BLE001 - boundary only, no secrets retained
            self._fail_pending(UncertainExecution("agent_protocol", str(exc)[:512]))
        finally:
            self._fail_pending(UncertainExecution("agent_disconnected", "ACP server disconnected"))

    async def _dispatch(self, line: bytes) -> None:
        if len(line) > self.max_message_bytes:
            raise UncertainExecution("provider_protocol", "ACP event exceeds byte limit")
        try:
            message = json.loads(line)
        except ValueError:
            # Some live ACP servers still print a diagnostic line to stdout
            # around session load/prompt. It is not a protocol message and
            # never authorizes a replay; the request keeps its own timeout.
            return
        if not isinstance(message, dict):
            return
        method = message.get("method")
        identifier = message.get("id")
        if isinstance(method, str):
            await self._handle_incoming(method, message.get("params", {}), identifier)
            return
        if identifier is not None:
            await self._handle_response(identifier, message)
            return
        raise UncertainExecution("agent_protocol", "Malformed ACP message")

    async def _handle_incoming(self, method: str, params, identifier) -> None:
        if method == "session/update":
            await self._handle_update(params)
            return
        if identifier is not None:
            if self.on_request is None:
                await self._send_error(identifier, -32601, "Capability not available")
                return
            result = await self.on_request(method, params)
            if result is None:
                await self._send_error(identifier, -32601, "Capability not available")
            else:
                await self.send({"jsonrpc": "2.0", "id": identifier, "result": result})
            return
        # JSON-RPC notifications are advisory. Vendor extensions may arrive
        # before/after a session is bound; they never authorize a replay.
        return

    async def _send_error(self, identifier, code: int, message: str) -> None:
        await self.send(
            {"jsonrpc": "2.0", "id": identifier, "error": {"code": code, "message": message}}
        )

    async def _handle_update(self, params) -> None:
        # History replay around session/load may include advisory shapes that
        # carry no turn text. They are ignored; a bound session mismatch still
        # fails closed so one provider identity can never feed another session.
        if not isinstance(params, dict):
            return
        if self._session_id is None:
            return
        if params.get("sessionId") != self._session_id:
            raise UncertainExecution("agent_identity", "Unexpected ACP session update")
        update = params.get("update", {})
        if not isinstance(update, dict):
            return
        kind = update.get("sessionUpdate")
        if kind in _MESSAGE_KINDS:
            if not self._started:
                self._started = True
                if self.on_activity is not None:
                    await self.on_activity(kind)
        if kind == "agent_message_chunk":
            content = update.get("content", {})
            if isinstance(content, dict) and content.get("type") == "text":
                if self._duplicate(update):
                    return
                self._text.append(content.get("text", ""))

    def _duplicate(self, update: dict) -> bool:
        """Dedupe only by the protocol's own message identity; never guess."""
        message_id = update.get("messageId")
        chunk_index = update.get("chunkIndex")
        if not (isinstance(message_id, str) and isinstance(chunk_index, int)):
            return False
        key = (message_id, chunk_index)
        if key in self._seen_chunks:
            return True
        if len(self._seen_chunks) >= 65536:
            self._seen_chunks.clear()
        self._seen_chunks.add(key)
        return False

    async def _handle_response(self, identifier, message: dict) -> None:
        entry = self._response_events.pop(identifier, None)
        if entry is None or entry[0].done():
            raise UncertainExecution("agent_identity", "Unexpected ACP response id")
        future, method = entry
        if "error" in message:
            error = UncertainExecution("agent_rpc", "ACP server returned an error")
            code = message["error"].get("code") if isinstance(message["error"], dict) else None
            error.provider_error = {
                "adapter": "acp",
                "rpc_method": method,
                "rpc_code": code if type(code) is int else None,
            }
            future.set_exception(error)
            return
        result = message.get("result", {})
        # Bind the session atomically when its own response is processed, so an
        # immediately following session/update in the same read buffer is validated
        # against the correct session even before the caller runs bind_session().
        if method == "session/new":
            session_id = result.get("sessionId") if isinstance(result, dict) else None
            try:
                self._session_id = bind_session(self._session_id, session_id)
            except UncertainExecution as exc:
                future.set_exception(exc)
                raise
        future.set_result(result)

    def _fail_pending(self, exc: UncertainExecution) -> None:
        if self._failure is None:
            self._failure = exc
        if getattr(exc, "provider_error", None) is None:
            # Controlled adapter message only, never raw provider output.
            exc.provider_error = {"adapter": "acp", "reason": str(exc)[:160]}
        while self._response_events:
            _, entry = self._response_events.popitem()
            future = entry[0]
            if not future.done():
                future.set_exception(exc)

    # -- observation ---------------------------------------------------------

    @property
    def text(self) -> str:
        return self._text.text

    @property
    def truncated(self) -> bool:
        return self._text.truncated

    @property
    def started(self) -> bool:
        return self._started

    @property
    def session_id(self) -> str | None:
        return self._session_id
