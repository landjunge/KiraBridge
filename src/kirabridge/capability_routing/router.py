"""Deterministic policy over evidence; never calls a model or changes defaults."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EFFORTS = {
    "none": 0,
    "minimal": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "xhigh": 4,
    "max": 5,
    "ultra": 6,
}
CLI = Literal["codex", "grok", "claude", "opencode", "gemini", "copilot", "cursor", "aider"]
Work = Literal[
    "routine", "implementation", "debug", "architecture", "security", "review", "research"
]
MINIMUM = {
    "routine": "low",
    "implementation": "medium",
    "debug": "high",
    "architecture": "high",
    "security": "xhigh",
    "review": "high",
    "research": "medium",
}


class RoutingError(ValueError):
    """No launch is authorized by a missing/uncertain capability decision."""


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Model(Record):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_./:+-]{0,160}$")
    provider: str
    efforts: list[str]
    fit: dict[str, int]
    cost_rank: int = Field(ge=0, le=10)
    context_tokens: int | None = Field(default=None, ge=1)
    evidence: str

    @field_validator("efforts")
    @classmethod
    def known_efforts(cls, values):
        if not values or len(set(values)) != len(values) or any(v not in EFFORTS for v in values):
            raise ValueError("Efforts must be explicit and unique")
        return values

    @field_validator("fit")
    @classmethod
    def bounded_fit(cls, values):
        if any(k not in MINIMUM or not 0 <= v <= 5 for k, v in values.items()):
            raise ValueError("Invalid workload fit")
        return values


class Capability(Record):
    id: CLI
    installed_version: str | None
    capabilities: list[str]
    models: list[Model]
    documented_models: list[str]
    sources: list[str]
    limitations: str


class Matrix(Record):
    schema_version: Literal["bigplan.cli-matrix.v1"]
    checked_at: str
    expires_at: str
    clis: list[Capability]

    @field_validator("clis")
    @classmethod
    def unique_clis(cls, entries):
        if len({entry.id for entry in entries}) != len(entries):
            raise ValueError("Duplicate CLI")
        for entry in entries:
            if len({m.id for m in entry.models}) != len(entry.models):
                raise ValueError("Duplicate model")
        return entries


class Access(Record):
    cli: CLI
    executable: str
    version: str
    models: list[str]
    access_kind: Literal["subscription", "approved_api", "approved_local"]
    verified_at: str
    expires_at: str
    evidence: str


class Runtime(Record):
    schema_version: Literal["bigplan.cli-runtime.v1"]
    access: list[Access]
    allowed_roots: list[str]
    state_dir: str
    allow_write: bool = False


class Task(Record):
    task_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,120}$")
    workload: Work
    prompt: str = Field(min_length=1, max_length=65536)
    cwd: str
    ownership_ref: str = Field(min_length=1, max_length=500)
    allowed_clis: list[CLI] = Field(default_factory=lambda: ["codex", "grok"])
    required_capabilities: list[str] = Field(default_factory=lambda: ["headless", "coding"])
    minimum_context_tokens: int = Field(default=0, ge=0)
    min_effort: str | None = None
    explicit_cli: CLI | None = None
    explicit_model: str | None = None
    explicit_effort: str | None = None
    independent_of_provider: str | None = None
    read_only: bool = True
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    delegation_depth: int = Field(default=0, ge=0, le=1)


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise RoutingError("Evidence timestamp needs a timezone")
    return result


def fresh(checked: str, expires: str, now: datetime, max_age: timedelta):
    start, end = timestamp(checked), timestamp(expires)
    if start > now + timedelta(minutes=5) or end <= now or end <= start or now - start > max_age:
        raise RoutingError("Evidence expired, stale, or future-dated; refresh before delegation")


def fingerprint(value) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump()
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def select(matrix: Matrix, runtime: Runtime, task: Task, *, now=None) -> dict:
    """Select only known, granted combinations; preserve explicit requirements."""
    now = now or datetime.now(timezone.utc)
    fresh(matrix.checked_at, matrix.expires_at, now, timedelta(days=7))
    if task.delegation_depth:
        raise RoutingError("A delegated child cannot delegate again")
    for effort in (task.min_effort, task.explicit_effort):
        if effort is not None and effort not in EFFORTS:
            raise RoutingError("Unknown requested effort")
    minimum = max(EFFORTS[MINIMUM[task.workload]], EFFORTS.get(task.min_effort, 0))
    if task.explicit_effort and EFFORTS[task.explicit_effort] < minimum:
        raise RoutingError("Requested effort is below the task's declared minimum")
    if task.explicit_cli and task.explicit_cli not in task.allowed_clis:
        raise RoutingError("Explicit CLI is outside this task's authorized candidates")
    if not task.read_only and not runtime.allow_write:
        raise RoutingError("Runtime does not grant writing")
    candidates, rejected = [], []
    for cli in matrix.clis:
        if cli.id not in task.allowed_clis or (task.explicit_cli and cli.id != task.explicit_cli):
            continue
        grants = [a for a in runtime.access if a.cli == cli.id]
        if len(grants) != 1:
            rejected.append(f"{cli.id}: no unique verified access")
            continue
        access = grants[0]
        try:
            fresh(access.verified_at, access.expires_at, now, timedelta(days=1))
        except (RoutingError, ValueError):
            rejected.append(f"{cli.id}: access evidence needs refresh")
            continue
        if cli.installed_version != access.version:
            rejected.append(f"{cli.id}: version mismatch")
            continue
        if not set(task.required_capabilities) <= set(cli.capabilities):
            rejected.append(f"{cli.id}: required capability missing")
            continue
        for model in cli.models:
            if model.id not in access.models or (
                task.explicit_model and model.id != task.explicit_model
            ):
                continue
            if model.provider == task.independent_of_provider:
                continue
            if (
                task.minimum_context_tokens
                and (model.context_tokens or 0) < task.minimum_context_tokens
            ):
                continue
            fit = model.fit.get(task.workload, 0)
            if fit < (2 if task.workload == "routine" else 4):
                continue
            efforts = [e for e in model.efforts if EFFORTS[e] >= minimum and e != "ultra"]
            if task.explicit_effort:
                efforts = [e for e in efforts if e == task.explicit_effort]
            if not efforts:
                continue
            effort = min(efforts, key=lambda e: EFFORTS[e])
            # Suitability first, then relative cost and the operator's larger Codex budget.
            # These ranks are policy judgments, never measured speed/prices/quotas.
            score = model.cost_rank * 3 + (0 if cli.id == "codex" else 4) - fit
            candidates.append((score, cli.id, model.id, effort, model.provider, access))
    if not candidates:
        raise RoutingError(
            "No evidenced, authorized CLI/model/effort matches; " + "; ".join(rejected)
        )
    _, cli, model, effort, provider, access = min(candidates, key=lambda row: row[:4])
    return {
        "schema": "bigplan.cli-decision.v1",
        "task_id": task.task_id,
        "cli": cli,
        "model": model,
        "effort": effort,
        "provider": provider,
        "executable": access.executable,
        "expected_version": access.version,
        "access_kind": access.access_kind,
        "matrix_sha256": fingerprint(matrix),
        "task_sha256": fingerprint(task),
        "runtime_sha256": fingerprint(runtime),
        "selected_at": now.isoformat(),
        "effective_model": "unverified",
        "effective_effort": "unverified",
        "coordinator": "codex",
        "reason": (
            f"{task.workload}; capabilities/access/version checked; minimum effort {minimum}; "
            "suitability then cost rank; Codex budget preferred"
        ),
        "excluded": rejected,
    }
