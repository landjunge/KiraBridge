"""Preview policy, private-token lifecycle and transport routing; native guest is separate."""

import json
import sys
from types import SimpleNamespace

import pytest

from kirabridge import windows_preview as preview
from kirabridge.bridge_core.models import BridgeError


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    monkeypatch.setattr(preview, "require_windows", lambda: None)
    monkeypatch.setattr(preview, "require_desktop", lambda: None)
    monkeypatch.setattr(preview, "private_directory", lambda path: path.mkdir(exist_ok=True))
    monkeypatch.setattr(preview, "private_json", lambda path: json.loads(path.read_text()))

    def write(path, text):
        with path.open("x") as output:
            output.write(text)

    monkeypatch.setattr(preview, "write_private", write)
    return preview.prepare(tmp_path, port=18865)


def test_nonwindows_run_refused_before_any_state_or_native_desktop_work(monkeypatch, tmp_path):
    monkeypatch.setattr(preview, "sys", SimpleNamespace(platform="darwin", stderr=sys.stderr))
    monkeypatch.setattr(preview, "require_desktop", lambda: pytest.fail("No native probe on Mac"))
    destination = tmp_path / "must-not-exist"
    assert preview.main(["--state-dir", str(destination)]) == 1
    assert not destination.exists()


def test_minimal_policy_and_loopback_only_config(prepared):
    config = prepared.config
    assert config.host == "127.0.0.1" and not config.allow_remote and config.port == 18865
    assert set(config.principals) == {"local"}
    policy = config.principals["local"]
    assert tuple(policy.capabilities) == preview.CAPABILITIES
    assert policy.approval_mode == "automatic" and policy.permission_level is None
    assert not policy.allow_any_executable
    assert policy.roots == policy.read_roots == policy.executables == policy.agents == []
    assert not config.agents and not config.team.enabled and not config.file_transfer.enabled
    assert not config.threaddesk.enabled and not config.messaging.receivers


def test_token_is_private_persisted_and_never_in_public_output(prepared, capsys):
    again = preview.prepare(prepared.credential_path.parent, port=18865)
    assert again.token == prepared.token
    public = json.dumps(again.public("http"))
    assert prepared.token not in public and prepared.token not in repr(prepared)
    assert json.loads(public)["credential_file"] == str(prepared.credential_path)
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"schema": "wrong", "local": "x" * 64},
        {"schema": preview.CREDENTIAL_SCHEMA, "local": "x\r\n" * 30},
        {"schema": preview.CREDENTIAL_SCHEMA, "local": "x" * 64, "other": 1},
    ],
)
def test_existing_bad_credential_payload_is_not_rotated_or_overwritten(prepared, value):
    raw = json.dumps(value)
    prepared.credential_path.write_text(raw)
    with pytest.raises(BridgeError) as caught:
        preview.prepare(prepared.credential_path.parent)
    assert caught.value.code == "preview_credentials_invalid"
    assert prepared.credential_path.read_text() == raw


def test_malformed_existing_credentials_are_preserved(prepared):
    prepared.credential_path.write_text("{broken")
    with pytest.raises(BridgeError) as caught:
        preview.prepare(prepared.credential_path.parent)
    assert caught.value.code == "preview_credentials_invalid"
    assert prepared.credential_path.read_text() == "{broken"


@pytest.mark.parametrize("transport", ["http", "stdio"])
async def test_transport_uses_existing_server_with_env_scoped_to_owned_bridge(
    monkeypatch, prepared, capsys, transport
):
    events = []
    monkeypatch.setenv(preview.TOKEN_ENV, "previous-process-setting")

    class Bridge:
        def __init__(self, config):
            self.config = config
            self.store = SimpleNamespace(close=lambda: events.append("store-close"))
            assert preview.os.environ[preview.TOKEN_ENV] == prepared.token

        async def __aenter__(self):
            events.append("bridge-start")
            return self

        async def __aexit__(self, *args):
            events.append("bridge-stop")

    class Server:
        async def run_stdio_async(self):
            events.append("stdio")

        async def serve(self, *, sockets):
            assert sockets == [handle]
            events.append("http")

    handle = SimpleNamespace(close=lambda: events.append("socket-close"))
    monkeypatch.setattr(preview, "build_bridge", Bridge)
    monkeypatch.setattr(
        preview, "listener", lambda port: handle if port == 18865 else pytest.fail()
    )
    monkeypatch.setattr(preview, "http_server", lambda bridge: Server())
    monkeypatch.setattr(preview, "stdio_server", lambda bridge: Server())
    await preview.serve(prepared, transport)
    assert events[0:2] == ["bridge-start", transport]
    assert "bridge-stop" in events and "store-close" in events
    assert ("socket-close" in events) is (transport == "http")
    assert preview.os.environ[preview.TOKEN_ENV] == "previous-process-setting"
    captured = capsys.readouterr()
    assert captured.out == "" and prepared.token not in captured.err
    assert json.loads(captured.err)["transport"] == transport


def test_help_is_available_without_windows_or_state_creation(capsys):
    with pytest.raises(SystemExit) as caught:
        preview.main(["--help"])
    assert caught.value.code == 0
    assert "--transport" in capsys.readouterr().out


async def test_failed_bridge_start_restores_authentication_environment(monkeypatch, prepared):
    monkeypatch.delenv(preview.TOKEN_ENV, raising=False)
    closed = []

    class BrokenBridge:
        def __init__(self, config):
            self.store = SimpleNamespace(close=lambda: closed.append(True))

        async def __aenter__(self):
            raise BridgeError("already_running", "Original dispatcher preserved")

        async def __aexit__(self, *args):
            pytest.fail("Failed __aenter__ must not invoke __aexit__")

    monkeypatch.setattr(preview, "build_bridge", BrokenBridge)
    with pytest.raises(BridgeError) as caught:
        await preview.serve(prepared, "stdio")
    assert caught.value.code == "already_running"
    assert preview.TOKEN_ENV not in preview.os.environ and closed == [True]


def test_listener_always_binds_ipv4_loopback_without_network_side_effect(monkeypatch):
    observed = []
    handle = SimpleNamespace(
        setsockopt=lambda *args: None,
        bind=lambda address: observed.append(address),
        listen=lambda backlog: None,
        setblocking=lambda value: None,
        close=lambda: None,
    )
    monkeypatch.setattr(preview.socket, "socket", lambda *args: handle)
    assert preview.listener(18865) is handle
    assert observed == [("127.0.0.1", 18865)]
