"""Stdio connection to the shared daemon; tokens stay out of agent configuration files."""

import asyncio
import json

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent

from kirabridge import __version__
from kirabridge.bridge_core.models import BridgeError
from kirabridge.local_runtime import connection_observer, peer
from kirabridge.mcp_gateway.client import MCPClientPool


class DaemonConnection:
    """Reconnect a known closed owner before a call, never replay an in-flight call."""

    def __init__(self, pool, endpoint):
        self.pool, self.endpoint = pool, endpoint
        self.lock = asyncio.Lock()

    async def ensure_connection(self):
        async with self.lock:
            if self.endpoint.id not in self.pool.sessions:
                await self.pool.disconnect(self.endpoint.id)
                await self.pool.connect(self.endpoint)

    async def call_tool(self, name, arguments):
        await self.ensure_connection()
        return await self.pool.call(self.endpoint.id, name, arguments)

    async def list_tools(self):
        await self.ensure_connection()
        return (await self.pool.sessions[self.endpoint.id].list_tools()).tools


async def connect_stdio(config, principal):
    async with MCPClientPool(observer=connection_observer(config, principal)) as pool:
        await pool.connect(peer(config, principal))
        connection = DaemonConnection(pool, peer(config, principal))

        server = Server(
            "KiraBridge",
            version=__version__,
            instructions="Check bridge_health or operation_catalog for approval_mode. "
            "Use task_request; automatic mode queues permitted work without a browser click. "
            "Only when approval_required is true, give the operator local_approval_url. "
            "Do not ask for approval when approval_required is false. "
            "Set a unique completion_target and keep a completion_receive consumer active; "
            "completion_ack only after processing. Inactive ChatGPT chats are not awakened. "
            "Use task_get and task_events for additional evidence; "
            "no task-ID copying is needed. "
            "Use message_send/message_receive for addressed peer communication, not shared files. "
            "message_channel_status reports peers and the separate managed receiver; "
            "existing interactive sessions are not attached.",
        )

        @server.list_tools()
        async def list_tools():
            return await connection.list_tools()

        @server.call_tool()
        async def call_tool(name, arguments):
            try:
                return await connection.call_tool(name, arguments)
            except BridgeError as exc:
                data = {"error": {"code": exc.code}}
                if hasattr(exc, "diagnostic"):
                    data["diagnostic"] = exc.diagnostic
                return CallToolResult(
                    isError=True,
                    content=[TextContent(type="text", text=json.dumps(data))],
                    structuredContent=data,
                )

        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
