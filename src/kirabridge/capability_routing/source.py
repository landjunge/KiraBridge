"""Read the explicit ThreadDesk document through its service, never write its store."""

from __future__ import annotations

import json

from .router import Matrix, RoutingError

BEGIN = "<!-- bigplan-cli-matrix:v1 -->"
END = "<!-- /bigplan-cli-matrix -->"


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RoutingError("Ambiguous duplicate matrix JSON key")
        result[key] = value
    return result


class ThreadDeskSource:
    def __init__(self, get_thread, thread_id: str):
        self.get_thread, self.thread_id = get_thread, thread_id

    def load(self):
        # A new service read on EVERY delegation. No cache fallback.
        thread = self.get_thread(self.thread_id)
        if hasattr(thread, "to_dict"):
            thread = thread.to_dict()
        if (
            not isinstance(thread, dict)
            or thread.get("id") != self.thread_id
            or type(thread.get("revision")) is not int
        ):
            raise RoutingError("ThreadDesk identity/revision is missing")
        # Public API Thread.to_dict() nests notes in context; MCP flattens them.
        if "notes" in thread:
            notes = thread["notes"]
        else:
            context = thread.get("context")
            notes = context.get("notes") if isinstance(context, dict) else None
        if not isinstance(notes, str):
            raise RoutingError("ThreadDesk notes must be text")
        if len(notes.encode()) > 100000 or notes.count(BEGIN) != 1 or notes.count(END) != 1:
            raise RoutingError("ThreadDesk matrix markers are missing or ambiguous")
        if notes.index(BEGIN) >= notes.index(END):
            raise RoutingError("ThreadDesk matrix markers are reversed")
        raw = notes.split(BEGIN, 1)[1].split(END, 1)[0].strip()
        matrix = Matrix.model_validate(json.loads(raw, object_pairs_hook=unique_object))
        return matrix, {"thread_id": self.thread_id, "revision": thread["revision"]}


def local_source(workspace, thread_id):
    # Same existing public API as bigplan-report. Explicit workspace, no active-thread lookup.
    from threaddesk.api.service import ThreadService
    from threaddesk.storage.json_store import JsonStore

    service = ThreadService(JsonStore(workspace))
    return ThreadDeskSource(service.get, thread_id)
