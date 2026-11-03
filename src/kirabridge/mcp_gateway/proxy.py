"""Stdio connection to the shared daemon; tokens stay out of agent configuration files."""

import asyncio
import json

from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations

from kirabridge.bridge_core.models import BridgeError, digest
from kirabridge.local_runtime import connection_observer, peer
from kirabridge.mcp_gateway.client import MCPClientPool


class DaemonConnection:
    """Reconnect a known closed owner before a call, never replay an in-flight call."""

    def __init__(self, pool, endpoint):
        self.pool, self.endpoint = pool, endpoint
        self.lock = asyncio.Lock()
        self.revision = None
        self.change_generation = 0

    async def ensure_connection(self):
        async with self.lock:
            if self.endpoint.id not in self.pool.sessions:
                await self.pool.disconnect(self.endpoint.id)
                await self.pool.connect(self.endpoint)

    async def call_tool(self, name, arguments, *, routine_health=False):
        await self.ensure_connection()
        tools = await self.list_tools()
        if name not in {tool.name for tool in tools}:
            raise BridgeError("tool_unavailable", "Tool absent from the current daemon catalog")
        if routine_health:
            return await self.pool.call(self.endpoint.id, name, arguments, routine_health=True)
        return await self.pool.call(self.endpoint.id, name, arguments)

    async def list_tools(self):
        await self.ensure_connection()
        tools = await self.pool.list_tools(self.endpoint.id)
        revision = digest([tool.model_dump(mode="json", by_alias=True) for tool in tools])
        if self.revision is not None and self.revision != revision:
            self.change_generation += 1
        self.revision = revision
        return tools


def dynamic_input_schema(item):
    """Mutation envelopes keep the peer schema intact and cannot collide with its fields."""
    if not item.get("requires_operation_id", False):
        return item["inputSchema"]
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "operation_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,128}$"},
            "arguments": item["inputSchema"],
        },
        "required": ["operation_id", "arguments"],
    }


def dynamic_call_arguments(item, arguments):
    if not item.get("requires_operation_id", False):
        return {"name": item["name"], "arguments": arguments}
    if (
        not isinstance(arguments, dict)
        or set(arguments) != {"operation_id", "arguments"}
        or not isinstance(arguments.get("arguments"), dict)
    ):
        raise BridgeError("invalid_arguments", "Use the advertised mutation envelope")
    return {"name": item["name"], **arguments}


