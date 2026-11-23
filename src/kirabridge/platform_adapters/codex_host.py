"""Bounded RPC to an assigned root on the existing Codex 0.169/0.171 Unix WebSocket.

No host start, discovery by title/CWD, terminal input or input retry. Assignment
is configuration authority; host responses prove its current local continuity.
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import re
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
MAX_ANSWER_BYTES = 262144


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
        if (opened.st_dev, opened.st_ino) != (
            record.st_dev,
            record.st_ino,
        ) or opened.st_size > 16384:
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
            or not _same_host_line(binding, _process_path(pid))
            or not fields[6].startswith(_process_path(pid) + " app-server ")
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


_RELEASE = re.compile(r"^(\d+)\.(\d+)\.(\d+)-([a-z0-9_]+-apple-darwin)$")


def _same_host_line(binding, actual):
    """Verify the pinned managed install with its version-specific compatibility rule.

    Never trusts a path outside CODEX_HOME/packages/app-server-daemon/releases/<v>/bin/codex.
    The established 0.169 line remains patch-tolerant; the new 0.171 pin is exact.
    """
    if binding.protocol_version == "0.171.0":
        return actual == binding.host_executable and _is_exact_0171_release(binding, actual)
    if actual == binding.host_executable:
        return True
    releases = Path(binding.codex_home) / "packages" / "app-server-daemon" / "releases"
    found, pinned = Path(actual), Path(binding.host_executable)
    try:
        if (
            found != found.resolve(strict=True)
            or found.name != "codex"
            or found.parent.name != "bin"
        ):
            return False
        a, b = found.parent.parent, pinned.parent.parent
        if a.parent != releases or b.parent != releases:
            return False
        left, right = _RELEASE.match(a.name), _RELEASE.match(b.name)
    except OSError:
        return False
    return bool(left and right and left.group(1, 2, 4) == right.group(1, 2, 4))


def _is_exact_0171_release(binding, path):
    candidate = Path(path)
    releases = Path(binding.codex_home) / "packages" / "app-server-daemon" / "releases"
    try:
        if (
            candidate != candidate.resolve(strict=True)
            or candidate.name != "codex"
            or candidate.parent.name != "bin"
            or candidate.parent.parent.parent != releases
        ):
            return False
        match = _RELEASE.match(candidate.parent.parent.name)
    except OSError:
        return False
    return bool(match and match.group(1, 2, 3) == ("0", "171", "0"))


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
        capture_output=True,
        text=True,
        timeout=2,
        check=True,
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
                "ws://localhost/",
                sock=raw,
                open_timeout=3,
                close_timeout=1,
                max_size=MAX_RESPONSE,
                ping_interval=None,
            ) as ws:
                rpc = _RPC(ws)
                initialized = await rpc.call(
                    "initialize",
                    {
                        "clientInfo": {"name": "kirabridge", "version": __version__},
                        "capabilities": {"experimentalApi": True},
                    },
                )
                agent = re.match(
                    r"^codex-tui/(\d+)\.(\d+)\.(\d+) ", initialized.get("userAgent", "")
                )
                wanted = binding.protocol_version.split(".")[:2]
                if (
                    initialized.get("codexHome") != binding.codex_home
                    or agent is None
                    or list(agent.groups()[:2]) != wanted
                    or binding.protocol_version == "0.171.0"
                    and ".".join(agent.groups()) != binding.protocol_version
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

    async def read_bound_thread(self, rpc, binding, *, cwd=None):
        result = await rpc.call(
            "thread/read", {"threadId": binding.thread_id, "includeTurns": False}
        )
        thread = result.get("thread", {})
        self._verify_thread(thread, binding, cwd)
        return thread

    @staticmethod
    def _verify_thread(thread, binding, cwd):
        thread_cwd = thread.get("cwd") if isinstance(thread, dict) else None
        if (
            not isinstance(thread, dict)
            or thread.get("id") != binding.thread_id
            or thread.get("sessionId") != binding.session_id
            or thread.get("source") != binding.source
            or "parentThreadId" not in thread
            or "attachedToThreadId" not in thread
            or thread.get("parentThreadId") is not None
            or thread.get("attachedToThreadId") is not None
            or (
                not isinstance(thread_cwd, str)
                or not Path(thread_cwd).is_absolute()
                or cwd is not None
                and Path(thread_cwd).resolve() != Path(cwd)
            )
        ):
            raise refused()

    async def observe(self, rpc, generation, binding, *, cwd=None, resume=False):
        thread = await self.read_bound_thread(rpc, binding, cwd=cwd)
        thread_cwd = str(Path(thread["cwd"]).resolve())
        status = thread.get("status", {})
        if not isinstance(status, dict):
            raise refused("native_codex_target_not_ready")
        if (
            resume
            and binding.protocol_version == "0.171.0"
            and status.get("type") == "notLoaded"
            and thread.get("ephemeral") is False
        ):
            # Restore from Codex's own persisted history. Do not supply a path,
            # alternate history, or overrides that could change the resumed thread.
            restored = await rpc.call(
                "thread/resume", {"threadId": binding.thread_id, "excludeTurns": True}
            )
            self._verify_thread(restored.get("thread"), binding, thread_cwd)
            thread = await self.read_bound_thread(rpc, binding, cwd=thread_cwd)
            status = thread.get("status", {})
        if thread.get("canAcceptDirectInput") is not True:
            raise refused()
        if not isinstance(status, dict):
            raise refused("native_codex_target_not_ready")
        if status.get("type") not in {"active", "idle"} or status.get("activeFlags"):
            raise refused("native_codex_target_not_ready")
        if status["type"] == "active" and status.get("activeFlags") != []:
            raise refused("native_codex_target_not_ready")
        turns = await rpc.call(
            "thread/turns/list",
            {
                "threadId": binding.thread_id,
                "limit": 1,
                "sortDirection": "desc",
                "itemsView": "summary",
            },
        )
        rows = turns.get("data")
        if not isinstance(rows, list) or len(rows) > 1:
            raise refused("native_codex_target_not_ready")
        active = rows[0] if rows and rows[0].get("status") == "inProgress" else None
        if (status["type"] == "active") != bool(active):
            raise refused("native_codex_target_not_ready")
        if active is not None and (not isinstance(active.get("id"), str) or not active["id"]):
            raise refused("native_codex_target_not_ready")
        return {
            "binding_sha256": digest(binding.model_dump()),
            "host_generation": generation,
            "thread_id": binding.thread_id,
            "session_id": binding.session_id,
            "thread_cwd": thread_cwd,
            "expected_turn_id": active["id"] if active else None,
            "operation": "turn/steer" if active else "turn/start",
        }

    async def prepare(self, binding):
        async with self.connection(binding) as (rpc, generation):
            return await self.observe(rpc, generation, binding, resume=True)

    async def deliver(self, binding, prepared, message_id, body, before_send):
        async with self.connection(binding) as (rpc, generation):
            current = await self.observe(rpc, generation, binding)
            # A host restart may refresh physical generation; a different turn
            # never changes a claimed steering attempt into another operation.
            for key in (
                "binding_sha256",
                "thread_id",
                "session_id",
                "thread_cwd",
                "operation",
                "expected_turn_id",
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

    async def wait_reply(self, binding, turn_id, body, timeout, *, cwd=None):
        """Observe the exact submitted turn and return its unambiguous final text."""
        async with asyncio.timeout(timeout):
            async with self.connection(binding) as (rpc, _):
                await self.read_bound_thread(rpc, binding, cwd=cwd)
                while True:
                    turns = await rpc.call(
                        "thread/turns/list",
                        {
                            "threadId": binding.thread_id,
                            "limit": 8,
                            "sortDirection": "desc",
                            "itemsView": "full",
                        },
                    )
                    turn = next(
                        (row for row in turns.get("data", []) if row.get("id") == turn_id),
                        None,
                    )
                    if turn is not None and turn.get("status") != "inProgress":
                        return _verified_answer(turn, body)
                    await asyncio.sleep(1)


def _verified_answer(turn, body):
    items = turn.get("items", [])
    if isinstance(items, list) and all(isinstance(item, dict) for item in items):
        users = [index for index, item in enumerate(items) if item.get("type") == "userMessage"]
        finals = [
            index
            for index, item in enumerate(items)
            if item.get("type") == "agentMessage" and item.get("phase") == "final_answer"
        ]
        if turn.get("status") == "completed" and len(users) == len(finals) == 1:
            content = items[users[0]].get("content")
            text = items[finals[0]].get("text")
            if (
                users[0] < finals[0]
                and isinstance(content, list)
                and len(content) == 1
                and isinstance(content[0], dict)
                and content[0].get("type") == "text"
                and content[0].get("text") == body
                and not content[0].get("text_elements")
                and isinstance(text, str)
                and text.strip()
                and len(text.encode("utf-8")) <= MAX_ANSWER_BYTES
            ):
                return text
    raise UncertainExecution(
        "native_codex_turn_unverified", "The native turn has no exact verified answer"
    )


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
