import asyncio
import json
import os
import signal
import sys

from conftest import request, submit

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import State


async def test_real_dispatcher_sigkill_never_duplicates(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = tmp_path / "config.toml"
    policy.write_text(
        "data_dir=" + json.dumps(str(tmp_path / "state")) + "\n"
        '[principals.local]\ncapabilities=["terminal.execute","task.read","bridge.health"]\n'
        "roots=[" + json.dumps(str(workspace)) + "]\n"
        "executables=[" + json.dumps(sys.executable) + "]\n"
    )
    from kirabridge.bridge_core.config import load_config

    config = load_config(str(policy))
    original = Bridge(config)
    code = (
        "import time; from pathlib import Path; "
        "p=Path('effect'); p.write_text(p.read_text()+'x' if p.exists() else 'x'); time.sleep(0.3)"
    )
    value = request(
        "terminal.execute", {"argv": [sys.executable, "-c", code], "cwd": str(workspace)}
    )
    submit(original, value)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "kirabridge.cli",
        "--config",
        str(policy),
        "serve",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    child_pid = None
    try:
        async with asyncio.timeout(10):
            while (
                original.store.get(value.task_id)["state"] != State.RUNNING
                or not (workspace / "effect").exists()
            ):
                await asyncio.sleep(0.01)
        child_pid = original.store.get(value.task_id)["evidence"]["pid"]
        process.kill()
        await process.wait()
        await asyncio.sleep(0.4)
        original.store.close()
        async with Bridge(config) as recovered:
            assert recovered.store.get(value.task_id)["state"] == "unknown"
            assert recovered.submit("local", value, "")["state"] == "unknown"
            assert (workspace / "effect").read_text() == "x"
            assert recovered.store.claim("test", 30) is None
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        if process.stdin:
            process.stdin.close()
        if child_pid:
            try:
                os.killpg(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        original.store.close()
