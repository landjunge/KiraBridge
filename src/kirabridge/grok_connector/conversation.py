"""Return completed work inside Grok's tool turn, without replaying that work."""

from __future__ import annotations

from kirabridge import LOCAL_APPROVAL_URL
from kirabridge.bridge_core.models import State

WAIT_SECONDS = 18.0  # Below the existing gateway/client transport deadlines.
ACTIVE = {State.QUEUED, State.ACCEPTED, State.RUNNING}


def enabled_for(bridge, principal):
    settings = bridge.config.grok_connector
    return settings.enabled and principal == settings.principal


async def result_for_conversation(bridge, principal, task):
    """An authenticated tool response is not evidence of audio playback."""
    if not enabled_for(bridge, principal) or "id" not in task:
        return task
    # Re-read through the normal owner/permission check, including on reconnect.
    task = bridge.task(principal, task["id"])
    if task["state"] in ACTIVE:
        try:
            await bridge.tasks.wait(principal, task["id"], timeout=WAIT_SECONDS)
        except TimeoutError:
            pass
        task = bridge.task(principal, task["id"])

    state, operation = task["state"], task["operation"]
    result = task.get("result") or {}
    waiting = state in ACTIVE
    input_only = operation == "session.input" and state == State.COMPLETED
    if state == State.CREATED:
        text = "Der Auftrag wartet auf deine Erlaubnis in KiraBridge."
    elif waiting:
        text = "Der Auftrag läuft noch. Eine fertige Antwort liegt noch nicht vor."
    elif input_only:
        text = (
            "Die Eingabe ist im gewählten Terminal zugestellt. "
            "Eine Antwort ist noch nicht bestätigt."
        )
    elif state == State.COMPLETED:
        text = result.get("final_message") or result.get("text") or result.get("stdout") or ""
        if not isinstance(text, str):
            text = ""
        if not text:
            text = (
                "Der Auftrag ist abgeschlossen. "
                "Die tatsächlichen Ergebnisse stehen im Ergebnisfeld."
            )
    else:
        error = task.get("error") or {}
        text = {
            State.UNKNOWN: "Der Ausgang ist unklar. Der Auftrag wird nicht erneut gestartet.",
            State.CANCELLED: "Der Auftrag wurde abgebrochen.",
            State.BLOCKED: "Der Auftrag ist blockiert.",
        }.get(state, "Der Auftrag ist fehlgeschlagen.")
        detail = (
            result.get("final_message")
            or result.get("text")
            or result.get("stderr")
            or error.get("message")
        )
        if isinstance(detail, str) and detail:
            text += " " + detail

    response = {
        **task,
        "approval_required": state == State.CREATED,
        "local_approval_url": LOCAL_APPROVAL_URL,
        "conversation_return": {
            "text": text,
            "final": state not in ACTIVE | {State.CREATED} and not input_only,
            "continue_required": waiting,
            "next_call": {"tool": "task_get", "arguments": {"task_id": task["id"]}}
            if waiting
            else None,
            "terminal_reply_tool": "session_read" if input_only else None,
            "scope": "terminal_input_delivery" if input_only else "task_execution_result",
            "delivery": "current_tool_response",
            "audio_playback": "not_observed_by_bridge",
        },
    }
    # Record what was prepared. The network peer and its speaker are outside this
    # function; recording this event must never create a "voice verified" badge.
    with bridge.store.transaction():
        bridge.store.audit(
            "conversation.response.prepared",
            principal,
            task["id"],
            {
                "state": state,
                "final": response["conversation_return"]["final"],
                "scope": response["conversation_return"]["scope"],
                "audio_playback": "not_observed_by_bridge",
            },
        )
    return response
