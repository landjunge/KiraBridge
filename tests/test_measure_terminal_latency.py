"""The one-command latency probe: plain summary, errors reported, never crashes."""

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

from kirabridge import timing
from kirabridge.bridge_core.models import BridgeError


@pytest.fixture
def probe(monkeypatch):
    # The script switches timing on at import; restore the environment afterwards.
    monkeypatch.setenv(timing.ENV, "0")
    monkeypatch.setattr(timing.LOGGER, "handlers", list(timing.LOGGER.handlers))
    spec = importlib.util.spec_from_file_location(
        "measure_terminal_latency",
        Path(__file__).parents[1] / "scripts/measure_terminal_latency.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


class FakeTransport:
    def __init__(self, fail=None):
        self.fail = fail

    async def catalog(self):
        with timing.timed("terminal_catalog"):
            with timing.timed("terminal_native"):
                await asyncio.sleep(0)
            with timing.timed("ps_catalog"):
                pass
            if self.fail:
                raise self.fail
            return [{"pane_id": "a"}, {"pane_id": "b"}]


async def test_summary_lists_phases_and_found_sessions(probe, monkeypatch):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(probe.asyncio, "sleep", lambda _: real_sleep(0))
    collector = probe.install_collector()
    result = await probe.measure(FakeTransport(), 3, collector)
    text = probe.summary(result, 3)
    assert "Gefundene Terminal-Sitzungen: 2" in text
    assert "Fenster finden (gesamt)" in text and "Terminal.app fragen" in text
    assert "Fehler" not in text
    assert len(result["walls"]) == 3 and len(collector.rows) == 9


async def test_errors_are_reported_not_raised(probe, monkeypatch):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(probe.asyncio, "sleep", lambda _: real_sleep(0))
    collector = probe.install_collector()
    failing = FakeTransport(BridgeError("session_automation_denied", "denied"))
    result = await probe.measure(failing, 2, collector)
    text = probe.summary(result, 2)
    assert result["errors"] == ["session_automation_denied"] * 2
    assert "Fehler: 2x" in text and "session_automation_denied" in text


def test_collector_keeps_only_numbers_and_phase_names(probe):
    collector = probe.install_collector()
    timing.LOGGER.info("timing phase=ps_catalog ms=12.5 outcome=ok sessions=3")
    timing.LOGGER.info("unrelated /secret/path message")
    assert collector.rows == [("ps_catalog", 12.5, "ok")]


def test_refuses_to_run_off_macos(probe, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["measure_terminal_latency.py"])
    monkeypatch.setattr(probe.sys, "platform", "linux")
    assert probe.main() == 1
    assert "auf dem Mac" in capsys.readouterr().out
