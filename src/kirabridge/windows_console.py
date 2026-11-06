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
    visible_environment,
    wait_result,
)


class WindowsConsoleHandoffInput(Input):
    handoff_id: str = Field(pattern=r"^[a-z][a-z0-9-]{7,63}$", strict=True)
    argv: list[str] = Field(min_length=1, max_length=8)
    cwd: str = Field(min_length=3, max_length=240, strict=True)
    timeout_seconds: int = Field(default=8, ge=1, le=8, strict=True)
    hold_seconds: int = Field(default=0, ge=0, le=15, strict=True)

    @model_validator(mode="after")
    def bounded_command(self):
        if not self.cwd[0].isascii() or not self.cwd[0].isalpha() or self.cwd[1:3] != ":\\":
            raise ValueError("The console directory must be an absolute Windows path")
        if any(part in {"", ".", ".."} for part in self.cwd.split("\\")[1:]):
            raise ValueError("The console directory cannot contain parent segments")
        if any(not isinstance(item, str) or not item or len(item) > 240 for item in self.argv):
            raise ValueError("Each console argument must be a short string")
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
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    async def execute(self, task, args, running, progress=None):
        operation, principal = task["operation"], task["principal"]
        self.authorize(principal, operation)
        self.require()
        if operation == "windows.console.status":
            record = self._read(args.handoff_id)
            await running({"evidence_type": "windows_console_status", "automatic_retry": False})
            return {
                "handoff_id": args.handoff_id,
                "state": None if record is None else record["state"],
                "record": record,
                "provider": "windows.console.v1",
                "effect_attempted": False,
            }
        existing = self._read(args.handoff_id)
        if existing and existing.get("state") == "completed":
            await running({"evidence_type": "windows_console_duplicate", "automatic_retry": False})
            return {
                **existing,
                "deduplicated": True,
                "spawned": False,
                "provider": "windows.console.v1",
            }
        if existing:
            raise UncertainExecution(
                "windows_console_unknown",
                "This handoff already started and has no completed result; no replay",
            )
        async with self.desktop_input.transaction() as turn:
            self.authorize(principal, operation)
            self.authorize(principal, "windows.console.status")
            record_path = self._path(args.handoff_id)
            result_path = record_path.with_suffix(".result.json")
            python = sys.executable if self.spawner is None else self.spawner.python
            plan = console_plan(
                python=python,
                handoff_id=args.handoff_id,
                result_path=str(result_path),
                cwd=args.cwd,
                argv=tuple(args.argv),
                hold_seconds=args.hold_seconds,
                timeout_seconds=args.timeout_seconds,
            )
            if plan["hidden"] or plan["redirect_stdio"]:
                raise BridgeError("windows_console_hidden", "Refusing a hidden console handoff")
            _atomic_json(
                record_path,
                {
                    "handoff_id": args.handoff_id,
                    "state": "started",
                    "argv": list(args.argv),
                    "creation_flags": plan["creation_flags"],
                    "show": plan["show"],
                    "deduplicated": False,
                },
            )
            turn.mark_attempted()
            await running({"evidence_type": "windows_console_started", "automatic_retry": False})
            try:
                if self.spawner is None:
                    from kirabridge.platform_adapters.windows.visible_console import (
                        Win32VisibleSpawner,
                    )

                    self.spawner = Win32VisibleSpawner()
                spawned = self.spawner.start(plan)
                result = wait_result(result_path, args.timeout_seconds + 2)
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
            if result.get("handoff_id") != args.handoff_id or result.get("state") != "completed":
                _atomic_json(
                    record_path,
                    {
                        **self._read(args.handoff_id),
                        "state": "unknown",
                        "result_state": result.get("state"),
                        "automatic_retry": False,
                    },
                )
                raise UncertainExecution(
                    "windows_console_unknown",
                    "Visible console result is not a completion; no replay",
                )
            completed = {
                **result,
                "state": "completed",
                "deduplicated": False,
                "spawned": True,
                "pid": spawned.get("pid"),
                "creation_flags": plan["creation_flags"],
                "show": plan["show"],
                "environment_keys": list(plan["environment_keys"]),
                "credential_environment_copied": any(
                    "TOKEN" in key or "SECRET" in key or key.endswith("_KEY")
                    for key in visible_environment()
                ),
                "provider": "windows.console.v1",
                "automatic_retry": False,
            }
            _atomic_json(record_path, completed)
            return completed
