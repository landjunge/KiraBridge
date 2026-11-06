"""A stop during failed reporting must not start additional status subprocesses."""

import asyncio
import importlib.util
import json
import signal
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_stop_during_worker_report_does_not_start_more_reports(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "loop_reporting_stop", Path(__file__).parents[1] / "scripts/bigplan_loop.py"
    )
    runtime = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, runtime)
    spec.loader.exec_module(runtime)
    loop = asyncio.get_running_loop()
    signal_handlers = {}
    monkeypatch.setattr(
        loop, "add_signal_handler", lambda sig, callback: signal_handlers.setdefault(sig, callback)
    )
    profile = {"instance": "fixture", "cwd": str(tmp_path), "workspace": str(tmp_path / "desk")}
    cfg = SimpleNamespace(state_path=tmp_path / "state", port=0, autonext=SimpleNamespace(cards=[]))
    monkeypatch.setattr(runtime, "load_profile", lambda path: profile)
    monkeypatch.setattr(runtime, "configuration", lambda value: cfg)
    workers = [
        {"id": f"work-{i}", "assignee": "codex", "state": "completed", "core_task_id": f"task-{i}"}
        for i in range(3)
    ]

    class FakeDB:
        def execute(self, query):
            if "FROM team_work" in query:
                return SimpleNamespace(fetchall=lambda: workers)
            assert "FROM autonext_items" in query
            return []

    class FakeBridge:
        def __init__(self, config):
            self.store = SimpleNamespace(db=FakeDB())
            self.autonext = SimpleNamespace(
                inspect=lambda: {"state": "disabled", "reason": "fixture"}
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class FakeSocket:
        def bind(self, address):
            pass

        def listen(self, backlog):
            pass

        def getsockname(self):
            return ("127.0.0.1", 12345)

        def close(self):
            pass

    class FakeServer:
        def __init__(self, config):
            self.started = False
            self.closed = asyncio.Event()

        @property
        def should_exit(self):
            return self.closed.is_set()

        @should_exit.setter
        def should_exit(self, value):
            if value:
                self.closed.set()

        async def serve(self, sockets):
            self.started = True
            await self.closed.wait()

    monkeypatch.setattr(runtime, "Bridge", FakeBridge)
    monkeypatch.setattr(runtime, "socket", SimpleNamespace(socket=FakeSocket))
    monkeypatch.setattr(
        runtime, "uvicorn", SimpleNamespace(Server=FakeServer, Config=lambda *a, **k: None)
    )
    monkeypatch.setattr(runtime, "create_http_app", lambda bridge: None)
    monkeypatch.setattr(runtime, "seed", lambda bridge: ("team", "anchor"))

    async def advance(*args):
        return None, None

    monkeypatch.setattr(runtime, "advance", advance)
    monkeypatch.setattr(runtime, "process_completions", lambda *args: {"pending": 0})
    reports = []

    def worker_report(profile, work):
        reports.append(work["id"])
        # Model SIGTERM while the status subprocess is still running. Its timeout
        # returns UNKNOWN, after which the controller must stop scheduling reports.
        loop.call_soon_threadsafe(signal_handlers[signal.SIGTERM])
        return {"report_id": "report-1", "state": "unknown", "error": "report_timeout"}

    def coordinator_report(*args):
        reports.append("coordinator")
        return {"state": "sent", "error": None}

    monkeypatch.setattr(runtime, "report_worker", worker_report)
    monkeypatch.setattr(runtime, "report", coordinator_report)
    await asyncio.wait_for(runtime.serve(tmp_path / "profile.json"), timeout=5)
    assert reports == ["work-0"]
    status = json.loads((cfg.state_path / "status.json").read_text())
    assert status["reporting"]["workers"]["work-0"]["state"] == "unknown"
    assert status["reporting"]["coordinator"] is None
