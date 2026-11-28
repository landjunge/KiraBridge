"""Stdio connection to the shared daemon; tokens stay out of agent configuration files."""

import asyncio
import json
import time

from jsonschema import ValidationError
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool

from kirabridge.bridge_core.models import BridgeError, digest
from kirabridge.local_runtime import connection_observer, peer
from kirabridge.mcp_gateway.client import MCPClientPool
from kirabridge.mcp_gateway.proxy_contract import (
    PROXY_INSTRUCTIONS,
    dynamic_call_arguments,
    dynamic_tool_definition,
    read_dynamic_catalog,
    require_dynamic_tool,
)
from kirabridge.mcp_gateway.proxy_contract import (
    dynamic_input_schema as dynamic_input_schema,
)
from kirabridge.mcp_gateway.proxy_contract import (
    dynamic_tool_name as dynamic_tool_name,
)
from kirabridge.mcp_gateway.schema_validation import (
    SchemaValidatorCache,
    explicit_scalar_const_types,
)
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


async def connect_stdio(config, principal, *, task_policy=None):
    async with MCPClientPool(observer=connection_observer(config, principal)) as pool:
        await pool.connect(peer(config, principal))
        connection = DaemonConnection(pool, peer(config, principal))

        server = Server(
            "KiraBridge",
            version=pool.initializations[connection.endpoint.id].serverInfo.version,
            instructions=PROXY_INSTRUCTIONS,
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

        @server.list_tools()
        async def list_tools():
            downstream.add(server.request_context.session)
            baseline = list(await connection.list_tools())
            known = {tool.name for tool in baseline}
            if task_policy is None or any(name.startswith("td_") for name in task_policy.tools):
                discovered, _ = await read_dynamic_catalog(connection.call_tool)
                baseline.extend(
                    Tool(**dynamic_tool_definition(name, item))
                    for name, item in discovered.items()
                    if name not in known
                )
            await changed()
            return (
                [
                    tool.model_copy(
                        update={"inputSchema": explicit_scalar_const_types(tool.inputSchema)}
                    )
                    for tool in baseline
                    if task_policy.permits_tool(tool)
                ]
                if task_policy
                else baseline
            )

        @server.call_tool(validate_input=False)
        async def call_tool(name, arguments):
            try:
                downstream.add(server.request_context.session)
                from kirabridge.technical_entries import proxy_retention

                retained = proxy_retention(config, name, arguments)
                if retained is not None:
                    # Keep the latest state in this process. Do not call the ThreadDesk peer.
                    result = await connection.call_tool("threaddesk_dynamic_call", retained)
                    data = result.structuredContent
                    if isinstance(data, dict) and "error" in data:
                        return CallToolResult(
                            isError=True,
                            content=[TextContent(type="text", text=json.dumps(data))],
                            structuredContent=data,
                        )
                    if task_policy is not None:
                        try:
                            task_policy.observe_result(name, arguments, result)
                        except Exception:
                            pass
                    await changed()
                    return result
                definition = await server._get_cached_tool_definition(name)
                if task_policy is not None:
                    await task_policy.authorize(connection, name, arguments, definition=definition)
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
                    item = await require_dynamic_tool(connection.call_tool, name)
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
                    if task_policy is not None:
                        task_policy.observe_result(name, arguments, result)
                    await changed()
                    return result
                result = await connection.call_tool(name, arguments)
                if task_policy is not None:
                    task_policy.observe_result(name, arguments, result)
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
                        if task_policy is None:
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
