"""Live logs are bounded, principal-scoped observation and never affect execution."""

import sys

import pytest
from conftest import request

from kirabridge.bridge_core.config import LiveLogsConfig
from kirabridge.bridge_core.models import BridgeError
from kirabridge.live_logs import LiveLogHub


def _hub(**overrides):
    return LiveLogHub(LiveLogsConfig(**overrides))


def test_cursor_read_is_incremental_and_marks_dropped_lines():
    hub = _hub(max_lines_per_source=10, max_bytes_per_source=4096)
    hub.open("t1", "local", operation="terminal.execute")
    hub.append("t1", "local", "stdout", "one\ntwo\n")
    first = hub.read("local", "t1")
    assert [entry["text"] for entry in first["entries"]] == ["one", "two"]
    assert first["next_cursor"] == 2 and first["reset"] is False
    hub.append("t1", "local", "stderr", "three\n")
    second = hub.read("local", "t1", cursor=first["next_cursor"])
    assert [entry["text"] for entry in second["entries"]] == ["three"]
    assert second["entries"][0]["channel"] == "stderr"
    for number in range(20):
        hub.append("t1", "local", "stdout", f"line-{number}")
    latest = hub.read("local", "t1", cursor=second["next_cursor"])
    assert latest["reset"] is True and latest["dropped"] == 13
    assert [entry["text"] for entry in latest["entries"]] == [
        f"line-{number}" for number in range(10, 20)
    ]
    assert latest["entries"][-1]["seq"] > latest["cursor"] > 0


def test_principal_scope_unknown_source_and_channel_filter():
    hub = _hub()
    hub.open("shared", "local")
    hub.append("shared", "local", "stdout", "local-only\n")
    hub.append("shared", "other", "stdout", "intruder\n")
    assert [entry["text"] for entry in hub.read("local", "shared")["entries"]] == ["local-only"]
    assert hub.status("other")["count"] == 0
    with pytest.raises(BridgeError) as failure:
        hub.read("other", "shared")
    assert failure.value.code == "logs_unavailable"
    with pytest.raises(BridgeError):
        hub.read("local", "missing")
    assert hub.read("local", "shared", channels=["events"])["entries"] == []


def test_sources_are_bounded_and_recording_never_raises():
    hub = _hub(max_sources=2, max_line_chars=64)
    hub.open("a", "local")
    hub.open("b", "local")
    hub.close("a")
    hub.open("c", "local")  # Evicts the oldest closed source only.
    assert "a" not in hub.sources and hub.status("local")["count"] == 2
    hub.open("d", "local")  # Both remaining sources are live: refuse, never displace.
    assert "d" not in hub.sources and hub.dropped_sources == 1
    hub.append("b", "local", "events", "x" * 500)
    hub.append("b", "local", "stdout", object())
    hub.append("b", "local", "unknown", "ignored")
    entry = hub.read("local", "b", channels=["events"])["entries"][0]
    assert len(entry["text"]) <= 64 + 32 and entry["text"].endswith("chars]")
    assert hub.read("local", "b", channels=["stdout"])["entries"] == []
    assert hub.status("local")["sources"][0]["next_cursor"] == 1


def test_disabled_hub_records_nothing():
    hub = LiveLogHub(LiveLogsConfig(enabled=False))
    assert hub.tracks("terminal.execute") is False
    assert hub.open("t1", "local") is None
    hub.append("t1", "local", "stdout", "never recorded\n")
    assert hub.sources == {}


async def test_bridge_captures_child_streams_and_progress_events(bridge, config):
    config.principals["local"].approval_mode = "automatic"
    workspace = config.principals["local"].roots[0]
    code = "import sys; print('stdout-line'); print('stderr-line', file=sys.stderr); sys.exit(0)"
    value = request(
        "terminal.execute",
        {"argv": [sys.executable, "-c", code], "cwd": workspace},
    )
    async with bridge:
        bridge.prepare("local", value)
        result = await bridge.tasks.wait("local", value.task_id)
    assert result["state"] == "completed"
    status = bridge.live_logs.status("local")
    assert [row["source_id"] for row in status["sources"]] == [value.task_id]
    source = status["sources"][0]
    assert source["state"] == "closed" and source["exit_code"] == 0
    assert source["operation"] == "terminal.execute" and source["pid"] > 0
    entries = bridge.live_logs.read("local", value.task_id)["entries"]
    text = {entry["text"] for entry in entries}
    assert {"stdout-line", "stderr-line"} <= text
    assert any(
        entry["channel"] == "events" and "local_process_spawned" in entry["text"]
        for entry in entries
    )

    # The read operation returns the same bounded view without dispatching work.
    async def running(_evidence):
        return None

    async def progress(_evidence):
        return None

    task = {
        "id": "read-live",
        "principal": "local",
        "operation": "logs.live",
        "args": {"source_id": value.task_id, "channels": ["stdout"]},
        "state": "running",
    }
    read = await bridge.execute(task, running, progress)
    assert read["source_id"] == value.task_id
    assert {entry["channel"] for entry in read["entries"]} == {"stdout"}
    listing = await bridge.execute({**task, "args": {}}, running, progress)
    assert [row["source_id"] for row in listing["sources"]] == [value.task_id]


async def test_bridge_read_requires_the_logs_capability(bridge, config):
    config.principals["local"].capabilities.remove("logs.live")
    task = {
        "id": "read-live",
        "principal": "local",
        "operation": "logs.live",
        "args": {},
        "state": "running",
    }

    async def noop(_evidence):
        return None

    with pytest.raises(BridgeError, match="Capability"):
        await bridge.execute(task, noop, noop)
    with pytest.raises(BridgeError):
        bridge.security.principal("local", "logs.live")


async def test_status_agent_view_lists_live_sources_without_text(bridge):
    bridge.live_logs.open("task-1", "local", operation="agent.execute", agent="codex")
    bridge.live_logs.append("task-1", "local", "stdout", "secret-free line\n")
    from kirabridge.development_status import agent_status

    result = await agent_status(bridge, "local")
    assert result["live_logs"]["running"] == ["task-1"]
    assert result["live_logs"]["by_state"] == {"running": 1}
    assert "secret-free line" not in str(result["live_logs"])
    assert result["live_logs"]["read_operation"] == "logs.live"


def test_mcp_tool_is_registered_and_read_only(bridge):
    import asyncio

    from kirabridge.mcp_gateway.server import create_server

    server = create_server(bridge)
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert {"live_logs", "agent_status"} <= set(tools)
    assert tools["live_logs"].annotations.readOnlyHint is True
