"""Explicitly isolated Live instance: private state, own port, no production path."""

import asyncio
import json
import os
import stat
import time
from pathlib import Path

import httpx
import pytest

from kirabridge.approval_console import ApprovalConsole, signed_token
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import load_config
from kirabridge.bridge_core.models import BridgeError
from kirabridge.isolated_live import (
    PRODUCTION_CONSOLE_PORT,
    IsolatedApplication,
    isolated_config_path,
    live_console,
    login_page,
    prepare,
    serve_isolated,
)

ORIGIN = "http://127.0.0.1:54321"


@pytest.fixture
def home(tmp_path, monkeypatch):
    fake = tmp_path / "home"
    (fake / ".config/kirabridge").mkdir(parents=True)
    (fake / ".local/share/kirabridge").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake))
    return fake


def _session(key):
    return {"authorization": "Bearer " + signed_token(key, "session")}


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


def test_canonical_alias_directory_yields_a_canonical_receipt(tmp_path):
    real = tmp_path / "real-instance"
    real.mkdir(mode=0o700)
    real.chmod(0o700)
    alias = tmp_path / "alias-instance"
    alias.symlink_to(real, target_is_directory=True)
    config, directory, path, _key = prepare(alias / "config.toml")
    assert directory == real.resolve()
    assert path == (real / "config.toml").resolve()
    login = (directory / "approval-login.html").resolve()
    assert login.parent == directory.resolve()


def test_console_origin_is_bound_to_exactly_one_loopback_port(tmp_path):
    config, _directory, _path, key = prepare(tmp_path / "instance/config.toml")
    bridge = Bridge(config)
    try:
        console = ApprovalConsole(IsolatedApplication(bridge), key, origin=ORIGIN, live_only=True)
        assert console.origin == ORIGIN
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
        assert console.origin == ORIGIN
    finally:
        bridge.store.close()


@pytest.mark.parametrize("port", [8765, 8766, 8767])
def test_production_ports_are_refused(tmp_path, port):
    with pytest.raises(BridgeError, match="production ports|production console port"):
        asyncio.run(serve_isolated(tmp_path / "instance/config.toml", port=port))


def test_login_page_targets_the_isolated_origin_only():
    page = login_page("k" * 32, ORIGIN, "instance")
    assert f'action="{ORIGIN}/login"' in page
    assert "8766" not in page
    assert "ticket" in page


def test_live_only_console_route_table_has_no_mutation_surface(tmp_path):
    console, bridge, _key, _directory, _path = live_console(
        tmp_path / "instance/config.toml", origin=ORIGIN
    )
    try:
        paths = {route.path for route in console.app.routes}
        assert paths == {
            "/health",
            "/login",
            "/",
            "/live",
            "/login.js",
            "/networkpunkt.css",
            "/live.js",
            "/live.css",
            "/api/control/live",
        }
    finally:
        bridge.store.close()


async def test_own_session_reads_live_and_a_foreign_key_is_rejected(tmp_path):
    console, bridge, key, _directory, _path = live_console(
        tmp_path / "instance/config.toml", origin=ORIGIN
    )
    try:
        bridge.live_logs.open("t1", "local", operation="agent.execute", agent="codex")
        transport = httpx.ASGITransport(app=console)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as client:
            assert (await client.get("/api/control/live")).status_code == 401
            foreign = await client.get("/api/control/live", headers=_session("x" * 48))
            assert foreign.status_code == 401
            own = await client.get("/api/control/live", headers=_session(key))
            assert own.status_code == 200
            assert own.json()["agents"][0]["task_id"] == "t1"
            assert own.json()["agents"][0]["uncertain"] is False
            page = await client.get("/live")
            assert page.status_code == 200 and "KiraBridge Live" in page.text
            root = await client.get("/")
            assert root.status_code == 200 and "KiraBridge Live" in root.text
    finally:
        bridge.store.close()


async def test_capability_removal_denies_live_with_503(tmp_path):
    console, bridge, key, _directory, _path = live_console(
        tmp_path / "instance/config.toml", origin=ORIGIN
    )
    try:
        bridge.config.principals["local"].capabilities.remove("logs.live")
        transport = httpx.ASGITransport(app=console)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as client:
            denied = await client.get("/api/control/live", headers=_session(key))
            assert denied.status_code == 503
            assert denied.json()["ok"] is False
            assert denied.json()["error"]["code"] == "forbidden"
    finally:
        bridge.store.close()


async def test_no_action_endpoint_is_reachable_and_spies_see_zero_effects(tmp_path, monkeypatch):
    console, bridge, key, _directory, _path = live_console(
        tmp_path / "instance/config.toml", origin=ORIGIN
    )
    calls: list[str] = []

    def spy(name):
        def record(*_args, **_kwargs):
            calls.append(name)
            raise AssertionError(name)

        return record

    for target in (
        "kirabridge.operator_actions.ControlActions.execute",
        "kirabridge.operator_actions.ControlActionRepository.reserve",
        "kirabridge.operator_platform.LocalProcessPlatform.command",
        "subprocess.run",
        "asyncio.create_subprocess_exec",
    ):
        monkeypatch.setattr(target, spy(target.rsplit(".", 1)[-1]))
    try:
        transport = httpx.ASGITransport(app=console)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as client:
            session = _session(key)
            attempts = [
                (
                    "post",
                    "/api/control/action",
                    {"action_id": "synthetic", "service": "console", "action": "restart"},
                ),
                ("post", "/api/control/permissions", {}),
                ("post", "/api/control/doctor", {}),
                ("post", "/api/control/terminal/input", {}),
                ("post", "/api/tasks/t/approve", {}),
                ("get", "/protocol", None),
            ]
            for method, path, payload in attempts:
                headers = session | {"origin": ORIGIN}
                if method == "post":
                    response = await client.post(path, headers=headers, json=payload)
                else:
                    response = await client.get(path, headers=headers)
                assert response.status_code == 404, (method, path, response.status_code)
            assert calls == []
    finally:
        bridge.store.close()


async def test_foreign_origin_post_is_rejected_as_csrf(tmp_path):
    console, bridge, _key, _directory, _path = live_console(
        tmp_path / "instance/config.toml", origin=ORIGIN
    )
    try:
        transport = httpx.ASGITransport(app=console)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as client:
            response = await client.post(
                "/login",
                headers={"origin": "http://127.0.0.1:8766"},
                content="ticket=invalid",
            )
            assert response.status_code == 403
            assert response.json()["error"] == "csrf"
    finally:
        bridge.store.close()


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
    try:
        async with httpx.AsyncClient(base_url=origin, timeout=5) as client:
            page = await client.get("/live")
            assert page.status_code == 200 and "KiraBridge Live" in page.text
            denied = await client.get("/api/control/live")
            assert denied.status_code == 401
            absent = await client.post("/api/control/action", json={})
            assert absent.status_code == 404
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
