"""Exercise real task state transitions with a fake, boundary-aware session port."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from conftest import request, submit

from kirabridge.bridge_core.models import BridgeError, State


@pytest.fixture(params=["shell", "agent_paste"])
def dispatch_case(request, bridge, config, monkeypatch):
    route = request.param
    config.principals["local"].capabilities += ["session.inspect"]
    bridge.tasks.preflight = None
    calls = []

    async def selected(*_):
        return {"pane_id": "%1", "expected_pid": 42, "busy": False, "processes": []}

    binding = SimpleNamespace(agent_pid=43)
    monkeypatch.setattr(bridge.sessions, "selected", selected)
    monkeypatch.setattr(
        bridge.sessions,
        "explicit_agent_binding",
        lambda _: ("codex", binding) if route == "agent_paste" else (None, None),
    )

    @asynccontextmanager
    async def selection(*_):
        yield

    async def reconcile(*_, **__):
        return None

    monkeypatch.setattr(bridge.sessions, "agent_selection", selection)
    monkeypatch.setattr(bridge.visible_handoffs, "reconcile_target_reservations", reconcile)
    return bridge, route, calls


async def execute_case(case, monkeypatch, phase):
    bridge, route, calls = case

    async def session_port(*_, before_transport=None, **__):
        if phase == "preflight":
            raise BridgeError("same_failure", "Rejected before transport")
        assert before_transport is not None
        await before_transport()
        persisted = bridge.store.get("task-1")
        assert persisted["state"] == State.RUNNING
        assert persisted["evidence"]["terminal_input_attempted"] is True
        calls.append("transport")
        if phase == "attempt":
            raise BridgeError("same_failure", "Failed after possible transport")
        return {"paste_event_sent": True, "return_sent": False}

    monkeypatch.setattr(bridge.sessions, "send" if route == "shell" else "insert", session_port)
    value = request(
        "session.input",
        {
            "pane_id": "%1",
            "expected_pid": 42,
            "text": "literal text",
            "submit": False,
        },
    )
    submit(bridge, value)
    task = bridge.store.claim(bridge.tasks.owner, bridge.config.lease_seconds)
    assert task["id"] == value.task_id
    await bridge.tasks._execute(task)
    return bridge.store.get(value.task_id)


async def test_pretransport_rejection_is_failed_without_attempt_evidence(
    dispatch_case, monkeypatch
):
    task = await execute_case(dispatch_case, monkeypatch, "preflight")
    assert task["state"] == State.FAILED
    assert task["error"]["code"] == "same_failure"
    assert task["evidence"]["safe_to_retry"] is True
    assert task["evidence"]["last_observation"].get("terminal_input_attempted") is not True
    assert not dispatch_case[2]


async def test_same_error_after_attempt_remains_unknown_and_never_requeued(
    dispatch_case, monkeypatch
):
    task = await execute_case(dispatch_case, monkeypatch, "attempt")
    bridge, route, calls = dispatch_case
    assert task["state"] == State.UNKNOWN
    assert task["error"]["code"] == "same_failure"
    assert task["evidence"]["safe_to_retry"] is False
    evidence = task["evidence"]["last_observation"]
    assert evidence["terminal_input_attempted"] is True
    assert evidence["expected_pid"] == 42
    if route == "agent_paste":
        assert evidence["agent_pid"] == 43 and evidence["return_sent"] is False
    assert calls == ["transport"]
    assert bridge.store.claim(bridge.tasks.owner, bridge.config.lease_seconds) is None


async def test_persist_failure_never_enters_transport(dispatch_case, monkeypatch):
    bridge, _, calls = dispatch_case
    transition = bridge.store.transition

    def fail_attempt_marker(task_id, state, evidence=None, **kwargs):
        if state == State.RUNNING and (evidence or {}).get("terminal_input_attempted"):
            raise BridgeError("evidence_unavailable", "Cannot persist attempt marker")
        return transition(task_id, state, evidence, **kwargs)

    monkeypatch.setattr(bridge.store, "transition", fail_attempt_marker)
    task = await execute_case(dispatch_case, monkeypatch, "success")
    assert not calls
    assert task["state"] == State.UNKNOWN  # Dispatcher stays conservative on journal failure.
    assert task["error"]["code"] == "evidence_unavailable"
    assert task["evidence"]["safe_to_retry"] is False


async def test_success_records_attempt_before_transport(dispatch_case, monkeypatch):
    task = await execute_case(dispatch_case, monkeypatch, "success")
    assert task["state"] == State.COMPLETED
    assert dispatch_case[2] == ["transport"]


@pytest.mark.parametrize("state", ["accepted", "running"])
def test_buffer_reservation_accepts_only_claimed_pretransport_tasks(bridge, config, state):
    from kirabridge.session_manager import SessionInput

    config.session_input_policy.enabled = True
    config.session_input_policy.principals = ["local"]
    config.principals["local"].capabilities += ["session.inspect"]
    value = request(
        "session.input",
        {
            "pane_id": "%1",
            "expected_pid": 42,
            "text": "literal go-go-go",
            "submit": False,
        },
    )
    submit(bridge, value)
    task = bridge.store.claim(bridge.tasks.owner, bridge.config.lease_seconds)
    if state == "running":
        bridge.store.transition(
            task["id"], State.RUNNING, {"prepared": True}, owner=bridge.tasks.owner
        )
    args = SessionInput.model_validate(value.arguments)
    approved = bridge.tasks.input_policy.dispatch("local", args, value.task_id)
    assert approved.text == "literal"
    stored = bridge.store.get(value.task_id)
    assert stored["state"] == state
    assert stored["input_buffer"]["state"] == "dispatching"
    assert stored["evidence"].get("terminal_input_attempted") is not True
    with pytest.raises(BridgeError, match="not been released"):
        bridge.tasks.input_policy.dispatch("local", args, value.task_id)


@pytest.mark.parametrize(
    "state", ["created", "queued", "completed", "failed", "cancelled", "unknown"]
)
def test_released_buffer_cannot_dispatch_outside_active_claim_states(bridge, config, state):
    from kirabridge.session_manager import SessionInput

    config.session_input_policy.enabled = True
    config.session_input_policy.principals = ["local"]
    config.principals["local"].capabilities += ["session.inspect"]
    value = request(
        "session.input",
        {
            "pane_id": "%1",
            "expected_pid": 42,
            "text": "literal go-go-go",
            "submit": False,
        },
    )
    submit(bridge, value)
    # Deliberately keep an otherwise valid released buffer in each forbidden state.
    bridge.store.db.execute("UPDATE tasks SET state=? WHERE id=?", (state, value.task_id))
    with pytest.raises(BridgeError, match="not been released"):
        bridge.tasks.input_policy.dispatch(
            "local", SessionInput.model_validate(value.arguments), value.task_id
        )
    assert bridge.store.get(value.task_id)["input_buffer"]["state"] == "released"


@pytest.mark.parametrize("mismatch", ["principal", "args"])
def test_accepted_reservation_preserves_owner_and_exact_input(bridge, config, mismatch):
    from kirabridge.session_manager import SessionInput

    config.session_input_policy.enabled = True
    config.session_input_policy.principals = ["local"]
    config.principals["local"].capabilities += ["session.inspect"]
    value = request(
        "session.input",
        {
            "pane_id": "%1",
            "expected_pid": 42,
            "text": "literal go-go-go",
            "submit": False,
        },
    )
    submit(bridge, value)
    bridge.store.claim(bridge.tasks.owner, bridge.config.lease_seconds)
    args = SessionInput.model_validate(value.arguments)
    if mismatch == "args":
        args = args.model_copy(update={"text": "changed go-go-go"})
    with pytest.raises(BridgeError):
        bridge.tasks.input_policy.dispatch(
            "other" if mismatch == "principal" else "local", args, value.task_id
        )
    assert bridge.store.get(value.task_id)["input_buffer"]["state"] == "released"
