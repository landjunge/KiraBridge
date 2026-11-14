"""Bounded, content-free diagnostics for native catalog timeouts."""

import asyncio
import os
import sys

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport


async def run_blocked_ps(monkeypatch, program):
    import kirabridge.platform_adapters.terminal_app as module

    original = asyncio.create_subprocess_exec
    children = []

    async def spawn(*argv, **options):
        assert argv == ("/bin/ps", "-axo", "uid=,pid=,ppid=,tty=,comm=")
        child = await original(sys.executable, "-I", "-B", "-c", program, **options)
        children.append(child)
        return child

    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    try:
        await TerminalAppTransport(asyncio.Lock())._ps_catalog()
    except BridgeError as error:
        return error, children
    raise AssertionError("blocked process unexpectedly completed")


@pytest.mark.parametrize(
    ("program", "stage", "size", "eof"),
    [
        ("import os,time; os.write(1,b'x'*37); time.sleep(60)", "stdout_read", 37, False),
        ("import os,time; os.write(1,b'x'*37); os.close(1); time.sleep(60)", "exit_wait", 37, True),
    ],
)
async def test_timeout_metadata_identifies_blocked_phase_without_output(
    monkeypatch, program, stage, size, eof
):
    error, children = await run_blocked_ps(monkeypatch, program)

    assert len(children) == 1
    assert children[0].returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(children[0].pid, 0)
    metadata = error.provider_error
    assert metadata["phase"] == "native_process_catalog"
    assert metadata["reason"] == "timeout"
    assert metadata["stage"] == stage
    assert metadata["stdout_bytes"] == size
    assert metadata["stdout_eof"] is eof
    assert metadata["exit_status"] is None
    assert 0 <= metadata["elapsed_ms"] < 10000
    assert 0 <= metadata["cleanup_ms"] < 10000
    assert len(str(metadata)) <= 1024
    assert "xxxxx" not in str(metadata)
