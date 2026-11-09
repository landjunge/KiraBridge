"""A hung or closed ThreadDesk stdio peer is replaced; tool calls are never replayed.

Only synthetic local stdio peers, temporary directories and temporary state are used.
"""

import asyncio
import os
import signal
import sys
import time
from pathlib import Path

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.threaddesk_dynamic import call, catalog

PEER = str(Path(__file__).with_name("td_synthetic_peer.py"))


def set_mode(peer_dir, value):
    (peer_dir / "mode").write_text(value)


def lines(peer_dir, name):
    path = peer_dir / name
    return path.read_text().split() if path.exists() else []


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def eventually(check, seconds=10):
    deadline = time.monotonic() + seconds
    while not check() and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    return check()


@pytest.fixture
def peer_dir(tmp_path):
    path = tmp_path / "peer"
    path.mkdir()
    return path


@pytest.fixture(autouse=True)
def no_stray_peers(peer_dir):
    yield
    for pid in lines(peer_dir, "pids"):
        try:
            os.kill(int(pid), signal.SIGCONT)
            os.kill(int(pid), signal.SIGKILL)
        except ProcessLookupError:
            pass


@pytest.fixture
async def td(bridge, config, peer_dir):
    config.threaddesk.enabled = True
    config.threaddesk.command = sys.executable
    config.threaddesk.args = [PEER, str(peer_dir)]
    config.threaddesk.dynamic_read_proxy = True
    config.threaddesk.workspace = config.principals["local"].roots[0]
    config.threaddesk.timeout = 1
    bridge.threaddesk.pool.call_timeout = 1  # The manager copied the default at construction.
    for policy in config.principals.values():
        policy.permission_level = "full"
    yield bridge
    await bridge.threaddesk.close()


def names(result):
    return {item["name"] for item in result["tools"]}


@pytest.mark.parametrize("fault", ["hang_get_thread", "exit_get_thread", "close_get_thread"])
async def test_catalog_returns_after_peer_hangs_or_closes_without_replaying_the_call(
    td, peer_dir, fault
):
    set_mode(peer_dir, f"serial,{fault}")
    assert "echo_read" in names(await catalog(td, "local"))
    broken = [int(pid) for pid in lines(peer_dir, "pids")]
    assert len(broken) == 1

    with pytest.raises(BridgeError):  # The outcome is unknown and stays unknown.
        await call(td, "local", "get_thread", {"id": "x"})
    set_mode(peer_dir, "serial")  # Replacement peers are healthy.

    started = time.monotonic()
    assert "echo_read" in names(await catalog(td, "local"))

    assert time.monotonic() - started < 8
    assert len(lines(peer_dir, "pids")) == 2  # Exactly one bounded replacement.
    assert await eventually(lambda: not alive(broken[0]))  # The old process is gone.
    assert lines(peer_dir, "calls").count("get_thread") == 1  # No automatic replay.


async def test_hanging_call_does_not_block_the_catalog_for_other_clients(td, peer_dir):
    td.config.threaddesk.timeout = td.threaddesk.pool.call_timeout = 4
    set_mode(peer_dir, "hang_get_thread")  # Threaded peer: it still answers other requests.
    assert "echo_read" in names(await catalog(td, "local"))
    pending = asyncio.create_task(call(td, "local", "get_thread", {"id": "x"}))
    assert await eventually(lambda: "get_thread" in lines(peer_dir, "calls"))

    started = time.monotonic()
    assert "echo_read" in names(await catalog(td, "local"))

    assert time.monotonic() - started < 1.5  # The pending call holds no catalog lock.
    with pytest.raises(BridgeError):
        await pending
    assert len(lines(peer_dir, "pids")) == 1  # A responsive peer is not replaced.


@pytest.mark.parametrize("how", ["kill", "stop"])
async def test_catalog_returns_after_an_idle_peer_died_or_froze(td, peer_dir, how):
    set_mode(peer_dir, "serial")
    assert "echo_read" in names(await catalog(td, "local"))
    victim = int(lines(peer_dir, "pids")[0])
    os.kill(victim, signal.SIGKILL if how == "kill" else signal.SIGSTOP)
    await asyncio.sleep(0.2)

    listed = None
    for _ in range(2):  # A clear error may precede the bounded replacement, never a hang.
        try:
            listed = await catalog(td, "local")
            break
        except BridgeError:
            pass

    assert listed is not None and "echo_read" in names(listed)
    assert len(lines(peer_dir, "pids")) == 2
    assert await eventually(lambda: not alive(victim))


async def test_repeated_peer_failures_are_paced_and_capped(td, peer_dir):
    set_mode(peer_dir, "die_at_start")
    manager = td.threaddesk
    for _ in range(2):  # The first rebuild is immediate; the second is followed by a pause.
        with pytest.raises(BridgeError) as failed:
            await manager.connect()
        assert failed.value.diagnostic["consecutive_failures"] in {1, 2}
        assert failed.value.diagnostic["automatic_retry"] is False
    assert len(lines(peer_dir, "pids")) == 2

    with pytest.raises(BridgeError) as paced:
        await manager.connect()  # Inside the pause: no new process, a clear diagnosis.
    assert paced.value.code == "threaddesk_reconnect_backoff"
    assert 0 < paced.value.diagnostic["retry_after_seconds"] <= 1
    assert len(lines(peer_dir, "pids")) == 2

    manager.failures = 40  # Many failures never push the pause beyond the cap.
    assert manager.peer_failure("x", "y", reset=True).diagnostic["retry_after_seconds"] == 60
    set_mode(peer_dir, "serial")
    manager.retry_at = 0.0
    assert "echo_read" in names(await catalog(td, "local"))
    assert manager.failures == 0  # A healthy catalog read clears the pacing.


async def test_catalog_tool_reports_a_named_diagnosis_instead_of_an_empty_error(td, monkeypatch):
    from anyio import ClosedResourceError

    from kirabridge.mcp_gateway.server import create_server

    async def broken(*_):
        raise ClosedResourceError  # Its message is empty, like the observed failure.

    monkeypatch.setattr("kirabridge.threaddesk_dynamic.catalog", broken)
    _, structured = await create_server(td).call_tool("threaddesk_dynamic_catalog", {})

    assert structured["error"]["code"] == "threaddesk_peer_failure"
    assert "ClosedResourceError" in structured["error"]["message"]
    assert structured["diagnostic"]["automatic_retry"] is False
