"""The launchd completion sender must start from the release venv with the current config."""

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from kirabridge.event_push import EventError

SERVE = Path(__file__).parents[1] / "integrations/chat-events/serve.py"


@pytest.mark.parametrize("persistent", [False, True])
async def test_sender_recovers_after_exhausted_transient_startup_probes(
    tmp_path, monkeypatch, persistent
):
    spec = importlib.util.spec_from_file_location("chat_events_test", SERVE)
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    original_asyncio = adapter.asyncio
    calls, delays = [], []

    async def wait_backend_ready(call):
        calls.append(call)
        if len(calls) == 1:
            raise EventError("backend_startup_unavailable")

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(adapter, "wait_backend_ready", wait_backend_ready)
    monkeypatch.setattr(
        adapter,
        "asyncio",
        SimpleNamespace(
            sleep=sleep, create_task=original_asyncio.create_task, gather=original_asyncio.gather
        ),
    )
    config = tmp_path / "config.toml"
    config.write_text(
        f'data_dir = "{tmp_path / "data"}"\n'
        '[principals.chatgpt]\ntoken_env = "KB_EVENTS_TEST_TOKEN"\n'
        'capabilities = ["bridge.health", "task.read"]\n'
    )
    monkeypatch.setenv("KB_EVENTS_TEST_TOKEN", "t" * 48)
    state = tmp_path / "event-state"
    *_, lifecycle = adapter.make_sender(
        adapter.load_config(str(config)), "chatgpt", state, [], persistent=persistent
    )
    if not persistent:
        with pytest.raises(EventError, match="backend_startup_unavailable"):
            async with lifecycle(None):
                pytest.fail("embedded sender unexpectedly started")
        assert len(calls) == 1
        assert delays == []
        return

    async with lifecycle(None) as worker:
        assert not worker.done()
    assert len(calls) == 2
    assert delays == [15]
    with sqlite3.connect(state / "events.sqlite3") as db:
        observations = db.execute("SELECT kind FROM observations ORDER BY seq").fetchall()
    assert observations == [("worker_waiting",), ("worker_ready",)]


def test_sender_only_starts_with_current_config_structure(tmp_path):
    calls = []

    class Backend(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((request["params"].get("name"), self.headers["Authorization"]))
            body = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "result": {"structuredContent": {"dispatcher_active": True}},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state = tmp_path / "event-state"
    state.mkdir(mode=0o700)
    config = tmp_path / "config.toml"
    # Sections that crashed the old development-checkout sender (extra_forbidden).
    config.write_text(
        f'data_dir = "{tmp_path / "data"}"\nport = {server.server_port}\n'
        '[principals.chatgpt]\ntoken_env = "KB_EVENTS_TEST_TOKEN"\n'
        'capabilities = ["bridge.health", "task.read"]\n'
        "[threaddesk]\ndynamic_read_proxy = true\ndynamic_tool_proxy = true\n"
        f'[file_transfer]\nenabled = true\nexport_roots = ["{tmp_path}"]\n'
    )
    token = "t" * 48
    process = subprocess.Popen(
        [sys.executable, SERVE, "--config", config, "--state", state, "--sender-only"],
        env={**os.environ, "KB_EVENTS_TEST_TOKEN": token},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 20
        while ("bridge_health", "Bearer " + token) not in calls:
            assert process.poll() is None, process.stderr.read()
            assert time.monotonic() < deadline, "sender never asked backend readiness"
            time.sleep(0.05)
        time.sleep(0.5)
        assert process.poll() is None, process.stderr.read()
    finally:
        process.terminate()
        process.wait(timeout=10)
        server.shutdown()
    assert "Traceback" not in process.stderr.read()
