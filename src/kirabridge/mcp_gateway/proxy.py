"""Stdio connection to the shared daemon; tokens stay out of agent configuration files."""

import asyncio
import json
import time

from jsonschema import ValidationError
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations

from kirabridge.bridge_core.models import BridgeError, digest
from kirabridge.local_runtime import connection_observer, peer
from kirabridge.mcp_gateway.client import MCPClientPool
from kirabridge.mcp_gateway.schema_validation import SchemaValidatorCache
from kirabridge.mcp_gateway.timing import ToolSpan, instrument_server

SCHEMA_CACHE_SECONDS = 30.0


class DaemonConnection:
    """Reconnect a known closed owner before a call, never replay an in-flight call."""

    def __init__(self, pool, endpoint):
        self.pool, self.endpoint = pool, endpoint
        self.lock = asyncio.Lock()
        self.revision = None
        self.change_generation = 0
        self.catalog_lock = asyncio.Lock()
        self._catalog = None
        self._catalog_generation = None
        self._catalog_read_at = 0.0
        self._catalog_epoch = None

    def connection_generation(self):
        return (
            self.pool.sessions.get(self.endpoint.id),
            self.pool.connection_ids.get(self.endpoint.id),
        )

    async def ensure_connection(self):
        try:
            async with asyncio.timeout(self.pool.call_timeout), self.lock:
                if self.endpoint.id not in self.pool.sessions:
                    await self.pool.disconnect(self.endpoint.id)
                    await self.pool.connect(self.endpoint)
        except TimeoutError:
            failure = self.pool.failure(
                self.endpoint.id,
                "peer_connection_timeout",
                "MCP connection step timed out before tool dispatch",
            )
            failure.diagnostic.update(
                phase="connection.step.timed_out",
                tool_dispatch="no",
                evidence_scope="this_client_tool_dispatch",
                guidance="This connection step did not dispatch a tool request. Connection "
                "or initialization may have started; this is not evidence about other "
                "callers or remote activity. No automatic retry.",
            )
            raise failure from None

    async def call_tool(self, name, arguments, *, routine_health=False):
        span = ToolSpan()
        tools = await self.tools_for_call()
        if name not in {tool.name for tool in tools}:
            # Newly advertised tools need not wait for the short metadata TTL.
            tools = await self.list_tools()
            if name not in {tool.name for tool in tools}:
                raise BridgeError("tool_unavailable", "Tool absent from the current daemon catalog")
        catalog_ms = span.elapsed_ms
        if routine_health:
            result = await self.pool.call(self.endpoint.id, name, arguments, routine_health=True)
        else:
            result = await self.pool.call(self.endpoint.id, name, arguments)
        data = result.structuredContent
        discovery = data.get("discovery") if isinstance(data, dict) else None
        if isinstance(discovery, dict) and self._catalog_epoch is not None:
            if any(
                key in discovery and discovery[key] != value
                for key, value in self._catalog_epoch.items()
            ):
                self._catalog = None
        return span.result(result, "proxy_dispatch", catalog_ms=catalog_ms)

    async def tools_for_call(self):
        """Cache schemas for at most thirty seconds, never execution or authorization.

        The daemon still validates current permissions for every call. Explicit
        discovery stays fresh; notifications, epochs and connection changes expire
        this local metadata immediately. Failed refreshes never serve old schemas.
        """
        await self.ensure_connection()
        async with asyncio.timeout(self.pool.call_timeout), self.catalog_lock:
            if (
                self._catalog is not None
                and self._catalog_generation == self.connection_generation()
                and self.endpoint.id not in self.pool.catalog_dirty
                and self.pool.catalogs.get(self.endpoint.id) is self._catalog
                and time.monotonic() - self._catalog_read_at < SCHEMA_CACHE_SECONDS
            ):
                return self._catalog
            return await self.refresh_tools()

    async def list_tools(self):
        await self.ensure_connection()
        async with asyncio.timeout(self.pool.call_timeout), self.catalog_lock:
            return await self.refresh_tools()

    async def poll_health(self):
        """Use the fresh minimal epoch when advertised; retain older-daemon support."""
        tools = await self.tools_for_call()
        name = (
            "bridge_epoch"
            if any(tool.name == "bridge_epoch" for tool in tools)
            else "bridge_health"
        )
        return await self.call_tool(name, {}, routine_health=True)

    async def refresh_tools(self):
        self._catalog = None
        tools = await self.pool.list_tools(self.endpoint.id)
        revision = digest([tool.model_dump(mode="json", by_alias=True) for tool in tools])
        if self.revision is not None and self.revision != revision:
            self.change_generation += 1
        self.revision = revision
        self._catalog = tools
        self._catalog_generation = self.connection_generation()
        self._catalog_read_at = time.monotonic()
        metadata = (tools[0].meta or {}).get("kirabridge") if tools else None
        self._catalog_epoch = (
            {
                key: metadata[key]
                for key in ("version", "instance_id", "revision", "principal")
                if key in metadata
            }
            if isinstance(metadata, dict)
            else None
        )
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
            "Use keyboard_sequence for ordered genuine individual keystrokes in one call; "
            "use keyboard_control text only for literal text requests. No clipboard is used. "
            "Reduce cloud roundtrips: read_query operation=tool.batch combines 1–8 existing "
            "read-only calls [{tool,arguments}]; read.batch combines query objects. "
            "Prefer result_format=structured for lossless structured values without duplicate "
            "child JSON text; full preserves envelopes. "
            "Read_query operation=task.observe returns an existing task and events together "
            "with wait_seconds<=18 and events_after; never resubmit uncertain work. "
            "For known schemas submit directly, without routine health/catalog prefetches. "
            "Select operation_catalog operations=[...] for the needed schemas only. "
            "A completed inline response needs no unconditional task/status/completion poll. "
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
            "session.input sends literal text and slash commands; "
            "submit=false pastes without Return. "
            "Use agent.execute or message_send(kind=work) for addressed agent assignments. "
            "session_input_policy controls only an optional buffer, not terminal availability. "
            "agent_status includes interactive_terminal_sessions; cached tools can discover and "
            "read handles using read_query operations session.catalog and session.read. "
            "These tools have the same permissions on mobile, browser, Live and voice. "
            "Use connection_check from the actual conversation to verify its current device/mode.",
        )

        downstream = set()
        last_generation = 0
        input_validators = SchemaValidatorCache()

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

        @server.call_tool(validate_input=False)
        async def call_tool(name, arguments):
            try:
                downstream.add(server.request_context.session)
                definition = await server._get_cached_tool_definition(name)
                if definition is not None:
                    try:
                        input_validators.validate(arguments or {}, definition.inputSchema)
                    except ValidationError as error:
                        return CallToolResult(
                            isError=True,
                            content=[
                                TextContent(
                                    type="text", text=f"Input validation error: {error.message}"
                                )
                            ],
                        )
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

        instrument_server(server, "stdio_proxy")

        async def monitor():
            while True:
                await asyncio.sleep(1)
                if downstream:
                    try:
                        # Reads only; a failed/uncertain mutation is never retried.
                        # call_tool already refreshes the catalog and revision.
                        await connection.poll_health()
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
