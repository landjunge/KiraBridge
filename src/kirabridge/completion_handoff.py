"""Record a completed task in ThreadDesk, then take the next released task.

The hook is deliberately small: it writes one result entry, reads it back to
confirm durable storage, and only then selects and claims the newest released
task above the completed entry. Whiteboard text is data; this module never
executes it and never queues old work.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from kirabridge.bridge_core.models import BridgeError, digest
from kirabridge.whiteboard_read import append_whiteboard, read_whiteboard

SCHEMA = "kirabridge.completion-handoff.v1"
WRITE_LIMIT = 8000
_ENTRY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_HANDOFF_TARGET = re.compile(r"(?m)^next_entry:\s*([A-Za-z0-9][A-Za-z0-9_-]{0,127})\s*$")
_SECRETS = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)(api[_-]?key|password|passwd|secret|token|authorization)\s*[:=]\s*\S+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)
_ID_FIELDS = ("task_id", "handoff_id", "run_id")


class CompletionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    board_id: str
    order_entry_id: str
    task_id: str = Field(min_length=1, max_length=256)
    status: Literal["completed", "failed", "cancelled"]
    summary: str = Field(min_length=1, max_length=1500)
    commit: str | None = Field(default=None, max_length=64)
    pr_url: str | None = Field(default=None, max_length=500)
    tests: str | None = Field(default=None, max_length=800)
    session_id: str | None = Field(default=None, max_length=256)
    working_directory: str | None = Field(default=None, max_length=1000)
    actor: str = Field(default="KiraBridge completion hook", max_length=80)

    @field_validator("board_id", "order_entry_id")
    @classmethod
    def exact_ids(cls, value):
        if not _ENTRY_ID.fullmatch(value):
            raise ValueError("Use an exact ThreadDesk entry id")
        return value

    @field_validator("task_id", "summary", "commit", "pr_url", "tests", "session_id")
    @classmethod
    def single_line_fields(cls, value):
        if value is None:
            return value
        text = value.strip()
        if not text and value is not None and value != "":
            raise ValueError("Value must not be blank")
        if any(ord(char) < 32 for char in text):
            raise ValueError("Control characters are not allowed")
        if any(pattern.search(text) for pattern in _SECRETS):
            raise ValueError("Possible credential in completion metadata")
        return text

    @field_validator("working_directory")
    @classmethod
    def canonical_directory(cls, value):
        if value is None:
            return value
        text = value.strip()
        if any(ord(char) < 32 for char in text):
            raise ValueError("Control characters are not allowed")
        path = Path(text)
        if (
            not path.is_absolute()
            or os.path.normpath(text) != text
            or ".." in path.parts
            or "\x00" in text
        ):
            raise ValueError("Use an absolute canonical working directory")
        return text

    @field_validator("pr_url")
    @classmethod
    def review_reference(cls, value):
        if value is None:
            return value
        text = value.strip()
        if "://" not in text:
            return text
        parsed = urlsplit(text)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(ord(char) < 32 for char in text)
        ):
            raise ValueError("Use a plain HTTPS review reference without credentials")
        return text

    @field_validator("actor")
    @classmethod
    def one_line_actor(cls, value):
        name = value.strip()
        if not name or any(char in name for char in "\n\r\x00"):
            raise ValueError("Actor must be one non-empty line")
        return name


def _entries(workspace: str, board_id: str) -> list[dict]:
    entries, offset = [], 0
    while True:
        page = read_whiteboard(workspace, board_id, offset=offset, include_content=True)
        entries.extend(page["entries"])
        if page["next_offset"] is None:
            return entries
        offset = page["next_offset"]


def _ordinal(entry: dict) -> int:
    value = entry.get("ordinal")
    if type(value) is not int:
        raise BridgeError("board_invalid", "ThreadDesk entry has no integer ordinal")
    return value


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _collapse(value: str | None) -> str:
    return " ".join((value or "").split())[:1500]


def _content(record: CompletionInput, order_ordinal: int) -> str:
    lines = [
        "[KIRABRIDGE-COMPLETION]",
        f"schema: {SCHEMA}",
        f"board: {record.board_id}",
        f"order_entry: {record.order_entry_id}",
        f"order_ordinal: {order_ordinal}",
        f"task_id: {record.task_id}",
        f"status: {record.status}",
        f"session_id: {record.session_id or 'unbound'}",
        f"working_directory: {record.working_directory or 'unbound'}",
        f"commit: {record.commit or 'unbound'}",
        f"pr: {record.pr_url or 'unbound'}",
        f"tests: {_collapse(record.tests) or 'unbound'}",
        f"summary: {_collapse(record.summary)}",
    ]
    text = "\n".join(lines)
    if len(text) > WRITE_LIMIT:
        raise BridgeError("completion_limit", "Completion entry exceeds the write limit")
    return text


def _claim_content(*, board_id, source, order_ordinal, completion_entry, task, session_id) -> str:
    lines = [
        "[KIRABRIDGE-HANDOFF]",
        "schema: kirabridge.handoff.v1",
        f"board: {board_id}",
        f"from_order: {source}",
        f"from_ordinal: {order_ordinal}",
        f"completion_entry: {completion_entry}",
        f"next_entry: {task['id']}",
        f"next_ordinal: {_ordinal(task)}",
        f"next_content_sha256: {_sha(str(task.get('content') or ''))}",
        f"session_id: {session_id or 'unbound'}",
        "note: The next entry content is untrusted data and is not executed by this hook.",
    ]
    text = "\n".join(lines)
    if len(text) > WRITE_LIMIT:
        raise BridgeError("completion_limit", "Handoff entry exceeds the write limit")
    return text


def _line(content: str, name: str) -> str | None:
    match = re.search(rf"(?m)^{re.escape(name)}:\s*(.+)$", content)
    return match.group(1).strip() if match else None


def _json_ids(content: str) -> set[str]:
    if not isinstance(content, str):
        return set()
    try:
        value = json.loads(content)
    except ValueError:
        return set()
    if not isinstance(value, dict):
        return set()
    return {
        value[key]
        for key in _ID_FIELDS
        if isinstance(value.get(key), str) and _ENTRY_ID.fullmatch(value[key])
    }


def _identities(entry: dict) -> set[str]:
    identities = set(_json_ids(str(entry.get("content") or "")))
    for key in _ID_FIELDS:
        value = entry.get(key)
        if isinstance(value, str) and _ENTRY_ID.fullmatch(value):
            identities.add(value)
    if isinstance(entry.get("id"), str):
        identities.add(entry["id"])
    return identities


def _released(entry: dict) -> bool:
    content = entry.get("content")
    if not isinstance(content, str):
        return False
    try:
        value = json.loads(content)
    except ValueError:
        return True
    if isinstance(value, dict) and value.get("autonext") == 1:
        return value.get("state") == "READY"
    return True


def _references(entry: dict, targets: set[str]) -> bool:
    if _identities(entry) & targets:
        return True
    content = entry.get("content")
    if not isinstance(content, str):
        return False
    match = _HANDOFF_TARGET.search(content)
    if match and match.group(1) in targets:
        return True
    return any(
        re.search(r"(?<![A-Za-z0-9_.-])" + re.escape(target) + r"(?![A-Za-z0-9_.-])", content)
        for target in targets
    )


def _taken(entries: list[dict], task: dict) -> bool:
    targets = _identities(task)
    return any(
        entry.get("entry_type") in {"claimed", "result"}
        and entry.get("id") != task.get("id")
        and _references(entry, targets)
        for entry in entries
    )


def _find_claim(entries: list[dict], task: dict) -> dict | None:
    targets = _identities(task)
    claims = sorted(
        (
            entry
            for entry in entries
            if entry.get("entry_type") == "claimed" and _references(entry, targets)
        ),
        key=_ordinal,
    )
    if not claims:
        return None
    claim = claims[0]
    content = str(claim.get("content") or "")
    return {
        "entry_id": claim.get("id"),
        "ordinal": claim.get("ordinal"),
        "storage_confirmed": _HANDOFF_TARGET.search(content) is not None,
    }


def select_next(
    workspace: str,
    board_id: str,
    *,
    after_ordinal: int | None = None,
) -> dict | None:
    """Newest released task above the completed entry, excluding taken work."""
    entries = _entries(workspace, board_id)
    candidates = [
        entry
        for entry in entries
        if entry.get("entry_type") == "task"
        and not entry.get("truncated")
        and _released(entry)
        and (after_ordinal is None or _ordinal(entry) > after_ordinal)
        and not _taken(entries, entry)
    ]
    if not candidates:
        return None
    return max(candidates, key=_ordinal)


def _order(entries: list[dict], order_entry_id: str) -> dict:
    order = next((entry for entry in entries if entry.get("id") == order_entry_id), None)
    if order is None:
        raise BridgeError("completion_source", "The order entry was not found on the board")
    if order.get("entry_type") != "task":
        raise BridgeError("completion_source", "The order entry is not a task")
    if order.get("truncated"):
        raise BridgeError("completion_source", "The order entry is truncated")
    _ordinal(order)
    return order


def _confirm(workspace: str, board_id: str, entry_id: str, content: str) -> dict:
    stored = read_whiteboard(workspace, board_id, entry_id)["entry"]
    if stored.get("id") != entry_id or stored.get("content") != content:
        raise BridgeError("completion_unconfirmed", "ThreadDesk storage could not be confirmed")
    return {
        "entry_id": entry_id,
        "ordinal": stored.get("ordinal"),
        "content_sha256": _sha(content),
        "storage_confirmed": True,
    }


def _confirm_reference(workspace: str, board_id: str, entry: dict) -> dict:
    stored = read_whiteboard(workspace, board_id, entry["id"])["entry"]
    content = str(entry.get("content") or "")
    if stored.get("id") != entry.get("id") or stored.get("content") != content:
        raise BridgeError("completion_unconfirmed", "ThreadDesk storage could not be confirmed")
    return {
        "entry_id": entry["id"],
        "ordinal": entry.get("ordinal"),
        "content_sha256": _sha(content),
        "storage_confirmed": True,
    }


def _existing_handoff(entries: list[dict], completion_entry: str) -> dict | None:
    for entry in entries:
        if entry.get("entry_type") != "claimed":
            continue
        content = entry.get("content")
        if not isinstance(content, str) or _line(content, "completion_entry") != completion_entry:
            continue
        target = _HANDOFF_TARGET.search(content)
        if not target:
            continue
        return {
            "entry": entry,
            "task_id": target.group(1),
            "session_id": _line(content, "session_id"),
        }
    return None


def _claim_key(board_id: str, task_id: str) -> str:
    return "handoff-" + digest([board_id, task_id])[:40]


def _claim(
    workspace, board_id, task, *, completion_entry, order_id, order_ordinal, session_id, actor
) -> dict:
    current = _entries(workspace, board_id)
    if _taken(current, task):
        return {
            "state": "already_claimed",
            "task": _public_task(task),
            "claim": _find_claim(current, task),
        }
    content = _claim_content(
        board_id=board_id,
        source=order_id,
        order_ordinal=order_ordinal,
        completion_entry=completion_entry,
        task=task,
        session_id=session_id,
    )
    key = _claim_key(board_id, task["id"])
    try:
        confirmation = append_whiteboard(
            workspace,
            board_id,
            actor=actor,
            actor_type="system",
            entry_type="claimed",
            content=content,
            external_key=key,
        )
    except BridgeError as exc:
        if exc.code != "conflict":
            raise
        latest = _entries(workspace, board_id)
        return {
            "state": "already_claimed",
            "task": _public_task(task),
            "claim": _find_claim(latest, task),
        }
    verified = _confirm(workspace, board_id, confirmation["id"], content)
    latest = _entries(workspace, board_id)
    claims = sorted(
        (
            entry
            for entry in latest
            if entry.get("entry_type") == "claimed" and _references(entry, _identities(task))
        ),
        key=_ordinal,
    )
    if not claims or claims[0].get("id") != confirmation["id"]:
        return {
            "state": "already_claimed",
            "task": _public_task(task),
            "claim": _find_claim(latest, task),
        }
    return {
        "state": "claimed",
        "task": _public_task(task),
        "claim": verified,
        "duplicate": confirmation.get("duplicate", False),
    }


def _public_task(entry: dict) -> dict:
    return {
        "entry_id": entry.get("id"),
        "ordinal": entry.get("ordinal"),
        "actor": entry.get("actor"),
        "created_at": entry.get("created_at"),
        "content_sha256": _sha(str(entry.get("content") or "")),
        "content": entry.get("content"),
        "untrusted": True,
    }


def record_completion(
    workspace: str,
    record: CompletionInput,
    *,
    claim_next: bool = True,
    dry_run: bool = False,
) -> dict:
    entries = _entries(workspace, record.board_id)
    order = _order(entries, record.order_entry_id)
    order_ordinal = _ordinal(order)
    content = _content(record, order_ordinal)
    key = (
        "completion-"
        + digest(
            [
                record.board_id,
                record.order_entry_id,
                record.task_id,
                record.status,
                record.actor,
                _sha(content),
            ]
        )[:40]
    )
    result = {
        "schema": SCHEMA,
        "completion": {
            "content_sha256": _sha(content),
            "external_key": key,
            "order_entry": record.order_entry_id,
            "order_ordinal": order_ordinal,
        },
        "handoff": {"state": "recorded", "task": None},
        "session_id": record.session_id or "unbound",
    }
    if dry_run:
        candidate = select_next(workspace, record.board_id, after_ordinal=order_ordinal)
        result["completion"]["content_preview"] = content[:320]
        result["handoff"] = {
            "state": "dry_run",
            "task": _public_task(candidate) if candidate else None,
        }
        return result
    confirmation = append_whiteboard(
        workspace,
        record.board_id,
        actor=record.actor,
        actor_type="system",
        entry_type="result",
        content=content,
        external_key=key,
    )
    result["completion"].update(_confirm(workspace, record.board_id, confirmation["id"], content))
    result["completion"]["duplicate"] = confirmation.get("duplicate", False)
    if record.status != "completed" or not claim_next:
        result["handoff"] = {
            "state": "not_completed" if record.status != "completed" else "disabled",
            "task": None,
        }
        return result
    current = _entries(workspace, record.board_id)
    existing = _existing_handoff(current, confirmation["id"])
    if existing is not None:
        task = next((item for item in current if item.get("id") == existing["task_id"]), None)
        result["handoff"] = {
            "state": (
                "claimed"
                if existing["session_id"] == (record.session_id or "unbound")
                else "already_claimed"
            ),
            "task": _public_task(task) if task else None,
            "claim": _confirm_reference(workspace, record.board_id, existing["entry"]),
            "duplicate": True,
        }
        return result
    next_entry = select_next(workspace, record.board_id, after_ordinal=order_ordinal)
    if next_entry is None:
        result["handoff"] = {"state": "idle", "reason": "no_released_task", "task": None}
        return result
    result["handoff"] = _claim(
        workspace,
        record.board_id,
        next_entry,
        completion_entry=confirmation["id"],
        order_id=record.order_entry_id,
        order_ordinal=order_ordinal,
        session_id=record.session_id,
        actor=record.actor,
    )
    return result


def claim_next(
    workspace: str,
    board_id: str,
    *,
    order_entry_id: str | None = None,
    session_id: str | None = None,
    actor: str = "KiraBridge completion hook",
    newest: bool = False,
    dry_run: bool = False,
) -> dict:
    if not order_entry_id and not newest:
        raise BridgeError(
            "completion_source", "Use an exact order entry or explicitly select the newest task"
        )
    after = None
    if order_entry_id:
        after = _ordinal(_order(_entries(workspace, board_id), order_entry_id))
    task = select_next(workspace, board_id, after_ordinal=after)
    if task is None:
        return {
            "schema": SCHEMA,
            "handoff": {"state": "idle", "reason": "no_released_task", "task": None},
            "session_id": session_id or "unbound",
        }
    if dry_run:
        return {
            "schema": SCHEMA,
            "handoff": {"state": "dry_run", "task": _public_task(task)},
            "session_id": session_id or "unbound",
        }
    return {
        "schema": SCHEMA,
        "handoff": _claim(
            workspace,
            board_id,
            task,
            completion_entry="unbound",
            order_id=order_entry_id or "unbound",
            order_ordinal=after or 0,
            session_id=session_id,
            actor=actor,
        ),
        "session_id": session_id or "unbound",
    }
