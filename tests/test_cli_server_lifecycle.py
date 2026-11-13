import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import kirabridge.cli as cli
from kirabridge.bridge_core.models import BridgeError


@pytest.mark.asyncio
async def test_http_listener_conflict_is_reported_before_bridge_creation(monkeypatch):
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    occupied.bind(("127.0.0.1", 0))
    occupied.listen(1)
    config = SimpleNamespace(
        host="127.0.0.1",
        port=occupied.getsockname()[1],
        tls_cert=None,
        tls_key=None,
        max_http_requests=16,
    )
    constructed = []
    monkeypatch.setattr(cli, "Bridge", lambda value: constructed.append(value))
    try:
        with pytest.raises(BridgeError) as error:
            await cli._serve_http(config, "local")
        assert error.value.code == "bind_failed"
        assert constructed == []
    finally:
        occupied.close()


def test_embedded_server_sigterm_requests_shutdown_without_reraising(monkeypatch):
    handlers = {}
    previous = object()
    raised = []

    def replace_handler(signum, handler):
        old = handlers.get(signum, previous)
        handlers[signum] = handler
        return old

    monkeypatch.setattr(cli.signal, "signal", replace_handler)
    monkeypatch.setattr(cli.signal, "raise_signal", raised.append)

    class Server(cli._BridgeSignalHandling):
        def __init__(self):
            self.should_exit = False
            self.force_exit = False

    server = Server()
    with server.capture_signals():
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        assert server.should_exit is True
        assert server.force_exit is False

    assert handlers[signal.SIGTERM] is previous
    assert raised == []


def test_embedded_server_second_sigint_forces_shutdown(monkeypatch):
    handlers = {}

    def replace_handler(signum, handler):
        old = handlers.get(signum)
        handlers[signum] = handler
        return old

    monkeypatch.setattr(cli.signal, "signal", replace_handler)

    class Server(cli._BridgeSignalHandling):
        def __init__(self):
            self.should_exit = False
            self.force_exit = False

    server = Server()
    with server.capture_signals():
        handler = handlers[signal.SIGINT]
        handler(signal.SIGINT, None)
        assert server.should_exit is True
        assert server.force_exit is False
        handler(signal.SIGINT, None)
        assert server.force_exit is True


def test_http_cli_sigterm_runs_bridge_shutdown(tmp_path):
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "data_dir = "
        + json.dumps(str(tmp_path / "state"))
        + f'\nhost = "127.0.0.1"\nport = {port}\n'
        + "[principals.local]\n"
        + 'capabilities = ["bridge.health"]\nroots = []\nexecutables = []\n'
        + 'token_env = "KIRABRIDGE_TEST_TOKEN"\n'
    )
    source_root = str(Path(__file__).parents[1] / "src")
    env = {**os.environ, "PYTHONPATH": source_root}
    env["KIRABRIDGE_TEST_TOKEN"] = "test-token-" + "t" * 40
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "kirabridge.cli",
            "--config",
            str(config_path),
            "serve",
            "--transport",
            "http",
        ],
        cwd=source_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while True:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                pytest.fail(
                    f"server exited before readiness: {process.returncode}\n{stdout}\n{stderr}"
                )
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    pytest.fail("server did not become ready")
                time.sleep(0.02)
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, f"{stdout}\n{stderr}"
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


def _close_listeners(listeners):
    for listener in listeners:
        listener.close()


def test_bind_http_listener_literal_ipv4_stays_ipv4_only():
    listeners = cli._bind_http_listener(SimpleNamespace(host="127.0.0.1", port=0))
    try:
        assert [listener.family for listener in listeners] == [socket.AF_INET]
        assert listeners[0].getsockname()[0] == "127.0.0.1"
    finally:
        _close_listeners(listeners)


def test_bind_http_listener_reserves_resolved_localhost_families():
    expected = {
        info[0]
        for info in socket.getaddrinfo("localhost", 0, type=socket.SOCK_STREAM)
        if info[0] in {socket.AF_INET, socket.AF_INET6}
    }
    assert expected
    listeners = cli._bind_http_listener(SimpleNamespace(host="localhost", port=0))
    try:
        assert {listener.family for listener in listeners} == expected
    finally:
        _close_listeners(listeners)


def test_localhost_bind_fails_when_ipv4_port_is_occupied():
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    occupied.bind(("127.0.0.1", 0))
    occupied.listen(1)
    try:
        with pytest.raises(BridgeError) as error:
            cli._bind_http_listener(
                SimpleNamespace(host="localhost", port=occupied.getsockname()[1])
            )
        assert error.value.code == "bind_failed"
    finally:
        occupied.close()


def test_bind_http_listener_literal_ipv6_loopback():
    probe = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        probe.bind(("::1", 0))
    except OSError:
        pytest.skip("IPv6 loopback is unavailable")
    finally:
        probe.close()
    listeners = cli._bind_http_listener(SimpleNamespace(host="::1", port=0))
    try:
        assert [listener.family for listener in listeners] == [socket.AF_INET6]
        assert listeners[0].getsockname()[0] == "::1"
    finally:
        _close_listeners(listeners)
