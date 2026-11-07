from __future__ import annotations

import os
import shutil
import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from kirabridge.bridge_core.models import BridgeError, UncertainExecution


class PlatformAdapter(Protocol):
    name: str

    def clipboard_command(self, write: bool) -> list[str]: ...


class MacOSAdapter:
    name = "macos"

    def clipboard_command(self, write: bool) -> list[str]:
        return ["/usr/bin/pbcopy" if write else "/usr/bin/pbpaste"]


class LinuxAdapter:
    name = "linux"

    def clipboard_command(self, write: bool) -> list[str]:
        if os.environ.get("WAYLAND_DISPLAY"):
            executable = shutil.which("wl-copy" if write else "wl-paste")
            args = ["--type", "text/plain;charset=utf-8"] if write else ["--no-newline"]
        else:
            executable = shutil.which("xclip")
            args = ["-selection", "clipboard", "-in" if write else "-out"]
        if not executable:
            raise BridgeError("clipboard_unavailable", "Install wl-clipboard or xclip")
        return [executable, *args]

    def server_facts(self) -> dict:
        """Headless server limits. This is not a claim of macOS desktop parity."""
        try:
            self.clipboard_command(False)
            clipboard = "optional-tool"
        except BridgeError:
            clipboard = "unavailable"
        return {
            "role": "linux-server",
            "gui_parity": False,
            "mcp_http": "available",
            "authentication": "bearer",
            "health": "bridge_health",
            "service_manager": "systemd-user" if shutil.which("systemctl") else "unavailable",
            "desktop_gui": "unavailable",
            "macos_terminal_app": "unavailable",
            "native_keyboard": "unavailable",
            "clipboard": clipboard,
            "clipboard_required_for_server": False,
        }


class WindowsAdapter:
    name = "windows"

    def clipboard_command(self, write: bool) -> list[str]:
        raise BridgeError(
            "unsupported_platform", "Windows native clipboard adapter is an extension"
        )


def current_platform() -> PlatformAdapter:
    if sys.platform == "darwin":
        return MacOSAdapter()
    if sys.platform.startswith("linux"):
        return LinuxAdapter()
    return WindowsAdapter()


def subprocess_options() -> dict:
    if os.name == "posix":
        return {"start_new_session": True}
    raise BridgeError("unsupported_platform", "A Windows process-tree adapter is required")


@dataclass(frozen=True)
class _OwnedSession:
    sid: int
    uid: int


def _pin_owned_session(process) -> None:
    # Only spawn_process calls this, for its own start_new_session child. A
    # supplied PID, ancestry guess or already-exited leader cannot grant scope.
    try:
        if (
            process.returncode is None
            and process.pid > 1
            and os.getsid(process.pid) == os.getpgid(process.pid) == process.pid
            and process.pid not in {os.getsid(0), os.getpgrp()}
        ):
            process._kirabridge_owned_session = _OwnedSession(process.pid, os.geteuid())
    except ProcessLookupError:
        pass


def _session_members(process, pin):
    """Bounded public metadata only; no arguments, environment or ancestry grants."""
    import subprocess

    if (
        pin.sid != process.pid
        or pin.sid <= 1
        or pin.sid in {os.getsid(0), os.getpgrp()}
        or pin.uid != os.geteuid()
    ):
        raise UncertainExecution("process_cleanup_unknown", "Owned session identity changed")
    try:
        result = subprocess.run(
            ["/bin/ps", "-axo", "pid=,uid=,pgid=,stat="],
            capture_output=True,
            text=True,
            timeout=0.5,
            check=False,
        )
        if result.returncode or result.stderr or len(result.stdout) > 2 * 1024 * 1024:
            raise ValueError("Incomplete process census")
        rows, seen, caller_observed = [], set(), False
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) != 4 or len(rows) >= 100000:
                raise ValueError("Malformed process census")
            pid, uid, group = map(int, parts[:3])
            if pid == 0:  # Kernel task is outside this positive-PID interface.
                continue
            if pid < 0 or pid in seen:
                raise ValueError("Duplicate process identity")
            seen.add(pid)
            if pid == os.getpid():
                if uid != os.geteuid() or group != os.getpgrp() or parts[3].startswith("Z"):
                    raise ValueError("Caller process census identity changed")
                caller_observed = True
            try:
                sid = os.getsid(pid)
            except ProcessLookupError:
                continue  # This observed process is now absent, not unidentified.
            if pid == pin.sid and process.returncode is not None:
                raise ValueError("Reused session leader PID")
            if sid == pin.sid:
                try:
                    if group != os.getpgid(pid):
                        raise ValueError("Changing process group")
                except ProcessLookupError:
                    continue
            rows.append((pid, uid, group, sid, parts[3]))
        if not caller_observed:
            raise ValueError("Process census lacks its live caller anchor")
        members = tuple(row for row in rows if row[3] == pin.sid)
        groups = {row[2] for row in members if not row[4].startswith("Z")}
        if len(members) > 4096 or len(groups) > 128:
            raise ValueError("Owned session exceeds cleanup budget")
        if any(group <= 1 or group == os.getpgrp() for group in groups):
            raise ValueError("Protected process group")
        # A PGID cannot legitimately span sessions. Do not signal on a partial
        # ownership observation, including a foreign-UID member of the same group.
        if any(row[1] != pin.uid or row[3] != pin.sid for row in rows if row[2] in groups):
            raise ValueError("Unconfirmed session/group ownership")
        return members
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        raise UncertainExecution(
            "process_cleanup_unknown", "Owned process session cannot be confirmed"
        ) from error


