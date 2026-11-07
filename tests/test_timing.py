"""Opt-in latency logging: silent by default, numbers only, never task content."""

import asyncio
import logging
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kirabridge import timing
from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport


@pytest.fixture
def lines(monkeypatch):
    records = []

    class Collect(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Collect()
    timing.LOGGER.addHandler(handler)
    yield records
    timing.LOGGER.removeHandler(handler)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv(timing.ENV, "1")


def test_disabled_by_default_logs_nothing(monkeypatch, lines):
    monkeypatch.delenv(timing.ENV, raising=False)
    with timing.timed("phase"):
        pass
    assert lines == []


async def test_disabled_decorator_returns_result_unchanged(monkeypatch, lines):
    monkeypatch.delenv(timing.ENV, raising=False)

    @timing.timed_async("x")
    async def work(value):
        return value

    assert await work(7) == 7 and lines == []


def test_enabled_logs_phase_milliseconds_outcome_and_numeric_counters(on, lines):
    with timing.timed("ps_catalog") as fields:
        fields["attempts"] = 3
        fields["flag"] = True
    (line,) = lines
    assert line.startswith("timing phase=ps_catalog ms=")
    assert "outcome=ok" in line and "attempts=3" in line and "flag=1" in line


def test_strings_are_never_logged(on, lines):
    with timing.timed("p") as fields:
        fields["command"] = "rm -rf /secret/path"
        fields["count"] = 2
    (line,) = lines
    assert "secret" not in line and "command" not in line and "count=2" in line


def test_exception_is_reraised_and_named_as_outcome(on, lines):
    with pytest.raises(ValueError):
        with timing.timed("p"):
            raise ValueError("private detail")
    (line,) = lines
    assert "outcome=ValueError" in line and "private detail" not in line


async def test_cancellation_is_reported_and_propagates(on, lines):
    async def slow():
        with timing.timed("wait"):
            await asyncio.sleep(10)

    task = asyncio.create_task(slow())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert "outcome=CancelledError" in lines[0]


async def test_decorator_counts_sessions_and_mutation_flag(on, lines):
    @timing.timed_async("session_catalog")
    async def catalog(self, *, mutation=False):
        return {"sessions": [1, 2, 3], "secret": "x"}

    await catalog(None, mutation=True)
    (line,) = lines
    assert "sessions=3" in line and "mutation=1" in line and "secret" not in line


def test_enabling_overrides_a_critical_root_logger(on, monkeypatch):
    monkeypatch.setattr(timing.LOGGER, "handlers", [])
    logging.getLogger().setLevel(logging.CRITICAL)
    with timing.timed("p"):
        pass
    assert timing.LOGGER.level == logging.INFO and timing.LOGGER.propagate is False
    assert len(timing.LOGGER.handlers) == 1


async def test_native_failure_off_macos_is_timed_with_error_outcome(on, lines, monkeypatch):
    monkeypatch.setattr(
        "kirabridge.platform_adapters.terminal_app.sys", SimpleNamespace(platform="linux")
    )
    transport = TerminalAppTransport(asyncio.Lock(), desktop=object())
    with pytest.raises(BridgeError):
        await transport.native("secret script text")
    (line,) = lines
    assert "phase=terminal_native" in line and "outcome=BridgeError" in line
    assert "secret" not in line


async def test_catalog_logs_ps_and_total_phases(on, lines, monkeypatch):
    transport = TerminalAppTransport(asyncio.Lock(), desktop=object())
    monkeypatch.setattr(
        "kirabridge.platform_adapters.terminal_app.sys", SimpleNamespace(platform="darwin")
    )
    transport.native = AsyncMock(
        return_value=[{"window_id": 123, "tty": "/dev/ttys004", "busy": False}]
    )
    output = f"{os.getuid()} 345 1 ttys004 /bin/zsh\n".encode()
    child = SimpleNamespace(communicate=AsyncMock(return_value=(output, b"")), returncode=0)
    monkeypatch.setattr(
        "kirabridge.platform_adapters.terminal_app.asyncio.create_subprocess_exec",
        AsyncMock(return_value=child),
    )
    monkeypatch.setattr("kirabridge.platform_adapters.terminal_app.reap_process", AsyncMock())
    rows = await transport.catalog()
    assert len(rows) == 1
    phases = [line.split()[1] for line in lines]
    assert phases == ["phase=ps_catalog", "phase=terminal_catalog"]
    assert "sessions=1" in lines[1]
