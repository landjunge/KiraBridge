"""Private, session-scoped Zsh ZLE readiness for KiraBridge-owned shells.

The channel never transmits BUFFER contents or its length. It reports only an
empty flag, cursor, editor context and the bound process/TTY identity.
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import re
import secrets
import shlex
import shutil
import socket
import stat
import struct
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError

_TOKEN = re.compile(r"^[0-9a-f]{48}$")
_TTY = re.compile(r"^/dev/ttys[0-9]+$")
_MAX_REPORT = 2048
_PROBE_TIMEOUT = 1.0
_TITLE_PREFIX = "KiraBridge_ZLE_"


def _start_token(value: str) -> str:
    fields = value.split()
    # detailed Darwin ps output: uid tty weekday month day hh:mm:ss year ppid comm
    if len(fields) < 9:
        raise BridgeError("zle_identity_unknown", "Shell process start time is unavailable")
    if not re.fullmatch(r"[A-Z][a-z]{2}", fields[2]) or not re.fullmatch(
        r"\d{2}:\d{2}:\d{2}", fields[5]
    ) or not re.fullmatch(r"\d{4}", fields[6]):
        raise BridgeError("zle_identity_unknown", "Shell process start time is malformed")
    return " ".join(fields[2:7])


def _tty_identity(path: str) -> tuple[int, int]:
    if not isinstance(path, str) or not _TTY.fullmatch(path):
        raise BridgeError("zle_identity_unknown", "Shell TTY is invalid")
    value = os.stat(path, follow_symlinks=False)
    if not stat.S_ISCHR(value.st_mode) or value.st_uid != os.getuid():
        raise BridgeError("zle_identity_unknown", "Shell TTY ownership is invalid")
    dev = value.st_dev
    if dev >= 1 << 63:
        dev -= 1 << 64
    return dev, value.st_ino


def _peer_identity(sock: socket.socket) -> tuple[int, int]:
    """Return kernel-authenticated (uid, pid) on Darwin; refuse other platforms."""
    if sys_platform() != "darwin":
        raise BridgeError("zle_peer_unsupported", "ZLE readiness requires Darwin credentials")
    try:
        peer_pid = struct.unpack("i", sock.getsockopt(0, 2, struct.calcsize("i")))[0]
        uid, gid = ctypes.c_uint32(), ctypes.c_uint32()
        getpeereid = ctypes.CDLL(None).getpeereid
        getpeereid.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        getpeereid.restype = ctypes.c_int
        if getpeereid(sock.fileno(), ctypes.byref(uid), ctypes.byref(gid)) != 0:
            raise OSError("getpeereid failed")
    except (AttributeError, OSError, struct.error) as error:
        raise BridgeError(
            "zle_peer_unverified", "Unix socket peer identity is unavailable"
        ) from error
    if peer_pid <= 1 or uid.value != os.getuid():
        raise BridgeError("zle_peer_unverified", "Unix socket peer is not the current user shell")
    return uid.value, peer_pid


def sys_platform():
    # Kept local so unit tests can validate the parser on non-Darwin hosts.
    import sys

    return sys.platform


def _zshrc() -> str:
    """Private startup widget. Its protocol excludes all command-line text."""
    return r'''zmodload zsh/net/socket 2>/dev/null || return
zmodload zsh/stat 2>/dev/null || return
setopt extendedglob
[[ -n $KB_ZLE_SOCKET && -n $KB_ZLE_NONCE && -n $KB_ZLE_GENERATION ]] || return
[[ $KB_ZLE_NONCE == [0-9a-f]## && $KB_ZLE_GENERATION == [0-9a-f]## ]] || return
typeset -a _kb_start_parts
_kb_start_parts=( ${(z)"$(LC_ALL=C /bin/ps -p $$ -o lstart= 2>/dev/null)"} )
(( ${#_kb_start_parts} == 5 )) || return
typeset -g KB_ZLE_START="${(j: :)_kb_start_parts}"
typeset -g KB_ZLE_PID=$$
typeset -g KB_ZLE_TTY=$TTY
zstat -H _kb_tty_stat -- "$KB_ZLE_TTY" 2>/dev/null || return
typeset -g KB_ZLE_TTY_DEV=$_kb_tty_stat[device]
typeset -g KB_ZLE_TTY_INO=$_kb_tty_stat[inode]
typeset -gi KB_ZLE_SEQUENCE=0
zsocket "$KB_ZLE_SOCKET" 2>/dev/null || return
typeset -g KB_ZLE_FD=$REPLY
_kb_zle_report() {
  local challenge="$1" context="$2" tab=$'\t'
  local -i cursor=$CURSOR empty=0
  [[ -z $BUFFER ]] && empty=1
  (( ++KB_ZLE_SEQUENCE ))
  local report="STATE${tab}${KB_ZLE_NONCE}${tab}${KB_ZLE_GENERATION}${tab}${KB_ZLE_SEQUENCE}"
  report+="${tab}${KB_ZLE_PID}${tab}${KB_ZLE_START}${tab}${KB_ZLE_TTY}"
  report+="${tab}${KB_ZLE_TTY_DEV}${tab}${KB_ZLE_TTY_INO}"
  report+="${tab}${empty}${tab}${cursor}${tab}${context}${tab}${challenge}"
  print -r -u "$KB_ZLE_FD" -- "$report"
}
_kb_zle_init() { _kb_zle_report '' "$CONTEXT"; }
_kb_zle_redraw() { _kb_zle_report '' "$CONTEXT"; }
_kb_zle_finish() { _kb_zle_report '' finish; }
_kb_zle_probe_fd() {
  local command challenge
  if ! IFS= read -r -u "$1" command; then
    zle -F "$1" 2>/dev/null
    return 1
  fi
  local -a fields
  fields=( ${(ps:\t:)command} )
  if (( ${#fields} == 3 )) && [[ $fields[1] == PROBE \
      && $fields[2] == $KB_ZLE_NONCE \
      && $fields[3] == [0-9a-f]## ]]; then
    _kb_zle_report "$fields[3]" "$CONTEXT"
  fi
}
zle -N zle-line-init _kb_zle_init
zle -N zle-line-pre-redraw _kb_zle_redraw
zle -N zle-line-finish _kb_zle_finish
zle -N _kb_zle_probe_fd
zle -F -w "$KB_ZLE_FD" _kb_zle_probe_fd 2>/dev/null
'''


@dataclass
class _ShellSession:
    generation: str
    nonce: str
    directory: Path
    socket_path: Path
    tag: str
    server: asyncio.AbstractServer | None = None
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    probe_ready: asyncio.Event = field(default_factory=asyncio.Event)
    writer: asyncio.StreamWriter | None = None
    handler: asyncio.Task | None = None
    peer_pid: int | None = None
    expected_pid: int | None = None
    pane_id: str | None = None
    tty: str | None = None
    tty_dev: int | None = None
    tty_inode: int | None = None
    start_time: str | None = None
    sequence: int = 0
    latest: dict | None = None
    challenge: str | None = None
    challenge_started: float | None = None


class ZLEReadiness:
    """Owns opt-in ZLE channels for shells explicitly opened by KiraBridge."""

    def __init__(self, terminal_app):
        self.terminal_app = terminal_app
        self.sessions: dict[str, _ShellSession] = {}

    async def create(self) -> dict:
        if sys_platform() != "darwin":
            raise BridgeError("zle_platform_unsupported", "ZLE shell integration requires macOS")
        generation, nonce = secrets.token_hex(24), secrets.token_hex(24)
        directory = Path(tempfile.mkdtemp(prefix=f"kbzle-{os.getuid()}-", dir="/tmp"))
        os.chmod(directory, 0o700)
        socket_path = directory / "s"
        tag = _TITLE_PREFIX + generation
        shell = _ShellSession(generation, nonce, directory, socket_path, tag)
        try:
            zshenv = "\n".join(
                f"export {name}={shlex.quote(value)}"
                for name, value in (
                    ("KB_ZLE_SOCKET", str(socket_path)),
                    ("KB_ZLE_NONCE", nonce),
                    ("KB_ZLE_GENERATION", generation),
                )
            )
            (directory / ".zshenv").write_text(zshenv + "\n", encoding="utf-8")
            os.chmod(directory / ".zshenv", 0o600)
            (directory / ".zshrc").write_text(_zshrc(), encoding="utf-8")
            os.chmod(directory / ".zshrc", 0o600)
            shell.server = await asyncio.start_unix_server(
                lambda reader, writer: self._serve(shell, reader, writer),
                path=str(socket_path),
                limit=_MAX_REPORT,
            )
            os.chmod(socket_path, 0o600)
            self.sessions[generation] = shell
        except BaseException:
            await self._cleanup(shell)
            raise
        return {
            "generation": generation,
            "nonce": nonce,
            "socket": str(socket_path),
            "zdotdir": str(directory),
            "tag": tag,
        }

    @staticmethod
    def is_managed(row) -> bool:
        return row.get("controlled_shell") is True

    async def _serve(self, session, reader, writer):
        sock = writer.get_extra_info("socket")
        try:
            if sock is None:
                raise BridgeError("zle_peer_unverified", "Unix peer socket unavailable")
            _, peer_pid = _peer_identity(sock)
            session.peer_pid = peer_pid
            session.writer = writer
            while line := await reader.readline():
                if len(line) > _MAX_REPORT:
                    raise BridgeError("zle_protocol_invalid", "ZLE report exceeds limit")
                self._record(session, line, peer_pid)
        except (BridgeError, asyncio.IncompleteReadError, OSError, ValueError):
            pass
        finally:
            if session.writer is writer:
                session.writer = None
                session.ready.clear()
                session.probe_ready.set()
                if self.sessions.get(session.generation) is session:
                    self.sessions.pop(session.generation, None)
                    await self._cleanup(session)
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, RuntimeError):
                pass

    def _record(self, session, raw, peer_pid):
        try:
            fields = raw.decode("ascii").rstrip("\r\n").split("\t")
            if len(fields) != 13 or fields[0] != "STATE":
                raise ValueError
            (
                _,
                nonce,
                generation,
                sequence,
                pid,
                start,
                tty,
                dev,
                inode,
                empty,
                cursor,
                context,
                challenge,
            ) = fields
            values = tuple(map(int, (sequence, pid, dev, inode, empty, cursor)))
            sequence, pid, dev, inode, empty, cursor = values
            if (
                nonce != session.nonce
                or generation != session.generation
                or pid != peer_pid
                or sequence <= session.sequence
                or sequence <= 0
                or not _TTY.fullmatch(tty)
                or not start
                or len(start) > 64
                or len(challenge) > 48
                or challenge and not _TOKEN.fullmatch(challenge)
                or challenge
                and (
                    challenge != session.challenge
                    or session.challenge_started is None
                    or time.monotonic() - session.challenge_started > _PROBE_TIMEOUT
                )
                or empty not in (0, 1)
                or cursor < 0
                or (empty and cursor != 0)
                or context not in {"start", "cont", "select", "vared", "finish"}
            ):
                raise ValueError
            # zsh/stat renders Darwin's signed dev_t as uint64.
            if dev >= 1 << 63:
                dev -= 1 << 64
            actual_dev, actual_inode = _tty_identity(tty)
            if (dev, inode) != (actual_dev, actual_inode):
                raise ValueError
            if session.expected_pid is not None and (
                pid != session.expected_pid
                or tty != session.tty
                or start != session.start_time
                or dev != session.tty_dev
                or inode != session.tty_inode
            ):
                raise ValueError
        except (UnicodeError, ValueError, OSError, BridgeError):
            raise BridgeError(
                "zle_report_rejected", "ZLE readiness identity or state was rejected"
            ) from None
        session.sequence = sequence
        session.latest = {
            "sequence": sequence,
            "pid": pid,
            "start": start,
            "tty": tty,
            "dev": dev,
            "inode": inode,
            "empty": bool(empty),
            "cursor": cursor,
            "context": context,
            "challenge": challenge,
            "observed_at": time.monotonic(),
        }
        session.ready.set()
        if (
            session.challenge
            and challenge == session.challenge
            and session.challenge_started is not None
            and time.monotonic() - session.challenge_started <= _PROBE_TIMEOUT
        ):
            session.probe_ready.set()

    async def bind(self, token, row):
        session = self.sessions.get(token.get("generation"))
        if session is None or row.get("controlled_shell") is not True:
            raise BridgeError("zle_session_unbound", "Controlled shell readiness tag is missing")
        try:
            pid, tty = row.get("expected_pid"), row.get("tty")
            if type(pid) is not int or not isinstance(tty, str):
                raise BridgeError("zle_identity_unknown", "Controlled shell identity is incomplete")
            identity = await self.terminal_app.process_identity(pid, detailed=True)
            parts = identity.split()
            if len(parts) < 9 or int(parts[0]) != os.getuid() or parts[1] != Path(tty).name:
                raise BridgeError(
                    "zle_identity_unknown", "Controlled shell process identity changed"
                )
            dev, inode = _tty_identity(tty)
            session.expected_pid, session.pane_id, session.tty = pid, row["pane_id"], tty
            session.tty_dev, session.tty_inode = dev, inode
            session.start_time = _start_token(identity)
            await asyncio.wait_for(session.ready.wait(), timeout=_PROBE_TIMEOUT)
        except TimeoutError:
            await self.close_session(session.generation)
            raise BridgeError("zle_not_ready", "Zsh ZLE did not publish an initial state") from None
        except BaseException:
            await self.close_session(session.generation)
            raise
        latest = session.latest or {}
        if (
            latest.get("pid") != pid
            or latest.get("tty") != tty
            or latest.get("start") != session.start_time
            or latest.get("context") != "start"
        ):
            await self.close_session(session.generation)
            raise BridgeError(
                "zle_identity_unknown", "Initial ZLE state does not match the shell"
            )

    async def probe(self, row):
        tag = row.get("controlled_shell") is True
        session = next(
            (
                item
                for item in self.sessions.values()
                if item.pane_id == row.get("pane_id")
                and item.expected_pid == row.get("expected_pid")
            ),
            None,
        )
        if (
            not tag
            or session is None
            or self.sessions.get(session.generation) is not session
            or session.writer is None
            or session.expected_pid is None
        ):
            raise BridgeError(
                "zle_session_stale", "Controlled shell readiness session is not active"
            )
        if (
            row.get("tty") != session.tty
            or row.get("expected_pid") != session.expected_pid
            or session.writer.is_closing()
        ):
            await self.close_session(session.generation)
            raise BridgeError("zle_identity_unknown", "Controlled shell pane/TTY/PID changed")
        identity = await self.terminal_app.process_identity(
            session.expected_pid, detailed=True
        )
        parts = identity.split()
        if (
            len(parts) < 9
            or int(parts[0]) != os.getuid()
            or parts[1] != Path(session.tty).name
            or _start_token(identity) != session.start_time
            or _tty_identity(session.tty) != (session.tty_dev, session.tty_inode)
        ):
            await self.close_session(session.generation)
            raise BridgeError("zle_identity_unknown", "Controlled shell generation changed")
        challenge = secrets.token_hex(24)
        session.challenge = challenge
        session.challenge_started = time.monotonic()
        session.probe_ready.clear()
        baseline = session.sequence
        session.writer.write(f"PROBE\t{session.nonce}\t{challenge}\n".encode("ascii"))
        try:
            await session.writer.drain()
            await asyncio.wait_for(session.probe_ready.wait(), timeout=_PROBE_TIMEOUT)
        except (OSError, TimeoutError):
            session.challenge = None
            session.challenge_started = None
            raise BridgeError("zle_state_stale", "Fresh ZLE state was not returned") from None
        latest = session.latest or {}
        session.challenge = None
        session.challenge_started = None
        if (
            latest.get("sequence", session.sequence) <= baseline
            or latest.get("challenge") != challenge
        ):
            raise BridgeError("zle_report_replay", "Fresh ZLE response was not unique")
        if (
            latest.get("context") != "start"
            or not latest.get("empty")
            or latest.get("cursor") != 0
        ):
            raise BridgeError("zle_input_not_empty", "Zsh ZLE reports existing or non-start input")
        return {"ready": True, "generation": session.generation, "sequence": session.sequence}

    async def close(self):
        sessions = tuple(self.sessions.values())
        self.sessions.clear()
        for session in sessions:
            await self._cleanup(session)

    async def close_session(self, generation):
        session = self.sessions.pop(generation, None)
        if session is not None:
            await self._cleanup(session)

    @staticmethod
    async def _cleanup(session):
        if session.server is not None:
            session.server.close()
            try:
                await session.server.wait_closed()
            except (OSError, RuntimeError):
                pass
            session.server = None
        if session.writer is not None:
            session.writer.close()
            try:
                await session.writer.wait_closed()
            except (OSError, RuntimeError):
                pass
            session.writer = None
        # Only remove the private, owner-controlled directory created above.
        try:
            info = session.directory.lstat()
            if (
                stat.S_ISDIR(info.st_mode)
                and info.st_uid == os.getuid()
                and session.directory.parent == Path("/tmp")
                and session.directory.name.startswith(f"kbzle-{os.getuid()}-")
            ):
                shutil.rmtree(session.directory)
        except FileNotFoundError:
            pass
