"""Visible Windows console handoff. Output is shown and returned, never hidden.

The window is a new console running this same Python. Its import is pinned to
the activated runtime, not to an older installation on sys.path. PowerShell
execution policy is not read or changed. A completed handoff id is not started
again.
"""

from __future__ import annotations

import base64
import codecs
import hashlib
import json
import os
import signal
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
    env["PYTHONDONTWRITEBYTECODE"] = "1"
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


def _bound_stream(result: dict, name: str) -> bool:
    """Text, codec, length and hash must describe the same bytes."""
    text = result.get(name)
    encoding = result.get(f"{name}_encoding")
    digest = result.get(f"{name}_sha256")
    length = result.get(f"{name}_byte_length")
    if not isinstance(text, str) or result.get(f"{name}_decoded_strict") is not True:
        return False
    if result.get(f"{name}_ambiguous") is True:
        return False
    if not isinstance(encoding, str) or not encoding:
        return False
    if type(length) is not int or not 0 <= length <= RESULT_LIMIT:
        return False
    if not _hex64(digest):
        return False
    try:
        raw = text.encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    if len(raw) != length or hashlib.sha256(raw).hexdigest() != digest:
        return False
    encoded = result.get(f"{name}_raw_base64")
    if encoded is None:
        return True
    if not isinstance(encoded, str):
        return False
    try:
        return base64.b64decode(encoded, validate=True) == raw
    except (ValueError, TypeError):
        return False


def valid_console_result(record: dict, result: dict) -> bool:
    """A completion matches the task and the unchanged output bytes.

    exit_code must be an int. True and False are not exit codes. A hash,
    length or encoding that does not reproduce the text stays open.
    """
    if not isinstance(record, dict) or not isinstance(result, dict):
        return False
    if result.get("visible") is not True or result.get("state") != "completed":
        return False
    if type(result.get("exit_code")) is not int:
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
    return _bound_stream(result, "stdout") and _bound_stream(result, "stderr")


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


def _decode_result(
    data: bytes,
    *,
    text: str,
    encoding: str | None,
    strict: bool,
    ambiguous: bool,
    status: str,
    candidates: list[str],
    requested: str | None,
) -> dict:
    return {
        "text": text,
        "encoding": encoding,
        "sha256": hashlib.sha256(data).hexdigest(),
        "byte_length": len(data),
        "decoded_strict": strict,
        "ambiguous": ambiguous,
        "text_status": status,
        "candidate_encodings": candidates,
        "requested_encoding": requested,
        "raw_base64": base64.b64encode(data).decode("ascii"),
    }


def _output_encoding(value: str | None) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not 2 <= len(value) <= 32
        or any(char.isspace() or ord(char) < 33 for char in value)
    ):
        raise ValueError("Console output encoding must be a codec name")
    try:
        codecs.lookup(value)
    except LookupError as error:
        raise ValueError("Console output encoding is unknown") from error
    return value


def _round_trip(data: bytes, encoding: str) -> str | None:
    try:
        text = data.decode(encoding, "strict")
        if text.encode(encoding) == data:
            return text
    except (LookupError, UnicodeDecodeError, UnicodeEncodeError):
        return None
    return None


