import asyncio
from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.session_manager import SessionInput, SessionManager
from kirabridge.session_ports import SessionPorts


class ExistingTransport:
    available = True
    last_catalog_truncated = False

    def __init__(self, rows=()):
        self.rows, self.calls = list(rows), []
        self.desktop = SimpleNamespace(last={"state": "test_adapter"})
        self.return_uncertain = False

    async def catalog(self):
        return self.rows

    async def read(self, pane_id):
        self.calls.append(("read", pane_id))
        return "Actual selected output"

    async def insert(self, pane_id, text):
        self.calls.append(("insert", pane_id, text))

    async def press_return(self, pane_id):
        self.calls.append(("return", pane_id))
        if self.return_uncertain:
            raise UncertainExecution("session_input_unknown", "Return outcome unknown")

    async def send(self, *args, **kwargs):
        self.calls.append(("send", args, kwargs))

    async def open(self, command):
        self.calls.append(("open", command))
        pytest.fail("No test or failure may open a window")


def manager_without_core(*, rows=None, bound_pid=456):
    binding = SimpleNamespace(pane_id="terminal:123:ttys004", expected_pid=345, agent_pid=bound_pid)
    row = {
        "pane_id": binding.pane_id,
        "expected_pid": 345,
        "tty": "/dev/ttys004",
        "busy": True,
        "processes": [{"pid": 456, "name": "grok"}],
    }
    native, tmux, seen = ExistingTransport([row] if rows is None else rows), ExistingTransport(), []

    def authorize(principal, capability):
        seen.append((principal, capability))

    ports = SessionPorts(
        authorization=SimpleNamespace(principal=authorize),
        input_release=None,
        audit=SimpleNamespace(record=lambda *args, **kwargs: seen.append("audit")),
        environment={},
        agent_registry=lambda: ({"grok": object()}, {"grok": binding}),
        clipboard_lock=asyncio.Lock(),
    )
    manager = SessionManager(ports, terminal_app=native, tmux=tmux)
    return manager, native, tmux, seen


@pytest.mark.parametrize("sender", ["chatgpt", "grok_app", "codex", "grok"])
@pytest.mark.parametrize("failure", ["missing", "wrong_pid", "ambiguous", "stale_agent"])
async def test_bad_existing_target_cannot_insert_return_open_or_use_other_transport(
    sender, failure
):
    manager, native, tmux, _ = manager_without_core(
        bound_pid=457 if failure == "stale_agent" else 456
    )
    if failure == "missing":
        native.rows.clear()
    elif failure == "ambiguous":
        native.rows *= 2
    args = SessionInput(
        pane_id="terminal:123:ttys004",
        expected_pid=346 if failure == "wrong_pid" else 345,
        text="First line\nSecond line",
        submit=False,
    )
    for invoke in (
        lambda: manager.insert(sender, args),
        lambda: manager.press_return(sender, args.pane_id, args.expected_pid),
    ):
        with pytest.raises(BridgeError):
            await invoke()
    assert native.calls == tmux.calls == []


async def test_adapter_replacement_reads_and_separates_literal_paste_return_and_ack():
    manager, native, tmux, seen = manager_without_core()
    args = SessionInput(
        pane_id="terminal:123:ttys004",
        expected_pid=345,
        text="First line\nSecond line",
        submit=False,
    )
    output = await manager.read_observed("codex", args.pane_id, args.expected_pid)
    assert output["text"] == "Actual selected output" and "audit" in seen
    inserted = await manager.insert("codex", args)
    assert inserted == {"paste_event_sent": True, "return_sent": False, "agent_confirmed": False}
    assert [call[0] for call in native.calls] == ["read", "insert"]
    sent = await manager.press_return("codex", args.pane_id, args.expected_pid)
    assert sent == {"return_sent": True, "agent_confirmed": False}
    assert native.calls[-1] == ("return", args.pane_id) and tmux.calls == []
    assert ("codex", "session.input") in seen and ("codex", "terminal.execute") in seen


async def test_unknown_return_has_one_attempt_without_fallback_or_retry():
    manager, native, tmux, _ = manager_without_core()
    native.return_uncertain = True
    with pytest.raises(UncertainExecution):
        await manager.press_return("codex", "terminal:123:ttys004", 345)
    assert native.calls == [("return", "terminal:123:ttys004")] and tmux.calls == []


@pytest.mark.parametrize("sender", ["chatgpt", "grok_app", "codex", "grok"])
async def test_recognized_agent_cannot_bypass_central_handoff_with_direct_send(sender):
    manager, native, tmux, _ = manager_without_core()
    with pytest.raises(BridgeError) as error:
        await manager.send(
            sender,
            SessionInput(
                pane_id="terminal:123:ttys004", expected_pid=345, text="Do not route directly"
            ),
        )
    assert error.value.code == "visible_handoff_required" and native.calls == tmux.calls == []
