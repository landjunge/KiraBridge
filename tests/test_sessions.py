import asyncio
import shutil
import subprocess
import sys
import uuid

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.session_manager import SessionInput, SessionManager


@pytest.mark.asyncio
async def test_exact_session_input_and_capture_on_private_real_tmux(bridge, config, tmp_path):
    tmux = shutil.which("tmux")
    if not tmux:
        pytest.skip("tmux not installed")
    config.principals["local"].capabilities += ["session.inspect", "session.input"]
    bridge.terminal.environment["PATH"] = (
        str(__import__("pathlib").Path(tmux).parent) + ":" + bridge.terminal.environment["PATH"]
    )
    socket = "kb-test-" + uuid.uuid4().hex
    manager = SessionManager(bridge, socket_name=socket)
    fixture = tmp_path / "receiver.py"
    fixture.write_text(
        "import time\nprint('SESSION_READY',flush=True)\nline=input()\n"
        "print('RECEIVED:'+line,flush=True)\ntime.sleep(10)\n"
    )
    await asyncio.to_thread(
        subprocess.run,
        [tmux, "-L", socket, "new-session", "-d", "-s", "fixture", sys.executable, str(fixture)],
        check=True,
    )
    try:
        listed = await manager.catalog("local")
        selected = listed["sessions"][0]
        args = SessionInput(
            pane_id=selected["pane_id"],
            expected_pid=selected["expected_pid"],
            text="harmless session test",
        )
        with pytest.raises(BridgeError):
            await manager.send("other", args)
        with pytest.raises(BridgeError, match="exact current"):
            await manager.send(
                "local", args.model_copy(update={"expected_pid": args.expected_pid + 100000})
            )
        sent = await manager.send("local", args)
        assert sent["input_handed_to_transport"] and not sent["agent_processed"]
        async with asyncio.timeout(3):
            while True:
                captured = await manager.read("local", args.pane_id, args.expected_pid)
                if "RECEIVED:harmless session test" in captured["text"]:
                    break
                await asyncio.sleep(0.03)
    finally:
        await asyncio.to_thread(subprocess.run, [tmux, "-L", socket, "kill-server"], check=False)
