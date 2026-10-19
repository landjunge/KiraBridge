"""Operator setup preserves existing rights and supervised children terminate cleanly."""

import asyncio
import json
import os
import signal
import socket
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from kirabridge.bridge_core.config import GrokConnectorConfig, load_config
from kirabridge.bridge_core.models import BridgeError
from kirabridge.grok_connector import effective_settings, runtime, state_dir
from kirabridge.local_runtime import private_json, write_private


@pytest.fixture
def installed(tmp_path):
    path = tmp_path / "config/config.toml"
    path.parent.mkdir(mode=0o700)
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    text = (
        "data_dir=" + json.dumps(str(state)) + "\n"
        "credentials_file="
        + json.dumps(str(path.parent / "credentials.json"))
        + "\n"
        + """
[principals.local]
approval_mode="automatic"
capabilities=["bridge.health","task.read"]
token_env="KIRABRIDGE_LOCAL_TOKEN"
[principals.grok]
approval_mode="automatic"
capabilities=["bridge.health"]
token_env="KIRABRIDGE_GROK_TOKEN"
[principals.chatgpt]
approval_mode="automatic"
capabilities=["bridge.health","task.read","agent.execute","file.read","file.write","team.read","team.write","team.manage"]
agents=["grok"]
token_env="KIRABRIDGE_CHATGPT_TOKEN"
[team]
enabled=true
[team.workers.local]
[team.workers.chatgpt]
"""
    )
    path.write_text(text)
    credentials = path.parent / "credentials.json"
    data = {name: name + "-fixture-" + "x" * 40 for name in ("local", "grok", "chatgpt")}
    write_private(credentials, json.dumps(data))
    return path


def test_setup_separates_app_from_cli_and_preserves_original_rights_and_secrets(installed):
    before = load_config(str(installed))
    original = private_json(Path(before.credentials_file))
    result = runtime.prepare(
        installed, access="same-as-chatgpt", public_origin="https://gateway.example"
    )
    after = load_config(str(installed))
    credentials = private_json(Path(after.credentials_file))
    assert all(credentials[name] == token for name, token in original.items())
    assert credentials["grok_app"] not in original.values()
    assert all(after.principals[name] == policy for name, policy in before.principals.items())
    expected = before.principals["chatgpt"].model_copy(
        update={"token_env": "KIRABRIDGE_GROK_APP_TOKEN"}
    )
    assert after.principals["grok_app"] == expected
    assert after.team.workers["grok_app"].agent is None
    assert not result["voice_app_verified"] and not result["provider_voice_api_used"]
    again = runtime.prepare(
        installed, access="same-as-chatgpt", public_origin="https://gateway.example"
    )
    assert again["existing"] and credentials == private_json(Path(after.credentials_file))
    with pytest.raises(BridgeError, match="preserved"):
        runtime.prepare(installed, access="team", public_origin="https://gateway.example")


def test_default_team_profile_grants_no_direct_terminal_or_agent_execution(installed):
    runtime.prepare(installed, public_origin="https://gateway.example")
    app = load_config(str(installed)).principals["grok_app"]
    assert set(app.capabilities) == {
        "bridge.health",
        "task.read",
        "agent.inspect",
        "team.read",
        "team.write",
        "team.manage",
    }
    assert not app.roots and not app.executables and not app.agents
    assert app.team_only_execution


def test_interrupted_two_file_setup_recovers_only_its_pinned_transition(installed, monkeypatch):
    original = runtime.replace_private
    failed = False

    def interrupted(path, value):
        nonlocal failed
        if path == installed and not failed:
            failed = True
            raise OSError("controlled power loss after credentials save")
        return original(path, value)

    monkeypatch.setattr(runtime, "replace_private", interrupted)
    with pytest.raises(OSError, match="power loss"):
        runtime.prepare(installed, public_origin="https://gateway.example")
    current = load_config(str(installed))
    saved = private_json(Path(current.credentials_file))
    assert "grok_app" in saved and "grok_app" not in current.principals
    result = runtime.prepare(installed, public_origin="https://gateway.example")
    assert result["recovered"]
    assert "grok_app" in load_config(str(installed)).principals
    assert private_json(Path(current.credentials_file)) == saved


def test_interrupted_setup_does_not_overwrite_concurrent_operator_changes(installed, monkeypatch):
    original = runtime.replace_private

    def interrupted(path, value):
        if path == installed:
            raise OSError("controlled loss")
        return original(path, value)

    monkeypatch.setattr(runtime, "replace_private", interrupted)
    with pytest.raises(OSError):
        runtime.prepare(installed, public_origin="https://gateway.example")
    monkeypatch.setattr(runtime, "replace_private", original)
    changed = installed.read_text() + "\n# concurrent operator change\n"
    installed.write_text(changed)
    with pytest.raises(BridgeError, match="Changed local files preserved"):
        runtime.prepare(installed, public_origin="https://gateway.example")
    assert installed.read_text() == changed