def decode_console_bytes(
    data: bytes, *, legacy: tuple[str, ...] | None = None, encoding: str | None = None
) -> dict:
    """Decode console bytes without treating every single-byte page as proof.

    `encoding` selects one output codec, for example `cp850`, `cp1252` or
    `utf-8`. No other page is tried. Without it, UTF-8 is accepted only when
    the bytes are strict UTF-8. Legacy pages are accepted only when every page
    that round-trips produces the same text. Disagreeing pages stay ambiguous:
    `decoded_strict` is false, `text` is empty, and `raw_base64` keeps the bytes.
    """
    if not isinstance(data, bytes):
        raise TypeError("console output must be bytes")
    if encoding is not None:
        if not isinstance(encoding, str) or not encoding:
            return _decode_result(
                data,
                text="",
                encoding=None,
                strict=False,
                ambiguous=False,
                status="decode-failed",
                candidates=[],
                requested=None,
            )
        text = _round_trip(data, encoding)
        if text is None:
            return _decode_result(
                data,
                text="",
                encoding=None,
                strict=False,
                ambiguous=False,
                status="decode-failed",
                candidates=[],
                requested=encoding,
            )
        return _decode_result(
            data,
            text=text,
            encoding=encoding,
            strict=True,
            ambiguous=False,
            status="selected",
            candidates=[encoding],
            requested=encoding,
        )
    text = _round_trip(data, "utf-8")
    if text is not None:
        return _decode_result(
            data,
            text=text,
            encoding="utf-8",
            strict=True,
            ambiguous=False,
            status="utf-8",
            candidates=["utf-8"],
            requested=None,
        )
    pages = legacy_code_pages() if legacy is None else legacy
    decoded = []
    for name in pages:
        if not isinstance(name, str) or not name or name.lower() == "utf-8":
            continue
        page = _round_trip(data, name)
        if page is not None:
            decoded.append((name, page))
    texts = {page for _, page in decoded}
    if decoded and len(texts) == 1:
        name, page = decoded[0]
        return _decode_result(
            data,
            text=page,
            encoding=name,
            strict=True,
            ambiguous=False,
            status="legacy",
            candidates=[item for item, _ in decoded],
            requested=None,
        )
    if len(texts) > 1:
        return _decode_result(
            data,
            text="",
            encoding=None,
            strict=False,
            ambiguous=True,
            status="ambiguous",
            candidates=[item for item, _ in decoded],
            requested=None,
        )
    return _decode_result(
        data,
        text=data.decode("latin-1"),
        encoding="latin-1",
        strict=False,
        ambiguous=False,
        status="latin-1",
        candidates=[],
        requested=None,
    )


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
    output_encoding: str | None = None,
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
    selected_encoding = _output_encoding(output_encoding)
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
        *(("--encoding", selected_encoding) if selected_encoding else ()),
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
        "output_encoding": selected_encoding,
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


def _terminate_owned(process: subprocess.Popen, job=None) -> None:
    if job is not None:
        try:
            job.terminate()
        finally:
            # Assignment itself may fail while this exact child is suspended.
            if process.poll() is None:
                process.kill()
    elif os.name == "nt":
        if process.poll() is None:
            process.kill()
    else:
        # The leader may already have exited while a descendant keeps a pipe.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=1)


def _pipe_chunk(stream, remaining: int):
    """Read currently available bytes; never wait for an inherited writer."""
    if os.name == "nt":
        import ctypes
        import msvcrt

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.PeekNamedPipe.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_void_p,
        ]
        kernel.PeekNamedPipe.restype = ctypes.c_int
        available = ctypes.c_uint32()
        handle = msvcrt.get_osfhandle(stream.fileno())
        if not kernel.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
            error = ctypes.get_last_error()
            if error in (109, 232):  # broken pipe / no remaining pipe data
                return b""
            raise ctypes.WinError(error)
        if not available.value:
            return None
        return os.read(stream.fileno(), min(available.value, 4096, remaining + 1))
    try:
        return os.read(stream.fileno(), min(4096, remaining + 1))
    except BlockingIOError:
        return None


