"""Native Linux direct argv and its admission/identity/output boundaries."""

import asyncio
import os
import sys
from unittest.mock import AsyncMock

import pytest
from conftest import request
from test_mcp import http_bridge  # noqa: F401 -- isolated authenticated HTTP fixture

from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.read_query import ReadQuery, read_query
from kirabridge.readiness import ReadinessInput, readiness
from kirabridge.visible_terminal import VisibleTerminalInput

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Native Linux PTY")


@pytest.fixture
def direct(bridge, config, monkeypatch):
    policy = config.principals["local"]
    policy.capabilities.append("session.inspect")
    policy.approval_mode = "automatic"
    policy.client_type = "chatgpt"
    # Input preflight must be passive: no window/session can be opened here.
    bridge.sessions.open = AsyncMock(side_effect=AssertionError("No reusable shell"))
    bridge.sessions.catalog = AsyncMock(side_effect=AssertionError("No user session lookup"))
    monkeypatch.setattr(
        type(bridge.sessions.terminal_app), "available", property(lambda self: False)
    )
    return bridge, policy


def command(policy, code, **options):
    return VisibleTerminalInput(argv=[sys.executable, "-c", code], cwd=policy.roots[0], **options)


@pytest.mark.parametrize("create", [True, False])
async def test_native_argv_has_real_tty_cwd_output_exit_and_no_persistent_session(direct, create):
    bridge, policy = direct
    result = await bridge.visible_terminal.execute(
        {"id": "native-direct", "principal": "local"},
        command(
            policy,
            "import os; print(all(os.isatty(i) for i in range(3))); print(os.getcwd())",
            create_if_needed=create,
        ),
        AsyncMock(),
    )
    assert result["exit_code"] == 0 and result["success"]
    assert "True\r\n" in result["terminal_output"]
    assert policy.roots[0] in result["terminal_output"]
    assert result["execution_route"] == "linux_owned_pty"
    assert result["pane_id"] == f"linux:{result['pid']}"
    assert result["tty"].startswith("/dev/pts/")
    assert result["pty_closed"] and result["owned_processes_reaped"]
    assert not bridge.sessions.linux._sessions
    with pytest.raises(ProcessLookupError):
        os.kill(result["pid"], 0)


async def test_exact_argv_nonzero_and_output_limit(direct):
    bridge, policy = direct
    args = command(
        policy, "import sys; print(repr(sys.argv[1])); print('X'*10000); sys.exit(7)", max_output=80
    )
    args.argv.append("$(touch forbidden);\n$HOME")
    result = await bridge.visible_terminal.execute(
        {"id": "nonzero", "principal": "local"}, args, AsyncMock()
    )
    assert result["exit_code"] == 7 and not result["success"]
    assert "$(touch forbidden);\\n$HOME" in result["terminal_output"]
    assert len(result["terminal_output"].encode()) == 80
    assert result["output_truncated"] and result["output_bytes"] > 10000
    assert not result["timed_out"]


@pytest.mark.parametrize("failure", ["capability", "cwd", "executable", "pane", "privileged"])
async def test_denials_before_any_spawn(direct, failure, monkeypatch, tmp_path):
    bridge, policy = direct
    args = command(policy, "raise AssertionError('must not run')")
    options = {}
    if failure == "capability":
        policy.capabilities.remove("session.input")
    elif failure == "cwd":
        args.cwd = str(tmp_path)
    elif failure == "executable":
        policy.executables = []
    elif failure == "pane":
        args.pane_id, args.expected_pid = "terminal:123:ttys004", 345
    else:
        options["privileged"] = True
    spawn = AsyncMock(side_effect=AssertionError("Must reject before spawn"))
    monkeypatch.setattr(bridge.sessions.linux, "execute_argv", spawn)
    running = AsyncMock()
    with pytest.raises(BridgeError):
        await bridge.visible_terminal.execute(
            {"id": "denied", "principal": "local"}, args, running, **options
        )
    spawn.assert_not_awaited()
    running.assert_not_awaited()


async def test_timeout_reaps_only_own_processes_and_preserves_other_owned_shell(direct):
    bridge, policy = direct
    other = await bridge.sessions.linux.open_shell(policy.roots[0])
    observed = []

    async def running(identity):
        observed.append(identity)

    try:
        result = await bridge.visible_terminal.execute(
            {"id": "timeout", "principal": "local"},
            command(
                policy,
                "import subprocess,time; p=subprocess.Popen(['/bin/sleep','30']); "
                "print(p.pid,flush=True); time.sleep(30)",
                timeout=0.15,
            ),
            running,
        )
        assert result["timed_out"] and result["terminated"] and not result["success"]
        assert result["exit_code"] < 0
        assert observed[0]["pid"] == result["pid"] != other["expected_pid"]
        assert [r["pane_id"] for r in await bridge.sessions.linux.catalog()] == [other["pane_id"]]
        # The exact owned leader is gone. Descendant cleanup is the shared reaper's
        # native census contract (zombies may remain until the host reaps them).
        with pytest.raises(ProcessLookupError):
            os.kill(result["pid"], 0)
    finally:
        await bridge.sessions.linux.close(other["pane_id"])


