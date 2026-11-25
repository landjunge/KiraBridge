"""Run one team turn on the assigned Codex root through the app-server API.

The configured ordinary root must be idle. Its own turn record supplies
the exact final answer.
Host identity is verified by CodexHost. Nothing here retries input after it was sent.
"""

from __future__ import annotations

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.platform_adapters.codex_host import CodexHost, refused


class NativeCodexTurns(CodexHost):
    async def execute(self, binding, message_id, body, timeout, running, *, output_schema=None):
        if binding is None:
            raise BridgeError("native_codex_unconfigured", "Native Codex host is not configured")
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

        options = {"output_schema": output_schema} if output_schema is not None else {}
        sent = await self.deliver(binding, prepared, message_id, body, before_send, **options)
        try:
            text = await self.wait_reply(
                binding, sent["turn_id"], body, timeout, cwd=sent["thread_cwd"]
            )
        except TimeoutError as error:
            raise UncertainExecution(
                "native_codex_reply_unknown", "Native turn did not finish in time"
            ) from error
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
