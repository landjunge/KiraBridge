"""Native worker isolation and lease lifetime without touching host UI/clipboard."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.models import UncertainExecution
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport


async def test_native_script_travels_on_stdin_not_process_arguments(monkeypatch):
    calls = []
    source = 'JSON.stringify({private_test_text:"NEVER_IN_ARGV"});'

    async def communicate(payload):
        calls.append(payload)
        return b'{"ok":true}', b""

    child = SimpleNamespace(communicate=communicate, returncode=0)

    async def spawn(*args, **kwargs):
        assert source not in args and all("NEVER_IN_ARGV" not in str(arg) for arg in args)
        assert kwargs["stdin"] == asyncio.subprocess.PIPE
        return child

    class Desktop:
        async def require_interactive(self):
            pass

    monkeypatch.setattr("kirabridge.platform_adapters.terminal_app.sys.platform", "darwin")
    monkeypatch.setattr(
        "kirabridge.platform_adapters.terminal_app.asyncio.create_subprocess_exec", spawn
    )
    transport = TerminalAppTransport(asyncio.Lock(), desktop=Desktop())
    assert await transport.native(source) == {"ok": True}
    assert calls == [source.encode("utf-8")]


async def test_clipboard_owner_outlives_failed_gui_worker():
    events = []

    @asynccontextmanager
    async def owner(text):
        events.append("owner_ready")
        try:
            yield SimpleNamespace(generation=123)
        finally:
            events.append("owner_restored")

    transport = TerminalAppTransport(asyncio.Lock(), clipboard_owner=owner)

    async def failed_worker(source, *, mutation=False):
        assert events == ["owner_ready"]
        assert "!==123" in source and source.index("checkClipboard();") < source.index(
            'paste.actions.byName("AXPress").perform();'
        )
        assert "saved=[]" not in source and "pb.clearContents" not in source
        events.append("worker_reaped")
        raise UncertainExecution("session_input_unknown", "Worker timeout; do not replay")

    transport.native = failed_worker
    with pytest.raises(UncertainExecution):
        await transport.insert("terminal:123:ttys004", "literal test")
    assert events == ["owner_ready", "worker_reaped", "owner_restored"]
    assert not transport.clipboard_lock.locked()


async def test_repeated_cancellation_reaps_gui_before_clipboard_restore(monkeypatch):
    killed, finish_reap = asyncio.Event(), asyncio.Event()
    events = []

    @asynccontextmanager
    async def owner(text):
        try:
            yield SimpleNamespace(generation=123)
        finally:
            assert "reaped" in events
            events.append("restored")

    async def communicate(source):
        await asyncio.Event().wait()

    async def wait():
        await finish_reap.wait()
        events.append("reaped")
        child.returncode = -9
        return -9

    def kill():
        killed.set()

    child = SimpleNamespace(communicate=communicate, returncode=None, kill=kill, wait=wait)

    async def spawn(*args, **kwargs):
        return child

    class Desktop:
        async def require_interactive(self):
            pass

    monkeypatch.setattr("kirabridge.platform_adapters.terminal_app.sys.platform", "darwin")
    monkeypatch.setattr(
        "kirabridge.platform_adapters.terminal_app.asyncio.create_subprocess_exec", spawn
    )
    transport = TerminalAppTransport(asyncio.Lock(), desktop=Desktop(), clipboard_owner=owner)
    task = asyncio.create_task(transport.insert("terminal:123:ttys004", "literal"))
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.wait_for(killed.wait(), 1)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done() and "restored" not in events
    finish_reap.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ["reaped", "restored"]


@pytest.mark.parametrize(
    "text,before,after,expected",
    [
        ("literal\n", "history literal\n› ", "history literal\n› ", False),
        ("literal", "history literal\n› ", "history literal\n› x", False),
        ("literal", "history literal\n› ", "history literal\n› literal", True),
        ("first\nlast\n", "› ", "› first\nlast\n", True),
        ("\n", "› ", "› ", False),
        ("long text", "› ", "› [Pasted Content 9 chars]", True),
        pytest.param("literal ", "› ", "› literal ", True, id="trailing_space"),
    ],
)
def test_native_paste_observation_uses_new_nonempty_delta(text, before, after, expected):
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("JavaScript runtime unavailable")
    script = TerminalAppTransport.native_paste_observation(text)
    script += (
        "process.stdout.write(JSON.stringify(observedPaste("
        + json.dumps(before)
        + ","
        + json.dumps(after)
        + ")));"
    )
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, timeout=5, check=True
    )
    assert json.loads(result.stdout) is expected