def test_setup_refuses_active_work_without_credential_mutation(installed):
    config = load_config(str(installed))
    before = Path(config.credentials_file).read_bytes()
    database = config.state_path / "bridge.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE tasks(id TEXT,state TEXT)")
        db.execute("INSERT INTO tasks VALUES('existing','running')")
    with pytest.raises(BridgeError, match="finish"):
        runtime.prepare(installed, public_origin="https://gateway.example")
    assert Path(config.credentials_file).read_bytes() == before


@pytest.mark.parametrize(
    "origin",
    [
        "http://example.com",
        "https://user:pass@example.com",
        "https://example.com/mcp",
        "https://example.com?token=secret",
        "https://127.0.0.1",
    ],
)
def test_connector_rejects_unsafe_public_origin(origin):
    with pytest.raises(ValidationError):
        GrokConnectorConfig(public_origin=origin)


def test_connector_cannot_alias_cli_or_operator_identity():
    for name in ("grok", "local", "chatgpt", "codex"):
        with pytest.raises(ValidationError):
            GrokConnectorConfig(principal=name)


def test_supervisor_profile_cannot_change_port_or_identity(installed):
    runtime.prepare(installed, public_origin="https://initial.example")
    config = load_config(str(installed))
    config.grok_connector.enabled = True
    profile = state_dir(config) / "runtime-profile.json"
    write_private(
        profile,
        json.dumps(
            {
                "owner": runtime.OWNER,
                "port": config.grok_connector.port,
                "public_origin": "https://new.trycloudflare.com",
            }
        ),
    )
    assert effective_settings(config).public_origin == "https://new.trycloudflare.com"
    runtime.replace_private(
        profile,
        json.dumps(
            {"owner": runtime.OWNER, "port": 8766, "public_origin": "https://new.trycloudflare.com"}
        ),
    )
    with pytest.raises(BridgeError, match="profile"):
        effective_settings(config)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal/process acceptance")
async def test_supervisor_stops_own_tunnel_and_duplicate_start_creates_no_second_child(installed):
    config = load_config(str(installed))
    fake = installed.parent / "fake-cloudflared"
    fake.write_text(
        "#!"
        + sys.executable
        + "\nimport sys,time\n"
        + "print('https://fixture.trycloudflare.com',file=sys.stderr,flush=True)\n"
        + "while True: time.sleep(1)\n"
    )
    fake.chmod(0o700)
    runtime.prepare(installed, cloudflared=str(fake))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    installed.write_text(installed.read_text().replace("port = 8767", "port = " + str(port)))
    command = [
        sys.executable,
        "-m",
        "kirabridge.cli",
        "--config",
        str(installed),
        "grok-connector",
        "serve",
    ]
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    child = None
    try:
        profile = state_dir(config) / "runtime-profile.json"
        async with asyncio.timeout(15):
            while not profile.exists() or private_json(profile).get("state") != "ready":
                if process.returncode is not None:
                    _, error = await process.communicate()
                    pytest.fail(error.decode())
                await asyncio.sleep(0.05)
        record = private_json(profile)
        child = record["tunnel_pid"]
        async with httpx.AsyncClient(trust_env=False) as client:
            health = await client.get(f"http://127.0.0.1:{port}/health")
            assert health.json()["healthy"]
        duplicate = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        async with asyncio.timeout(10):
            await duplicate.communicate()
        assert duplicate.returncode != 0
        assert private_json(profile)["tunnel_pid"] == child
        process.terminate()
        async with asyncio.timeout(15):
            await process.communicate()
        assert private_json(profile)["state"] == "stopped"
        with pytest.raises(ProcessLookupError):
            os.kill(child, 0)
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()
        if child:
            try:
                os.kill(child, signal.SIGTERM)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize("loaded", [True, False])
async def test_idempotent_start_only_checks_loaded_app_access_without_signalling_services(
    installed, monkeypatch, loaded
):
    runtime.prepare(installed, public_origin="https://gateway.example")
    monkeypatch.setattr(runtime, "connector_status", lambda config: {"gateway_healthy": True})
    calls = []

    async def health(config, principal):
        calls.append(principal)
        if not loaded:
            raise BridgeError("unauthorized", "Identity not loaded by existing bridge")
        return {"name": "KiraBridge", "dispatcher_active": True}

    def forbidden(*args, **kwargs):
        pytest.fail("An idempotent connector start must not signal or restart any service")

    monkeypatch.setattr("kirabridge.local_runtime.daemon_health", health)
    monkeypatch.setattr(runtime.subprocess, "run", forbidden)
    monkeypatch.setattr(runtime.os, "kill", forbidden)
    result = await runtime.start(installed)
    assert calls == ["grok_app"]
    assert result["bridge_access_ready"] is loaded
    assert result["reload_required"] is not loaded
    assert result["local_services_reloaded"] is False


