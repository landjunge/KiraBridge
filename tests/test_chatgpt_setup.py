import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.config import load_config
from kirabridge.bridge_core.models import BridgeError
from kirabridge.chatgpt_setup import (
    configure_tunnel,
    persist_stdio_notification,
    runtime_status,
    wait_for_service,
)
from kirabridge.local_runtime import private_json, setup


def test_invalid_tunnel_and_key_never_start_external_setup(config, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("kirabridge.chatgpt_setup.subprocess.run", lambda *a, **kw: calls.append(a))
    with pytest.raises(BridgeError):
        configure_tunnel(config, tmp_path / "config", "fake", "x" * 40, "tunnel-client")
    with pytest.raises(BridgeError):
        configure_tunnel(
            config, tmp_path / "config", "tunnel_testonly12345", "short", "tunnel-client"
        )
    assert calls == []


@pytest.mark.parametrize(
    "payload,connected",
    [
        ({"process_running": True, "healthy": True, "ready": True}, True),
        ({"process_running": True, "healthy": True}, False),
        (
            {
                "process_running": True,
                "healthy": False,
                "ready": True,
                "component": {"healthy": True},
            },
            False,
        ),
    ],
)
def test_tunnel_state_requires_all_evidence(monkeypatch, payload, connected):
    monkeypatch.setattr(
        "kirabridge.chatgpt_setup.subprocess.run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=json.dumps(payload)),
    )
    result = runtime_status("fake-client")
    assert result["connected"] is connected
    assert result["chatgpt_tool_call"] == "unverified"


def test_account_setup_keeps_literal_key_out_of_commands_and_policy(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    configured = setup(str(tmp_path / "workspace"))
    path = Path(configured["config"])
    config = load_config(str(path))
    config.principals["local"].approval_mode = "automatic"
    config.principals["local"].permission_level = "full"
    config.principals["local"].automatic_operations = ["session.input"]
    config.principals["local"].allow_any_executable = True
    config.principals["local"].terminal_roots = ["/"]
    original = private_json(Path(config.credentials_file))
    key = "test-runtime-key-" + "x" * 40
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[-1] == "status":
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {"name": "KiraBridge", "api_version": "1", "dispatcher_active": True}
                ),
            )
        if "connect" in argv:
            assert kwargs["env"]["MCP_STDIO_SEND_INITIALIZED_NOTIFICATION"] == "true"
            profile = path.parent / "tunnel/kirabridge.yaml"
            profile.parent.mkdir()
            profile.write_text(json.dumps({"mcp": {"commands": []}, "existing": "preserved"}))
            profile.chmod(0o600)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"process_running": True, "healthy": True, "ready": True}),
        )

    monkeypatch.setattr("kirabridge.chatgpt_setup.subprocess.run", run)
    result = configure_tunnel(
        config, path, "tunnel_testonly12345678", key, str(tmp_path / "fake-client")
    )
    assert result["connected"]
    assert key not in json.dumps(calls)
    assert key not in path.read_text()
    stored_key = path.parent / "openai-tunnel-runtime.key"
    assert stored_key.read_text() == key and stored_key.stat().st_mode & 0o077 == 0
    updated = load_config(str(path))
    assert "chatgpt" in updated.principals
    assert updated.principals["chatgpt"].approval_mode == "automatic"
    assert updated.principals["chatgpt"].permission_level == "full"
    assert updated.principals["chatgpt"].automatic_operations == ["session.input"]
    assert updated.principals["chatgpt"].terminal_roots == ["/"]
    assert updated.principals["chatgpt"].allow_any_executable
    import shlex

    connect_argv = next(argv for argv in calls if "--mcp-command" in argv)
    command = shlex.split(connect_argv[connect_argv.index("--mcp-command") + 1])
    assert command[command.index("--config") + 1] == str(path.absolute())
    credentials = private_json(Path(updated.credentials_file))
    assert all(credentials[name] == token for name, token in original.items())
    assert credentials["chatgpt"] not in original.values()
    probe = next(i for i, argv in enumerate(calls) if argv[-1] == "status")
    connect = next(i for i, argv in enumerate(calls) if "connect" in argv)
    assert probe < connect
    profile = path.parent / "tunnel/kirabridge.yaml"
    settings = json.loads(profile.read_text())
    assert settings["mcp"]["stdio_send_initialized_notification"] is True
    assert settings["existing"] == "preserved" and profile.stat().st_mode & 0o077 == 0


def test_notification_shim_rejects_unexpected_profile_without_clobber(tmp_path):
    path = tmp_path / "tunnel/kirabridge.yaml"
    path.parent.mkdir()
    path.write_text('{"mcp":{"server_url":"http://127.0.0.1/mcp"}}')
    path.chmod(0o600)
    before = path.read_bytes()
    with pytest.raises(BridgeError, match="Expected the generated native stdio profile"):
        persist_stdio_notification(tmp_path / "config.toml")
    assert path.read_bytes() == before


def test_restart_waits_for_authenticated_dispatcher_health(tmp_path, monkeypatch):
    responses = iter(
        [
            SimpleNamespace(returncode=1, stdout='{"error":{"code":"peer_connection"}}'),
            SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {"name": "KiraBridge", "api_version": "1", "dispatcher_active": False}
                ),
            ),
            SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {"name": "KiraBridge", "api_version": "1", "dispatcher_active": True}
                ),
            ),
        ]
    )
    calls, delays = [], []

    def run(argv, **kwargs):
        calls.append(argv)
        return next(responses)

    monkeypatch.setattr("kirabridge.chatgpt_setup.subprocess.run", run)
    monkeypatch.setattr("kirabridge.chatgpt_setup.time.sleep", delays.append)
    path = tmp_path / "config.toml"
    wait_for_service(path)
    assert len(calls) == 3 and len(delays) == 2
    assert all(
        argv[-5:] == ["--config", str(path), "--principal", "chatgpt", "status"] for argv in calls
    )


def test_unready_service_does_not_start_tunnel(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    configured = setup(str(tmp_path / "workspace"))
    path = Path(configured["config"])
    config = load_config(str(path))
    clock = [0.0]
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[-1] == "status":
            clock[0] += 10
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr("kirabridge.chatgpt_setup.subprocess.run", run)
    monkeypatch.setattr("kirabridge.chatgpt_setup.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("kirabridge.chatgpt_setup.time.sleep", lambda delay: None)
    with pytest.raises(BridgeError, match="Local service is not ready"):
        configure_tunnel(config, path, "tunnel_testonly12345678", "x" * 40, "fake-client")
    assert not any("runtimes" in argv for argv in calls)
    assert not (path.parent / "openai-tunnel-runtime.key").exists()
