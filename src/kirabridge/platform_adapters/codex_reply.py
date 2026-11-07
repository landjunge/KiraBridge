"""Observe one new Codex answer on an independently process-bound local log.

An explicitly configured path/thread is only a candidate. Otherwise only that
exact process's open writers may supply one unambiguous task-local candidate.
The task-bound Codex process must hold the same device/inode open for writing. A pre-paste
cursor, exact new UserMessage, matching turn, final AgentMessage and completion
are all required. Nothing here authenticates a mailbox principal or sends input.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError
from kirabridge.filesystem_manager import PathScope
from kirabridge.platform_adapters import reap_process

MAX_LOG_BYTES = 64 * 1024 * 1024
MAX_APPEND_BYTES = 8 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
MAX_LSOF_BYTES = 16384
MAX_ANSWER_BYTES = 262144
MAX_CANDIDATES = 8


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _unavailable(reason):
    return {
        "state": "unavailable",
        "reason": reason if re.fullmatch(r"[a-z_]{1,100}", reason) else "invalid_local_protocol",
        "agent_confirmed": False,
    }


def _text(item, kind):
    content = item.get("content")
    if not isinstance(content, list) or not content:
        raise ValueError("unsupported_item_content")
    result = []
    for part in content:
        if (
            not isinstance(part, dict)
            or part.get("type") != kind
            or not isinstance(part.get("text"), str)
            or part.get("text_elements")
        ):
            raise ValueError("unsupported_item_content")
        result.append(part["text"])
    return "".join(result)


def _answer(records, thread_id, body):
    """The first new root user turn must be ours; never search past a mismatch."""
    turn, user, final, completed = None, None, None, None
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("invalid_protocol_record")
        if record.get("type") != "event_msg":
            continue  # response_item mirrors, quotations and tool output have no authority.
        event = record.get("payload")
        if not isinstance(event, dict):
            raise ValueError("invalid_protocol_record")
        kind = event.get("type")
        if not isinstance(kind, str):
            raise ValueError("invalid_protocol_record")
        if kind == "task_started":
            if turn is not None:
                raise ValueError("multiple_new_turns")
            turn = event.get("turn_id")
            attribution = event.get("turn_attribution", {})
            if (
                not isinstance(turn, str)
                or not turn
                or event.get("root_turn_id", turn) != turn
                or not isinstance(attribution, dict)
                or attribution.get("turn_id", turn) != turn
                or attribution.get("root_turn_id", turn) != turn
                or attribution.get("parent_turn_id") is not None
                or attribution.get("initiating_agent_path") is not None
                or attribution.get("turn_trigger", "user") != "user"
            ):
                raise ValueError("unsupported_turn_binding")
        elif kind == "item_completed":
            if turn is None or event.get("thread_id") != thread_id or event.get("turn_id") != turn:
                raise ValueError("item_turn_mismatch")
            item = event.get("item")
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
                raise ValueError("invalid_protocol_item")
            if item.get("type") == "UserMessage":
                if user is not None or final is not None or _text(item, "text") != body:
                    raise ValueError("new_user_body_mismatch")
                user = item["id"]
            elif item.get("type") == "AgentMessage" and item.get("phase") == "final_answer":
                if user is None or final is not None or item["id"] == user:
                    raise ValueError("unmatched_or_multiple_final_items")
                text = _text(item, "Text")
                if not text or len(text.encode("utf-8")) > MAX_ANSWER_BYTES:
                    raise ValueError("answer_limit")
                final = {"id": item["id"], "text": text}
        elif kind == "task_complete":
            if (
                turn is None
                or event.get("turn_id") != turn
                or event.get("root_turn_id", turn) != turn
                or user is None
                or final is None
                or event.get("last_agent_message", final["text"]) != final["text"]
            ):
                raise ValueError("unmatched_turn_completion")
            if completed is not None:
                raise ValueError("multiple_turn_completions")
            completed = {
                "state": "completed",
                "turn_id": turn,
                "user_item_id": user,
                "final_item_id": final["id"],
                "text": final["text"],
            }
        elif isinstance(kind, str) and kind.startswith(("turn_", "task_")):
            raise ValueError("unsupported_or_aborted_turn")
    return completed or {
        "state": "pending",
        "reason": "matching_completed_turn_not_observed",
        "observed_turn": turn is not None,
    }


class CodexReplyObserver:
    def __init__(self, sessions_root=None, *, process_factory=None):
        self.root = Path(sessions_root or Path.home() / ".codex" / "sessions").resolve()
        self.scope = PathScope([str(self.root)])
        self.process_factory = process_factory or asyncio.create_subprocess_exec

    def _open_session(self, selected):
        """Anchor every path component; changing a parent into a symlink cannot escape."""
        with self.scope.parent(str(selected)) as (parent, name):
            return os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)

    def _snapshot(self, path, thread_id, cursor=None, *, cwd=None):
        selected = Path(path)
        resolved = selected.resolve(strict=True)
        if (
            not selected.is_absolute()
            or selected != resolved
            or resolved == self.root
            or not resolved.is_relative_to(self.root)
        ):
            raise ValueError("session_path_not_canonical_or_outside_root")
        with os.fdopen(self._open_session(resolved), "rb") as f:
            before = os.fstat(f.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.getuid()
                or before.st_size > MAX_LOG_BYTES
            ):
                raise ValueError("session_not_bounded_owned_regular_file")
            header = f.readline(MAX_LINE_BYTES + 1)
            if len(header) > MAX_LINE_BYTES:
                raise ValueError("session_line_limit")
            if not header.endswith(b"\n"):
                raise ValueError("session_partial_line")
            metadata = json.loads(header)
            payload = metadata.get("payload", {})
            if (
                metadata.get("type") != "session_meta"
                or not isinstance(payload, dict)
                or not isinstance(payload.get("id"), str)
                or not re.fullmatch(r"[0-9a-f-]{36}", payload["id"])
                or (thread_id is not None and payload["id"] != thread_id)
                or payload.get("originator") != "codex-tui"
            ):
                raise ValueError("session_header_mismatch")
            if cwd is not None and (
                not isinstance(payload.get("cwd"), str)
                or not Path(payload["cwd"]).is_absolute()
                or Path(payload["cwd"]).resolve() != Path(cwd).resolve()
            ):
                raise ValueError("session_cwd_mismatch")
            raw = header + f.read(MAX_LOG_BYTES + 1 - len(header))
            after, current = os.fstat(f.fileno()), resolved.stat()
        identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        if len(raw) != before.st_size or any(
            (v.st_dev, v.st_ino, v.st_size, v.st_mtime_ns) != identity for v in (after, current)
        ):
            raise ValueError("session_changed_during_read")
        if not raw.endswith(b"\n"):
            raise ValueError("session_partial_line")
        if cursor is None:
            return {
                "version": 1,
                "path": str(resolved),
                "thread_id": payload["id"],
                "cwd": str(Path(cwd).resolve()) if cwd is not None else None,
                "device": before.st_dev,
                "inode": before.st_ino,
                "offset": len(raw),
                "prefix_sha256": _sha(raw),
            }
        offset = cursor.get("offset")
        if (
            type(offset) is not int
            or offset < len(header)
            or len(raw) < offset
            or (before.st_dev, before.st_ino) != (cursor.get("device"), cursor.get("inode"))
            or _sha(raw[:offset]) != cursor.get("prefix_sha256")
        ):
            raise ValueError("session_replaced_truncated_or_rewritten")
        appended = raw[offset:]
        if len(appended) > MAX_APPEND_BYTES:
            raise ValueError("session_append_limit")
        lines = appended.splitlines()
        if any(len(line) > MAX_LINE_BYTES for line in lines):
            raise ValueError("session_line_limit")
        return [json.loads(line) for line in lines], _sha(appended)

    async def _process_files(self, pid, expected_identity, process_identity, *, path=None):
        if await process_identity(pid, detailed=True) != expected_identity:
            raise ValueError("process_binding_changed")
        child = None
        try:
            async with asyncio.timeout(3):
                creation = asyncio.create_task(
                    self.process_factory(
                        "/usr/sbin/lsof",
                        "-a",
                        "-p",
                        str(pid),
                        "-F0pfaDint",
                        *([path] if path is not None else []),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                        limit=MAX_LSOF_BYTES + 1,
                    )
                )
                try:
                    child = await asyncio.shield(creation)
                except asyncio.CancelledError:
                    # The OS child may exist before asyncio returns its handle.
                    # Adopt it before exact cleanup, including repeated cancellation.
                    while not creation.done():
                        try:
                            await asyncio.shield(creation)
                        except asyncio.CancelledError:
                            pass
                        except Exception:
                            break
                    if not creation.cancelled() and creation.exception() is None:
                        child = creation.result()
                    raise
                raw = bytearray()
                while part := await child.stdout.read(min(4096, MAX_LSOF_BYTES + 1 - len(raw))):
                    raw.extend(part)
                    if len(raw) > MAX_LSOF_BYTES:
                        raise ValueError("process_file_observation_limit")
                await child.wait()
                if child.returncode:
                    raise ValueError("process_file_observation_unavailable")
                files = self._file_rows(bytes(raw), pid)
        finally:
            cancelled = isinstance(sys.exc_info()[1], asyncio.CancelledError)
            if child is not None:
                try:
                    await reap_process(child, process_group=False)
                except BridgeError:
                    if cancelled:
                        raise asyncio.CancelledError from None
                    raise
        if await process_identity(pid, detailed=True) != expected_identity:
            raise ValueError("process_binding_changed")
        return files

    @staticmethod
    def _file_rows(raw, pid):
        fields = [part.removeprefix(b"\n").decode("utf-8") for part in raw.split(b"\0")]
        fields = [part for part in fields if part]
        if not fields or fields[0] != f"p{pid}" or any(f.startswith("p") for f in fields[1:]):
            raise ValueError("process_file_identity_mismatch")
        files, item = [], None
        for field in fields[1:]:
            if field.startswith("f"):
                item = {"f": field[1:]}
                files.append(item)
            elif item is None or field[0] in item:
                raise ValueError("invalid_process_file_observation")
            else:
                item[field[0]] = field[1:]
        return files

    @staticmethod
    def _is_writer(item):
        return bool(re.fullmatch(r"[0-9]+[rwu]?", item.get("f", ""))) and item.get("a") in {
            "w",
            "u",
        }

    @classmethod
    def _matches(cls, item, cursor):
        return (
            cls._is_writer(item)
            and item.get("t") == "REG"
            and item.get("n") == cursor["path"]
            and int(item.get("D", "-1"), 16) == cursor["device"]
            and int(item.get("i", "-1")) == cursor["inode"]
        )

    async def _writer(self, cursor, pid, expected_identity, process_identity):
        files = await self._process_files(
            pid, expected_identity, process_identity, path=cursor["path"]
        )
        return any(self._matches(item, cursor) for item in files)

    async def _discover(self, binding, expected_identity, process_identity, cwd):
        if not isinstance(cwd, str) or not Path(cwd).is_absolute():
            raise ValueError("independent_thread_binding_unavailable")
        files = await self._process_files(binding.agent_pid, expected_identity, process_identity)
        working = [item for item in files if item.get("f") == "cwd" and item.get("t") == "DIR"]
        if (
            len(working) != 1
            or not Path(working[0].get("n", "")).is_absolute()
            or Path(working[0]["n"]).resolve() != Path(cwd).resolve()
        ):
            raise ValueError("process_cwd_mismatch")
        candidates = {
            item.get("n"): item
            for item in files
            if self._is_writer(item)
            and item.get("t") == "REG"
            and isinstance(item.get("n"), str)
            and len(item["n"]) <= 4096
            and Path(item["n"]).is_absolute()
            and Path(item["n"]).is_relative_to(self.root)
            and Path(item["n"]).suffix == ".jsonl"
        }
        if len(candidates) > MAX_CANDIDATES:
            raise ValueError("too_many_rollout_writer_candidates")
        matches = []
        for path, item in candidates.items():
            try:
                cursor = await asyncio.to_thread(self._snapshot, path, None, cwd=cwd)
                if self._matches(item, cursor):
                    matches.append(cursor)
            except (OSError, ValueError, TypeError, AttributeError):
                continue  # Invalid/non-session descriptors are not another thread source.
            if len(matches) > 1:
                raise ValueError("ambiguous_process_rollout_writers")
        if not matches:
            raise ValueError("process_rollout_writer_unavailable")
        return matches[0]

    async def prepare(self, binding, *, process_identity, expected_identity, body, cwd=None):
        if not expected_identity:
            return _unavailable("independent_thread_binding_unavailable")
        try:
            if binding.codex_thread_id and binding.codex_rollout_path:
                cursor = await asyncio.to_thread(
                    self._snapshot, binding.codex_rollout_path, binding.codex_thread_id, cwd=cwd
                )
                if not await self._writer(
                    cursor, binding.agent_pid, expected_identity, process_identity
                ):
                    return _unavailable("process_does_not_own_bound_rollout_writer")
                origin = "explicit_verified_writer"
            elif not binding.codex_thread_id and not binding.codex_rollout_path:
                cursor = await self._discover(binding, expected_identity, process_identity, cwd)
                if not await self._writer(
                    cursor, binding.agent_pid, expected_identity, process_identity
                ):
                    return _unavailable("process_binding_changed")
                origin = "process_writer_discovery"
            else:
                return _unavailable("independent_thread_binding_unavailable")
            # The log must still be the exact pre-paste baseline after process observation.
            records, _ = await asyncio.to_thread(
                self._snapshot, cursor["path"], cursor["thread_id"], cursor, cwd=cursor["cwd"]
            )
            if records:
                return _unavailable("session_changed_during_binding")
            return {
                "state": "ready",
                "cursor": {
                    **cursor,
                    "agent_pid": binding.agent_pid,
                    "process_identity": expected_identity,
                    "body_sha256": _sha(body.encode("utf-8")),
                    "binding": binding.model_dump(),
                    "binding_origin": origin,
                },
            }
        except (OSError, ValueError, TypeError, AttributeError, BridgeError, TimeoutError) as exc:
            return _unavailable(str(exc) if isinstance(exc, ValueError) else "binding_unavailable")

    async def before_submit(self, cursor, binding, *, body):
        """Our Paste has not submitted: a new turn here cannot be our answer."""
        try:
            records, _ = await asyncio.to_thread(
                self._snapshot, cursor["path"], cursor["thread_id"], cursor, cwd=cursor.get("cwd")
            )
            state = _answer(records, cursor["thread_id"], body)
            if state["state"] != "pending" or state["observed_turn"]:
                return _unavailable("turn_observed_before_our_return")
            return {"state": "ready", "cursor": cursor}
        except (OSError, ValueError, TypeError, KeyError, AttributeError, BridgeError) as exc:
            return _unavailable(str(exc) if isinstance(exc, ValueError) else "reply_unavailable")

    async def observe(self, cursor, binding, *, body, process_identity):
        if (
            not isinstance(cursor, dict)
            or type(cursor.get("version")) is not int
            or cursor["version"] != 1
            or cursor.get("binding") != binding.model_dump()
            or cursor.get("agent_pid") != binding.agent_pid
            or (
                binding.codex_thread_id is not None
                and (
                    cursor.get("thread_id") != binding.codex_thread_id
                    or cursor.get("path") != binding.codex_rollout_path
                    or cursor.get("binding_origin") != "explicit_verified_writer"
                )
            )
            or (
                binding.codex_thread_id is None
                and cursor.get("binding_origin") != "process_writer_discovery"
            )
            or cursor.get("body_sha256") != _sha(body.encode("utf-8"))
        ):
            return _unavailable("original_reply_cursor_mismatch")
        try:
            records, append_hash = await asyncio.to_thread(
                self._snapshot, cursor["path"], cursor["thread_id"], cursor, cwd=cursor.get("cwd")
            )
            answer = _answer(records, cursor["thread_id"], body)
            if answer["state"] != "completed":
                return answer
            if not await self._writer(
                cursor, binding.agent_pid, cursor["process_identity"], process_identity
            ):
                return _unavailable("process_binding_changed")
            # lsof/process observation must not turn a prior parse into a stale
            # proof if the same inode was rewritten while that helper ran.
            _, verified_hash = await asyncio.to_thread(
                self._snapshot, cursor["path"], cursor["thread_id"], cursor, cwd=cursor.get("cwd")
            )
            if verified_hash != append_hash:
                return {"state": "pending", "reason": "session_changed_during_binding"}
            return {
                **answer,
                "reply_source": "bound_local_codex_rollout",
                "agent_confirmed": False,
                "evidence": {
                    "reply_source": "bound_local_codex_rollout",
                    "identity_scope": "OS_process_and_local_protocol_not_authenticated_mailbox",
                    "binding": cursor["binding"],
                    "protocol_binding": {
                        "thread_id": cursor["thread_id"],
                        "rollout_path": cursor["path"],
                        "cwd": cursor.get("cwd"),
                        "origin": cursor["binding_origin"],
                    },
                    "baseline_offset": cursor["offset"],
                    "baseline_sha256": cursor["prefix_sha256"],
                    "appended_sha256": append_hash,
                    "expected_payload_sha256": cursor["body_sha256"],
                    "turn_id": answer["turn_id"],
                    "user_item_id": answer["user_item_id"],
                    "final_item_id": answer["final_item_id"],
                    "task_complete_observed": True,
                    "process_writer_verified": True,
                    "agent_confirmed": False,
                },
            }
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            BridgeError,
            TimeoutError,
        ) as exc:
            if isinstance(exc, ValueError) and str(exc) in {
                "session_partial_line",
                "session_changed_during_read",
            }:
                return {"state": "pending", "reason": str(exc)}
            return _unavailable(str(exc) if isinstance(exc, ValueError) else "reply_unavailable")