def run_owned_command(
    command, *, cwd: str, env: dict[str, str], timeout: float, limit: int
) -> dict:
    """Bound execution and pipe draining by one deadline, including descendants."""
    popen = {
        "cwd": cwd,
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    job = None
    process = None
    finished = False
    try:
        if os.name == "nt":
            from kirabridge.platform_adapters.windows.owned_job import WindowsChildJob

            job = WindowsChildJob()
            popen["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x4
        else:
            popen["start_new_session"] = True
        process = subprocess.Popen(list(command), **popen)
        if job is not None:
            job.assign_and_resume(process)
        streams = {"stdout": process.stdout, "stderr": process.stderr}
        if os.name != "nt":
            for stream in streams.values():
                os.set_blocking(stream.fileno(), False)
        boxes = {
            name: {"data": bytearray(), "eof": False, "overflow": False, "error": None}
            for name in streams
        }
        deadline = time.monotonic() + timeout
        draining_until = None
        timed_out = False
        while True:
            received = False
            for name, stream in streams.items():
                box = boxes[name]
                if box["eof"] or box["overflow"]:
                    continue
                try:
                    chunk = _pipe_chunk(stream, limit - len(box["data"]))
                except OSError as error:
                    box.update(eof=True, error=type(error).__name__)
                    continue
                if chunk is None:
                    continue
                if not chunk:
                    box["eof"] = True
                    continue
                received = True
                remaining = limit - len(box["data"])
                box["data"].extend(chunk[:remaining])
                box["overflow"] = len(chunk) > remaining
            done = process.poll() is not None
            pipes_done = all(box["eof"] or box["overflow"] for box in boxes.values())
            if done and pipes_done:
                break
            now = time.monotonic()
            overflow = any(box["overflow"] for box in boxes.values())
            if draining_until is None and (overflow or now >= deadline):
                timed_out = not overflow
                _terminate_owned(process, job)
                draining_until = time.monotonic() + 0.25
            if draining_until is not None and time.monotonic() >= draining_until:
                break
            if not received:
                time.sleep(0.01)
        code = process.wait(timeout=1)
        read_error = any(box["error"] for box in boxes.values())
        if any(box["overflow"] for box in boxes.values()):
            state, exit_code = "truncated", code
        elif timed_out:
            state, exit_code = "timeout", None
        elif read_error:
            state, exit_code = "failed", code
        else:
            state, exit_code = "completed", code
        finished = True
        return {
            "state": state,
            "exit_code": exit_code,
            "stdout": bytes(boxes["stdout"]["data"]),
            "stderr": bytes(boxes["stderr"]["data"]),
            "child_pid": process.pid,
            "owned_job": job is not None,
        }
    finally:
        try:
            if process is not None and not finished:
                _terminate_owned(process, job)
        finally:
            if job is not None:
                job.close(keep_completed_descendants=finished and state == "completed")
            if process is not None:
                # No reader thread owns a BufferedReader lock during close.
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()


def _parse_console_argv(argv: list[str]):
    if argv[:1] != ["--"] or len(argv) < 8:
        return None
    runtime, expected, handoff_id, result_path, hold_text, timeout_text, cwd, *tail = argv[1:]
    encoding = None
    if len(tail) >= 2 and tail[0] == "--encoding":
        encoding = tail[1]
        tail = tail[2:]
    if not tail:
        return None
    return (
        runtime,
        expected,
        handoff_id,
        result_path,
        hold_text,
        timeout_text,
        cwd,
        encoding,
        tail,
    )


def _visible_text_state(outcome: dict, stdout: dict, stderr: dict) -> str:
    unresolved = (
        stdout["ambiguous"]
        or stderr["ambiguous"]
        or stdout["text_status"] == "decode-failed"
        or stderr["text_status"] == "decode-failed"
    )
    if outcome["state"] == "completed" and unresolved:
        return "open"
    return outcome["state"]


def _write_console(stream, decoded: dict, raw: bytes) -> None:
    if decoded["decoded_strict"]:
        stream.write(decoded["text"])
        return
    stream.flush()
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(raw)
        buffer.flush()


def _stream_fields(name: str, decoded: dict) -> dict:
    return {
        name: decoded["text"],
        f"{name}_encoding": decoded["encoding"],
        f"{name}_sha256": decoded["sha256"],
        f"{name}_byte_length": decoded["byte_length"],
        f"{name}_decoded_strict": decoded["decoded_strict"],
        f"{name}_ambiguous": decoded["ambiguous"],
        f"{name}_text_status": decoded["text_status"],
        f"{name}_candidate_encodings": decoded["candidate_encodings"],
        f"{name}_requested_encoding": decoded["requested_encoding"],
        f"{name}_raw_base64": decoded["raw_base64"],
    }


def console_main(argv: list[str]) -> int:
    """Run inside the visible console. Print the child output, then store it."""
    parsed = _parse_console_argv(argv)
    if parsed is None:
        return 2
    (
        runtime,
        expected,
        handoff_id,
        result_path,
        hold_text,
        timeout_text,
        cwd,
        output_encoding,
        command,
    ) = parsed
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
            stdout = decode_console_bytes(outcome["stdout"], encoding=output_encoding)
            stderr = decode_console_bytes(outcome["stderr"], encoding=output_encoding)
            state = _visible_text_state(outcome, stdout, stderr)
            body.update(
                {
                    "state": state,
                    "exit_code": outcome["exit_code"],
                    "child_pid": outcome["child_pid"],
                    **_stream_fields("stdout", stdout),
                    **_stream_fields("stderr", stderr),
                }
            )
            _write_console(sys.stdout, stdout, outcome["stdout"])
            if outcome["stderr"]:
                _write_console(sys.stderr, stderr, outcome["stderr"])
            code = 0 if state == "completed" else 1
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
