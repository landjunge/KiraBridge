"""Capture host Zsh's input and VT output on a new private PTY, within 25 seconds.

Manual Intel fixture. It never addresses Terminal.app, existing TTYs, installed
configuration or user profiles. The parent operator chooses where to run it.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import json
import os
import platform
import pty
import re
import select
import shlex
import signal
import struct
import subprocess
import termios
import time
from pathlib import Path

PROMPT = "KB_ZLE_WIRE_PROMPT> "
WORK_SECONDS = 22.0  # Reserve the remaining three seconds for owned-child cleanup.
BYTE_LIMIT = 1_048_576


def probe(root):
    if (platform.system(), platform.machine()) != ("Darwin", "x86_64"):
        raise RuntimeError("This manual fixture requires the Intel Mac")
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    dotdir = root / "empty-zdotdir"
    dotdir.mkdir(mode=0o700)
    started = time.monotonic()
    deadline = started + WORK_SECONDS
    term = os.environ.get("TERM", "xterm-256color")
    if not term or len(term) > 128 or any(ord(c) < 32 for c in term):
        raise ValueError("Invalid inherited TERM")
    environment = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(root),
        "ZDOTDIR": str(dotdir),
        "HISTFILE": str(root / "history"),
        "TERM": term,
        "LC_ALL": "C",
        "LANG": "C",
        "PS1": PROMPT,
        "PS2": "KB_ZLE_WIRE_CONT> ",
        "SHELL": "/bin/zsh",
    }
    evidence = {
        "state": "in_progress",
        "scope": "only a newly forked private PTY child; no Terminal.app UI access",
        "platform": platform.platform(),
        "term": term,
        "term_inherited": "TERM" in os.environ,
        "argv": ["/bin/zsh", "-f", "-d", "-i"],
        "profiles": "private HOME/ZDOTDIR; -f/-d; compiled mandatory zshenv may still run",
        "rows": 24,
        "columns": 80,
        "phases": [],
    }
    master = None
    child = None
    status = None
    total_received = 0

    def remaining(maximum):
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("Private ZLE probe work deadline exceeded")
        return min(left, maximum)

    def save():
        evidence["elapsed_seconds"] = time.monotonic() - started
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")

    def record(label, sent, received):
        item = {
            "label": label,
            "sent_hex": sent.hex(),
            "sent_escaped": repr(sent),
            "received_hex": received.hex(),
            "received_escaped": repr(received),
            "received_bytes": len(received),
            "literal_space_count": received.count(b" "),
            "backspace_count": received.count(b"\x08"),
            "carriage_return_count": received.count(b"\r"),
            "erase_sequences_hex": [m.hex() for m in re.findall(rb"\x1b\[[0-2]?[KJ]", received)],
            "wire_sha256": hashlib.sha256(received).hexdigest(),
        }
        evidence["phases"].append(item)
        (root / (label + ".bin")).write_bytes(received)
        save()
        return item

    def read_chunk(timeout):
        nonlocal total_received
        ready, _, _ = select.select([master], [], [], remaining(timeout))
        if not ready:
            return b""
        try:
            raw = os.read(master, 65536)
        except OSError as error:
            if error.errno == errno.EIO:
                return b""
            raise
        total_received += len(raw)
        if total_received > BYTE_LIMIT:
            raise RuntimeError("Private ZLE output exceeded its byte budget")
        return raw

    def drain(quiet=0.12):
        result = bytearray()
        while True:
            raw = read_chunk(quiet)
            if not raw:
                return bytes(result)
            result.extend(raw)

    def exchange(label, sent, *, expect=None):
        if sent:
            written = os.write(master, sent)
            if written != len(sent):
                raise RuntimeError("Partial private fixture write; do not repeat")
        result = bytearray()
        if expect is not None:
            until = time.monotonic() + remaining(3.0)
            while expect not in result:
                if time.monotonic() >= until:
                    raise TimeoutError("Private ZLE prompt/setup not observed")
                result.extend(read_chunk(min(0.1, until - time.monotonic())))
        result.extend(drain())
        record(label, sent, bytes(result))

    def buffer_witness(label, expected):
        for name in ("buffer", "postdisplay", "cursor", "ready"):
            (root / (name + ".txt")).unlink(missing_ok=True)
        exchange(label + "-widget", b"\x18\x02")
        ready = root / "ready.txt"
        until = time.monotonic() + remaining(1.0)
        while not ready.exists() or ready.read_text() != "complete\n":
            if time.monotonic() >= until:
                raise TimeoutError("Private ZLE witness not completed")
            time.sleep(min(0.01, remaining(0.01)))
        values = {
            name: (root / (name + ".txt")).read_text().removesuffix("\n")
            for name in ("buffer", "postdisplay", "cursor")
        }
        evidence["phases"][-1]["zle_witness"] = values
        save()
        if values["buffer"] != expected:
            raise AssertionError(f"Private buffer mismatch: {values!r}")
        return values

    try:
        version = subprocess.run(
            ["/bin/zsh", "--version"],
            env=environment,
            capture_output=True,
            check=True,
            timeout=remaining(1.0),
        )
        evidence["zsh_version"] = version.stdout.decode().strip()
        child, master = pty.fork()
        if child == 0:
            try:
                os.chdir(root)
                os.execve("/bin/zsh", evidence["argv"], environment)
            except BaseException:
                os._exit(127)
        evidence["owned_child_pid"] = child
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        exchange("startup", b"", expect=PROMPT.encode())
        # The prompt proves the child completed pty.fork's session setup. Checking
        # immediately after fork would race the child's setsid call.
        evidence["owned_session_id"] = os.getsid(child)
        if evidence["owned_session_id"] != child:
            raise RuntimeError("Private PTY child session identity unconfirmed")
        setup = (
            "bindkey -e; function _kb_wire_probe() { "
            'builtin print -r -- "$BUFFER" > '
            + shlex.quote(str(root / "buffer.txt"))
            + '; builtin print -r -- "${POSTDISPLAY-}" > '
            + shlex.quote(str(root / "postdisplay.txt"))
            + '; builtin print -r -- "$CURSOR" > '
            + shlex.quote(str(root / "cursor.txt"))
            + "; builtin print -r -- complete > "
            + shlex.quote(str(root / "ready.txt"))
            + "; }; zle -N _kb_wire_probe; bindkey '^X^B' _kb_wire_probe; "
            + "bindkey '^U'; builtin print -r -- KB_ZLE_WIRE_SETUP_DONE"
        )
        exchange("setup", setup.encode() + b"\n", expect=b"\r\nKB_ZLE_WIRE_SETUP_DONE\r\n")
        buffer_witness("initial-empty", "")

        # No probe widget runs between insertion and Ctrl-U in this first pair.
        exchange("original-insert", b"# KB_ACCEPT_RACE")
        exchange("original-ctrl-u", b"\x15")
        buffer_witness("original-cleared", "")

        long_text = "abcdefghijklmnopqrstuvwx"
        exchange("long-insert", long_text.encode())
        buffer_witness("long-before-delete", long_text)
        exchange("five-backspaces", b"\x7f" * 5)
        buffer_witness("shortened-buffer", long_text[:-5])
        exchange("shortened-ctrl-u", b"\x15")
        buffer_witness("shortened-cleared", "")

        exchange("short-insert", b"abc")
        exchange("short-ctrl-u", b"\x15")
        buffer_witness("short-cleared", "")
        evidence["checks_complete"] = True
        # Exit only after the last actual BUFFER witness confirmed emptiness.
        exchange("owned-child-exit", b"exit\n")
        until = time.monotonic() + remaining(1.0)
        while status is None and time.monotonic() < until:
            observed, value = os.waitpid(child, os.WNOHANG)
            if observed == child:
                status = value
                break
            time.sleep(0.01)
        if status is None:
            raise TimeoutError("Owned fixture did not exit")
        if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
            raise RuntimeError("Owned fixture exited unsuccessfully")
    except BaseException as error:
        evidence["state"] = "failed"
        evidence["error"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        if child not in (None, 0) and status is None:
            # A non-reaped child PID cannot be recycled. Never signal an existing
            # session or a PID found through catalogue/search heuristics.
            evidence["cleanup_signals"] = []
            for sig in (signal.SIGHUP, signal.SIGKILL):
                observed, value = os.waitpid(child, os.WNOHANG)
                if observed == child:
                    status = value
                    break
                if os.getsid(child) != child:
                    evidence["cleanup_identity_error"] = True
                    break
                os.kill(child, sig)
                evidence["cleanup_signals"].append(sig.name)
                until = min(started + 24.8, time.monotonic() + 0.3)
                while time.monotonic() < until:
                    observed, value = os.waitpid(child, os.WNOHANG)
                    if observed == child:
                        status = value
                        break
                    time.sleep(0.01)
                if status is not None:
                    break
        if master is not None:
            os.close(master)
        evidence["child_reaped"] = child is None or status is not None
        evidence["child_wait_status"] = status
        if evidence.get("state") != "failed":
            evidence["state"] = "passed" if evidence["child_reaped"] else "failed"
        save()
    print(json.dumps({"state": evidence["state"], "evidence": str(root / "evidence.json")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    options = parser.parse_args()
    probe(options.root.resolve())
