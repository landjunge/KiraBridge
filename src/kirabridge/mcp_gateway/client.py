from __future__ import annotations

import asyncio
import re
import time
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError

from kirabridge.bridge_core.models import BridgeError, digest


class ObservedClientSession(ClientSession):
    def __init__(self, *args, notice, **kwargs):
        self.notice = notice
        super().__init__(*args, **kwargs)

    async def send_request(self, request, *args, **kwargs):
        initializing = isinstance(request.root, types.InitializeRequest)
        if initializing:
            self.notice("initialize.started")
        result = await super().send_request(request, *args, **kwargs)
        if initializing:
            self.notice("initialize.response")
        return result

    async def send_notification(self, notification, *args, **kwargs):
        result = await super().send_notification(notification, *args, **kwargs)
        if isinstance(notification.root, types.InitializedNotification):
            self.notice("initialized.sent", notification_receipt="unknown; queued to SDK stream")
        return result


@dataclass(frozen=True)
class Peer:
    """Trusted, explicitly configured endpoints. stdio programs are local execution authority."""

    id: str
    url: str | None = None
    command: str | None = None
    args: tuple[str, ...] = ()
    token: str | None = field(default=None, repr=False)
    ca_file: str | None = None
    env: dict[str, str] | None = field(default=None, repr=False)
    cwd: str | None = None


