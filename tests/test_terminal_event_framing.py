"""Protocol event limits apply to lines, independent of pipe read boundaries."""

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kirabridge.bridge_core.models import BridgeError, TerminalInput
from kirabridge.terminal_manager import TerminalManager

EVENT_LIMIT = 1048576


class ChunkReader:
    def __init__(self, data, chunk_size=65536):
        self.data = data
        self.chunk_size = chunk_size

    async def read(self, size):
        await asyncio.sleep(0)
        result = self.data[: min(size, self.chunk_size)]
        self.data = self.data[len(result) :]
        return result


async def execute_events(monkeypatch, tmp_path, data, *, chunk_size=65536, callback=None):
    process = SimpleNamespace(
        pid=345,
        returncode=0,
        stdout=ChunkReader(data, chunk_size),
        stderr=ChunkReader(b""),
        stdin=None,
        wait=AsyncMock(return_value=0),
    )
    spawn = AsyncMock(return_value=process)
    cleanup = AsyncMock()
    monkeypatch.setattr("kirabridge.terminal_manager.spawn_process", spawn)
    monkeypatch.setattr("kirabridge.terminal_manager.reap_process", cleanup)
    manager = TerminalManager()
    lines = []

    async def receive(line):
        lines.append(line)
        if callback is not None:
            await callback(line)

    try:
        result = await manager.execute(
            "framing-owned",
            "local",
            TerminalInput(argv=[sys.executable], cwd=str(tmp_path), max_output=0, timeout=2),
            [str(tmp_path)],
            [sys.executable],
            AsyncMock(),
            line_callback=receive,
        )
        return result, lines
    finally:
        spawn.assert_awaited_once()
        cleanup.assert_awaited_once_with(process)
        assert manager.sessions == {}


@pytest.mark.parametrize("prefix", [b"{}\n", b"ready\n"])
async def test_valid_near_limit_event_and_following_event_share_chunk(
    monkeypatch, tmp_path, prefix
):
    event = b"x" * (EVENT_LIMIT - 1)
    data = prefix + event + b"\nnext\n"
    result, lines = await execute_events(monkeypatch, tmp_path, data)
    assert lines == [prefix[:-1].decode(), event.decode(), "next"]
    assert result["output_bytes"] == len(data)
    assert result["truncated"] is True
    assert result["timed_out"] is False


@pytest.mark.parametrize("newline", [b"", b"\n"])
async def test_event_content_at_byte_limit_is_accepted(monkeypatch, tmp_path, newline):
    event = b"x" * EVENT_LIMIT
    _, lines = await execute_events(monkeypatch, tmp_path, event + newline)
    assert len(lines) == 1 and len(lines[0]) == EVENT_LIMIT


@pytest.mark.parametrize("newline", [b"", b"\n"])
async def test_oversized_single_event_is_still_rejected(monkeypatch, tmp_path, newline):
    with pytest.raises(BridgeError) as error:
        await execute_events(monkeypatch, tmp_path, b"x" * (EVENT_LIMIT + 1) + newline)
    assert error.value.code == "agent_protocol"


async def test_many_short_lines_and_split_utf8_are_delivered_exactly(monkeypatch, tmp_path):
    data = ("äöü\n" * 20000 + "end").encode()
    result, lines = await execute_events(monkeypatch, tmp_path, data, chunk_size=1025)
    assert lines == ["äöü"] * 20000 + ["end"]
    assert result["output_bytes"] == len(data)


async def test_callback_failure_is_not_swallowed_or_replayed(monkeypatch, tmp_path):
    callback = AsyncMock(side_effect=BridgeError("agent_protocol", "invalid event"))
    with pytest.raises(BridgeError) as error:
        await execute_events(monkeypatch, tmp_path, b"first\nsecond\n", callback=callback)
    assert error.value.code == "agent_protocol"
    callback.assert_awaited_once_with("first")
