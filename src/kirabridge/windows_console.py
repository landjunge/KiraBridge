"""Visible console handoff with status and one completion per handoff id."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from pydantic import Field, model_validator

from kirabridge.bridge_core.models import BridgeError, Input, UncertainExecution
from kirabridge.platform_adapters.windows.visible_console import (
    console_plan,
    runtime_identity,
    valid_console_result,
    visible_environment,
    wait_result,
)


class WindowsConsoleHandoffInput(Input):
    handoff_id: str = Field(pattern=r"^[a-z][a-z0-9-]{7,63}$", strict=True)
    argv: list[str] = Field(min_length=1, max_length=8)
    cwd: str = Field(min_length=3, max_length=240, strict=True)
    timeout_seconds: int = Field(default=8, ge=1, le=8, strict=True)
    hold_seconds: int = Field(default=0, ge=0, le=15, strict=True)
    output_encoding: str | None = None

    @model_validator(mode="after")
    def bounded_command(self):
        if not self.cwd[0].isascii() or not self.cwd[0].isalpha() or self.cwd[1:3] != ":\\":
            raise ValueError("The console directory must be an absolute Windows path")
        if any(part in {"", ".", ".."} for part in self.cwd.split("\\")[1:]):
            raise ValueError("The console directory cannot contain parent segments")
        if any(not isinstance(item, str) or not item or len(item) > 240 for item in self.argv):
            raise ValueError("Each console argument must be a short string")
        encoding = self.output_encoding
        if encoding is not None and (
            not 2 <= len(encoding) <= 32
            or any(char.isspace() or ord(char) < 33 for char in encoding)
        ):
            raise ValueError("output_encoding must be a codec name such as cp850, cp1252, or utf-8")
        return self


class WindowsConsoleStatusInput(Input):
    handoff_id: str = Field(pattern=r"^[a-z][a-z0-9-]{7,63}$", strict=True)


WINDOWS_CONSOLE_INPUTS = {
    "windows.console.handoff": WindowsConsoleHandoffInput,
    "windows.console.status": WindowsConsoleStatusInput,
}


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, separators=(",", ":"))
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


class WindowsConsoleManager:
    def __init__(self, authorize, desktop_input, state_dir, *, spawner=None, host=None):
        self.authorize, self.desktop_input = authorize, desktop_input
        self.state_dir = Path(state_dir)
        self.spawner = spawner
        self.host = sys.platform if host is None else host

    def require(self):
        if self.host != "win32":
            raise BridgeError("unsupported_platform", "A visible Windows console requires Windows")

    def catalog(self, decide):
        return [
            {
                "operation": operation,
                "provider_id": "windows.console.v1",
                "host_platform": self.host,
                "available": self.host == "win32",
                "eligible_for_submission": self.host == "win32" and decide(operation)["authorized"],
                "policy": decide(operation),
                "scope": (
                    "New shown console, result returned from that session; "
                    "a completed handoff is not started again"
                ),
            }
            for operation in WINDOWS_CONSOLE_INPUTS
        ]

    def _path(self, handoff_id: str) -> Path:
        return self.state_dir / "windows-console" / f"{handoff_id}.json"

    def _read(self, handoff_id: str) -> dict | None:
        path = self._path(handoff_id)
        if not path.exists() or path.is_symlink():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _result_path(self, handoff_id: str) -> Path:
        return self._path(handoff_id).with_suffix(".result.json")

    def _load_result(self, handoff_id: str) -> dict | None:
        path = self._result_path(handoff_id)
        if not path.is_file() or path.is_symlink():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _duplicate(self, record: dict) -> dict:
        return {
            **record,
            "deduplicated": True,
            "spawned": False,
            "reconciled": record.get("reconciled") is True,
            "provider": "windows.console.v1",
            "automatic_retry": False,
        }

    def _accepted(
        self, record: dict, result: dict, *, spawned: bool, reconciled: bool, pid=None
    ) -> dict:
        completed = {
            "handoff_id": record["handoff_id"],
            "state": "completed",
            "argv": list(record["argv"]),
            "runtime_root": record["runtime_root"],
            "import_path": record["import_path"],
            "source_sha256": record["source_sha256"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "stdout_encoding": result["stdout_encoding"],
            "stderr_encoding": result["stderr_encoding"],
            "stdout_sha256": result["stdout_sha256"],
            "stderr_sha256": result["stderr_sha256"],
            "stdout_byte_length": result["stdout_byte_length"],
            "stderr_byte_length": result["stderr_byte_length"],
            "stdout_decoded_strict": result["stdout_decoded_strict"],
            "stderr_decoded_strict": result["stderr_decoded_strict"],
            "stdout_ambiguous": result.get("stdout_ambiguous") is True,
            "stderr_ambiguous": result.get("stderr_ambiguous") is True,
            "exit_code": result["exit_code"],
            "visible": True,
            "deduplicated": not spawned,
            "spawned": spawned,
            "reconciled": reconciled,
            "pid": pid,
            "creation_flags": record.get("creation_flags"),
            "show": record.get("show"),
            "environment_keys": list(record.get("environment_keys") or []),
            "credential_environment_copied": any(
                "TOKEN" in key or "SECRET" in key or key.endswith("_KEY")
                for key in visible_environment()
            ),
            "provider": "windows.console.v1",
            "automatic_retry": False,
        }
        return completed

    def _reconcile(self, record: dict | None, handoff_id: str) -> dict | None:
        if not record or record.get("state") == "completed":
            return None
        result = self._load_result(handoff_id)
        if result is None or not valid_console_result(record, result):
            return None
        return self._accepted(record, result, spawned=False, reconciled=True, pid=record.get("pid"))

    async def execute(self, task, args, running, progress=None):
        operation, principal = task["operation"], task["principal"]
        self.authorize(principal, operation)
        self.require()
        async with self.desktop_input.transaction() as turn:
            self.authorize(principal, operation)
            record = self._read(args.handoff_id)
            if operation == "windows.console.status":
                reconciled = self._reconcile(record, args.handoff_id)
                if reconciled is not None:
                    _atomic_json(self._path(args.handoff_id), reconciled)
                    record = reconciled
                await running({"evidence_type": "windows_console_status", "automatic_retry": False})
                return {
                    "handoff_id": args.handoff_id,
                    "state": None if record is None else record["state"],
                    "record": record,
                    "deduplicated": bool(record and record.get("state") == "completed"),
                    "provider": "windows.console.v1",
                    "effect_attempted": False,
                }
            self.authorize(principal, "windows.console.status")
            if record and list(record.get("argv") or []) != list(args.argv):
                raise UncertainExecution(
                    "windows_console_unknown",
                    "This handoff id belongs to a different command; no replay",
                )
            if record and record.get("state") == "completed":
                await running(
                    {"evidence_type": "windows_console_duplicate", "automatic_retry": False}
                )
                return self._duplicate(record)
            reconciled = self._reconcile(record, args.handoff_id)
            if reconciled is not None:
                _atomic_json(self._path(args.handoff_id), reconciled)
                await running(
                    {"evidence_type": "windows_console_duplicate", "automatic_retry": False}
                )
                return reconciled
            if record is not None:
                raise UncertainExecution(
                    "windows_console_unknown",
                    "This handoff already started and has no completed result; no replay",
                )
            record_path = self._path(args.handoff_id)
            result_path = self._result_path(args.handoff_id)
            identity = runtime_identity()
            python = sys.executable if self.spawner is None else self.spawner.python
            plan = console_plan(
                python=python,
                handoff_id=args.handoff_id,
                result_path=str(result_path),
                cwd=args.cwd,
                argv=tuple(args.argv),
                hold_seconds=args.hold_seconds,
                timeout_seconds=args.timeout_seconds,
                runtime_root=identity["runtime_root"],
                source_sha256=identity["source_sha256"],
                import_path=identity["import_path"],
                output_encoding=args.output_encoding,
            )
            if plan["hidden"] or plan["redirect_stdio"]:
                raise BridgeError("windows_console_hidden", "Refusing a hidden console handoff")
            reserved = {
                "handoff_id": args.handoff_id,
                "state": "started",
                "argv": list(args.argv),
                "cwd": args.cwd,
                "runtime_root": plan["runtime_root"],
                "import_path": plan["import_path"],
                "source_sha256": plan["source_sha256"],
                "creation_flags": plan["creation_flags"],
                "show": plan["show"],
                "environment_keys": list(plan["environment_keys"]),
                "deduplicated": False,
                "spawned": False,
            }
            _atomic_json(record_path, reserved)
            turn.mark_attempted()
            await running({"evidence_type": "windows_console_started", "automatic_retry": False})
            try:
                if self.spawner is None:
                    from kirabridge.platform_adapters.windows.visible_console import (
                        Win32VisibleSpawner,
                    )

                    self.spawner = Win32VisibleSpawner()
                spawned = self.spawner.start(plan)
                try:
                    result = wait_result(result_path, args.timeout_seconds + 2)
                except UncertainExecution:
                    result = self._load_result(args.handoff_id)
                    if result is None:
                        raise
            except UncertainExecution:
                _atomic_json(
                    record_path,
                    {**self._read(args.handoff_id), "state": "unknown", "automatic_retry": False},
                )
                raise
            except Exception as error:
                _atomic_json(
                    record_path,
                    {**self._read(args.handoff_id), "state": "unknown", "automatic_retry": False},
                )
                raise UncertainExecution(
                    "windows_console_unknown",
                    "Visible console handoff stopped after start; no replay",
                ) from error
            if not valid_console_result(reserved, result):
                _atomic_json(
                    record_path,
                    {
                        **self._read(args.handoff_id),
                        "state": "unknown",
                        "result_state": result.get("state") if isinstance(result, dict) else None,
                        "automatic_retry": False,
                    },
                )
                raise UncertainExecution(
                    "windows_console_unknown",
                    "Visible console result is not a completion; no replay",
                )
            completed = self._accepted(
                reserved, result, spawned=True, reconciled=False, pid=spawned.get("pid")
            )
            _atomic_json(record_path, completed)
            return completed
