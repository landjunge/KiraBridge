"""Keep technical whiteboard writes in the existing audit trail.

ThreadDesk remains the place for plans, decisions, important findings and
current status. Progress, claims, tasks and problems are stored here instead.
A failure to store still answers success: this path never rejects a call.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

TECHNICAL_ENTRY_TYPES = frozenset({"progress", "claimed", "task", "problem"})
_TEXT_LIMIT = 2000
_NAME_LIMIT = 256
EXPLANATION = (
    "ThreadDesk speichert nur Pläne, Entscheidungen, wichtige Erkenntnisse "
    "und aktuelle Stände. Dieser technische Eintrag liegt in KiraBridge."
)


def routing_enabled(config: Any) -> bool:
    desk = getattr(config, "threaddesk", None)
    if isinstance(desk, dict):
        return desk.get("route_technical_entries", True) is not False
    if desk is None:
        return True
    return getattr(desk, "route_technical_entries", True) is not False


def is_whiteboard_append(name: Any) -> bool:
    if not isinstance(name, str) or not name or len(name) > 80:
        return False
    folded = name.replace(".", "_")
    while "__" in folded:
        folded = folded.replace("__", "_")
    if folded == "whiteboard_append":
        return True
    if folded.startswith("td_"):
        rest = folded[3:]
        return rest in {"whiteboard_append", "td_whiteboard_append"}
    return False


def _domain(arguments: Any) -> dict | None:
    """Deepest object that names an entry type. Envelopes wrap that object."""
    if not isinstance(arguments, dict):
        return None
    chosen = None
    queue = [arguments]
    seen = 0
    while queue and seen < 8:
        current = queue.pop(0)
        seen += 1
        if not isinstance(current, dict):
            continue
        entry_type = current.get("entry_type")
        if isinstance(entry_type, str) and entry_type:
            chosen = current
        for key in ("arguments", "data"):
            child = current.get(key)
            if isinstance(child, dict):
                queue.append(child)
    return chosen


def technical_entry_type(arguments: Any) -> str | None:
    chosen = _domain(arguments)
    if chosen is None:
        return None
    entry_type = chosen.get("entry_type")
    if entry_type in TECHNICAL_ENTRY_TYPES:
        return entry_type
    return None


def should_retain(config: Any, name: Any, arguments: Any) -> bool:
    try:
        return (
            routing_enabled(config)
            and is_whiteboard_append(name)
            and technical_entry_type(arguments) is not None
        )
    except Exception:
        return False


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


def _clip(value: Any, limit: int) -> str:
    text = _text(value)
    return text if len(text) <= limit else text[:limit]


def _thread_id(chosen: dict, root: Any) -> str:
    for source in (chosen, root if isinstance(root, dict) else None):
        if not isinstance(source, dict):
            continue
        for key in ("thread_id", "id"):
            value = source.get(key)
            if isinstance(value, str):
                return _clip(value, _NAME_LIMIT)
    return ""


def _who(principal: Any, actor: str) -> str:
    for value in (principal, actor, "unknown"):
        text = _clip(value, _NAME_LIMIT).strip()
        if text:
            return text
    return "unknown"


def retained_record(store: Any, principal: Any, tool: Any, arguments: Any) -> dict:
    """Audit one technical entry. Truncation and a missing store do not raise."""
    try:
        chosen = _domain(arguments) or {}
        entry_type = technical_entry_type(arguments) or "progress"
        raw = _text(chosen.get("content"))
        actor = _clip(chosen.get("actor"), _NAME_LIMIT)
        thread_id = _thread_id(chosen, arguments)
        digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
        metadata = {
            "tool": _clip(tool, 80) or "whiteboard_append",
            "thread_id": thread_id,
            "entry_type": entry_type,
            "actor": actor,
            "at": time.time(),
            "content_sha256": digest,
            "content": raw[:_TEXT_LIMIT],
            "content_truncated": len(raw) > _TEXT_LIMIT,
        }
        key = chosen.get("external_key")
        if isinstance(key, str) and key:
            metadata["external_key"] = _clip(key, 128)
        stored = _audit(store, _who(principal, actor), metadata)
        return {
            "routed": "kirabridge",
            "stored": stored,
            "explanation": EXPLANATION,
            "entry_type": entry_type,
            "thread_id": thread_id,
            "actor": actor,
            "content_sha256": digest,
            "content_truncated": len(raw) > _TEXT_LIMIT,
        }
    except Exception:
        return {
            "routed": "kirabridge",
            "stored": False,
            "explanation": EXPLANATION,
            "entry_type": "progress",
            "thread_id": "",
            "actor": "",
            "content_sha256": hashlib.sha256(b"").hexdigest(),
            "content_truncated": False,
        }


def _audit(store: Any, principal: str, metadata: dict) -> bool:
    if store is None:
        return False
    try:
        with store.transaction():
            store.audit("whiteboard.technical", principal, None, metadata)
        return True
    except Exception:
        smaller = {
            "thread_id": metadata.get("thread_id") or "",
            "entry_type": metadata.get("entry_type") or "progress",
            "actor": metadata.get("actor") or "",
            "at": time.time(),
            "content_sha256": metadata.get("content_sha256") or "",
            "content": "",
            "content_truncated": True,
        }
        try:
            with store.transaction():
                store.audit("whiteboard.technical", principal, None, smaller)
            return True
        except Exception:
            return False


def dynamic_success(bridge: Any, principal: Any, name: str, arguments: Any) -> dict:
    body = retained_record(getattr(bridge, "store", None), principal, name, arguments)
    return {
        "success": True,
        "routed": "kirabridge",
        "stored": body["stored"],
        "explanation": body["explanation"],
        "value": body,
        "scope": "kirabridge_technical_entry",
        "tool": name,
        "instruction": body["explanation"],
        "automatic_retry": False,
        "response_received": False,
        "effect_confirmed": False,
    }


def manager_success(store: Any, principal: Any, arguments: Any) -> dict:
    body = retained_record(store, principal, "whiteboard_append", arguments)
    return {
        "success": True,
        "value": body,
        "scope": "kirabridge_technical_entry",
        "instruction": body["explanation"],
        "evidence": {
            "adapter": "kirabridge",
            "tool": "whiteboard_append",
            "peer_called": False,
            "routed": "kirabridge",
        },
    }


def proxy_retention(config: Any, name: Any, arguments: Any) -> dict | None:
    """Daemon call that stores the entry, or None when ThreadDesk still receives it."""
    if not should_retain(config, name, arguments):
        return None
    payload = arguments if isinstance(arguments, dict) else {}
    forwarded = {"name": name, "arguments": payload}
    operation_id = payload.get("operation_id")
    if not isinstance(operation_id, str):
        nested = payload.get("arguments")
        operation_id = nested.get("operation_id") if isinstance(nested, dict) else None
    if isinstance(operation_id, str) and operation_id:
        forwarded["operation_id"] = operation_id[:128]
    return forwarded


def mcp_append_decision(
    bridge: Any,
    principal: Any,
    *,
    thread_id: Any,
    entry_type: Any,
    content: Any,
    actor: Any,
    actor_type: Any,
    external_key: Any,
) -> dict | None:
    payload = {
        "thread_id": thread_id,
        "entry_type": entry_type,
        "content": content,
        "actor": actor,
        "actor_type": actor_type,
        "external_key": external_key,
    }
    if not should_retain(getattr(bridge, "config", None), "whiteboard_append", payload):
        return None
    return retained_record(getattr(bridge, "store", None), principal, "whiteboard_append", payload)
