import asyncio
import shutil
import subprocess
import sys
import uuid
from types import SimpleNamespace

import pytest
from conftest import request
from test_mcp import http_bridge  # noqa: F401

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import BridgeError, State
from kirabridge.operator_application import operator_application
from kirabridge.session_manager import SessionInput, SessionManager


@pytest.fixture
def buffered(bridge, config, monkeypatch):
    config.session_input_policy.enabled = True
    config.session_input_policy.principals = ["local"]
    config.principals["local"].approval_mode = "automatic"
    config.principals["local"].capabilities += ["session.inspect"]
    calls = []

    async def selected(*args):
        return None

    async def command(*args, **kwargs):
        calls.append(args)
        return ""

    monkeypatch.setattr(bridge.sessions, "selected", selected)
    monkeypatch.setattr(bridge.sessions.tmux, "command", command)
    return bridge, calls


def value(text="hello", task_id="buffer-1"):
    return request(
        "session.input", {"pane_id": "%1", "expected_pid": 1, "text": text}, task_id=task_id
    )


async def finish(bridge, task_id):
    await bridge.tasks.start()
    try:
        task = await bridge.tasks.wait("local", task_id, timeout=5)
        assert task["state"] == State.COMPLETED, task
        return task
    finally:
        await bridge.tasks.stop()


async def test_full_permission_still_buffers_then_separate_token_releases_once(buffered):
    bridge, calls = buffered
    task = value()
    first = bridge.prepare("local", task)
    assert first["state"] == State.CREATED
    assert first["input_buffer"]["state"] == "waiting"
    assert first["input_buffer"]["expires"] - first["input_buffer"]["created"] == 60
    assert not calls
    assert bridge.store.claim("test", 30) is None
    token = bridge.security.grant("local", task)
    assert bridge.submit("local", task, token)["state"] == State.QUEUED
    result = await finish(bridge, task.task_id)
    assert result["input_buffer"]["state"] == "sent"
    assert result["result"]["input_handed_to_transport"]
    assert not result["result"]["agent_processed"]
    assert calls == [
        ("send-keys", "-t", "%1", "-l", "--", "hello", ";", "send-keys", "-t", "%1", "Enter")
    ]
    assert bridge.submit("local", task, token)["state"] == State.COMPLETED
    assert len(calls) == 1
    assert bridge.store.db.execute("SELECT used FROM approvals").fetchone()[0]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("hello go-go-go", "hello"),
        ("hello\ngo-go-go\n", "hello"),
    ],
)
async def test_suffix_persists_buffer_before_immediate_dispatch(buffered, text, expected):
    bridge, calls = buffered
    task = value(text)
    queued = bridge.prepare("local", task)
    assert queued["input_buffer"]["release_source"] == "suffix"
    assert queued["state"] == State.QUEUED
    await finish(bridge, task.task_id)
    assert calls[0][5] == expected
    assert bridge.task("local", task.task_id)["args"]["text"] == text


@pytest.mark.parametrize("text", ["go-go-go then hello", "hello GO-GO-GO", "hello"])
def test_only_trailing_exact_marker_releases(buffered, text):
    bridge, calls = buffered
    assert bridge.prepare("local", value(text))["state"] == State.CREATED
    assert not calls


def test_wrong_token_and_changed_content_cannot_release(buffered):
    bridge, calls = buffered
    task = value()
    bridge.prepare("local", task)
    wrong = bridge.security.grant("other", task)
    with pytest.raises(BridgeError, match="one-use"):
        bridge.submit("local", task, wrong)
    changed = task.model_copy(update={"arguments": {**task.arguments, "text": "changed"}})
    token = bridge.security.grant("local", changed)
    with pytest.raises(BridgeError, match="different request"):
        bridge.submit("local", changed, token)
    assert bridge.task("local", task.task_id)["input_buffer"]["state"] == "waiting"
    assert not calls


async def test_local_daniel_approval_issues_and_consumes_separate_token(buffered):
    bridge, calls = buffered
    bridge.prepare("local", value())
    bridge.tasks.approve("buffer-1", source="local_console")
    await finish(bridge, "buffer-1")
    assert len(calls) == 1
    assert bridge.store.db.execute("SELECT used FROM approvals").fetchone()[0]
    assert bridge.task("local", "buffer-1")["input_buffer"]["release_source"] == "local_console"


async def test_real_http_client_buffers_and_releases_with_separate_token(
    http_bridge,  # noqa: F811
    buffered,
):
    from kirabridge.mcp_gateway.client import MCPClientPool, Peer

    bridge, endpoint = http_bridge
    _, calls = buffered
    task = value()
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        first = (
            await clients.call("local", "action_request", {"request": task.model_dump()})
        ).structuredContent
        assert first["state"] == "created" and not calls
        token = bridge.security.grant("local", task)
        await clients.call(
            "local", "action_submit", {"request": task.model_dump(), "approval": token}
        )
        assert (await bridge.tasks.wait("local", task.task_id, timeout=5))[
            "state"
        ] == State.COMPLETED
        assert len(calls) == 1


async def test_authenticated_console_approval_and_protocol_show_buffer(buffered):
    from test_approval_console import KEY, authenticated, client

    from kirabridge.approval_console import ApprovalConsole

    bridge, calls = buffered
    task = value()
    bridge.prepare("local", task)
    async with client(ApprovalConsole(operator_application(bridge), KEY)) as browser:
        detail = (await browser.get("/api/tasks/" + task.task_id, headers=authenticated())).json()
        assert detail["task"]["input_buffer"]["state"] == "waiting"
        result = await browser.post(
            "/api/tasks/" + task.task_id + "/approve",
            headers=authenticated(),
            json={"request_hash": detail["request_hash"]},
        )
        assert result.status_code == 200
        await finish(bridge, task.task_id)
        entries = (await browser.get("/api/control/protocol", headers=authenticated())).json()[
            "entries"
        ]
    assert {entry["kind"] for entry in entries} >= {
        "session.input.buffered",
        "session.input.released",
        "session.input.dispatching",
        "session.input.sent",
    }
    assert len(calls) == 1


