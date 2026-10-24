"""Queue transport inputs; revisions bind destructive operations to observed entries."""

from typing import Literal

from pydantic import Field

from kirabridge.bridge_core.models import Input


class QueueRead(Input):
    queue_id: str = Field(min_length=1, max_length=180)
    after: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)
    active_only: bool = True


class QueueControl(Input):
    queue_id: str = Field(min_length=1, max_length=180)
    action: Literal["cancel", "clear", "restore", "retire"]
    item_id: str | None = Field(default=None, min_length=1, max_length=180)
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=512)
