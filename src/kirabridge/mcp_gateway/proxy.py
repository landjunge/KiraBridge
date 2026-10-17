"""Stdio connection to the shared daemon; tokens stay out of agent configuration files."""

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent

from kirabridge import __version__
from kirabridge.bridge_core.models import BridgeError
from kirabridge.local_runtime import peer
from kirabridge.mcp_gateway.client import MCPClientPool


async def connect_stdio(config, principal):
    async with MCPClientPool() as pool:
        await pool.connect(peer(config, principal))
        server = Server(
            "KiraBridge",
            version=__version__,
            instructions="Use task_request and give the operator local_approval_url on their Mac. "
            "Requests appear there automatically; no task-ID copying is needed. "
            "Use task_get and task_events to verify execution after local approval.",
        )

        @server.list_tools()
        async def list_tools():
            return (await pool.sessions["daemon"].list_tools()).tools

        @server.call_tool()
        async def call_tool(name, arguments):
            try:
                return await pool.call("daemon", name, arguments)
            except BridgeError as exc:
                return CallToolResult(
                    isError=True, content=[TextContent(type="text", text=exc.code)]
                )

        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
