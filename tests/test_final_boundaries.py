import asyncio
import sys

from conftest import request, submit

from kirabridge.bridge_core.models import TerminalInput


def test_task_list_pagination_and_principal_isolation(bridge, config):
    for number in range(3):
        submit(
            bridge,
            request(
                arguments={"path": config.principals["local"].roots[0]}, task_id=f"list-{number}"
            ),
        )
    first = bridge.list_tasks("local", limit=2)
    second = bridge.list_tasks("local", after=first["next_cursor"], limit=2)
    assert len(first["tasks"]) == 2 and len(second["tasks"]) == 1
    assert bridge.list_tasks("other")["tasks"] == []
    assert all("args" not in row for row in first["tasks"])


async def test_stalled_child_stdin_cannot_hang_cleanup(bridge, config):
    async def running(evidence):
        pass

    async with asyncio.timeout(8):
        result = await bridge.terminal.execute(
            "stdin-test",
            "local",
            TerminalInput(
                argv=[sys.executable, "-c", "import time; time.sleep(60)"],
                cwd=config.principals["local"].roots[0],
                timeout=0.1,
            ),
            config.principals["local"].roots,
            [sys.executable],
            running,
            stdin=b"x" * 1048576,
        )
    assert result["timed_out"] and result["exit_code"] != 0
    assert not bridge.terminal.sessions
