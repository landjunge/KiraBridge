from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BridgeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class UncertainExecution(BridgeError):
    """The external effect cannot be proven; never retry automatically."""


class State(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"


TRANSITIONS = {
    State.CREATED: {State.QUEUED, State.CANCELLED},
    State.QUEUED: {State.ACCEPTED, State.CANCELLED, State.BLOCKED},
    State.ACCEPTED: {State.RUNNING, State.FAILED, State.UNKNOWN, State.CANCELLED},
    State.RUNNING: {State.COMPLETED, State.FAILED, State.UNKNOWN, State.CANCELLED},
    State.UNKNOWN: {State.COMPLETED, State.FAILED, State.CANCELLED},
    State.BLOCKED: set(),
    State.COMPLETED: set(),
    State.FAILED: set(),
    State.CANCELLED: set(),
}


def canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TaskRequest(Input):
    api_version: str = "1"
    task_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    operation: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any]
    idempotency_key: str = Field(min_length=1, max_length=128)
    parent_id: str | None = None


class TerminalInput(Input):
    argv: list[str] = Field(min_length=1, max_length=256)
    cwd: str
    timeout: float = Field(default=60.0, gt=0, le=3600)
    max_output: int = Field(default=65536, ge=0, le=1048576)


class PathInput(Input):
    path: str


class ReadInput(PathInput):
    max_bytes: int = Field(default=65536, ge=1, le=1048576)


class WriteInput(PathInput):
    text: str = Field(max_length=1048576)
    overwrite: bool = False


class MoveInput(PathInput):
    destination: str


class ClipboardRead(Input):
    max_bytes: int = Field(default=65536, ge=1, le=1048576)


class ClipboardWrite(Input):
    text: str = Field(max_length=1048576)


class EmptyInput(Input):
    pass


class ProcessInput(Input):
    task_id: str


class AgentInput(Input):
    agent: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,40}$")
    prompt: str = Field(min_length=1, max_length=262144)
    cwd: str
    timeout: float = Field(default=300.0, gt=0, le=3600)
