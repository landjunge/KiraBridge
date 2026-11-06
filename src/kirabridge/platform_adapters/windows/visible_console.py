"""Visible Windows console handoff. Output is shown and returned, never hidden.

The window is a new console running this same Python. PowerShell execution
policy is not read or changed. A completed handoff id is not started again.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
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


def visible_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    """Keep the Windows process environment small. Do not copy credentials."""
    source = os.environ if source is None else source
    env = {key: source[key] for key in ENV_ALLOW if key in source and source[key]}
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def console_plan(
    *,
    python: str,
    handoff_id: str,
    result_path: str,
    cwd: str,
    argv: tuple[str, ...],
    hold_seconds: int,
    timeout_seconds: int,
) -> dict:
    if any(token.lower() in FORBIDDEN_TOKENS for token in argv):
        raise BridgeError(
            "windows_console_forbidden",
            "Refusing an execution-policy change, encoded command, or hidden window",
        )
    if any("\x00" in item or any(ord(char) < 32 for char in item) for item in argv):
        raise ValueError("Console arguments cannot contain NUL or ASCII controls")
    flags = CREATE_NEW_CONSOLE | CREATE_UNICODE_ENVIRONMENT
    if flags & (CREATE_NO_WINDOW | DETACHED_PROCESS):
        raise BridgeError("windows_console_hidden", "Refusing a hidden console handoff")
    launch = (
        "from kirabridge.platform_adapters.windows.visible_console import console_main\n"
        "import sys\n"
        "raise SystemExit(console_main(sys.argv[1:]))\n"
    )
    command = [
        python,
        "-B",
        "-u",
        "-c",
        launch,
        "--",
        handoff_id,
        result_path,
        str(hold_seconds),
        str(timeout_seconds),
        cwd,
        *argv,
    ]
    return {
        "argv": tuple(command),
        "cwd": cwd,
        "creation_flags": flags,
        "show": SW_SHOWNORMAL,
        "startup_flags": STARTF_USESHOWWINDOW,
        "hidden": False,
        "redirect_stdio": False,
        "environment_keys": tuple(sorted(visible_environment())),
        "command_preview": " ".join(quote_windows(part) for part in argv),
    }


def console_main(argv: list[str]) -> int:
    """Run inside the visible console. Print the child output, then store it."""
    if argv[:1] != ["--"] or len(argv) < 6:
        return 2
    handoff_id, result_path, hold_text, timeout_text, cwd, *command = argv[1:]
    hold, timeout = int(hold_text), int(timeout_text)
    if not 0 <= hold <= 15 or not 1 <= timeout <= 8 or not command:
        return 2
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
        stdout = completed.stdout.decode("utf-8")
        stderr = completed.stderr.decode("utf-8")
        code = int(completed.returncode)
        state = "completed"
    except subprocess.TimeoutExpired as error:
        stdout = (error.stdout or b"").decode("utf-8", "strict") if error.stdout else ""
        stderr = (error.stderr or b"").decode("utf-8", "strict") if error.stderr else ""
        code, state = None, "timeout"
    if len(stdout) > RESULT_LIMIT or len(stderr) > RESULT_LIMIT:
        stdout, stderr, state = stdout[:RESULT_LIMIT], stderr[:RESULT_LIMIT], "truncated"
    sys.stdout.write(stdout)
    if stderr:
        sys.stderr.write(stderr)
    sys.stdout.write(f"\nKIRABRIDGE_VISIBLE_RESULT {handoff_id} {state} {code}\n")
    sys.stdout.flush()
    _write_json(
        Path(result_path),
        {
            "handoff_id": handoff_id,
            "state": state,
            "exit_code": code,
            "stdout": stdout,
            "stderr": stderr,
            "visible": True,
        },
    )
    if hold:
        time.sleep(hold)
    return 0 if state == "completed" else 1


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
