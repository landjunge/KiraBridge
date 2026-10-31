"""Exact native process metadata/signals; never process groups, command lines or environments."""

from typing import Literal

from pydantic import Field, model_validator

from kirabridge.bridge_core.models import Input


class SystemProcessListInput(Input):
    """Sorted public process metadata, with GUI executable paths and explicit unknown CLI paths."""

    include_system: bool = False
    offset: int = Field(default=0, ge=0, le=100000)
    limit: int = Field(default=100, ge=1, le=500)
    expected_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def stable_page(self):
        if self.offset and self.expected_revision is None:
            raise ValueError("Process continuation requires the observed inventory revision")
        return self


class SystemProcessInput(Input):
    """Inspect one exact PID and kernel start token; arguments and environment are never read."""

    pid: int = Field(gt=0, le=2**31 - 1)
    expected_start: str = Field(pattern=r"^[0-9]{1,12}\.[0-9]{6}$")


class SystemSignalInput(SystemProcessInput):
    """Signal after fresh PID/start, owner and lineage checks.

    Kernel kill has no atomic process-start guard.
    """

    signal: Literal["TERM", "INT", "HUP", "KILL"]


SERVICE_INPUTS = {
    "system.processes": SystemProcessListInput,
    "system.process": SystemProcessInput,
    "system.signal": SystemSignalInput,
}
