"""Explicitly isolated Live instance: private state, own port, no production path."""

import asyncio
import json
import os
import stat
import time
from pathlib import Path

import httpx
import pytest

from kirabridge.approval_console import ApprovalConsole
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import load_config
from kirabridge.bridge_core.models import BridgeError
from kirabridge.isolated_live import (
    PRODUCTION_CONSOLE_PORT,
    IsolatedDaemon,
    isolated_config_path,
    login_page,
    prepare,
    serve_isolated,
)
from kirabridge.live_status import project
from kirabridge.operator_application import operator_application


@pytest.fixture
def home(tmp_path, monkeypatch):
    fake = tmp_path / "home"
    (fake / ".config/kirabridge").mkdir(parents=True)
    (fake / ".local/share/kirabridge").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake))
    return fake


def test_refuses_the_production_config_and_state(home):
    production = home / ".config/kirabridge/config.toml"
    with pytest.raises(BridgeError, match="production config or state|must end in config.toml"):
        isolated_config_path(production)
    with pytest.raises(BridgeError, match="production config or state"):
        isolated_config_path(home / ".local/share/kirabridge/instance/config.toml")
    with pytest.raises(BridgeError, match="absolute"):
        isolated_config_path("relative/config.toml")
    with pytest.raises(BridgeError, match="config.toml"):
        isolated_config_path("/private/instance/other.toml")


def test_creates_private_state_and_fresh_credentials(home, tmp_path):
    production_credentials = home / ".config/kirabridge/credentials.json"
    production_credentials.write_text(json.dumps({"local": "PROD-KEY-" + "a" * 40}))
    production_credentials.chmod(0o600)
    before = production_credentials.read_bytes()

    config, directory, path, key = prepare(tmp_path / "instance/config.toml")
    assert directory.stat().st_mode & 0o077 == 0
    assert config.credentials_file == str(directory / "credentials.json")
    isolated = json.loads((directory / "credentials.json").read_text())["local"]
    assert isolated != json.loads(before)["local"]
    assert production_credentials.read_bytes() == before
    assert len(key) >= 32
    assert (directory / "console-credentials.json").stat().st_mode & 0o077 == 0
    assert path == (tmp_path / "instance/config.toml").resolve()
    assert config.data_dir == str(directory / "data")
    assert "logs.live" in config.principals["local"].capabilities
    assert PRODUCTION_CONSOLE_PORT != 9


def test_rejects_a_config_that_points_at_foreign_state(tmp_path):
    config = tmp_path / "instance/config.toml"
    prepare(config)
    config.write_text(
        'data_dir = "/tmp/elsewhere"\n'
        f'credentials_file = "{tmp_path / "instance/credentials.json"}"\n'
        '[principals.local]\ncapabilities = ["logs.live"]\n'
    )
    with pytest.raises(BridgeError, match="own data"):
        prepare(config)


def test_isolated_daemon_serves_only_the_live_projection(tmp_path):
    config, _directory, _path, _key = prepare(tmp_path / "instance/config.toml")
    bridge = Bridge(config)
    try:
        daemon = IsolatedDaemon(bridge)
        bridge.live_logs.open("t1", "local", operation="agent.execute", agent="codex")
        projected = asyncio.run(daemon.call("live_status"))
        assert projected["agents"][0]["task_id"] == "t1"
        direct = project(bridge, "local")
        stable = (
            "task_id",
            "principal",
            "family",
            "state",
            "step",
            "failure",
            "uncertain",
            "acceptance",
        )
        assert [{k: a[k] for k in stable} for a in projected["agents"]] == [
            {k: a[k] for k in stable} for a in direct["agents"]
        ]
        assert projected["coverage"] == direct["coverage"]
        with pytest.raises(BridgeError, match="only serves live_status"):
            asyncio.run(daemon.call("status"))
        bridge.config.principals["local"].capabilities.remove("logs.live")
        with pytest.raises(BridgeError, match="Capability"):
            asyncio.run(daemon.call("live_status"))
    finally:
        bridge.store.close()


def test_console_origin_is_bound_to_exactly_one_loopback_port(tmp_path):
    config, _directory, _path, key = prepare(tmp_path / "instance/config.toml")
    bridge = Bridge(config)
    try:
        application = operator_application(bridge)
        console = ApprovalConsole(application, key, origin="http://127.0.0.1:54321")
        assert console.origin == "http://127.0.0.1:54321"
        assert console.expected_host == b"127.0.0.1:54321"
        for origin in (
            "https://127.0.0.1:54321",
            "http://192.168.1.5:54321",
            "http://localhost:54321",
            "http://127.0.0.1",
            "http://127.0.0.1:54321/other",
            "http://user:pass@127.0.0.1:54321",
        ):
            with pytest.raises(BridgeError, match="explicit loopback origin"):
                console.set_origin(origin)
        assert console.origin == "http://127.0.0.1:54321"
    finally:
        bridge.store.close()


def test_production_console_port_is_refused(tmp_path):
    with pytest.raises(BridgeError, match="production console port"):
        asyncio.run(serve_isolated(tmp_path / "instance/config.toml", port=PRODUCTION_CONSOLE_PORT))


def test_login_page_targets_the_isolated_origin_only():
    page = login_page("k" * 32, "http://127.0.0.1:54321", "instance")
    assert 'action="http://127.0.0.1:54321/login"' in page
    assert "8766" not in page
    assert "ticket" in page


async def test_console_serves_live_on_its_own_origin(tmp_path, capsys):
    config = tmp_path / "instance/config.toml"
    task = asyncio.create_task(serve_isolated(config))
    login = tmp_path / "instance/approval-login.html"
    deadline = time.monotonic() + 20
    while not login.exists():
        assert not task.done(), task.exception() if task.done() else ""
        assert time.monotonic() < deadline
        await asyncio.sleep(0.05)
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    receipt = json.loads(lines[-1])
    origin = receipt["origin"]
    port = int(origin.rsplit(":", 1)[1])
    assert receipt["isolated"] is True
    assert port != PRODUCTION_CONSOLE_PORT
    assert Path(receipt["login_file"]) == login
    assert time.time() >= 0
    assert not origin.startswith("https")
    try:
        async with httpx.AsyncClient(base_url=origin, timeout=5) as client:
            page = await client.get("/live")
            assert page.status_code == 200 and "KiraBridge Live" in page.text
            denied = await client.get("/api/control/live")
            assert denied.status_code == 401
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
            foreign = await client.get("/live", headers={"host": "127.0.0.1:8766"})
            assert foreign.status_code == 403
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_isolated_state_is_not_the_production_state(home, tmp_path):
    config, directory, _path, _key = prepare(tmp_path / "instance/config.toml")
    assert not str(directory).startswith(str(home))
    assert load_config(str(directory / "config.toml")).data_dir == str(directory / "data")
    assert os.stat(directory).st_mode & stat.S_IRWXG == 0
