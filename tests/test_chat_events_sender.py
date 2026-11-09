"""The launchd completion sender must start from the release venv with the current config."""

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SERVE = Path(__file__).parents[1] / "integrations/chat-events/serve.py"


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
