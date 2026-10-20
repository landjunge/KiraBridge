"""Bounded local scan/query owner; cached text is never returned as a snippet."""

from __future__ import annotations

import re
import sqlite3
from collections import OrderedDict
from time import monotonic
from uuid import uuid4

from kirabridge.bridge_core.models import BridgeError, digest
from kirabridge.file_index.cache import Cache
from kirabridge.file_index.source import BATCH_BYTES, ENTRIES, FILE_BYTES, Source, SourceFailure


class FileIndex:
    def __init__(self, config, security):
        self.config, self.security = config, security
        self.cache = Cache(config.state_path)
        self.instance = uuid4().hex
        self.queries, self.scans = OrderedDict(), OrderedDict()

    def close(self):
        for book in (self.queries, self.scans):
            while book:
                _, state = book.popitem()
                state["iterator"].close()
        self.cache.close()

    def context(self, principal, project):
        self.security.principal(principal, "file.read")
        self.security.principal(principal, "file.list")
        if not self.config.file_index.enabled:
            return {"enabled": False, "mode": "disabled", "status": "disabled", "binding": ""}
        source = Source(self.config, self.security, principal, project)
        token = source.view()[2]
        scope = digest([principal, project])
        try:
            state = self.cache.state(scope)
            mode = (
                "fts5"
                if (
                    self.cache.fts
                    and state["token"] == token
                    and state["status"] == "reconciled_observation"
                )
                else "bounded_scan"
            )
        except (sqlite3.Error, OSError, BridgeError, ValueError):
            state, mode = {"status": "index_unavailable", "epoch": ""}, "bounded_scan"
        binding = digest([self.instance, token, state["epoch"], mode])
        return {
            "enabled": True,
            "source": source,
            "token": token,
            "scope": scope,
            "mode": mode,
            "status": state["status"],
            "binding": binding,
        }

    def status(self, principal, project):
        context = self.context(principal, project)
        return {key: context[key] for key in ("enabled", "mode", "status", "binding")}

    def _current(self, principal, project, expected):
        current = self.context(principal, project)
        if current["binding"] != expected["binding"] or current["enabled"] != expected["enabled"]:
            raise BridgeError("generation_changed", "Search observation changed")

    def scan(self, principal, project, *, restart=False):
        context = self.context(principal, project)
        if not context["enabled"]:
            raise BridgeError("index_disabled", "File index is disabled")
        key, source = context["scope"], context["source"]
        state = self.scans.pop(key, None)
        if state is not None and (restart or state["token"] != context["token"]):
            state["iterator"].close()
            state = None
        try:
            if state is None:
                scan = self.cache.start(key, context["token"])
                state = {
                    "token": context["token"],
                    "scan": scan,
                    "partial": False,
                    "iterator": source.walk(context["token"]),
                    "exhausted": False,
                }
            documents, count, size, reasons = [], 0, 0, set()
            deadline = monotonic() + 0.1
            while not state["exhausted"] and count < ENTRIES and size <= BATCH_BYTES - FILE_BYTES:
                if monotonic() > deadline:
                    reasons.add("time_budget")
                    break
                try:
                    relative, kind = next(state["iterator"])
                except StopIteration:
                    state["exhausted"] = True
                    break
                count += 1
                if kind != "file":
                    if kind != "skip":
                        reasons.add(kind)
                        state["partial"] = True
                    continue
                try:
                    doc = source.capture(relative, context["token"])
                    size += doc.size
                    documents.append(doc)
                except SourceFailure as exc:
                    size += FILE_BYTES
                    if exc.code != "source_excluded":
                        reasons.add(exc.code)
                        state["partial"] = True
            source.checked_view(context["token"])
            if count >= ENTRIES:
                reasons.add("candidate_budget")
            if size > BATCH_BYTES - FILE_BYTES:
                reasons.add("byte_budget")
            result = self.cache.write(
                key,
                state["scan"],
                documents,
                exhausted=state["exhausted"],
                partial=state["partial"],
            )
            if result["status"] == "building":
                self.scans[key] = state
                while len(self.scans) > 2:
                    _, old = self.scans.popitem(last=False)
                    old["iterator"].close()
            else:
                state["iterator"].close()
            return {
                "status": result["status"],
                "scanned": count,
                "source_bytes": size,
                "complete": False,
                "reasons": sorted(reasons | {"filesystem_snapshot_unverified"}),
            }
        except (sqlite3.Error, OSError):
            if state is not None:
                state["iterator"].close()
            return {
                "status": "index_unavailable",
                "complete": False,
                "reasons": ["index_unavailable"],
            }
        except BaseException:
            if state is not None:
                state["iterator"].close()
            raise

    def query(self, principal, project, text, *, limit=20, cursor=None):
        try:
            length = len(text.encode("utf-8")) if isinstance(text, str) else 513
        except UnicodeError:
            length = 513
        if (
            length > 512
            or not isinstance(text, str)
            or not text.strip()
            or any(ord(ch) < 32 or 127 <= ord(ch) <= 159 for ch in text)
            or len(text.split()) > 16
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise BridgeError("invalid_search_query", "Use 1–16 literal terms and a bounded limit")
        context = self.context(principal, project)
        if not context["enabled"]:
            if cursor is not None:
                raise BridgeError("generation_changed", "Search observation changed")
            return {
                "hits": [],
                "mode": "disabled",
                "index_status": "disabled",
                "complete": False,
                "truncated": False,
                "reasons": ["disabled"],
                "next_cursor": None,
            }
        signature = digest([principal, project, text.split(), limit])
        for key in list(self.queries):
            if monotonic() - self.queries[key]["created"] > 300:
                self.queries.pop(key)["iterator"].close()
        if cursor is not None:
            if not isinstance(cursor, str) or len(cursor) > 64 or cursor not in self.queries:
                raise BridgeError("cursor_expired", "Search cursor unavailable")
            state = self.queries.pop(cursor)
            if state["binding"] != context["binding"] or state["signature"] != signature:
                state["iterator"].close()
                raise BridgeError("generation_changed", "Search observation changed")
        else:
            mode = context["mode"]
            iterator = (
                self.cache.candidates(context["scope"], text.split())
                if mode == "fts5"
                else context["source"].walk(context["token"])
            )
            state = {
                "iterator": iterator,
                "mode": mode,
                "binding": context["binding"],
                "signature": signature,
                "created": monotonic(),
            }
        hits, count, size, reasons, exhausted = [], 0, 0, {"filesystem_snapshot_unverified"}, False
        deadline = monotonic() + 0.1
        try:
            while len(hits) < limit and count < ENTRIES and size <= BATCH_BYTES - FILE_BYTES:
                if monotonic() > deadline:
                    reasons.add("time_budget")
                    break
                try:
                    relative, kind = next(state["iterator"])
                except StopIteration:
                    exhausted = True
                    break
                except sqlite3.Error:
                    if cursor is not None or state["mode"] != "fts5":
                        raise BridgeError("index_unavailable", "Search index unavailable") from None
                    state["iterator"].close()
                    state["iterator"] = context["source"].walk(context["token"])
                    state["mode"] = "bounded_scan"
                    reasons.add("index_unavailable")
                    continue
                count += 1
                if not relative:
                    if kind != "skip":
                        reasons.add(kind)
                    if kind == "query_budget":
                        break
                    continue
                try:
                    doc = context["source"].capture(relative, context["token"])
                    size += doc.size
                except SourceFailure as exc:
                    size += FILE_BYTES
                    if exc.code != "source_excluded":
                        reasons.add(exc.code)
                    continue
                matches = [
                    re.search(re.escape(term), doc.text, re.IGNORECASE) for term in text.split()
                ]
                if all(matches):
                    begin, end = matches[0].span()
                    hits.append(
                        {
                            "path": str(context["source"].view()[1] / doc.relative),
                            "stamp": doc.stamp,
                            "size_observed": doc.size,
                            "start": begin,
                            "end": end,
                            "snippet": doc.text[max(0, begin - 60) : max(0, begin - 60) + 240],
                        }
                    )
            self._current(principal, project, context)
            if count >= ENTRIES:
                reasons.add("candidate_budget")
            if size > BATCH_BYTES - FILE_BYTES:
                reasons.add("byte_budget")
            token = None
            if not exhausted:
                token = uuid4().hex
                self.queries[token] = state
                while len(self.queries) > 4:
                    _, old = self.queries.popitem(last=False)
                    old["iterator"].close()
            else:
                state["iterator"].close()
            return {
                "hits": hits,
                "mode": state["mode"],
                "index_status": context["status"],
                "match_semantics": "FTS5 literal AND, current-source verification"
                if state["mode"] == "fts5"
                else "literal case-insensitive substring AND",
                "generation": context["binding"],
                "complete": False,
                "truncated": True,
                "reasons": sorted(reasons),
                "next_cursor": token,
            }
        except BaseException:
            state["iterator"].close()
            raise
