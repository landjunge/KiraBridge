"""UI input status reads consume only their own completion and never resend."""

import copy
from types import SimpleNamespace

import httpx
import pytest

from kirabridge.approval_console import ORIGIN, ApprovalConsole, signed_token
from kirabridge.bridge_core.models import BridgeError
from kirabridge.operator_application import operator_application
from kirabridge.operator_control import OperatorControl


class InputRPC:
    def __init__(self, state="running"):
        self.calls = []
        self.task = {
            "id": "input-intent-1",
            "operation": "session.input",
            "state": state,
            "args": {},
            "result": {"return_sent": True} if state == "completed" else None,
        }
        self.notices = []
        self.ack_error = False
        self.ack_applied_then_error = False

    def complete(self, state="completed"):
        self.task.update(
            state=state, result={"return_sent": True} if state == "completed" else None
        )
        self.notices = [
            {
                "id": "completion-input-1",
                "target": "ui-input:intent-1",
                "receipt": "owned-receipt",
                "payload": {"source": "task", "task_id": "input-intent-1", "state": state},
            }
        ]

    async def __call__(self, name, args):
        self.calls.append((name, copy.deepcopy(args)))
        if name == "action_request":
            self.task["args"] = args["request"]["arguments"]
            return copy.deepcopy(self.task)
        if name == "task_get":
            assert args == {"task_id": "input-intent-1"}
            return copy.deepcopy(self.task)
        if name == "completion_receive":
            assert args["target"] == "ui-input:intent-1"
            assert args["source_id"] == "input-intent-1"
            return {"notices": copy.deepcopy(self.notices)}
        if name == "completion_ack":
            assert args == {"notice_id": "completion-input-1", "receipt": "owned-receipt"}
            if self.ack_error:
                if self.ack_applied_then_error:
                    self.notices = []
                raise BridgeError("daemon_timeout", "Acknowledgement reply missing")
            self.notices = []
            return {"id": args["notice_id"], "ack_scope": "consumer_processed"}
        raise AssertionError(name)


def control(rpc):
    instance = OperatorControl(
        config=lambda: SimpleNamespace(),
        queries=None,
        daemon=None,
        platform=None,
        actions=None,
        maintenance=None,
        grant_window=None,
        audit=None,
        connectors=None,
    )
    instance.rpc = rpc
    return instance


def value(**extra):
    return {
        "action_id": "intent-1",
        "pane_id": "terminal:123:ttys004",
        "expected_pid": 345,
        "text": "/resume",
        **extra,
    }


async def test_key_only_input_forwards_the_displayed_observation_without_rewriting_it():
    rpc = InputRPC()
    view = value(text="", key="enter", expected_cursor="c" * 64, expected_agent_pid=456)
    result = await control(rpc).terminal_input(view)
    request = rpc.calls[0][1]
    assert request["request"]["arguments"] == {
        "pane_id": view["pane_id"],
        "expected_pid": 345,
        "text": "",
        "submit": True,
        "key": "enter",
        "expected_cursor": "c" * 64,
        "expected_agent_pid": 456,
    }
    assert request["completion_target"] == "ui-input:intent-1"
    assert result["state"] == "running"


async def test_plain_text_input_does_not_acquire_key_guards():
    rpc = InputRPC()
    await control(rpc).terminal_input(value())
    assert rpc.calls[0][1]["request"]["arguments"] == {
        "pane_id": "terminal:123:ttys004",
        "expected_pid": 345,
        "text": "/resume",
        "submit": True,
    }


@pytest.mark.parametrize("initial", ["running", "accepted", "queued", "completed"])
async def test_each_initial_state_is_followed_to_one_scoped_completion(initial):
    rpc = InputRPC(initial)
    instance = control(rpc)
    if initial == "completed":
        rpc.complete()
    first = await instance.terminal_input(value())
    assert first["state"] == initial
    if initial != "completed":
        rpc.complete()
        final = await instance.terminal_input_status("intent-1")
        assert final["state"] == "completed"
    await instance.terminal_input_status("intent-1")
    assert sum(name == "action_request" for name, _ in rpc.calls) == 1
    assert sum(name == "completion_ack" for name, _ in rpc.calls) == 1
    ack_index = next(i for i, (name, _) in enumerate(rpc.calls) if name == "completion_ack")
    assert rpc.calls[ack_index - 1][0] == "task_get"


@pytest.mark.parametrize("state", ["failed", "unknown", "cancelled", "blocked"])
async def test_non_success_terminal_outcomes_are_preserved_and_their_notice_is_processed(state):
    rpc = InputRPC()
    instance = control(rpc)
    await instance.terminal_input(value())
    rpc.complete(state)
    final = await instance.terminal_input_status("intent-1")
    assert final["state"] == state
    assert final["ui_completion"]["pending"] is False
    assert sum(name == "action_request" for name, _ in rpc.calls) == 1
    assert rpc.notices == []


@pytest.mark.parametrize("applied", [False, True])
async def test_ack_failure_keeps_the_same_task_and_status_read_reconciles_without_resubmission(
    applied,
):
    rpc = InputRPC()
    rpc.complete()
    rpc.ack_error = True
    rpc.ack_applied_then_error = applied
    instance = control(rpc)
    first = await instance.terminal_input(value())
    assert first["state"] == "completed"
    assert first["ui_completion"]["pending"] is True
    assert first["ui_completion"]["error"]["code"] == "daemon_timeout"
    rpc.ack_error = False
    final = await instance.terminal_input_status("intent-1")
    assert final["state"] == "completed" and final["ui_completion"]["pending"] is False
    assert sum(name == "action_request" for name, _ in rpc.calls) == 1


async def test_a_foreign_notice_is_not_acknowledged_or_drained():
    rpc = InputRPC()
    rpc.complete()
    rpc.notices[0]["payload"]["task_id"] = "some-other-task"
    result = await control(rpc).terminal_input(value())
    assert result["ui_completion"]["pending"] is True
    assert not any(name == "completion_ack" for name, _ in rpc.calls)
    assert rpc.notices


async def test_status_rejects_an_invalid_action_id_before_any_rpc():
    rpc = InputRPC()
    with pytest.raises(BridgeError):
        await control(rpc).terminal_input_status("../foreign")
    assert rpc.calls == []


async def test_scoped_status_route_requires_operator_authentication_and_never_enqueues(
    bridge, monkeypatch
):
    key = "ui-input-status-" + "x" * 48
    app = ApprovalConsole(operator_application(bridge), key)
    rpc = InputRPC()
    rpc.complete()
    monkeypatch.setattr(app.control_center.service, "rpc", rpc)
    headers = {"Authorization": "Bearer " + signed_token(key, "session"), "Origin": ORIGIN}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        route = "/api/control/terminal/input/intent-1"
        assert (await client.get(route)).status_code == 401
        response = await client.get(route, headers=headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["task"]["state"] == "completed"
    assert not any(name == "action_request" for name, _ in rpc.calls)
