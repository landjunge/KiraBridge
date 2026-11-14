"""Real private subprocess pipes; no Terminal, live process census or UI effects."""

import asyncio
import os
import sys

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport


def redirect_ps(monkeypatch, program):
    import kirabridge.platform_adapters.terminal_app as module

    original = asyncio.create_subprocess_exec
    children = []

    async def spawn(*argv, **options):
        assert argv == ("/bin/ps", "-axo", "uid=,pid=,ppid=,tty=,comm=")
        child = await original(sys.executable, "-I", "-B", "-c", program, **options)
        children.append(child)
        return child

    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    return TerminalAppTransport(asyncio.Lock()), children


def assert_reaped(children):
    assert len(children) == 1
    assert children[0].returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(children[0].pid, 0)


async def test_catalog_drains_valid_output_larger_than_pipe_buffer(monkeypatch):
    transport, children = redirect_ps(
        monkeypatch,
        "import os; os.write(1, b''.join(f'501 {p} 1 ?? /bin/example\\n'.encode() "
        "for p in range(1,16001)))",
    )
    output, code = await transport._ps_catalog()
    assert len(output) > 256 * 1024
    assert len(output.splitlines()) == 16000
    assert code == 0
    assert_reaped(children)


async def test_catalog_rejects_oversized_unfinished_output_before_observation_timeout(monkeypatch):
    transport, children = redirect_ps(
        monkeypatch,
        "import os,time; os.write(1,b'x'*(2*1024*1024)); time.sleep(60)",
    )
    with pytest.raises(BridgeError) as error:
        await transport._ps_catalog()
    assert error.value.code == "session_observation_invalid"
    assert error.value.provider_error == {
        "phase": "native_process_catalog",
        "reason": "output_limit",
    }
    assert_reaped(children)


async def test_catalog_blocked_child_times_out_and_reaps_without_partial_success(monkeypatch):
    transport, children = redirect_ps(
        monkeypatch, "import os,time; os.write(1,b'501 1 0 ?? /bin/example\\n'); time.sleep(60)"
    )
    with pytest.raises(BridgeError) as error:
        await transport._ps_catalog()
    assert error.value.code == "session_observation_timeout"
    assert error.value.provider_error == {"phase": "native_process_catalog", "reason": "timeout"}
    assert_reaped(children)


async def test_catalog_cancellation_reaps_own_blocked_child_without_retry(monkeypatch):
    transport, children = redirect_ps(monkeypatch, "import time; time.sleep(60)")
    task = asyncio.create_task(transport._ps_catalog())
    async with asyncio.timeout(5):
        while not children:
            await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert_reaped(children)


@pytest.mark.parametrize("delta", [-1, 0, 1])
async def test_catalog_output_limit_boundary(monkeypatch, delta):
    size = 1048576 + delta
    transport, children = redirect_ps(monkeypatch, f"import os; os.write(1,b'x'*{size})")
    if delta > 0:
        with pytest.raises(BridgeError) as error:
            await transport._ps_catalog()
        assert error.value.provider_error == {
            "phase": "native_process_catalog",
            "reason": "output_limit",
        }
    else:
        output, code = await transport._ps_catalog()
        assert len(output) == size
        assert code == 0
    assert_reaped(children)


async def test_stdout_eof_does_not_accept_a_still_running_process(monkeypatch):
    transport, children = redirect_ps(monkeypatch, "import os,time; os.close(1); time.sleep(60)")
    with pytest.raises(BridgeError) as error:
        await transport._ps_catalog()
    assert error.value.code == "session_observation_timeout"
    assert_reaped(children)
