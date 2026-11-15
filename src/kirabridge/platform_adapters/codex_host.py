"""Bounded RPC to an assigned root on the existing Codex 0.169 Unix WebSocket.

No host start/resume, discovery by title/CWD, terminal input or retry. Assignment
is configuration authority; host responses prove its current local continuity.
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import socket
import stat
import struct
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from kirabridge import __version__
from kirabridge.bridge_core.models import BridgeError, UncertainExecution, digest

MAX_RESPONSE = 1048576


def refused(code="native_codex_binding_changed"):
    return BridgeError(code, "Assigned native Codex root could not be freshly verified")


def _private(path, kind, *, readable=False):
    before = path.lstat()
    if (
        not kind(before.st_mode)
        or before.st_uid != os.getuid()
        or stat.S_IMODE(before.st_mode) & (0o022 if readable else 0o077)
    ):
        raise refused("native_codex_host_unverified")
    return before


def _socket(binding):
    """Verify the connected peer, not just a private-looking socket pathname."""
    if sys.platform != "darwin":
        raise refused("native_codex_host_unsupported")
    home = Path(binding.codex_home)
    if home != home.resolve(strict=True):
        raise refused("native_codex_host_unverified")
    _private(home, stat.S_ISDIR)
    registry = home / "app-server-daemon" / "daemon.pid"
    _private(registry.parent, stat.S_ISDIR)
    # Codex writes daemon.pid as 0644 inside its 0700 directory.
    record = _private(registry, stat.S_ISREG, readable=True)
    fd = os.open(registry, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (
            (opened.st_dev, opened.st_ino) != (record.st_dev, record.st_ino)
            or opened.st_size > 16384
        ):
            raise refused("native_codex_host_unverified")
        saved = json.loads(stream.read(16385))
    pid = saved.get("pid")
    identity = saved.get("processIdentity", {})
    if type(pid) is not int or pid <= 0 or type(identity.get("startSeconds")) is not int:
        raise refused("native_codex_host_unverified")
    path = _host_socket_path(pid)
    before = _private(path, stat.S_ISSOCK)
    raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        raw.settimeout(3)
        raw.connect(str(path))
        # Darwin SOL_LOCAL / LOCAL_PEERPID. No user-controlled PID is trusted.
        peer_pid = struct.unpack("i", raw.getsockopt(0, 2, 4))[0]
        if peer_pid != pid:
            raise refused("native_codex_host_unverified")
        result = subprocess.run(
            ["/bin/ps", "-ww", "-p", str(pid), "-o", "uid=,lstart=,args="],
            capture_output=True,
            text=True,
            timeout=2,
            env={**os.environ, "LC_ALL": "C"},
            check=True,
        )
        fields = result.stdout.strip().split(None, 6)
        if len(fields) != 7:
            raise refused("native_codex_host_unverified")
        started = int(datetime.strptime(" ".join(fields[1:6]), "%a %b %d %H:%M:%S %Y").timestamp())
        if (
            int(fields[0]) != os.getuid()
            or started != identity["startSeconds"]
            or _process_path(pid) != binding.host_executable
            or not fields[6].startswith(binding.host_executable + " app-server ")
            or "--managed-daemon" not in fields[6].split()
            or "--listen unix://" not in fields[6]
        ):
            raise refused("native_codex_host_unverified")
        after = _private(path, stat.S_ISSOCK)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise refused("native_codex_host_unverified")
        raw.setblocking(False)
        generation = digest(
            {"process": identity, "socket_device": after.st_dev, "socket_inode": after.st_ino}
        )
        return raw, generation
    except BaseException:
        raw.close()
        raise


def _process_path(pid):
    # BSD ps truncates nonfinal comm columns; proc_pidpath is the OS image path.
    libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    buffer = ctypes.create_string_buffer(4096)
    count = libproc.proc_pidpath(pid, buffer, len(buffer))
    if count <= 0:
        raise refused("native_codex_host_unverified")
    return os.fsdecode(buffer.value)


def _host_socket_path(pid):
    """The current registered host's unique private socket, including after moves.

    Never scan other Codex processes or choose a thread by a terminal's readiness.
    Connected descriptors can repeat the listener pathname, so dedupe paths first.
    """
    result = subprocess.run(
        ["/usr/sbin/lsof", "-nP", "-a", "-p", str(pid), "-U", "-Fpn"],
        capture_output=True, text=True, timeout=2, check=True,
    )
    if len(result.stdout.encode()) > 16384:
        raise refused("native_codex_host_unverified")
    lines = result.stdout.splitlines()
    if not lines or lines[0] != f"p{pid}" or any(line.startswith("p") for line in lines[1:]):
        raise refused("native_codex_host_unverified")
    candidates = set()
    for line in lines[1:]:
        if not line.startswith("n/") or len(line) > 4097:
            continue
        path = Path(line[1:])
        try:
            if path != path.resolve(strict=True):
                continue
            _private(path.parent, stat.S_ISDIR)
            _private(path, stat.S_ISSOCK)
        except (OSError, BridgeError):
            continue
        candidates.add(path)
    if len(candidates) != 1:
        raise refused("native_codex_host_unverified")
    return candidates.pop()


class CodexHost:
    def __init__(self, *, socket_factory=None, connector=None):
        self.socket_factory = socket_factory or _socket
        self.connector = connector

    @asynccontextmanager
    async def connection(self, binding):
        # A timeout of the metadata observation cannot turn into an input retry.
        raw = None
        observation = asyncio.create_task(asyncio.to_thread(self.socket_factory, binding))
        try:
            try:
                raw, generation = await asyncio.shield(observation)
            except asyncio.CancelledError:
                # Metadata IO may still finish in its worker thread; close only
                # that observation's socket when it does, without opening RPC.
                observation.add_done_callback(_close_observed_socket)
                raise
            from websockets.asyncio.client import connect

            connector = self.connector or connect
            async with connector(
                "ws://localhost/", sock=raw, open_timeout=3, close_timeout=1,
                max_size=MAX_RESPONSE, ping_interval=None,
            ) as ws:
                rpc = _RPC(ws)
                initialized = await rpc.call(
                    "initialize",
                    {
                        "clientInfo": {"name": "kirabridge", "version": __version__},
                        "capabilities": {"experimentalApi": True},
                    },
                )
                if (
                    initialized.get("codexHome") != binding.codex_home
                    or not initialized.get("userAgent", "").startswith(
                        "codex-tui/" + binding.protocol_version + " "
                    )
                ):
                    raise refused("native_codex_host_unverified")
                await ws.send(json.dumps({"method": "initialized", "params": {}}))
                yield rpc, generation
        except BridgeError:
            raise
        except Exception as error:
            raise refused("native_codex_host_unavailable") from error
        finally:
            if raw is not None:
                raw.close()

    async def observe(self, rpc, generation, binding):
        result = await rpc.call(
            "thread/read", {"threadId": binding.thread_id, "includeTurns": False}
        )
        thread = result.get("thread", {})
        if (
            thread.get("id") != binding.thread_id
            or thread.get("sessionId") != binding.session_id
            or thread.get("source") != binding.source
            or "parentThreadId" not in thread
            or "attachedToThreadId" not in thread
            or thread.get("parentThreadId") is not None
            or thread.get("attachedToThreadId") is not None
            or thread.get("canAcceptDirectInput") is not True
        ):
            raise refused()
        status = thread.get("status", {})
        if status.get("type") not in {"active", "idle"} or status.get("activeFlags"):
            raise refused("native_codex_target_not_ready")
        if status["type"] == "active" and status.get("activeFlags") != []:
            raise refused("native_codex_target_not_ready")
        turns = await rpc.call(
            "thread/turns/list",
            {
                "threadId": binding.thread_id, "limit": 1,
                "sortDirection": "desc", "itemsView": "summary",
            },
        )
        rows = turns.get("data")
        if not isinstance(rows, list) or len(rows) > 1:
            raise refused("native_codex_target_not_ready")
        active = rows[0] if rows and rows[0].get("status") == "inProgress" else None
        if (status["type"] == "active") != bool(active):
            raise refused("native_codex_target_not_ready")
        if active is not None and (
            not isinstance(active.get("id"), str) or not active["id"]
        ):
            raise refused("native_codex_target_not_ready")
        return {
            "binding_sha256": digest(binding.model_dump()),
            "host_generation": generation,
            "thread_id": binding.thread_id,
            "session_id": binding.session_id,
            "expected_turn_id": active["id"] if active else None,
            "operation": "turn/steer" if active else "turn/start",
        }

    async def prepare(self, binding):
        async with self.connection(binding) as (rpc, generation):
            return await self.observe(rpc, generation, binding)

    async def deliver(self, binding, prepared, message_id, body, before_send):
        async with self.connection(binding) as (rpc, generation):
            current = await self.observe(rpc, generation, binding)
            # A host restart may refresh physical generation; a different turn
            # never changes a claimed steering attempt into another operation.
            for key in (
                "binding_sha256", "thread_id", "session_id", "operation", "expected_turn_id"
            ):
                if current[key] != prepared[key]:
                    raise refused("native_codex_target_changed")
            params = {
                "threadId": binding.thread_id,
                "clientUserMessageId": message_id,
                "input": [{"type": "text", "text": body, "text_elements": []}],
            }
            if current["expected_turn_id"] is not None:
                params["expectedTurnId"] = current["expected_turn_id"]
            await before_send(current)
            try:
                result = await rpc.call(current["operation"], params)
                turn_id = (
                    result.get("turnId")
                    if current["operation"] == "turn/steer"
                    else result.get("turn", {}).get("id")
                )
                if (
                    not isinstance(turn_id, str)
                    or not turn_id
                    or current["expected_turn_id"] is not None
                    and turn_id != current["expected_turn_id"]
                ):
                    raise ValueError("native turn response mismatch")
            except BaseException as error:
                # Includes cancellation and explicit rejection. Reconciliation
                # owns the original attempt; a new key never permits a replay.
                raise UncertainExecution(
                    "native_codex_delivery_unknown", "Reconcile the original native Codex attempt"
                ) from error
            return {
                **current,
                "turn_id": turn_id,
                "accepted_at": time.time(),
                "native_input_attempted": True,
                "terminal_input_attempted": False,
                "completion_scope": "native_input_delivery",
                "agent_confirmed": False,
                "agent_work_completion_verified": False,
                "request_reply_satisfied": False,
                "automatic_retry": False,
            }


class _RPC:
    def __init__(self, ws):
        self.ws, self.counter = ws, 0

    async def call(self, method, params):
        self.counter += 1
        identifier = self.counter
        async with asyncio.timeout(3):
            await self.ws.send(json.dumps({"id": identifier, "method": method, "params": params}))
            for _ in range(64):
                response = json.loads(await self.ws.recv())
                if not isinstance(response, dict) or "method" in response:
                    continue  # Never answer approvals or invoke server-requested tools.
                if response.get("id") != identifier:
                    continue
                if response.get("error") or not isinstance(response.get("result"), dict):
                    raise refused("native_codex_rpc_rejected")
                return response["result"]
        raise refused("native_codex_host_unavailable")


def _close_observed_socket(task):
    try:
        raw, _ = task.result()
    except BaseException:
        return
    raw.close()