async def _owned_session_groups(process, pin):
    import asyncio

    return await asyncio.to_thread(_session_members, process, pin)


async def _signal_owned_session(process, pin, value):
    members = await _owned_session_groups(process, pin)
    groups = {row[2] for row in members if not row[4].startswith("Z")}
    for group in sorted(groups):
        # No await between these final positive identity checks and the syscall.
        # Public killpg is still not an atomic session/start-token operation.
        if group <= 1 or group == os.getpgrp() or pin.sid == os.getsid(0):
            raise UncertainExecution("process_cleanup_unknown", "Protected cleanup group")
        current_members = 0
        for pid, uid, pgid, sid, _state in members:
            if pgid != group:
                continue
            if uid != pin.uid or sid != pin.sid:
                raise UncertainExecution("process_cleanup_unknown", "Session ownership changed")
            try:
                if os.getsid(pid) != pin.sid or os.getpgid(pid) != group:
                    raise UncertainExecution(
                        "process_cleanup_unknown", "Session membership changed"
                    )
                current_members += 1
            except ProcessLookupError:
                continue
        if not current_members:
            continue  # Never signal a stale numeric PGID after its last anchor exited.
        try:
            os.killpg(group, value)
        except ProcessLookupError:
            pass
        except PermissionError as error:
            # Darwin may refuse a group that became entirely zombie/absent.
            # Only a fresh verified observation can establish that no live member
            # still needs termination; EPERM alone never proves cleanup.
            current = await _owned_session_groups(process, pin)
            if any(row[2] == group and not row[4].startswith("Z") for row in current):
                raise UncertainExecution(
                    "process_cleanup_unknown", "Session signal refused"
                ) from error


async def _stop_owned_session(process, pin, grace):
    import asyncio

    await _signal_owned_session(process, pin, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), grace)
    except TimeoutError:
        pass
    await _signal_owned_session(process, pin, signal.SIGKILL)
    await process.wait()
    if any(not row[4].startswith("Z") for row in await _owned_session_groups(process, pin)):
        raise UncertainExecution(
            "process_cleanup_unknown", "Owned session still has live processes"
        )


async def spawn_process(
    argv: list[str], cwd_fd: int, env: dict, *, stdin, stdout, stderr, limit: int = 1048576
):
    import asyncio

    subprocess_options()  # Fail closed on platforms without an adapter.
    read_fd, write_fd = os.pipe()
    process = None
    transport = None
    try:
        creation = asyncio.create_task(
            asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                str(Path(__file__).with_name("_exec.py")),
                str(cwd_fd),
                str(write_fd),
                *argv,
                pass_fds=(cwd_fd, write_fd),
                env=env,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                limit=limit,
                **subprocess_options(),
            )
        )
        try:
            process = await asyncio.shield(creation)
        except asyncio.CancelledError:
            while not creation.done():
                try:
                    await asyncio.shield(creation)
                except asyncio.CancelledError:
                    pass
            process = creation.result()
            _pin_owned_session(process)
            raise
        _pin_owned_session(process)
        os.close(write_fd)
        write_fd = -1
        reader = asyncio.StreamReader(limit=1024)
        transport, _ = await asyncio.get_running_loop().connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), os.fdopen(read_fd, "rb")
        )
        read_fd = -1
        async with asyncio.timeout(10):
            error = await reader.read(1024)
        if error:
            raise BridgeError("spawn_failed", "Configured executable could not be started")
        return process
    except BaseException as exc:
        if process:
            await reap_process(process)
            if not isinstance(exc, (BridgeError, asyncio.CancelledError)):
                raise UncertainExecution(
                    "spawn_unknown", "Process startup outcome is unknown"
                ) from exc
        raise
    finally:
        if transport:
            transport.close()
        for fd in (read_fd, write_fd):
            if fd != -1:
                os.close(fd)