async def connect_stdio(config, principal):
    async with MCPClientPool(observer=connection_observer(config, principal)) as pool:
        await pool.connect(peer(config, principal))
        connection = DaemonConnection(pool, peer(config, principal))

        server = Server(
            "KiraBridge",
            version=pool.initializations[connection.endpoint.id].serverInfo.version,
            instructions="Direct ChatGPT terminal work uses terminal_control / terminal.visible. "
            "no busy/unconfirmed window and no invisible fallback. Internal Codex/Grok execution "
            "and ThreadDesk are separate. Refresh tools/list on list_changed and compare "
            "discovery.revision after connection/version/session changes. "
            "Check per-operation permission_decision; approval_mode is legacy policy metadata. "
            "Use task_request; automatic mode queues permitted work without a browser click. "
            "Only when approval_required is true, give the operator local_approval_url. "
            "Do not ask for approval when approval_required is false. "
            "Set a unique completion_target and keep a completion_receive consumer active; "
            "completion_ack only after processing. Inactive ChatGPT chats are not awakened. "
            "Use task_get and task_events for additional evidence; "
            "no task-ID copying is needed. "
            "Use message_send/message_receive for addressed peer communication, not shared files. "
            "Eve is Grok Voice, Kira is ChatGPT Voice, Grok Build and Codex are terminals. "
            "Eve relays only Daniel's unchanged dictation, without additions. "
            "Explicit voice and terminal user requests need no special approval marker. "
            "Normal permissions apply; historical buffers never auto-release. "
            "CLI handoffs require assigned existing visible windows; no background fallback. "
            "message_channel_status reports the dispatcher and each identity separately; "
            "For existing Terminal.app tabs and tmux panes use session_catalog and session_read; "
            "session_open opens a visible window. session.input addresses an exact catalog handle. "
            "session_input_policy controls only an optional buffer, not terminal availability. "
            "agent_status includes interactive_terminal_sessions; cached tools can discover and "
            "read handles using read_query operations session.catalog and session.read. "
            "These tools have the same permissions on mobile, browser, Live and voice. "
            "Use connection_check from the actual conversation to verify its current device/mode.",
        )

        downstream = set()
        last_generation = 0

        async def changed():
            nonlocal last_generation
            if last_generation != connection.change_generation:
                last_generation = connection.change_generation
                for session in tuple(downstream):
                    try:
                        await session.send_tool_list_changed()
                    except Exception:
                        downstream.discard(session)

        async def dynamic_catalog():
            """Only the configured peer can advertise new read tools; failures stay isolated."""
            try:
                result = await connection.call_tool("threaddesk_dynamic_catalog", {})
                data = result.structuredContent
                if result.isError or not isinstance(data, dict):
                    return {}
                entries = data.get("tools")
                if not isinstance(entries, list) or len(entries) > 256:
                    return {}
                names = {}
                for item in entries:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("name")
                    schema = item.get("inputSchema")
                    if (
                        isinstance(name, str)
                        and name.startswith(
                            tuple("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
                        )
                        and name.replace("_", "").replace("-", "").isalnum()
                        and len(name) <= 64
                        and isinstance(schema, dict)
                    ):
                        names["td_" + name] = item
                return names
            except Exception:
                # A missing/offline optional ThreadDesk cannot break core Bridge tools.
                return {}

        @server.list_tools()
        async def list_tools():
            downstream.add(server.request_context.session)
            baseline = list(await connection.list_tools())
            known = {tool.name for tool in baseline}
            discovered = await dynamic_catalog()
            for name, item in discovered.items():
                if name in known:
                    continue
                baseline.append(
                    Tool(
                        name=name,
                        description="ThreadDesk: " + (item.get("description") or ""),
                        inputSchema=dynamic_input_schema(item),
                        annotations=ToolAnnotations(
                            **item.get(
                                "annotations",
                                {
                                    "readOnlyHint": True,
                                    "destructiveHint": False,
                                    "openWorldHint": False,
                                },
                            )
                        ),
                    )
                )
            await changed()
            return baseline

        @server.call_tool()
        async def call_tool(name, arguments):
            try:
                downstream.add(server.request_context.session)
                if name.startswith("td_"):
                    # Re-list to reject stale tool names and changes after discovery.
                    discovered = await dynamic_catalog()
                    item = discovered.get(name)
                    if item is None:
                        raise BridgeError("threaddesk_tool_denied", "Dynamic tool is unavailable")
                    result = await connection.call_tool(
                        "threaddesk_dynamic_call",
                        dynamic_call_arguments(item, arguments or {}),
                    )
                    data = result.structuredContent
                    if isinstance(data, dict) and "error" in data:
                        return CallToolResult(
                            isError=True,
                            content=[TextContent(type="text", text=json.dumps(data))],
                            structuredContent=data,
                        )
                    await changed()
                    return result
                result = await connection.call_tool(name, arguments)
                await changed()
                return result
            except BridgeError as exc:
                data = {"error": {"code": exc.code}}
                if hasattr(exc, "diagnostic"):
                    data["diagnostic"] = exc.diagnostic
                return CallToolResult(
                    isError=True,
                    content=[TextContent(type="text", text=json.dumps(data))],
                    structuredContent=data,
                )

        async def monitor():
            while True:
                await asyncio.sleep(1)
                if downstream:
                    try:
                        # Reads only; a failed/uncertain mutation is never retried.
                        await connection.call_tool("bridge_health", {}, routine_health=True)
                        await connection.list_tools()
                        await changed()
                    except Exception:
                        pass  # The next explicit call reports its connection error.

        async with stdio_server() as (read, write):
            watcher = asyncio.create_task(monitor())
            try:
                await server.run(
                    read,
                    write,
                    server.create_initialization_options(
                        notification_options=NotificationOptions(tools_changed=True)
                    ),
                )
            finally:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
