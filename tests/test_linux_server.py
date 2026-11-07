"""Linux server service, honest limits, and preserved user data."""

import asyncio
import importlib.util
import json
import socket
import sqlite3
import sys
from pathlib import Path
from subprocess import CompletedProcess
from types import SimpleNamespace

import httpx
import pytest
import uvicorn

from kirabridge.installation import quote_systemd, render_linux_unit
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.http import AuthenticatedHTTP, create_http_app
from kirabridge.platform_adapters import LinuxAdapter


def installer_module():
    path = Path(__file__).parents[1] / "installer/install.py"
    spec = importlib.util.spec_from_file_location("linux_server_install", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_linux_runtime_accepts_normal_venv_python_link_but_refuses_linked_release(tmp_path):
    installer = installer_module()
    release = tmp_path / "release"
    venv = release / ".venv/bin"
    venv.mkdir(parents=True)
    (venv / "python").symlink_to(sys.executable)
    assert installer.python(release) == venv / "python"
    linked = tmp_path / "linked-release"
    linked.symlink_to(release, target_is_directory=True)
    with pytest.raises(RuntimeError, match="Symlink release root"):
        installer.adopt_release(SimpleNamespace(release_root=linked))


@pytest.mark.parametrize("name", ["config%test.toml", 'config$"\\test.toml'])
def test_systemd_owner_matches_escaped_argument_and_rejects_other_config(tmp_path, name):
    installer = installer_module()
    assert installer.systemd_argument(tmp_path / name) == quote_systemd(tmp_path / name)
    config = tmp_path / name
    unit = tmp_path / "test.service"
    unit.write_text(
        render_linux_unit(["python", "-m", "kirabridge.cli", "--config", str(config), "serve"])
    )
    args = SimpleNamespace(service="systemd-user", config=config, plist=unit)
    installer.validate_service_owner(args)
    args.config = tmp_path / "another.toml"
    with pytest.raises(RuntimeError, match="expected KiraBridge config"):
        installer.validate_service_owner(args)


def test_no_service_activation_records_selected_mode_for_rollback(tmp_path):
    installer = installer_module()
    prefix = tmp_path / "install"
    prefix.mkdir(mode=0o700)
    config = tmp_path / "config.toml"
    config.write_text("data_dir = " + json.dumps(str(tmp_path / "data")) + "\n")
    release = tmp_path / "release"
    release.mkdir()
    (release / "release.json").write_text(
        json.dumps(
            {
                "version": "0.8.0rc41",
                "commit": "c" * 40,
                "service": "systemd-user",
            }
        )
    )
    args = SimpleNamespace(
        prefix=prefix,
        config=config,
        launcher=tmp_path / "bin/kirabridge",
        plist=tmp_path / "test.service",
        service="none",
        full_access=False,
    )
    installer.activate(args, release)
    assert json.loads((prefix / "current.json").read_text())["service"] == "none"
    installer.rollback(args)
    assert not args.launcher.exists() and not (prefix / "current.json").exists()


def test_linux_unit_quotes_server_command_and_keeps_secrets_optional():
    config = "/srv/kira bridge/config.toml"
    body = render_linux_unit(
        ["/opt/kirabridge/.venv/bin/python", "-m", "kirabridge.cli", "--config", config, "serve"]
    )
    assert quote_systemd(config) in body
    assert 'EnvironmentFile="-/srv/kira bridge/secrets.env"\n' in body
    assert "NoNewPrivileges=true\n" in body
    assert "TimeoutStopSec=15\n" in body
    assert "WantedBy=default.target\n" in body


def test_linux_unit_environment_is_scoped_to_selected_config(tmp_path):
    config = tmp_path / 'other %$" installation/config.toml'
    body = render_linux_unit(["python", "--config", str(config), "serve"])
    expected = str(config.parent / "secrets.env").replace('"', '\\"').replace("%", "%%")
    assert 'EnvironmentFile="-' + expected + '"\n' in body
    assert "$$" not in next(
        line for line in body.splitlines() if line.startswith("EnvironmentFile=")
    )
    assert "%h/.config/kirabridge/secrets.env" not in body


def test_fresh_server_config_uses_isolated_port_and_preserves_existing(tmp_path, monkeypatch):
    installer = installer_module()
    monkeypatch.setattr(installer, "run", lambda *a, **k: b"[]")
    args = SimpleNamespace(
        config=tmp_path / "config/config.toml",
        prefix=tmp_path / "install",
        workspace=tmp_path / "workspace",
        full_access=False,
        port=18765,
    )
    installer.fresh_config(args, tmp_path / "release")
    original = args.config.read_bytes()
    assert b"port = 18765\n" in original
    credentials = args.config.parent / "credentials.json"
    credentials_before = credentials.read_bytes()
    args.port = 28765
    installer.fresh_config(args, tmp_path / "another-release")
    assert args.config.read_bytes() == original
    assert credentials.read_bytes() == credentials_before


def test_linux_server_facts_do_not_claim_desktop(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    def which(name):
        return "/usr/bin/systemctl" if name == "systemctl" else None

    monkeypatch.setattr("kirabridge.platform_adapters.shutil.which", which)
    facts = LinuxAdapter().server_facts()
    assert facts["role"] == "linux-server"
    assert facts["gui_parity"] is False
    assert facts["desktop_gui"] == "unavailable"
    assert facts["macos_terminal_app"] == "unavailable"
    assert facts["native_keyboard"] == "unavailable"
    assert facts["mcp_http"] == "available"
    assert facts["authentication"] == "bearer"
    assert facts["service_manager"] == "systemd-user"
    assert facts["clipboard"] == "unavailable"
    assert facts["clipboard_required_for_server"] is False


async def test_linux_health_and_status_report_server_limits(bridge, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(
        "kirabridge.platform_adapters.shutil.which",
        lambda name: "/usr/bin/systemctl" if name == "systemctl" else None,
    )
    health = bridge.health("local")
    assert health["server"]["gui_parity"] is False
    assert health["server"]["desktop_gui"] == "unavailable"
    bridge.macos.capability_probe.facts["platform"] = "linux"
    status = await bridge.platform_status("local")
    assert status["provider_id"] == "linux.server.systemd-user"
    assert status["operations"] == []
    assert status["interactive_desktop_observed"] is False
    assert "macOS GUI and Terminal.app" in status["unsupported_features"]


def test_systemd_start_stop_restart_and_foreign_unit(monkeypatch, tmp_path):
    installer = installer_module()
    unit = tmp_path / "kirabridge.service"
    unit.write_text("placeholder\n")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if "show" in argv:
            stdout = f"FragmentPath={unit}\nActiveState=active\n"
        else:
            stdout = ""
        return CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(installer.subprocess, "run", fake_run)
    args = SimpleNamespace(service="systemd-user", plist=unit)
    installer.stop_service(args)
    installer.start_service(args)
    installer.restart_service(args)
    assert calls[1][2:] == ["stop", "--", "kirabridge.service"]
    assert calls[2][2:] == ["daemon-reload"]
    assert calls[3][2:5] == ["enable", "--now", "--"]
    assert calls[5][2:4] == ["restart", "--"]
    calls.clear()

    def other(argv, **kwargs):
        return CompletedProcess(
            argv,
            0,
            stdout="FragmentPath=/other/kirabridge.service\nActiveState=active\n",
            stderr="",
        )

    monkeypatch.setattr(installer.subprocess, "run", other)
    with pytest.raises(RuntimeError, match="another unit"):
        installer.loaded(args)


def test_update_and_rollback_keep_config_credentials_and_unknowns(tmp_path, monkeypatch):
    installer = installer_module()
    prefix = tmp_path / "install"
    prefix.mkdir(mode=0o700)
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    database = state / "bridge.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("create table tasks (task_id text primary key, state text, detail text)")
        db.execute("insert into tasks values ('keep', 'unknown', 'user-result')")
    (state / "user-note.txt").write_text("keep-user-data\n")
    credentials = tmp_path / "credentials.json"
    credentials.write_text('{"local":"not-printed"}\n')
    config = tmp_path / "config.toml"
    config.write_text(
        "data_dir = "
        + json.dumps(str(state))
        + "\ncredentials_file = "
        + json.dumps(str(credentials))
        + "\n"
    )
    before_config = config.read_bytes()
    before_credentials = credentials.read_bytes()
    launcher = tmp_path / "bin/kirabridge"
    launcher.parent.mkdir()
    launcher.write_text(
        "#!/bin/sh\nexec /old/python -m kirabridge.cli --config " + str(config) + ' "$@"\n'
    )
    unit = tmp_path / "kirabridge.service"
    unit.write_text(
        '[Service]\nExecStart="/old/python" "-m" "kirabridge.cli" "--config" "'
        + str(config)
        + '" "serve" "--transport" "http"\n'
    )
    old_unit = unit.read_bytes()
    release = prefix / "releases/new"
    release.mkdir(parents=True)
    (release / "release.json").write_text(json.dumps({"version": "0.8.0rc40", "commit": "b" * 40}))
    args = SimpleNamespace(
        prefix=prefix,
        config=config,
        launcher=launcher,
        plist=unit,
        service="systemd-user",
        full_access=False,
    )
    monkeypatch.setattr(installer, "loaded", lambda args: True)
    monkeypatch.setattr(installer, "cli", lambda *a, **k: {"version": "0.8.0rc39", "runtime": {}})
    monkeypatch.setattr(
        installer,
        "wait_health",
        lambda *a, **k: {"version": "0.8.0rc40", "runtime": {"pid": 1}},
    )
    monkeypatch.setattr(installer, "stop_service", lambda args: None)
    monkeypatch.setattr(installer, "start_service", lambda args: None)
    monkeypatch.setattr(installer, "systemd_unit", lambda release, argv: render_linux_unit(argv))
    systemd_calls = []

    def systemctl(args, *command, **kwargs):
        systemd_calls.append(command)
        return CompletedProcess(command, 0, stdout="disabled", stderr="")

    monkeypatch.setattr(installer, "_systemctl", systemctl)
    installer.activate(args, release)
    assert "NoNewPrivileges=true" in unit.read_text()
    assert str(config) in unit.read_text()
    with sqlite3.connect(database) as db:
        db.execute("insert into tasks values ('later', 'unknown', 'after-switch')")
    installer.rollback(args)
    assert systemd_calls == [
        ("is-enabled", "--", unit.name),
        ("daemon-reload",),
        ("disable", "--", unit.name),
    ]
    assert unit.read_bytes() == old_unit
    assert config.read_bytes() == before_config
    assert credentials.read_bytes() == before_credentials
    assert (state / "user-note.txt").read_text() == "keep-user-data\n"
    with sqlite3.connect(database) as db:
        rows = {
            task_id: (state, detail)
            for task_id, state, detail in db.execute("select task_id, state, detail from tasks")
        }
    assert rows["keep"] == ("unknown", "user-result")
    assert rows["later"] == ("unknown", "after-switch")
    backup = next((prefix / "backups").glob("*/bridge.before.sqlite3"))
    with sqlite3.connect(backup) as db:
        saved = dict(db.execute("select task_id, detail from tasks"))
    assert saved == {"keep": "user-result"}


async def test_http_mcp_health_rejects_missing_and_wrong_bearer(bridge, monkeypatch):
    token = "local-server-" + "a" * 32
    monkeypatch.setenv("BRIDGE_SERVER_TOKEN", token)
    bridge.config.principals["local"].token_env = "BRIDGE_SERVER_TOKEN"
    seen = []

    async def application(scope, receive, send):
        seen.append(True)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    gate = AuthenticatedHTTP(application, bridge)

    async def call(headers):
        messages = []

        async def send(message):
            messages.append(message)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        await gate({"type": "http", "headers": headers}, receive, send)
        return messages[0]["status"]

    assert await call([]) == 401
    assert await call([(b"authorization", b"Bearer " + b"n" * 40)]) == 401
    assert await call([(b"authorization", b"Bearer " + token.encode())]) == 204
    assert seen == [True]

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(8)
    port = sock.getsockname()[1]
    bridge.config.port = port
    bridge.config.host = "127.0.0.1"
    server = uvicorn.Server(
        uvicorn.Config(create_http_app(bridge), log_level="critical", access_log=False)
    )
    endpoint = f"http://127.0.0.1:{port}/mcp"
    async with bridge:
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if task.done():
                        await task
                    await asyncio.sleep(0.01)
            async with httpx.AsyncClient() as client:
                missing = await client.get(endpoint, timeout=5)
                wrong = await client.get(
                    endpoint, headers={"Authorization": "Bearer " + "n" * 40}, timeout=5
                )
            assert missing.status_code == 401
            assert wrong.status_code == 401
            async with MCPClientPool() as pool:
                await pool.connect(Peer("daemon", url=endpoint, token=token))
                health = (await pool.call("daemon", "bridge_health", {})).structuredContent
            assert health["name"] == "KiraBridge"
            assert health["dispatcher_active"] is True
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, 10)
            sock.close()
