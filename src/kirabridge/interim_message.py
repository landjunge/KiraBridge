"""Deliver one explicitly addressed Codex follow-up without starting/stopping a turn.

The caller owns the durable task/message and records the attempt before native IO.
No replay, queue, agent.execute, Escape, Ctrl-C or process fallback exists here.
"""

import asyncio
import hashlib
import json
import re

from kirabridge.bridge_core.models import BridgeError, UncertainExecution, digest
from kirabridge.cli_adapters import adapter_for
from kirabridge.cli_adapters._legacy_readiness import input_view


def normalized_composer(raw):
    view = input_view("codex", raw)
    return re.sub(r"^([ \t]*)»", r"\1›", view, count=1)


async def execute(bridge, task, args, target, binding, running, progress):
    principal = task["principal"]
    policy = bridge.security.principal(principal, "agent.execute")
    bridge.security.principal(principal, "session.input")
    bridge.security.principal(principal, "terminal.execute")
    if target != "codex" or target not in policy.agents:
        raise BridgeError("agent_denied", "Interim steering requires the selected Codex agent")
    if not bridge.config.visible_handoffs.allow_interim_messages:
        raise BridgeError("interim_messages_disabled", "The user disabled interim messages")
    if args.expected_agent_pid != binding.agent_pid:
        raise BridgeError("visible_target_changed", "The explicitly addressed agent changed")
    if args.text.lstrip().startswith("/") or any(
        ord(c) < 32 and c not in "\n\t" for c in args.text
    ):
        raise BridgeError(
            "invalid_arguments", "Interim messages contain text, not commands or keys"
        )
    adapter = adapter_for(target)
    async with bridge.sessions.agent_selection(principal, target, binding):
        selection = bridge.sessions.current_selection()
        if not selection or not selection[2]:
            raise BridgeError(
                "interim_transport_unavailable", "No identity-bound steering transport"
            )
        # One short input transaction; an already running agent turn is not this lock.
        async with bridge.sessions.lock:
            selected = await bridge.sessions.selected(principal, args.pane_id, args.expected_pid)
            if not bridge.sessions.binding_matches(selected, binding, target):
                raise BridgeError("visible_target_changed", "Exact destination changed")
            # Preserve uncertain/incomplete earlier inputs. A delivered running
            # handoff is allowed and remains completely unchanged by this message.
            for row in bridge.store.db.execute(
                "SELECT binding FROM visible_handoffs WHERE state IN "
                "('planned','inserting','inserted','submitting','unknown')"
            ):
                original = json.loads(row[0])
                if original.get("pane_id") == binding.pane_id:
                    raise BridgeError("visible_target_busy", "Earlier input needs reconciliation")
            # Use the same bounded, identity-bound observation as session.read.
            # A transient renderer frame may be observed again before any input;
            # this never repeats a paste or re-admits an existing failed task.
            for attempt in range(3):
                output = await bridge.visible_handoffs.check_target(principal, target, binding)
                state = await bridge.visible_handoffs.binding_readiness(
                    principal, target, binding, output
                )
                await progress(
                    {
                        "evidence_type": "codex_interim_preflight",
                        "terminal_input_attempted": False,
                        "automatic_retry": False,
                        "observation": state,
                        "screen_sha256": hashlib.sha256(output["text"].encode()).hexdigest(),
                        "observation_attempt": attempt + 1,
                    }
                )
                if state.get("interim_ready"):
                    before = output["text"]
                    break
                if state.get("state") not in {"unknown", "working"} or attempt == 2:
                    error = BridgeError("visible_target_not_ready", state["reason"])
                    error.observation = state
                    raise error
                await asyncio.sleep(0.1)
            approved = bridge.tasks.input_policy.dispatch(principal, args, task["id"])
            await adapter.preflight_input(
                bridge.sessions, binding, approved.text, {"text": before}, composer_only=True
            )
            evidence = {
                "evidence_type": "codex_interim_message",
                "pane_id": binding.pane_id,
                "expected_pid": binding.expected_pid,
                "agent_pid": binding.agent_pid,
                "payload_sha256": digest(approved.text),
                "native_route": "existing_terminal_codex_enter_steer",
                "app_server_steer": "not_bound",
                "new_agent_turn": False,
                "interrupt_sent": False,
                "automatic_retry": False,
                "terminal_input_attempted": True,
            }
            await running({**evidence, "phase": "inserting", "return_sent": False})
            await bridge.sessions.terminal_app.insert(
                binding.pane_id,
                approved.text,
                identity_guard=selection[2],
                expected_screen=before,
                agent_target=target,
                composer_only=True,
            )
            after = await bridge.sessions.terminal_app.read(binding.pane_id)
            columns = await bridge.sessions.terminal_app.input_columns(
                binding.pane_id,
                identity_guard=selection[2],
                expected_screen=after,
                composer_only=True,
            )
            if not adapter.insertion_observed(
                normalized_composer(after),
                approved.text,
                normalized_composer(before),
                columns=columns,
            ):
                raise UncertainExecution(
                    "visible_insert_unknown", "Interim paste unverified; no Return"
                )
            await progress({**evidence, "phase": "submitting", "return_sent": False})
            await bridge.sessions.terminal_app.press_return(
                binding.pane_id,
                identity_guard=selection[2],
                expected_screen=after,
                composer_only=True,
            )
            await progress({**evidence, "phase": "sent", "return_sent": True})
    bridge.tasks.input_policy.sent(principal, task["id"])
    return {
        "success": True,
        "scope": "visible_input_delivery",
        "input_kind": "interim_message",
        "submitted": True,
        "return_sent": True,
        "evidence": evidence,
        "agent_confirmed": False,
        "work_continues": "not_interrupted_by_transport",
        "acceptance_observed": False,
        "response_observed": False,
    }
