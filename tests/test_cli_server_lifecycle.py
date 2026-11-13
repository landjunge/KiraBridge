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


def test_http_listener_resolves_and_prebinds_all_hostname_addresses(monkeypatch):
    addresses = [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 8765)),
        (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("::1", 8765, 0, 0)),
    ]
    created = []

    class FakeSocket:
        def __init__(self, family, type, proto):
            self.family = family
            self.options = []
            self.bound = None
            self.closed = False
            created.append(self)

        def setsockopt(self, level, option, value):
            self.options.append((level, option, value))

        def bind(self, address):
            self.bound = address

        def set_inheritable(self, value):
            self.inheritable = value

        def close(self):
            self.closed = True

    monkeypatch.setattr(cli.socket, "getaddrinfo", lambda *args, **kwargs: addresses)
    monkeypatch.setattr(cli.socket, "socket", FakeSocket)

    listeners = cli._bind_http_listeners(SimpleNamespace(host="localhost", port=8765))

    assert set(listener.family for listener in listeners) == {socket.AF_INET, socket.AF_INET6}
    assert {listener.bound for listener in listeners} == {
        ("127.0.0.1", 8765),
        ("::1", 8765, 0, 0),
    }
    assert all(listener.inheritable is True for listener in listeners)
    ipv6 = next(listener for listener in listeners if listener.family == socket.AF_INET6)
    assert (socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, True) in ipv6.options


@pytest.mark.asyncio
async def test_http_server_passes_every_prebound_address_to_uvicorn(monkeypatch):
    class FakeListener:
        closed = False

        def close(self):
            self.closed = True

    listeners = [FakeListener(), FakeListener()]
    served = {}

    class FakeBridge:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

    class FakeServer:
        def __init__(self, config):
            self.config = config

        async def serve(self, *, sockets):
            served["sockets"] = sockets

    fake_uvicorn = SimpleNamespace(Config=lambda app, **kwargs: (app, kwargs), Server=FakeServer)
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.setattr(cli, "Bridge", lambda config: FakeBridge())
    monkeypatch.setattr(cli, "_bind_http_listeners", lambda config: listeners)
    monkeypatch.setattr("kirabridge.mcp_gateway.http.create_http_app", lambda bridge: object())

    await cli._serve_http(
        SimpleNamespace(
            host="localhost",
            port=8765,
            tls_cert=None,
            tls_key=None,
            max_http_requests=16,
        ),
        "local",
    )

    assert served["sockets"] is listeners
    assert all(listener.closed for listener in listeners)


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
        + f'\nhost = "localhost"\nport = {port}\n'
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
    targets = {
        sockaddr
        for family, _, _, _, sockaddr in socket.getaddrinfo(
            "localhost",
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            flags=socket.AI_PASSIVE,
        )
        if family in {socket.AF_INET, socket.AF_INET6}
    }
    assert targets
    try:
        deadline = time.monotonic() + 10
        while True:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                pytest.fail(
                    f"server exited before readiness: {process.returncode}\n{stdout}\n{stderr}"
                )
            try:
                for target in targets:
                    with socket.create_connection(target[:2], timeout=0.1):
                        pass
                break
            except OSError:
                if time.monotonic() >= deadline:
                    pytest.fail(f"server did not accept all localhost addresses: {targets!r}")
                time.sleep(0.02)
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, f"{stdout}\n{stderr}"
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