def test_timeout_survives_restart_and_cannot_be_revived(buffered, config, monkeypatch):
    bridge, calls = buffered
    config.session_input_policy.timeout_seconds = 12
    task = value()
    first = bridge.prepare("local", task)
    token = bridge.security.grant("local", task)
    restarted = Bridge(config)
    try:
        import kirabridge.session_input_policy as module

        monkeypatch.setattr(
            module, "time", SimpleNamespace(time=lambda: first["input_buffer"]["expires"] + 1)
        )
        restarted.tasks.input_policy.expire()
        result = restarted.task("local", task.task_id)
        assert result["state"] == State.CANCELLED
        assert result["input_buffer"]["state"] == "expired"
        assert result["evidence"]["reason"] == "input_buffer_expired"
        assert restarted.submit("local", task, token)["state"] == State.CANCELLED
        with pytest.raises(BridgeError):
            restarted.tasks.approve(task.task_id)
        assert restarted.store.claim("test", 30) is None
        assert (
            restarted.store.db.execute("SELECT count(*) FROM completion_notices").fetchone()[0] == 1
        )
    finally:
        restarted.store.close()
    assert not calls


def test_denied_input_cannot_be_revived_with_valid_token(buffered):
    bridge, calls = buffered
    task = value()
    bridge.prepare("local", task)
    token = bridge.security.grant("local", task)
    bridge.store.transition(task.task_id, State.CANCELLED, {"source": "local_operator_rejection"})
    assert bridge.submit("local", task, token)["state"] == State.CANCELLED
    assert bridge.task("local", task.task_id)["input_buffer"]["state"] == "cancelled"
    assert not calls


async def test_direct_send_cannot_bypass_buffer(buffered):
    bridge, calls = buffered
    args = SessionInput.model_validate(value().arguments)
    with pytest.raises(BridgeError, match="buffered task"):
        await bridge.sessions.send("local", args)
    bridge.prepare("local", value())
    with pytest.raises(BridgeError, match="not been released"):
        await bridge.sessions.send("local", args, task_id="buffer-1")
    assert not calls


async def test_disabling_policy_does_not_release_existing_buffer(buffered, config):
    bridge, calls = buffered
    bridge.prepare("local", value())
    config.session_input_policy.enabled = False
    with pytest.raises(BridgeError):
        await bridge.sessions.send(
            "local", SessionInput.model_validate(value().arguments), task_id="buffer-1"
        )
    assert not calls


def test_marker_does_not_bypass_manual_rights_and_empty_marker_rejected(buffered, config):
    bridge, _ = buffered
    config.principals["local"].approval_mode = "manual"
    assert bridge.prepare("local", value("hello go-go-go"))["state"] == State.CREATED
    with pytest.raises(BridgeError, match="empty"):
        bridge.prepare("local", value("go-go-go", "empty"))


async def test_two_step_delivery_to_private_real_terminal(bridge, config, tmp_path):
    tmux = shutil.which("tmux")
    if not tmux:
        pytest.skip("tmux not installed")
    config.session_input_policy.enabled = True
    config.session_input_policy.principals = ["local"]
    config.principals["local"].approval_mode = "automatic"
    config.principals["local"].capabilities += ["session.inspect"]
    socket = "kb-buffer-" + uuid.uuid4().hex
    manager = SessionManager(bridge.sessions.ports, socket_name=socket)
    bridge.sessions = manager
    bridge.terminal.environment["PATH"] = (
        str(__import__("pathlib").Path(tmux).parent) + ":" + bridge.terminal.environment["PATH"]
    )
    receiver = tmp_path / "input_receiver.py"
    output = tmp_path / "received.txt"
    receiver.write_text(
        "import sys\nfrom pathlib import Path\nfor line in sys.stdin:\n"
        " with Path(sys.argv[1]).open('a') as output:\n  output.write(line)\n"
    )
    await asyncio.to_thread(
        subprocess.run,
        [
            tmux,
            "-L",
            socket,
            "new-session",
            "-d",
            "-s",
            "fixture",
            sys.executable,
            str(receiver),
            str(output),
        ],
        check=True,
    )
    try:
        selected = (await manager.catalog("local"))["sessions"][0]
        args = {k: selected[k] for k in ("pane_id", "expected_pid")}
        first = request("session.input", {**args, "text": "with-token"}, task_id="real-token")
        bridge.prepare("local", first)
        await bridge.tasks.start()
        await asyncio.sleep(0.15)
        assert not output.exists()
        bridge.submit("local", first, bridge.security.grant("local", first))
        assert (await bridge.tasks.wait("local", first.task_id, timeout=5))[
            "state"
        ] == State.COMPLETED
        second = request(
            "session.input", {**args, "text": "with-marker go-go-go"}, task_id="real-marker"
        )
        bridge.prepare("local", second)
        assert (await bridge.tasks.wait("local", second.task_id, timeout=5))[
            "state"
        ] == State.COMPLETED
        async with asyncio.timeout(3):
            while not output.exists() or len(output.read_text().splitlines()) < 2:
                await asyncio.sleep(0.03)
        assert output.read_text().splitlines() == ["with-token", "with-marker"]
    finally:
        await bridge.tasks.stop()
        await asyncio.to_thread(subprocess.run, [tmux, "-L", socket, "kill-server"], check=False)