class MCPClientPool:
    """One dedicated owner coroutine per connection, preserving anyio cancel-scope ownership."""

    interface_version = "1"

    def __init__(self, max_connections: int = 8, call_timeout: float = 30, observer=None):
        self.max_connections, self.call_timeout = max_connections, call_timeout
        self.owners: dict[str, asyncio.Task] = {}
        self.sessions: dict[str, ClientSession] = {}
        self.stops: dict[str, asyncio.Event] = {}
        self.gate = asyncio.Semaphore(32)
        self.observer = observer
        self.connection_ids: dict[str, str] = {}
        self.previous_ids: dict[str, str] = {}
        self.observation_failures = 0
        self.phases: dict[str, str] = {}
        self.initializations = {}
        self.catalogs = {}
        self.catalog_locks = {}
        self.catalog_dirty = set()
        self.health_epochs = {}
        self._disconnects: dict[asyncio.Task, asyncio.Task] = {}

    def notice(self, peer_id, phase, **metadata):
        connection_id = metadata.get("connection_id", self.connection_ids.get(peer_id))
        if connection_id == self.connection_ids.get(peer_id):
            self.phases[peer_id] = phase
        if self.observer:
            try:
                self.observer(
                    "connection",
                    {
                        "connection_id": self.connection_ids.get(peer_id),
                        "phase": phase,
                        "peer_ref": digest(peer_id),
                        "observer": "own_mcp_client",
                        "external_tunnel": "unknown",
                        **metadata,
                    },
                    task_id=metadata.get("task_id"),
                )
            except Exception:
                self.observation_failures += 1

    def failure(self, peer_id, code, message, *, task_id=None, operation="mcp.connect"):
        exc = BridgeError(code, message)
        exc.diagnostic = {
            "schema": "1",
            "diagnostic_id": uuid.uuid4().hex,
            "task_id": task_id,
            "at": time.time(),
            "operation": operation
            if re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", operation)
            else "unknown",
            "error_code": code,
            "connection_id": self.connection_ids.get(peer_id),
            "phase": self.phases.get(peer_id, "unknown"),
            "accepted": "unknown",
            "started": "unknown",
            "completed": "unknown",
            "execution_runtime": "unknown",
            "observer_runtime": getattr(self.observer, "runtime", "unknown"),
            "external_tunnel_lifecycle": "unknown",
            "automatic_retry": False,
            "guidance": "Reinitialize/reconnect only the connection; read the original task ID. "
            "Never blindly repeat a write with an uncertain outcome.",
        }
        return exc

    async def connect(self, peer: Peer) -> None:
        if peer.id in self.owners or len(self.owners) >= self.max_connections:
            raise BridgeError(
                "connection_limit", "Duplicate peer identity or connection capacity reached"
            )
        if bool(peer.url) == bool(peer.command):
            raise BridgeError("peer_config", "Configure exactly one transport per peer")
        if peer.url:
            parsed = urlparse(peer.url)
            local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            if parsed.username or parsed.password or parsed.fragment or parsed.query:
                raise BridgeError(
                    "peer_config", "Credentials and parameters must not be in endpoint URLs"
                )
            if parsed.scheme != "https" and not (local and parsed.scheme == "http"):
                raise BridgeError("insecure_peer", "Remote MCP peers require HTTPS")
        ready = asyncio.get_running_loop().create_future()
        stop = asyncio.Event()
        self.stops[peer.id] = stop
        self.connection_ids[peer.id] = uuid.uuid4().hex
        self.notice(
            peer.id,
            "connect.started",
            transport="http" if peer.url else "stdio",
            previous_connection_id=self.previous_ids.get(peer.id),
        )

        async def owner():
            try:
                async with AsyncExitStack() as stack:
                    if peer.url:
                        import ssl

                        client = await stack.enter_async_context(
                            httpx.AsyncClient(
                                headers={"Authorization": f"Bearer {peer.token}"}
                                if peer.token
                                else {},
                                timeout=httpx.Timeout(self.call_timeout, read=300),
                                trust_env=False,
                                follow_redirects=False,
                                verify=ssl.create_default_context(cafile=peer.ca_file)
                                if peer.ca_file
                                else True,
                            )
                        )
                        read, write, _ = await stack.enter_async_context(
                            streamable_http_client(peer.url, http_client=client)
                        )
                    else:
                        read, write = await stack.enter_async_context(
                            stdio_client(
                                StdioServerParameters(
                                    command=peer.command,
                                    args=list(peer.args),
                                    env=peer.env or {},
                                    cwd=peer.cwd,
                                ),
                            )
                        )
                    self.notice(peer.id, "transport.context_opened")

                    async def notification(message):
                        if isinstance(message, types.ServerNotification) and isinstance(
                            message.root, types.ToolListChangedNotification
                        ):
                            self.catalog_dirty.add(peer.id)

                    session = await stack.enter_async_context(
                        ObservedClientSession(
                            read,
                            write,
                            notice=lambda phase, **meta: self.notice(peer.id, phase, **meta),
                            message_handler=notification,
                        )
                    )
                    async with asyncio.timeout(self.call_timeout):
                        initialized = await session.initialize()
                    self.sessions[peer.id] = session
                    self.initializations[peer.id] = initialized
                    self.catalog_locks[peer.id] = asyncio.Lock()
                    self.notice(peer.id, "connection.ready")
                    ready.set_result(None)
                    await stop.wait()
            except BaseException:
                self.notice(peer.id, "connection.interrupted", error_code="peer_connection")
                if not ready.done():
                    ready.set_exception(
                        self.failure(peer.id, "peer_connection", "MCP connection failed")
                    )
            finally:
                self.sessions.pop(peer.id, None)
                self.initializations.pop(peer.id, None)
                self.catalogs.pop(peer.id, None)
                self.catalog_locks.pop(peer.id, None)
                self.catalog_dirty.discard(peer.id)
                self.health_epochs.pop(peer.id, None)
                self.notice(peer.id, "connection.closed")

        self.owners[peer.id] = asyncio.create_task(owner())
        try:
            async with asyncio.timeout(self.call_timeout):
                await ready
        except TimeoutError:
            failure = self.failure(peer.id, "peer_connection", "MCP initialization timed out")
            self.notice(peer.id, "connect.timed_out", error_code="peer_connection")
            await self.disconnect(peer.id)
            raise failure from None
        except BaseException:
            await self.disconnect(peer.id)
            raise

    async def list_tools(self, peer_id):
        """Fresh bounded pagination; catalogs never survive a connection generation."""
        session = self.sessions.get(peer_id)
        if session is None:
            raise self.failure(peer_id, "peer_disconnected", "MCP peer is not connected")
        async with self.catalog_locks.setdefault(peer_id, asyncio.Lock()):
            if self.sessions.get(peer_id) is not session:
                raise self.failure(peer_id, "peer_disconnected", "MCP connection changed")
            # Consume only invalidations preceding this refresh. A notification
            # arriving while a page is in flight still requires another refresh.
            self.catalog_dirty.discard(peer_id)
            tools, cursor, seen = [], None, set()
            try:
                async with asyncio.timeout(self.call_timeout):
                    for _ in range(8):
                        page = await session.list_tools(cursor=cursor)
                        if self.sessions.get(peer_id) is not session:
                            raise self.failure(
                                peer_id, "peer_disconnected", "MCP connection changed"
                            )
                        tools.extend(page.tools)
                        if len(tools) > 512 or len({t.name for t in tools}) != len(tools):
                            raise BridgeError(
                                "tool_catalog_invalid", "Ambiguous/oversized tool catalog"
                            )
                        cursor = page.nextCursor
                        if not cursor:
                            self.catalogs[peer_id] = tools
                            return tools
                        if cursor in seen:
                            raise BridgeError(
                                "tool_catalog_invalid", "Tool pagination cursor repeated"
                            )
                        seen.add(cursor)
                raise BridgeError("tool_catalog_invalid", "Tool pagination budget exceeded")
            except BaseException:
                if self.sessions.get(peer_id) is session:
                    self.catalog_dirty.add(peer_id)
                raise

    def health_epoch(self, peer_id, result):
        """A successful passive observation; never include volatile counts or raw contents."""
        data = result.structuredContent
        if result.isError or not isinstance(data, dict) or data.get("error"):
            return None
        observed = data.get("discovery")
        if (
            data.get("dispatcher_active") is not True
            or not isinstance(data.get("version"), str)
            or not isinstance(observed, dict)
            or not isinstance(observed.get("instance_id"), str)
            or not isinstance(observed.get("revision"), str)
        ):
            return None
        return digest(
            [
                self.connection_ids.get(peer_id),
                data["version"],
                observed["instance_id"],
                observed["revision"],
            ]
        )

    async def call(
        self,
        peer_id: str,
        tool: str,
        arguments: dict,
        *,
        task_id: str | None = None,
        routine_health: bool = False,
    ):
        request = arguments.get("request")
        task_id = (
            task_id
            or arguments.get("task_id")
            or (request.get("task_id") if isinstance(request, dict) else None)
        )
        if not isinstance(task_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", task_id):
            task_id = None
        session = self.sessions.get(peer_id)
        owner = self.owners.get(peer_id)
        connection_id = self.connection_ids.get(peer_id)
        if session is None:
            raise self.failure(
                peer_id,
                "peer_disconnected",
                "MCP peer is not connected",
                task_id=task_id,
                operation=tool,
            )
        # Only the internal passive poll may defer successful diagnostics. Explicit
        # reads and all execution/receipt tools retain the existing observation path.
        quiet = routine_health and tool == "bridge_health" and arguments == {} and task_id is None
        started = False
        call_phase = self.phases.get(peer_id, "unknown")

        def current_generation():
            return (
                self.sessions.get(peer_id) is session
                and self.owners.get(peer_id) is owner
                and self.connection_ids.get(peer_id) == connection_id
            )

        def notice_call(phase, **metadata):
            nonlocal call_phase
            call_phase = phase
            self.notice(peer_id, phase, connection_id=connection_id, **metadata)

        def fail_call(message):
            failure = self.failure(
                peer_id, "peer_unknown", message, task_id=task_id, operation=tool
            )
            failure.diagnostic.update(connection_id=connection_id, phase=call_phase)
            return failure

        def not_dispatched():
            notice_call("call.not_dispatched", tool=tool, task_id=task_id)
            failure = self.failure(
                peer_id,
                "peer_disconnected",
                "MCP connection changed before this client dispatched the request",
                task_id=task_id,
                operation=tool,
            )
            failure.diagnostic.update(
                connection_id=connection_id,
                phase=call_phase,
                accepted="no",
                started="no",
                completed="no",
                evidence_scope="this_client_request_dispatch",
                guidance="This client did not dispatch this request. This is not evidence "
                "about other requests or activity on the remote server. Refresh the "
                "connection and catalog before deciding on a new request; no automatic retry.",
            )
            return failure

        def observe_start():
            nonlocal started
            if not started:
                notice_call("call.started", tool=tool, task_id=task_id)
                started = True

        if peer_id in self.catalog_dirty:
            try:
                await self.list_tools(peer_id)
            except BridgeError as exc:
                if exc.code == "peer_disconnected" and not current_generation():
                    raise not_dispatched() from None
                raise
        if not quiet:
            observe_start()
        # No automatic retries: a timed-out tool may have already executed remotely.
        predispatch_failure = None
        try:
            async with self.gate, asyncio.timeout(self.call_timeout):
                if not current_generation():
                    predispatch_failure = not_dispatched()
                    raise predispatch_failure
                result = await session.call_tool(tool, arguments)
                if (
                    current_generation()
                    and tool == "bridge_health"
                    and self.health_epoch(peer_id, result) is None
                ):
                    self.health_epochs.pop(peer_id, None)
                if quiet and current_generation():
                    epoch = self.health_epoch(peer_id, result)
                    if epoch is not None and self.health_epochs.get(peer_id) == epoch:
                        self.phases[peer_id] = "call.returned"
                        return result
                    if epoch is None:
                        self.health_epochs.pop(peer_id, None)
                    else:
                        self.health_epochs[peer_id] = epoch
                    observe_start()
                if quiet:
                    observe_start()
                notice_call(
                    "call.returned",
                    tool=tool,
                    task_id=task_id,
                    outcome="response_received",
                )
                return result
        except TimeoutError:
            if tool == "bridge_health" and current_generation():
                self.health_epochs.pop(peer_id, None)
            observe_start()
            notice_call(
                "call.outcome_unknown",
                tool=tool,
                task_id=task_id,
                error_code="peer_unknown",
            )
            raise fail_call("Tool outcome unknown; do not retry blindly") from None
        except Exception as exc:
            if exc is predispatch_failure:
                raise
            if tool == "bridge_health" and current_generation():
                self.health_epochs.pop(peer_id, None)
            observe_start()
            notice_call(
                "call.outcome_unknown",
                tool=tool,
                task_id=task_id,
                error_code="peer_unknown",
            )
            failure = fail_call("Tool outcome unknown; reconcile before retry")
            if (
                isinstance(exc, McpError)
                and exc.error.code == types.CONNECTION_CLOSED
                and self.owners.get(peer_id) is owner
            ):
                # SDK EOF does not end its owner's stop.wait(). Close only this
                # proven dead connection; never replay the uncertain tool call.
                await self.disconnect(peer_id)
            raise failure from None
        except asyncio.CancelledError:
            if tool == "bridge_health" and current_generation():
                self.health_epochs.pop(peer_id, None)
            observe_start()
            notice_call("call.interrupted", tool=tool, task_id=task_id, error_code="peer_unknown")
            raise

    async def disconnect(self, peer_id: str) -> None:
        owner = self.owners.get(peer_id)
        if owner is None:
            return
        closing = self._disconnects.get(owner)
        if closing is None:

            async def close_owner():
                try:
                    if self.owners.get(peer_id) is not owner:
                        return
                    self.notice(peer_id, "disconnect.requested")
                    self.stops[peer_id].set()
                    try:
                        async with asyncio.timeout(5):
                            await asyncio.shield(asyncio.gather(owner, return_exceptions=True))
                    except TimeoutError:
                        owner.cancel()
                        await asyncio.gather(owner, return_exceptions=True)
                    self.owners.pop(peer_id, None)
                    self.stops.pop(peer_id, None)
                    self.previous_ids[peer_id] = self.connection_ids.pop(peer_id)
                    self.phases.pop(peer_id, None)
                    while len(self.previous_ids) > self.max_connections:
                        self.previous_ids.pop(next(iter(self.previous_ids)))
                finally:
                    self._disconnects.pop(owner, None)

            closing = self._disconnects[owner] = asyncio.create_task(close_owner())
        # Concurrent EOFs share one teardown. Cancelling an observer must not
        # abandon cleanup or let an old teardown remove a new connection.
        await asyncio.shield(closing)

    async def close(self) -> None:
        for peer_id in list(self.owners):
            await self.disconnect(peer_id)
        if self.observer:
            try:
                self.observer.close()
            except Exception:
                self.observation_failures += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()