@pytest.mark.parametrize("cancel", [False, True])
async def test_callback_failure_or_cancellation_closes_own_pty(direct, cancel):
    bridge, policy = direct
    started = asyncio.Event()
    identity = {}

    async def running(value):
        identity.update(value)
        started.set()
        if not cancel:
            raise RuntimeError("persist failed")

    worker = asyncio.create_task(
        bridge.visible_terminal.execute(
            {"id": "cancel", "principal": "local"},
            command(policy, "import time; time.sleep(30)"),
            running,
        )
    )
    await asyncio.wait_for(started.wait(), 5)
    if cancel:
        worker.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
        await worker
    with pytest.raises(ProcessLookupError):
        os.kill(identity["pid"], 0)
    assert not bridge.sessions.linux._sessions


@pytest.mark.parametrize("operation", ["terminal.visible", "terminal.execute"])
async def test_dispatch_alias_idempotency_original_output_and_passive_preflight(direct, operation):
    bridge, policy = direct
    preflight = readiness(
        bridge, "local", ReadinessInput(operations=[operation], working_directories=policy.roots)
    )
    assert preflight["operation_checks"][0]["code"] == "transport_not_probed"
    assert not bridge.sessions.linux._sessions
    value = request(
        operation,
        {"argv": [sys.executable, "-c", "print('KB_NATIVE_DIRECT_OK')"], "cwd": policy.roots[0]},
        task_id="direct-alias",
    )
    async with bridge:
        bridge.prepare("local", value)
        task = await bridge.tasks.wait("local", value.task_id, 8)
        assert task["state"] == "completed", task
        assert task["result"]["execution_route"] == "linux_owned_pty"
        assert bridge.prepare("local", value)["receipt"] == task["receipt"]
        output = read_query(
            bridge, "local", ReadQuery(operation="terminal.output", task_id=value.task_id)
        )
        if asyncio.iscoroutine(output):
            output = await output
        assert "KB_NATIVE_DIRECT_OK" in str(output)
        assert not bridge.sessions.linux._sessions


async def test_original_uname_a_repro_native_default(direct):
    bridge, policy = direct
    # The real development principal permits PATH lookup; preserve that contract.
    policy.allow_any_executable = True
    result = await bridge.visible_terminal.execute(
        {"id": "fresh-uname-repro", "principal": "local"},
        VisibleTerminalInput(argv=["uname", "-a"], cwd=policy.roots[0]),
        AsyncMock(),
    )
    assert result["success"] and result["exit_code"] == 0
    assert result["terminal_output"].startswith("Linux ")


async def test_output_flood_cannot_starve_timeout_and_zero_capture(direct):
    bridge, policy = direct
    result = await asyncio.wait_for(
        bridge.visible_terminal.execute(
            {"id": "flood", "principal": "local"},
            command(
                policy, "import os\nwhile True: os.write(1,b'X'*8192)", timeout=0.1, max_output=0
            ),
            AsyncMock(),
        ),
        8,
    )
    assert result["timed_out"] and not result["success"]
    assert result["terminal_output"] == "" and result["output_bytes"] > 0
    assert result["output_truncated"] and result["pty_closed"]


async def test_spawn_failure_closes_both_pty_descriptors(direct, monkeypatch):
    import kirabridge.platform_adapters.linux.owned_terminal as backend

    bridge, policy = direct
    before = set(os.listdir("/proc/self/fd"))
    spawn = AsyncMock(side_effect=BridgeError("spawn_failed", "test failure"))
    monkeypatch.setattr(backend, "spawn_process", spawn)
    with pytest.raises(BridgeError, match="test failure"):
        await bridge.visible_terminal.execute(
            {"id": "spawn-failure", "principal": "local"},
            command(policy, "pass"),
            AsyncMock(),
        )
    assert set(os.listdir("/proc/self/fd")) == before


async def test_authenticated_http_terminal_control_default_and_linux_catalog(
    http_bridge,  # noqa: F811 -- imported isolated fixture
    config,
):
    bridge, endpoint = http_bridge
    policy = config.principals["local"]
    policy.capabilities.append("session.inspect")
    policy.permission_level = "full"
    async with MCPClientPool() as pool:
        await pool.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        catalog = (
            await pool.call("local", "operation_catalog", {"operations": ["terminal.visible"]})
        ).structuredContent
        native = catalog["operations"]["terminal.visible"]["platform"]
        assert native["provider_id"] == "linux.owned_pty"
        assert native["technical_available"] and native["eligible_for_submission"]
        assert native["permissions"] == [] and native["runtime_availability"] == "not_probed"
        assert "short-lived owned PTY" in catalog["discovery"]["direct_terminal"]["selection"]
        response = (
            await pool.call(
                "local",
                "terminal_control",
                {
                    "argv": [sys.executable, "-c", "print('HTTP_NATIVE_PTY_OK')"],
                    "cwd": policy.roots[0],
                    "task_id": "http-native-direct",
                    "idempotency_key": "http-native-direct",
                },
            )
        ).structuredContent
        assert not response.get("error"), response
        task = await bridge.tasks.wait("local", "http-native-direct", 8)
        assert task["state"] == "completed", task
        assert task["result"]["success"] and task["result"]["pty_closed"]
        assert "HTTP_NATIVE_PTY_OK" in task["result"]["terminal_output"]
        assert not bridge.sessions.linux._sessions
