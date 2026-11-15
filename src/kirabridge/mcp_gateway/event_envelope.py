"""Optional SDK-independent Events envelope around the existing stdio proxy.

Only actual Events handlers permit capability advertisement. Other wire messages
are forwarded unchanged, preserving dynamic tools, aliases and notification IDs.
Callbacks originate from host subscription requests, never a guessed chat ID.
"""

from __future__ import annotations

import asyncio
import json
import sys

from kirabridge.event_push import EventError

MAX_LINE = 16 * 1024 * 1024
EVENT_METHODS = {"events/list", "events/subscribe", "events/unsubscribe"}


class EventEnvelope:
    def __init__(self, push, *, ready=None):
        self.push = push
        self.ready = ready or (lambda: push is not None)
        self.initializations = set()

    @staticmethod
    def parse(line):
        try:
            value = json.loads(line)
            return value if isinstance(value, dict) else None
        except (ValueError, UnicodeError):
            return None

    async def from_host(self, line):
        """Return (local response, child bytes); a notification gets no response."""
        value = self.parse(line)
        if value is None:
            return None, line
        method = value.get("method")
        if method == "initialize" and "id" in value:
            self.initializations.add(json.dumps(value["id"], sort_keys=True))
        if self.push is None or method not in EVENT_METHODS:
            return None, line
        if "id" not in value:
            return None, None  # Requests are required; never emit a notification response.
        response = {"jsonrpc": "2.0", "id": value["id"]}
        try:
            if not self.ready():
                raise EventError("event_sender_unavailable")
            params = value.get("params", {})
            if not isinstance(params, dict):
                raise EventError("invalid_event_params")
            if method == "events/list":
                if params.get("cursor") is not None:
                    raise EventError("invalid_events_cursor")
                result = self.push.event_list()
            elif method == "events/subscribe":
                result = await self.push.subscribe(
                    params.get("name"),
                    params.get("arguments"),
                    params.get("delivery"),
                    cursor=params.get("cursor"),
                    ttl_ms=params.get("ttlMs", 86400000),
                )
            else:
                result = self.push.unsubscribe(
                    params.get("name"), params.get("arguments"), params.get("delivery")
                )
            response["result"] = result
        except EventError as error:
            response["error"] = {
                "code": error.code,
                "message": "KiraBridge event request rejected",
                "data": {"reason": error.reason},
            }
        return json.dumps(response, separators=(",", ":")).encode() + b"\n", None

    def from_child(self, line):
        value = self.parse(line)
        if value is None or "id" not in value:
            return line
        key = json.dumps(value["id"], sort_keys=True)
        if key not in self.initializations:
            return line
        self.initializations.remove(key)
        result = value.get("result")
        if self.push is None or not self.ready() or not isinstance(result, dict):
            return line
        capabilities = result.get("capabilities")
        if not isinstance(capabilities, dict):
            return line
        capabilities["events"] = {}
        instructions = result.get("instructions")
        if isinstance(instructions, str):
            # Replace the obsolete unconditional assertion only on this enabled path.
            result["instructions"] = instructions.replace(
                "Inactive ChatGPT chats are not awakened.",
                "Native MCP Events can trigger a subscribed Work Cloud chat; "
                "an inbox or a webhook receipt alone does not prove a chat response.",
            )
        return json.dumps(value, separators=(",", ":")).encode() + b"\n"


async def serve(
    envelope,
    child_argv,
    reader,
    write,
    *,
    drain_timeout=2.0,
    terminate_timeout=3.0,
    kill_timeout=2.0,
):
    """Preserve the exact child's status; bound EOF drain and own-child cleanup."""
    child = await asyncio.create_subprocess_exec(
        *child_argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=None,
        limit=MAX_LINE,
    )
    output_lock = asyncio.Lock()

    async def emit(line):
        async with output_lock:
            await write(line)

    async def host_to_child():
        while line := await reader.readline():
            if len(line) > MAX_LINE:
                raise RuntimeError("mcp_wire_line_too_large")
            response, forwarded = await envelope.from_host(line)
            if response is not None:
                await emit(response)
            if forwarded is not None:
                try:
                    child.stdin.write(forwarded)
                    await child.stdin.drain()
                except (BrokenPipeError, ConnectionResetError) as error:
                    # Only this owned stdin closure can yield to an actual child
                    # exit. Host framing/output and other transport errors raise.
                    return error
        child.stdin.close()

    async def child_to_host():
        while line := await child.stdout.readline():
            await emit(envelope.from_child(line))

    async def bounded_wait(timeout):
        try:
            await asyncio.wait_for(asyncio.shield(exited), timeout)
            return True
        except TimeoutError:
            return False

    async def stop_owned_child():
        if child.returncode is not None:
            return
        try:
            child.terminate()
        except ProcessLookupError:
            pass
        if await bounded_wait(terminate_timeout):
            return
        try:
            child.kill()
        except ProcessLookupError:
            pass
        if not await bounded_wait(kill_timeout):
            raise RuntimeError("owned_mcp_child_did_not_exit_after_kill")

    upstream = asyncio.create_task(host_to_child())
    downstream = asyncio.create_task(child_to_host())
    exited = asyncio.create_task(child.wait())
    tasks = (upstream, downstream, exited)
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        # EOF in either direction gets one finite grace period. A natural child
        # exit may precede stdout EOF; preserve its buffered final response too.
        natural_exit = await bounded_wait(drain_timeout)
        if not natural_exit:
            await stop_owned_child()
        try:
            await asyncio.wait_for(asyncio.shield(downstream), drain_timeout)
        except TimeoutError:
            downstream.cancel()
            raise RuntimeError("owned_mcp_child_output_did_not_close") from None
        if upstream.done():
            stdin_error = upstream.result()  # Preserve unrelated late host errors.
            if stdin_error is not None and not natural_exit:
                raise RuntimeError("owned_mcp_child_closed_stdin_before_exit") from stdin_error
        return child.returncode
    finally:
        try:
            await stop_owned_child()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


async def stdio(envelope, child_argv):
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=MAX_LINE)
    protocol = asyncio.StreamReaderProtocol(reader)
    input_transport, _ = await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)
    output_transport, output_protocol = await loop.connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout.buffer
    )
    writer = asyncio.StreamWriter(output_transport, output_protocol, None, loop)

    async def write(line):
        writer.write(line)
        await writer.drain()

    try:
        return await serve(envelope, child_argv, reader, write)
    finally:
        input_transport.close()
        output_transport.close()