async def stop_process(process, grace: float = 2.0) -> None:
    import asyncio

    pin = getattr(process, "_kirabridge_owned_session", None)
    if isinstance(pin, _OwnedSession):
        return await _stop_owned_session(process, pin, grace)

    async def signal_group(value):
        try:
            os.killpg(process.pid, value)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # Darwin can report EPERM for an orphaned group containing only zombies.
            # Verify group membership instead of silently ignoring a live process.
            import subprocess

            result = await asyncio.to_thread(
                subprocess.run,
                ["/bin/ps", "-o", "stat=", "-g", str(process.pid)],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if result.returncode not in {0, 1} or any(
                line.strip() and not line.strip().startswith("Z")
                for line in result.stdout.splitlines()
            ):
                raise
            return False

    if not await signal_group(signal.SIGTERM):
        await process.wait()
        return
    # The group can outlive its leader. Do not confuse leader exit with tree termination.
    try:
        await asyncio.wait_for(process.wait(), grace)
    except TimeoutError:
        try:
            await signal_group(signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
    try:
        await signal_group(signal.SIGKILL)
    except ProcessLookupError:
        pass


async def _reap_worker_process(process) -> None:
    """Reap an exact created worker handle, never its containing process group."""
    import asyncio

    async def discard(reader):
        if reader is not None:
            while await reader.read(8192):
                pass

    async def cleanup():
        try:
            async with asyncio.timeout(5):
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                stdin = getattr(process, "stdin", None)
                if stdin is not None:
                    stdin.close()
                    try:
                        await stdin.wait_closed()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                await asyncio.gather(
                    discard(getattr(process, "stdout", None)),
                    discard(getattr(process, "stderr", None)),
                    process.wait(),
                )
        except TimeoutError:
            # Own pipes only; no PID/PGID search, descendant signals or unbounded wait.
            process._transport.close()
            raise BridgeError(
                "process_cleanup_unknown", "Worker cleanup could not be confirmed"
            ) from None

    reaping = asyncio.create_task(cleanup())
    cancelled = isinstance(sys.exc_info()[1], asyncio.CancelledError)
    while not reaping.done():
        try:
            await asyncio.shield(reaping)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if cancelled:
        # Retrieve a possible failure without losing the caller's cancellation.
        if not reaping.cancelled():
            reaping.exception()
        raise asyncio.CancelledError
    reaping.result()


async def reap_process(process, *, process_group=True) -> None:
    """Call only after other stream readers stop; drain pipes to avoid transport leaks."""
    import asyncio

    if not process_group:
        return await _reap_worker_process(process)

    async def discard(reader):
        if reader is not None:
            while await reader.read(8192):
                pass

    async def cleanup():
        stopping = asyncio.create_task(stop_process(process))
        drains = [
            asyncio.create_task(discard(process.stdout)),
            asyncio.create_task(discard(process.stderr)),
        ]
        try:
            async with asyncio.timeout(5):
                if process.stdin is not None:
                    process.stdin.close()
                    try:
                        await process.stdin.wait_closed()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                await asyncio.gather(stopping, *drains)
        except TimeoutError:
            # Close only our transport; a child that changed SID remains unknown.
            process._transport.close()
            raise UncertainExecution(
                "process_cleanup_unknown", "Process cleanup could not be confirmed"
            ) from None
        except BaseException:
            process._transport.close()
            raise
        finally:
            for task in [stopping, *drains]:
                if not task.done():
                    task.cancel()
            await asyncio.gather(stopping, *drains, return_exceptions=True)

    reaping = asyncio.create_task(cleanup())
    cancelled = isinstance(sys.exc_info()[1], asyncio.CancelledError)
    while not reaping.done():
        try:
            await asyncio.shield(reaping)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if cancelled:
        if not reaping.cancelled():
            reaping.exception()
        raise asyncio.CancelledError
    reaping.result()


class RuntimeLock:
    """Only a dispatcher holds this lock; administrative CLI transactions remain possible."""

    def __init__(self, path: Path):
        self.path, self.fd = path, None
        self._windows = None

    def acquire(self) -> None:
        if os.name == "nt":
            from kirabridge.platform_adapters.windows.locking import WindowsRuntimeLock

            if self._windows is None:
                self._windows = WindowsRuntimeLock(self.path)
            self._windows.acquire()
            return
        if os.name != "posix":
            raise BridgeError("unsupported_platform", "Runtime locking needs a Windows adapter")
        import fcntl

        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise BridgeError(
                "already_running", "A dispatcher already owns this state directory"
            ) from None
        self.fd = fd

    def release(self) -> None:
        if self._windows is not None:
            self._windows.release()
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
