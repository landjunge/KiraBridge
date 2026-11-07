"""Classify CLI slash commands and reuse the guarded literal-input executor.

This module neither interprets commands nor confirms any resulting menu or
permission dialog. The addressed CLI owns slash-command semantics.
"""

import asyncio
import re

from kirabridge.bridge_core.models import BridgeError
from kirabridge.cli_adapters.codex_slash import (
    bound_thread_title as bound_thread_title,
)
from kirabridge.cli_adapters.codex_slash import (
    resume_insertion_observed as resume_insertion_observed,
)


def command_name(text):
    match = re.match(r"/([A-Za-z][A-Za-z0-9_-]*)(?=$|[ \t\n])", text)
    return "/" + match[1] if match else None


async def execute(bridge, task, args, target, binding, running, progress):
    command = command_name(args.text)
    if command is None or args.key is not None:
        raise BridgeError("invalid_arguments", "A slash command requires explicit literal text")
    from kirabridge.cli_adapters import adapter_for

    adapter = adapter_for(target)
    from kirabridge.literal_session_input import execute as literal_execute

    capture = {}

    def verifier(target, raw, text, before, *, cwd=None, home=None):
        capture["before"] = before
        return adapter.slash_insertion_observed(
            bridge.sessions, binding, raw, text, before, cwd=cwd, home=home
        )

    result = await literal_execute(
        bridge,
        task,
        args,
        target,
        binding,
        running,
        progress,
        verifier=verifier,
        verifier_version=getattr(adapter, "slash_verifier_version", "literal-widget-v3"),
    )
    evidence = {"acceptance_observed": False, "acceptance_evidence": "unconfirmed"}
    if args.submit and capture:
        for _attempt in range(3):
            await asyncio.sleep(0.05)
            try:
                after = await bridge.visible_handoffs.check_target(
                    task["principal"], target, binding
                )
                state = await bridge.visible_handoffs.binding_readiness(
                    task["principal"], target, binding, after
                )
                if state.get("state") in {"working", "target_changed"}:
                    break
                evidence = adapter.command_result(
                    command, capture["before"], after["text"], binding, state.get("protocol")
                )
            except BridgeError:
                break  # Return was already sent. Never retry input to recover lost output.
            if evidence.get("acceptance_observed"):
                break
    return {
        **result,
        "input_kind": "slash_command",
        "slash_command": command,
        **evidence,
    }
