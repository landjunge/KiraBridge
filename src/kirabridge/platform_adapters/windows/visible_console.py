"""Visible Windows console handoff. Output is shown and returned, never hidden.

The window is a new console running this same Python. Its import is pinned to
the activated runtime, not to an older installation on sys.path. PowerShell
execution policy is not read or changed. A completed handoff id is not started
again.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.platform_adapters.windows.apps import (
    CREATE_NEW_CONSOLE,
    CREATE_NO_WINDOW,
    CREATE_UNICODE_ENVIRONMENT,
    DETACHED_PROCESS,
    STARTF_USESHOWWINDOW,
    SW_SHOWNORMAL,
    quote_windows,
)

ENV_ALLOW = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "LOCALAPPDATA",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
)
FORBIDDEN_TOKENS = frozenset(
    {"executionpolicy", "-executionpolicy", "bypass", "-enc", "-encodedcommand", "-w", "hidden"}
)
RESULT_LIMIT = 65536
BOOTSTRAP = (
    "import hashlib, sys\n"
    "from pathlib import Path\n"
    "argv = sys.argv[1:]\n"
    "if argv[:1] != ['--'] or len(argv) < 8:\n"
    "    raise SystemExit(2)\n"
    "runtime, expected = argv[1], argv[2]\n"
    "root = Path(runtime)\n"
    "if not root.is_absolute() or root.is_symlink():\n"
    "    raise SystemExit(3)\n"
    "sys.path = [str(root)] + [item for item in sys.path if item not in ('', str(root))]\n"
    "import kirabridge.platform_adapters.windows.visible_console as visible\n"
    "source = Path(visible.__file__).resolve()\n"
    "if root.resolve() not in source.parents:\n"
    "    raise SystemExit(4)\n"
    "digest = hashlib.sha256(source.read_bytes()).hexdigest()\n"
    "if digest != expected:\n"
    "    raise SystemExit(5)\n"
    "raise SystemExit(visible.console_main(argv))\n"
)


def visible_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    """Keep the Windows process environment small. Do not copy credentials."""
    source = os.environ if source is None else source
    env = {key: source[key] for key in ENV_ALLOW if key in source and source[key]}
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def runtime_identity() -> dict[str, str]:
    """Identity of the kirabridge package this process actually imported."""
    import kirabridge
    from kirabridge.platform_adapters.windows import visible_console as module

    package = Path(kirabridge.__file__).resolve()
    source = Path(module.__file__).resolve()
    root = package.parent.parent.resolve()
    if root not in source.parents:
        raise BridgeError(
            "windows_console_runtime", "Imported console source is outside the package root"
        )
    return {
        "runtime_root": str(root),
        "import_path": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }


def path_is_inside(root: str, candidate: str) -> bool:
    try:
        root_path = Path(root).resolve()
        path = Path(candidate).resolve()
    except OSError:
        return False
    return path == root_path or root_path in path.parents


def _hex64(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def valid_console_result(record: dict, result: dict) -> bool:
    """A late result matches the original task, argv and source identity."""
    if not isinstance(record, dict) or not isinstance(result, dict):
        return False
    if result.get("visible") is not True or result.get("state") != "completed":
        return False
    if result.get("handoff_id") != record.get("handoff_id"):
        return False
    if result.get("argv") != record.get("argv"):
        return False
    for key in ("runtime_root", "import_path", "source_sha256"):
        if not isinstance(result.get(key), str) or result.get(key) != record.get(key):
            return False
    if not _hex64(result.get("source_sha256")):
        return False
    if not path_is_inside(result["runtime_root"], result["import_path"]):
        return False
    if not isinstance(result.get("stdout"), str) or not isinstance(result.get("stderr"), str):
        return False
    for key in ("stdout_sha256", "stderr_sha256"):
        if not _hex64(result.get(key)):
            return False
    for key in ("stdout_encoding", "stderr_encoding"):
        if not isinstance(result.get(key), str) or not result[key]:
            return False
    return True


def legacy_code_pages() -> tuple[str, ...]:
    """OEM then ANSI. cmd.exe and Windows PowerShell use these, not UTF-8."""
    if sys.platform != "win32":
        return ()
    import ctypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    names = []
    for value in (int(kernel.GetOEMCP()), int(kernel.GetACP())):
        name = f"cp{value}"
        if name not in names:
            names.append(name)
    return tuple(names)


def decode_console_bytes(data: bytes, *, legacy: tuple[str, ...] | None = None) -> dict:
    """Return text plus the encoding that produced it. Never raise for bytes."""
    encodings = ("utf-8", *(legacy_code_pages() if legacy is None else legacy))
    chosen, text, strict = "latin-1", data.decode("latin-1"), False
    for encoding in encodings:
        try:
            text = data.decode(encoding, "strict")
        except (LookupError, UnicodeDecodeError):
            continue
        chosen, strict = encoding, True
        break
    return {
        "text": text,
        "encoding": chosen,
        "sha256": hashlib.sha256(data).hexdigest(),
        "byte_length": len(data),
        "decoded_strict": strict,
    }


def console_plan(
    *,
    python: str,
    handoff_id: str,
    result_path: str,
    cwd: str,
    argv: tuple[str, ...],
    hold_seconds: int,
    timeout_seconds: int,
    runtime_root: str,
    source_sha256: str,
    import_path: str,
) -> dict:
    if any(token.lower() in FORBIDDEN_TOKENS for token in argv):
        raise BridgeError(
            "windows_console_forbidden",
            "Refusing an execution-policy change, encoded command, or hidden window",
        )
    if any("\x00" in item or any(ord(char) < 32 for char in item) for item in argv):
        raise ValueError("Console arguments cannot contain NUL or ASCII controls")
    if (
        not isinstance(runtime_root, str)
        or not Path(runtime_root).is_absolute()
        or "\x00" in runtime_root
        or not _hex64(source_sha256)
        or not path_is_inside(runtime_root, import_path)
    ):
        raise ValueError("Console runtime identity is incomplete")
    flags = CREATE_NEW_CONSOLE | CREATE_UNICODE_ENVIRONMENT
    if flags & (CREATE_NO_WINDOW | DETACHED_PROCESS):
        raise BridgeError("windows_console_hidden", "Refusing a hidden console handoff")
    command = [
        python,
        "-B",
        "-P",
        "-u",
        "-c",
        BOOTSTRAP,
        "--",
        str(Path(runtime_root).resolve()),
        source_sha256,
        handoff_id,
        result_path,
        str(hold_seconds),
        str(timeout_seconds),
        cwd,
        *argv,
    ]
    return {
        "argv": tuple(command),
        "command": tuple(argv),
        "cwd": cwd,
        "handoff_id": handoff_id,
        "result_path": result_path,
        "runtime_root": str(Path(runtime_root).resolve()),
        "source_sha256": source_sha256,
        "import_path": str(Path(import_path).resolve()),
        "creation_flags": flags,
        "show": SW_SHOWNORMAL,
        "startup_flags": STARTF_USESHOWWINDOW,
        "hidden": False,
        "redirect_stdio": False,
        "environment_keys": tuple(sorted(visible_environment())),
        "command_preview": " ".join(quote_windows(part) for part in argv),
    }


def _read_limited(stream, limit: int) -> tuple[bytes, bool]:
    chunks = []
    total = 0
    while total < limit:
        chunk = stream.read(min(4096, limit - total))
        if not chunk:
            return b"".join(chunks), False
        chunks.append(chunk)
        total += len(chunk)
    extra = stream.read(1)
    return b"".join(chunks), bool(extra)


def _terminate_owned(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        process.terminate()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
        process.wait(timeout=1)


def run_owned_command(
    command, *, cwd: str, env: dict[str, str], timeout: float, limit: int
) -> dict:
    """Read at most `limit` bytes from each pipe, then stop the owned child."""
    popen = {
        "cwd": cwd,
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if os.name == "nt":
        popen["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen["start_new_session"] = True
    process = subprocess.Popen(list(command), **popen)
    boxes: dict[str, dict] = {"stdout": {}, "stderr": {}}
    overflow = threading.Event()

    def pump(stream, slot: str) -> None:
        error = None
        try:
            data, hit = _read_limited(stream, limit)
        except Exception as exc:
            data, hit, error = b"", False, type(exc).__name__
        boxes[slot]["data"] = data
        boxes[slot]["overflow"] = hit
        boxes[slot]["error"] = error
        if hit:
            overflow.set()

    threads = [
        threading.Thread(target=pump, args=(process.stdout, "stdout")),
        threading.Thread(target=pump, args=(process.stderr, "stderr")),
    ]
    for thread in threads:
        thread.start()
    timed_out = False
    deadline = time.monotonic() + timeout
    while process.poll() is None and not overflow.is_set():
        if time.monotonic() >= deadline:
            timed_out = True
            _terminate_owned(process)
            break
        time.sleep(0.02)
    if overflow.is_set():
        _terminate_owned(process)
    for thread in threads:
        thread.join(timeout=5)
    if process.poll() is None:
        _terminate_owned(process)
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            stream.close()
    code = process.wait(timeout=2)
    stdout = boxes["stdout"].get("data", b"")
    stderr = boxes["stderr"].get("data", b"")
    read_error = boxes["stdout"].get("error") or boxes["stderr"].get("error")
    if boxes["stdout"].get("overflow") or boxes["stderr"].get("overflow"):
        state, exit_code = "truncated", code
    elif timed_out:
        state, exit_code = "timeout", None
    elif read_error:
        state, exit_code = "failed", code
    else:
        state, exit_code = "completed", code
    return {
        "state": state,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "child_pid": process.pid,
    }


def console_main(argv: list[str]) -> int:
    """Run inside the visible console. Print the child output, then store it."""
    if argv[:1] != ["--"] or len(argv) < 8:
        return 2
    runtime, expected, handoff_id, result_path, hold_text, timeout_text, cwd, *command = argv[1:]
    try:
        hold, timeout = int(hold_text), int(timeout_text)
    except ValueError:
        return 2
    if not 0 <= hold <= 15 or not 1 <= timeout <= 8 or not command:
        return 2
    identity = runtime_identity()
    pinned = Path(runtime).resolve()
    mismatch = (
        identity["runtime_root"] != str(pinned)
        or identity["source_sha256"] != expected
        or Path(identity["runtime_root"]).resolve() not in Path(identity["import_path"]).parents
    )
    body: dict = {
        "handoff_id": handoff_id,
        "argv": list(command),
        "runtime_root": identity["runtime_root"],
        "import_path": identity["import_path"],
        "source_sha256": identity["source_sha256"],
        "visible": True,
        "stdout": "",
        "stderr": "",
        "stdout_encoding": "utf-8",
        "stderr_encoding": "utf-8",
        "stdout_sha256": hashlib.sha256(b"").hexdigest(),
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        "stdout_byte_length": 0,
        "stderr_byte_length": 0,
        "stdout_decoded_strict": True,
        "stderr_decoded_strict": True,
        "exit_code": None,
        "child_pid": None,
    }
    code = 1
    if mismatch:
        body["state"] = "rejected"
        code = 4
    else:
        try:
            outcome = run_owned_command(
                command,
                cwd=cwd,
                env=visible_environment(),
                timeout=timeout,
                limit=RESULT_LIMIT,
            )
        except Exception as error:
            body["state"] = "failed"
            body["stderr"] = type(error).__name__
            code = 1
        else:
            stdout = decode_console_bytes(outcome["stdout"])
            stderr = decode_console_bytes(outcome["stderr"])
            body.update(
                {
                    "state": outcome["state"],
                    "exit_code": outcome["exit_code"],
                    "child_pid": outcome["child_pid"],
                    "stdout": stdout["text"],
                    "stderr": stderr["text"],
                    "stdout_encoding": stdout["encoding"],
                    "stderr_encoding": stderr["encoding"],
                    "stdout_sha256": stdout["sha256"],
                    "stderr_sha256": stderr["sha256"],
                    "stdout_byte_length": stdout["byte_length"],
                    "stderr_byte_length": stderr["byte_length"],
                    "stdout_decoded_strict": stdout["decoded_strict"],
                    "stderr_decoded_strict": stderr["decoded_strict"],
                }
            )
            sys.stdout.write(stdout["text"])
            if stderr["text"]:
                sys.stderr.write(stderr["text"])
            code = 0 if outcome["state"] == "completed" else 1
    marker = f"KIRABRIDGE_VISIBLE_RESULT {handoff_id} {body['state']} {body['exit_code']}"
    sys.stdout.write(f"\n{marker}\n")
    sys.stdout.flush()
    _write_json(Path(result_path), body)
    if hold and body["state"] == "completed":
        time.sleep(hold)
    return code


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, separators=(",", ":"))
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


class Win32VisibleSpawner:
    def __init__(self, python: str | None = None):
        if sys.platform != "win32":
            raise BridgeError("unsupported_platform", "A visible Windows console requires Windows")
        self.python = python or sys.executable

    def start(self, plan: dict) -> dict:
        if (
            plan["hidden"]
            or plan["redirect_stdio"]
            or plan["show"] != SW_SHOWNORMAL
            or not plan["creation_flags"] & CREATE_NEW_CONSOLE
            or plan["creation_flags"] & CREATE_NO_WINDOW
        ):
            raise BridgeError("windows_console_hidden", "Refusing a hidden console handoff")
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = SW_SHOWNORMAL
        process = subprocess.Popen(
            list(plan["argv"]),
            cwd=plan["cwd"],
            env=visible_environment(),
            creationflags=plan["creation_flags"],
            startupinfo=startup,
            close_fds=True,
        )
        return {"pid": process.pid, "process": process}


def wait_result(path: Path, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        time.sleep(0.05)
    raise UncertainExecution(
        "windows_console_unknown",
        "The visible console did not return a result; do not start it again",
    )
