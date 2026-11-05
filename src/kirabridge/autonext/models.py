"""Operator grants are configuration; board prose never grants authority."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from kirabridge.bridge_core.models import Input

ID = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$"
SHA = r"^[a-f0-9]{64}$"
SESSION_ID = r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$"


class ApprovedCard(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    task_id: str = Field(pattern=ID)
    entry_id: str = Field(pattern=ID)
    content_sha256: str = Field(pattern=SHA)


class LegacyScopeBinding(BaseModel):
    """A historical execution identity, never an execution/completion grant."""

    model_config = ConfigDict(extra="forbid", strict=True)
    message_id: str = Field(pattern=ID)
    run_id: str = Field(pattern=ID)
    recipient: Literal["codex", "grok"]
    session_id: str = Field(pattern=SESSION_ID)
    observation_sha256: str = Field(pattern=SHA)
    cwd: str = Field(min_length=1, max_length=4096)

    @field_validator("cwd")
    @classmethod
    def absolute_scope(cls, value):
        if not Path(value).is_absolute() or "\x00" in value:
            raise ValueError("Historical execution scope must be absolute")
        return value


class LegacyScopePin(LegacyScopeBinding):
    attestation_path: str = Field(min_length=1, max_length=4096)
    attestation_sha256: str = Field(pattern=SHA)

    @field_validator("attestation_path")
    @classmethod
    def absolute_attestation(cls, value):
        return cls.absolute_scope(value)


class AutoNextConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    grant_id: str = Field(default="", max_length=96)
    principal: Literal["local", "chatgpt"] = "local"
    team_id: str = Field(default="", max_length=128)
    team_revision: int = Field(default=0, ge=0)
    board_id: str = Field(default="", max_length=128)
    after_work_id: str = Field(default="", max_length=128)
    after_result_sha256: str = ""
    cards: list[ApprovedCard] = Field(default_factory=list, max_length=16)
    legacy_scope_pins: list[LegacyScopePin] = Field(default_factory=list, max_length=64)
    max_tasks: int = Field(default=2, ge=1, le=16)
    lease_seconds: float = Field(default=360, ge=5, le=900)
    # A bounded operator observation, never an invented subscription quota.
    budget_state: Literal["unknown", "available", "exhausted"] = "unknown"
    budget_observed_at: float = Field(default=0, ge=0)
    budget_valid_until: float = Field(default=0, ge=0)
    budget_source_ref: str = Field(default="", max_length=256)
    billing_evidence_ref: str = Field(default="", max_length=256)

    @model_validator(mode="after")
    def bounded_grant(self):
        import re

        for key in ("message_id", "run_id", "session_id"):
            if len({getattr(pin, key) for pin in self.legacy_scope_pins}) != len(
                self.legacy_scope_pins
            ):
                raise ValueError("Legacy scope pins must have unique message, run and session IDs")
        if self.enabled:
            if (
                not all((self.team_id, self.board_id, self.after_work_id))
                or not re.fullmatch(ID, self.grant_id)
                or not re.fullmatch(SHA, self.after_result_sha256)
                or self.principal == "codex"
            ):
                raise ValueError("AutoNext needs an explicit operator grant and completion anchor")
            if len({c.task_id for c in self.cards}) != len(self.cards):
                raise ValueError("Task IDs must be unique within the grant")
        return self


class Acceptance(Input):
    kind: Literal["result_sha256", "operator_receipt"]
    expected_sha256: str | None = Field(default=None, pattern=SHA)

    @model_validator(mode="after")
    def expected_result(self):
        if (self.kind == "result_sha256") != (self.expected_sha256 is not None):
            raise ValueError("Only exact-result acceptance carries a preapproved result hash")
        return self


class ReadyCard(Input):
    autonext: Literal[1]
    task_id: str = Field(pattern=ID)
    state: Literal["READY", "IDEA", "HOLD", "UNKNOWN", "STALE", "CANCELLED"]
    product: Literal["KiraBridge", "ThreadDesk", "4AllPass", "TollGate", "AgentAuthority"]
    cwd: str = Field(min_length=1, max_length=4096)
    sandbox: Literal["read-only", "workspace-write"] = "read-only"
    title: str = Field(min_length=1, max_length=256)
    instruction: str = Field(min_length=1, max_length=12000)
    acceptance: Acceptance

    @field_validator("autonext", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Expected exact card version 1")
        return value

    @model_validator(mode="after")
    def writing_acceptance(self):
        if self.sandbox == "workspace-write" and self.acceptance.kind != "operator_receipt":
            raise ValueError("Writing work requires independently confirmed completion evidence")
        return self


class AutoNextControl(Input):
    action: Literal["wake", "confirm"]
    grant_id: str = Field(pattern=ID)
    task_id: str | None = Field(default=None, pattern=ID)
    result_sha256: str | None = Field(default=None, pattern=SHA)
    evidence_ref: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def exact_confirmation(self):
        fields = (self.task_id, self.result_sha256, self.evidence_ref)
        if (self.action == "confirm" and not all(fields)) or (
            self.action == "wake" and any(value is not None for value in fields)
        ):
            raise ValueError("Confirm binds one exact result; wake carries no executable input")
        return self
