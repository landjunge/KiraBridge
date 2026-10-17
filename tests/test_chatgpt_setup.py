import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.config import load_config
from kirabridge.bridge_core.models import BridgeError
from kirabridge.chatgpt_setup import configure_tunnel, runtime_status
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
    original = private_json(Path(config.credentials_file))
    key = "test-runtime-key-" + "x" * 40
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"process_running": True, "healthy": True, "ready": True}),
        )

    monkeypatch.setattr("kirabridge.chatgpt_setup.subprocess.run", run)
    result = configure_tunnel(config, path, "tunnel_testonly12345678", key, "fake-client")
    assert result["connected"]
    assert key not in json.dumps(calls)
    assert key not in path.read_text()
    stored_key = path.parent / "openai-tunnel-runtime.key"
    assert stored_key.read_text() == key and stored_key.stat().st_mode & 0o077 == 0
    updated = load_config(str(path))
    assert "chatgpt" in updated.principals
    credentials = private_json(Path(updated.credentials_file))
    assert all(credentials[name] == token for name, token in original.items())
    assert credentials["chatgpt"] not in original.values()