@pytest.mark.parametrize("loaded", [True, False])
async def test_new_connector_start_keeps_running_core_work_and_never_reloads_other_services(
    installed, monkeypatch, loaded
):
    runtime.prepare(installed, public_origin="https://gateway.example")
    config = load_config(str(installed))
    database = config.state_path / "bridge.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE tasks(id TEXT,state TEXT)")
        db.execute("INSERT INTO tasks VALUES('arrived-after-setup','running')")
    folder = state_dir(config)
    write_private(
        folder / "runtime-profile.json",
        json.dumps(
            {
                "owner": runtime.OWNER,
                "port": config.grok_connector.port,
                "state": "ready",
                "supervisor_pid": 12345,
                "public_origin": "https://gateway.example",
            }
        ),
    )
    launch_folder = installed.parent / "Library/LaunchAgents"
    launch_folder.mkdir(parents=True)
    monkeypatch.setattr(runtime.Path, "home", lambda: installed.parent)
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    commands, statuses = [], []

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=1 if command[1] == "print" else 0)

    def status(current):
        statuses.append(current)
        return {"gateway_healthy": len(statuses) > 1}

    def probe(pid, sig):
        assert pid == 12345 and sig == 0  # Existence probe only, never a service signal.

    async def health(current, principal):
        assert principal == "grok_app"
        return {"name": "KiraBridge", "dispatcher_active": loaded}

    monkeypatch.setattr(runtime.subprocess, "run", run)
    monkeypatch.setattr(runtime, "connector_status", status)
    monkeypatch.setattr(runtime.os, "kill", probe)
    monkeypatch.setattr("kirabridge.local_runtime.daemon_health", health)
    result = await runtime.start(installed)
    assert result["bridge_access_ready"] is loaded
    assert result["reload_required"] is not loaded
    assert result["local_services_reloaded"] is False
    assert commands and all(command[1] in {"print", "bootstrap"} for command in commands)
    assert all("com.kirabridge.bridge" not in " ".join(command) for command in commands)
    assert all("com.kirabridge.approvals" not in " ".join(command) for command in commands)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT * FROM tasks").fetchall() == [("arrived-after-setup", "running")]


@pytest.mark.parametrize("exit_code", [0, 1])
async def test_unexpected_tunnel_exit_fails_after_gateway_shutdown_without_real_services(
    installed, monkeypatch, exit_code
):
    await controlled_supervisor(installed, monkeypatch, exit_code=exit_code)


async def test_requested_supervisor_stop_remains_clean_and_stops_only_its_mock_child(
    installed, monkeypatch
):
    await controlled_supervisor(installed, monkeypatch, exit_code=None)


async def controlled_supervisor(installed, monkeypatch, *, exit_code):
    """Exercise lifecycle decisions with fake children/server, without service or network calls."""
    from kirabridge.grok_connector import gateway

    fake_binary = installed.parent / "mock-cloudflared"
    fake_binary.write_text("unused mock executable")
    fake_binary.chmod(0o700)
    runtime.prepare(installed, cloudflared=str(fake_binary))
    config = load_config(str(installed))
    done = asyncio.Event()
    servers = []

    class Stderr:
        async def readline(self):
            return b"https://controlled.trycloudflare.com\n"

        async def read(self, size):
            await done.wait()
            return b""

    class Tunnel:
        pid = 54321
        returncode = None
        terminated = 0
        stderr = Stderr()

        async def wait(self):
            await done.wait()
            return self.returncode

        def terminate(self):
            self.terminated += 1
            self.returncode = -15
            done.set()

        def kill(self):
            pytest.fail("The controlled child terminates cleanly")

    tunnel = Tunnel()

    class Server:
        def __init__(self, config):
            self.started = self.should_exit = self.stopped = False
            servers.append(self)

        async def serve(self):
            self.started = True
            while not self.should_exit:
                await asyncio.sleep(0.001)
            self.stopped = True

    async def spawn(*args, **kwargs):
        return tunnel

    monkeypatch.setattr(runtime.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(runtime.uvicorn, "Server", Server)
    monkeypatch.setattr(gateway, "create_gateway", lambda config: object())
    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", lambda *args: None)
    task = asyncio.create_task(runtime.serve(installed))
    profile = state_dir(config) / "runtime-profile.json"
    try:
        async with asyncio.timeout(2):
            while not profile.exists() or private_json(profile).get("state") != "ready":
                await asyncio.sleep(0.001)
        if exit_code is None:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert tunnel.terminated == 1
        else:
            tunnel.returncode = exit_code
            done.set()
            with pytest.raises(BridgeError) as error:
                await task
            assert error.value.code == "connector_tunnel_exited"
            assert tunnel.terminated == 0
        assert servers[0].stopped
        assert private_json(profile)["state"] == "stopped"
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
