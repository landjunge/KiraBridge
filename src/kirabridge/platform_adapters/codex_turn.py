"""Run one team turn on the loaded Codex root through the app-server API.

No window, paste or screen reading: the one loaded, parentless, idle root thread in the
worker's cwd gets `turn/start`, and its own turn record supplies the exact final answer.
Host identity is verified by CodexHost. Nothing here retries input after it was sent.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.platform_adapters.codex_host import CodexHost, refused

MAX_LOADED = 16


class NativeCodexTurns(CodexHost):
    async def discover(self, rpc, template, cwd):
        """The only loaded ordinary root whose cwd is the worker cwd; never a pin."""
        loaded = await rpc.call("thread/loaded/list", {})
        ids = loaded.get("data")
        if not isinstance(ids, list) or len(ids) > MAX_LOADED:
            raise refused("native_codex_target_not_ready")
        found = []
        for thread_id in ids:
            thread = (
                await rpc.call("thread/read", {"threadId": thread_id, "includeTurns": False})
            ).get("thread", {})
            if (
                thread.get("id") == thread_id
                and isinstance(thread.get("sessionId"), str)
                and thread.get("source") in {"cli", "vscode", "appServer"}
                and "parentThreadId" in thread
                and "attachedToThreadId" in thread
                and thread["parentThreadId"] is None
                and thread["attachedToThreadId"] is None
                and isinstance(thread.get("cwd"), str)
                and Path(thread["cwd"]).is_absolute()
                and Path(thread["cwd"]).resolve() == Path(cwd).resolve()
            ):
                found.append(thread)
        if len(found) != 1:
            raise refused("native_codex_root_not_unique")
        thread = found[0]
        return template.model_copy(
            update={
                "thread_id": thread["id"],
                "session_id": thread["sessionId"],
                "source": thread["source"],
            }
        )

    async def execute(self, template, cwd, message_id, body, timeout, running):
        if template is None:
            raise BridgeError("native_codex_unconfigured", "Native Codex host is not configured")
        async with self.connection(template) as (rpc, generation):
            binding = await self.discover(rpc, template, cwd)
        prepared = await self.prepare(binding)
        if prepared["operation"] != "turn/start":
            # A team turn never steers a turn that someone else is running.
            raise refused("native_codex_target_not_ready")

        async def before_send(current):
            await running(
                {
                    "evidence_type": "native_codex_turn_submitting",
                    "session_id": binding.session_id,
                    "thread_id": binding.thread_id,
                    "terminal_input_attempted": False,
                    "automatic_retry": False,
                }
            )

        sent = await self.deliver(binding, prepared, message_id, body, before_send)
        turn = await self._await_turn(binding, sent["turn_id"], timeout)
        items = turn.get("items", [])
        user_index = None
        for index, item in enumerate(items):
            if item.get("type") == "userMessage" and any(
                part.get("text") == body for part in item.get("content") or []
            ):
                user_index = index
        following = items[user_index + 1 :] if user_index is not None else []
        finals = [
            item
            for item in following
            if item.get("type") == "agentMessage" and item.get("phase") == "final_answer"
        ]
        if turn.get("status") != "completed" or user_index is None or not finals:
            raise UncertainExecution(
                "native_codex_turn_unverified", "The native turn has no exact verified answer"
            )
        text = finals[-1].get("text")
        if not isinstance(text, str) or not text:
            raise UncertainExecution("native_codex_turn_unverified", "Empty native final answer")
        return {
            "final_message": text,
            "text": text,
            "session_id": binding.session_id,
            "thread_id": binding.thread_id,
            "turn_id": sent["turn_id"],
            "reply_source": "native_codex_app_server",
            "terminal_input_attempted": False,
            "automatic_retry": False,
        }

    async def _await_turn(self, binding, turn_id, timeout):
        deadline = time.monotonic() + timeout
        async with self.connection(binding) as (rpc, _):
            while True:
                rows = await rpc.call(
                    "thread/turns/list",
                    {
                        "threadId": binding.thread_id,
                        "limit": 8,
                        "sortDirection": "desc",
                        "itemsView": "full",
                    },
                )
                row = next((r for r in rows.get("data", []) if r.get("id") == turn_id), None)
                if row is not None and row.get("status") != "inProgress":
                    return row
                if time.monotonic() >= deadline:
                    raise UncertainExecution(
                        "native_codex_reply_unknown", "Native turn did not finish in time"
                    )
                await asyncio.sleep(1)
