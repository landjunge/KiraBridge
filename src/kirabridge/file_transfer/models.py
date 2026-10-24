"""Stable metadata and input shapes; download capabilities never enter task arguments."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL = "kirabridge.threaddesk.files.v1"


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OpenAIFile(Model):
    # Required/optional fields follow official openai/fileParams exactly.
    download_url: str = Field(min_length=1, max_length=8192, repr=False)
    file_id: str = Field(min_length=1, max_length=256)
    mime_type: str = Field(default="", max_length=256)
    file_name: str = Field(default="", max_length=255)


class PrepareInput(Model):
    source_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    project_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    folder: str = Field(default="", max_length=2048)
    library_path: str | None = Field(default=None, max_length=4096)
    source_version: str | None = Field(default=None, max_length=256)
    expected_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class TransferInput(Model):
    transfer_id: str = Field(pattern=r"^[a-f0-9]{64}$")


class InventoryInput(Model):
    after: str = Field(default="", max_length=64)
    limit: int = Field(default=100, ge=1, le=100)


class Manifest(Model):
    protocol: Literal["kirabridge.threaddesk.files.v1"] = PROTOCOL
    name: str
    mime_type: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    project_id: str
    folder: str
    library_path: str | None
    source_kind: Literal["chatgpt_file_param", "authorized_export"]
    source_ref: str
    source_version: str | None
    destination_ref: str = Field(pattern=r"^[a-f0-9]{64}$")


class Limits(Model):
    max_file_bytes: int = Field(default=2 * 1024**3, ge=1, le=64 * 1024**3)
    max_staged_bytes: int = Field(default=8 * 1024**3, ge=1, le=256 * 1024**3)
    chunk_bytes: int = Field(default=256 * 1024, ge=16384, le=1024 * 1024)
    max_archive_entries: int = Field(default=10000, ge=1, le=100000)
    max_archive_expanded_bytes: int = Field(default=8 * 1024**3, ge=1, le=128 * 1024**3)
    max_compression_ratio: int = Field(default=200, ge=1, le=10000)
