from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from kirabridge.bridge_core.models import BridgeError


@dataclass(frozen=True)
class Peer:
    """Trusted, explicitly configured endpoints. stdio programs are local execution authority."""

    id: str
    url: str | None = None
    command: str | None = None
    args: tuple[str, ...] = ()
    token: str | None = field(default=None, repr=False)
    ca_file: str | None = None


class MCPClientPool:
    """One dedicated owner coroutine per connection, preserving anyio cancel-scope ownership."""

    interface_version = "1"

    def __init__(self, max_connections: int = 8, call_timeout: float = 30):
        self.max_connections, self.call_timeout = max_connections, call_timeout
        self.owners: dict[str, asyncio.Task] = {}
        self.sessions: dict[str, ClientSession] = {}
        self.stops: dict[str, asyncio.Event] = {}
        self.gate = asyncio.Semaphore(32)

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
                                    command=peer.command, args=list(peer.args), env={}
                                ),
                            )
                        )
                    session = await stack.enter_async_context(ClientSession(read, write))
                    async with asyncio.timeout(self.call_timeout):
                        await session.initialize()
                    self.sessions[peer.id] = session
                    ready.set_result(None)
                    await stop.wait()
            except BaseException:
                if not ready.done():
                    ready.set_exception(BridgeError("peer_connection", "MCP connection failed"))
            finally:
                self.sessions.pop(peer.id, None)

        self.owners[peer.id] = asyncio.create_task(owner())
        try:
            async with asyncio.timeout(self.call_timeout):
                await ready
        except BaseException:
            await self.disconnect(peer.id)
            raise

    async def call(self, peer_id: str, tool: str, arguments: dict):
        session = self.sessions.get(peer_id)
        if session is None:
            raise BridgeError("peer_disconnected", "MCP peer is not connected")
        # No automatic retries: a timed-out tool may have already executed remotely.
        try:
            async with self.gate, asyncio.timeout(self.call_timeout):
                return await session.call_tool(tool, arguments)
        except TimeoutError:
            raise BridgeError(
                "peer_unknown", "Tool outcome unknown; do not retry blindly"
            ) from None
        except Exception:
            raise BridgeError(
                "peer_unknown", "Tool outcome unknown; reconcile before retry"
            ) from None

    async def disconnect(self, peer_id: str) -> None:
        owner = self.owners.get(peer_id)
        if owner:
            self.stops[peer_id].set()
            try:
                async with asyncio.timeout(5):
                    await asyncio.shield(owner)
            except TimeoutError:
                owner.cancel()
                await asyncio.gather(owner, return_exceptions=True)
            self.owners.pop(peer_id, None)
            self.stops.pop(peer_id, None)

    async def close(self) -> None:
        for peer_id in list(self.owners):
            await self.disconnect(peer_id)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()
