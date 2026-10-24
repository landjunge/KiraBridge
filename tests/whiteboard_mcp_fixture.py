"""Isolated administration contract fixture, not ThreadDesk application code."""

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

root = Path(os.environ["THREADDESK_HOME"])
state_path = root / "whiteboard-fixture.json"
server = FastMCP("WhiteboardContractFixture")


def load():
    return json.loads(state_path.read_text()) if state_path.exists() else {"threads": {}, "ops": {}}


def save(state):
    pending = state_path.with_suffix(".pending")
    with pending.open("w") as target:
        json.dump(state, target, ensure_ascii=False)
        target.flush()
        os.fsync(target.fileno())
    pending.replace(state_path)


def failure(code, **details):
    value = {"code": code, "details": details}
    return CallToolResult(
        isError=True,
        content=[TextContent(type="text", text=json.dumps(value))],
        structuredContent=value,
    )


@server.tool()
def list_threads() -> dict[str, Any]:
    return {"threads": list(load()["threads"].values())}


@server.tool()
def get_thread(id: str) -> dict[str, Any]:
    return load()["threads"][id]


@server.tool()
def thread_operation_status(operation_id: str) -> dict[str, Any]:
    saved = load()["ops"].get(operation_id)
    return {
        "operation_id": operation_id,
        "found": bool(saved),
        "result": saved["receipt"] if saved else None,
    }


@server.tool()
def thread_manage(
    operation_id: str,
    action: str,
    expected_revision: int,
    data: dict[str, Any],
    id: str | None = None,
):
    state = load()
    payload = {
        "operation_id": operation_id,
        "action": action,
        "expected_revision": expected_revision,
        "data": data,
        "id": id,
    }
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    saved = state["ops"].get(operation_id)
    if saved:
        if saved["hash"] != fingerprint:
            return failure("operation_conflict")
        return {**saved["receipt"], "duplicate": True}
    for field in ("title", "description", "text"):
        if field in data and len(data[field]) > (100000 if field == "text" else 10000):
            return failure(
                "validation_error",
                max_length=100000 if field == "text" else 10000,
                actual_length=len(data[field]),
            )
    if action == "create":
        id = "synthetic" + str(len(state["threads"]) + 1)
        thread = {
            "id": id,
            "revision": 0,
            "title": data["title"],
            "description": data.get("description", ""),
            "notes": "",
        }
    else:
        thread = state["threads"][id]
        if thread["revision"] != expected_revision:
            return failure("revision_conflict", actual_revision=thread["revision"])
    if action == "update":
        thread.update(data)
    elif action == "set_note":
        thread["notes"] = (
            thread["notes"] + "\n" + data["text"]
            if data.get("append") and thread["notes"]
            else data["text"]
        )
    thread["revision"] += 1
    state["threads"][id] = thread
    receipt = {
        "operation_id": operation_id,
        "action": action,
        "thread_id": id,
        "revision": thread["revision"],
        "deleted": False,
        "duplicate": False,
        "thread": dict(thread),
    }
    state["ops"][operation_id] = {"hash": fingerprint, "receipt": receipt}
    save(state)
    marker = root / "lost-receipt-once"
    if "--lose-receipt" in sys.argv and not marker.exists():
        marker.write_text("stored before exit")
        os._exit(71)
    return receipt


if __name__ == "__main__":
    server.run(transport="stdio")
