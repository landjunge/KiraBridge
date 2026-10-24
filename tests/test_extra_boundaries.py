import asyncio
import os
import sys

import pytest
from conftest import request, submit

from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool, Peer


async def test_children_are_killed_when_parent_exits(bridge, config):
    code = (
        "import subprocess,sys; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        "print(p.pid,flush=True)"
    )
    value = request(
        "terminal.execute",
        {
            "argv": [sys.executable, "-c", code],
            "cwd": config.principals["local"].roots[0],
            # Allow interpreter/child startup on the actual Intel host under load.
            # The invariants remain timeout + observed child PID + child disappearance.
            "timeout": 3.0,
        },
    )
    submit(bridge, value)
    async with bridge:
        final = await bridge.tasks.wait("local", value.task_id, 10)
        assert final["result"]["timed_out"]
        pid = int(final["result"]["stdout"].strip())
        # An orphan may be briefly reaped by init; wait for observable disappearance.
        async with asyncio.timeout(5):
            while True:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                await asyncio.sleep(0.02)


async def test_state_database_is_excluded_even_inside_allowed_root(bridge, config):
    config.principals["local"].roots = [str(config.state_path.parent)]
    value = request("file.read", {"path": str(config.state_path / "bridge.sqlite3")})
    submit(bridge, value)
    async with bridge:
        final = await bridge.tasks.wait("local", value.task_id)
        assert final["state"] == "failed" and final["started"] is None
        assert final["error"]["code"] == "path_denied"


async def test_client_timeout_never_repeats_remote_call():
    class SlowSession:
        count = 0

        async def call_tool(self, name, arguments):
            self.count += 1
            await asyncio.sleep(30)

    pool = MCPClientPool(call_timeout=0.01)
    session = SlowSession()
    pool.sessions["fake"] = session
    with pytest.raises(BridgeError) as failure:
        await pool.call("fake", "side_effect", {})
    assert failure.value.code == "peer_unknown" and session.count == 1
    assert "secret" not in repr(Peer("x", url="https://host/mcp", token="secret"))
