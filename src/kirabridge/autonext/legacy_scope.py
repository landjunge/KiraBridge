"""Read-only historical scope proof for explicitly pinned legacy timeout jobs.

A scope observation does not complete, retire, requeue or otherwise alter a job.
Only original provider metadata and its persisted receiver progress anchor count.
"""

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from kirabridge.autonext.models import SHA, LegacyScopeBinding
from kirabridge.bridge_core.models import BridgeError, digest

MAX_ATTESTATION_BYTES = 16384
MAX_SOURCE_BYTES = 8 * 1024 * 1024


class ScopeSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["grok_summary", "grok_context", "codex_rollout"]
    path: str = Field(min_length=1, max_length=4096)
    sha256: str = Field(pattern=SHA)


class ScopeAttestation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1]
    binding: LegacyScopeBinding
    sources: list[ScopeSource] = Field(min_length=1, max_length=2)

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Expected exact attestation version 1")
        return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate evidence field")
        result[key] = value
    return result


def _object(raw):
    result = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(result, dict):
        raise ValueError("Expected bounded evidence object")
    return result


def _canonical_path(value):
    path = Path(value)
    if not path.is_absolute() or path.resolve(strict=True) != path or path.is_symlink():
        raise ValueError("Unbound historical evidence path")
    return path


def _read_private(path, maximum, expected_sha256):
    path = _canonical_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_mode & 0o077
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum
        ):
            raise ValueError("Historical evidence is not a private owned bounded regular file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(maximum + 1)
        after = os.fstat(fd)

        def identity(s):
            return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns

        if (
            identity(before) != identity(after)
            or len(raw) != before.st_size
            or _canonical_path(path) != path
            or hashlib.sha256(raw).hexdigest() != expected_sha256
        ):
            raise ValueError("Historical evidence changed")
        return raw
    finally:
        os.close(fd)


def _provider_root(recipient):
    return Path.home() / (".grok" if recipient == "grok" else ".codex") / "sessions"


def _historical_sources(pin, attestation):
    sources = {source.kind: source for source in attestation.sources}
    required = {"grok_summary", "grok_context"} if pin.recipient == "grok" else {"codex_rollout"}
    if len(sources) != len(attestation.sources) or set(sources) != required:
        raise ValueError("Historical source set differs")
    provider = _canonical_path(_provider_root(pin.recipient))
    if pin.recipient == "grok":
        folder = provider / quote(pin.cwd, safe="") / pin.session_id
        values = {}
        for kind, filename in (
            ("grok_summary", "summary.json"),
            ("grok_context", "prompt_context.json"),
        ):
            source = sources[kind]
            if Path(source.path) != folder / filename:
                raise ValueError("Historical Grok session path differs")
            values[kind] = _object(_read_private(source.path, MAX_SOURCE_BYTES, source.sha256))
        info = values["grok_summary"].get("info")
        if (
            not isinstance(info, dict)
            or info.get("id") != pin.session_id
            or info.get("cwd") != pin.cwd
            or values["grok_context"].get("working_directory") != pin.cwd
        ):
            raise ValueError("Historical Grok session identity differs")
    else:
        source = sources["codex_rollout"]
        path = _canonical_path(source.path)
        relative = path.relative_to(provider)
        if len(relative.parts) != 4 or not path.name.endswith("-" + pin.session_id + ".jsonl"):
            raise ValueError("Historical Codex rollout path differs")
        raw = _read_private(path, MAX_SOURCE_BYTES, source.sha256)
        first = _object(raw.splitlines()[0])
        metadata = first.get("payload")
        if (
            first.get("type") != "session_meta"
            or not isinstance(metadata, dict)
            or metadata.get("id") != pin.session_id
            or metadata.get("session_id", pin.session_id) != pin.session_id
            or metadata.get("cwd") != pin.cwd
        ):
            raise ValueError("Historical Codex session identity differs")


def legacy_scope_for_job(settings, row, db):
    """Return only one proven CWD; ordinary overlap checks remain authoritative."""
    pins = [pin for pin in settings.legacy_scope_pins if pin.message_id == row["message_id"]]
    if not pins:
        return None
    try:
        if len(pins) != 1:
            raise ValueError("Ambiguous legacy scope pin")
        pin = pins[0]
        if (
            row["state"] != "unknown"
            or row["error"] != "agent_timeout"
            or row["execution_cwd"] is not None
            or row["run_id"] != pin.run_id
            or row["recipient"] != pin.recipient
            or not _canonical_path(pin.cwd).is_dir()
            or len(row["evidence"].encode("utf-8")) > MAX_ATTESTATION_BYTES
        ):
            raise ValueError("Legacy execution identity differs")
        evidence = _object(row["evidence"])
        if evidence.get("run_id") != pin.run_id:
            raise ValueError("Legacy receiver run differs")
        observation = evidence.get("last_observation")
        for _ in range(3):
            if not isinstance(observation, str):
                break
            observation = _object(observation)
        if (
            not isinstance(observation, dict)
            or observation.get("agent") != pin.recipient
            or observation.get("session_id") != pin.session_id
            or digest(observation) != pin.observation_sha256
        ):
            raise ValueError("Original receiver session observation differs")
        anchored = False
        for event in db.execute(
            "SELECT evidence FROM message_events WHERE message_id=? "
            "AND kind='message.agent_progress' "
            "ORDER BY seq DESC LIMIT 256",
            (pin.message_id,),
        ):
            if len(event[0].encode("utf-8")) > MAX_ATTESTATION_BYTES:
                continue
            progress = _object(event[0])
            if (
                progress.get("run_id") == pin.run_id
                and progress.get("evidence_sha256") == pin.observation_sha256
            ):
                anchored = True
                break
        if not anchored:
            raise ValueError("No original progress anchor")
        raw = _read_private(pin.attestation_path, MAX_ATTESTATION_BYTES, pin.attestation_sha256)
        attestation = ScopeAttestation.model_validate(_object(raw))
        binding = LegacyScopeBinding.model_validate(
            pin.model_dump(exclude={"attestation_path", "attestation_sha256"})
        )
        if attestation.binding != binding:
            raise ValueError("Scope attestation differs from operator pin")
        _historical_sources(pin, attestation)
        return pin.cwd
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise BridgeError(
            "autonext_scope_unknown", "Pinned historical execution scope is unconfirmed"
        ) from None
