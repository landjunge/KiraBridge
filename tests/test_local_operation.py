import asyncio
import json
import sys
from pathlib import Path

import pytest
from conftest import request
from test_mcp import http_bridge  # noqa: F401

from kirabridge.bridge_core.config import load_config
from kirabridge.bridge_core.models import BridgeError
from kirabridge.local_runtime import private_json, setup, token_for
from kirabridge.mcp_gateway.client import MCPClientPool, Peer


async def test_pending_request_requires_local_approval(bridge, config):
    value = request(arguments={"path": config.principals["local"].roots[0]})
    pending = bridge.prepare("local", value)
    assert pending["state"] == "created" and pending["receipt"] is None
    async with bridge:
        await asyncio.sleep(0.05)
        assert bridge.store.get(value.task_id)["state"] == "created"
        assert bridge.prepare("local", value)["id"] == value.task_id
        bridge.tasks.approve(value.task_id)
        assert (await bridge.tasks.wait("local", value.task_id))["state"] == "completed"
        with pytest.raises(BridgeError):
            bridge.tasks.approve(value.task_id)


async def test_cli_operator_can_deny_pending_request(bridge, config, tmp_path):
    from test_retry_cli import cli

    value = request(arguments={"path": config.principals["local"].roots[0]})
    bridge.prepare("local", value)
    path = tmp_path / "deny.toml"
    path.write_text("data_dir=" + json.dumps(config.data_dir) + "\n")
    code, output, _ = await cli("--config", str(path), "deny", value.task_id)
    assert code == 0 and json.loads(output)["state"] == "cancelled"
    assert bridge.store.get(value.task_id)["receipt"] is None


def test_pending_cannot_bypass_policy_or_quota(bridge, config):
    config.max_queued = 1
    value = request(arguments={"path": config.principals["local"].roots[0]})
    bridge.prepare("local", value)
    with pytest.raises(BridgeError, match="capacity"):
        bridge.prepare(
            "local", value.model_copy(update={"task_id": "other", "idempotency_key": "other"})
        )
    bridge.tasks.cancel_queued("local", value.task_id)
    with pytest.raises(BridgeError):
        bridge.tasks.approve(value.task_id)
    with pytest.raises(BridgeError):
        bridge.prepare("missing", value)


def test_setup_is_private_and_never_overwrites_existing_config(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = setup(str(tmp_path / "workspace"))
    config = load_config()
    assert config.host == "127.0.0.1" and not config.allow_remote
    assert set(config.principals) == {"local", "codex", "grok"}
    assert "agent.execute" not in config.principals["codex"].capabilities
    assert "file.delete" not in config.principals["local"].capabilities
    secret_path = Path(config.credentials_file)
    secrets = private_json(secret_path)
    assert len(set(secrets.values())) == 3
    assert all(len(value) >= 32 for value in secrets.values())
    assert secret_path.stat().st_mode & 0o077 == 0
    assert token_for(config, "codex") == secrets["codex"]
    with pytest.raises(BridgeError):
        setup(str(tmp_path / "different"))
    assert private_json(secret_path) == secrets
    assert result["secrets_printed"] is False


def test_insecure_or_symlinked_credentials_fail_closed(tmp_path):
    path = tmp_path / "credentials.json"
    path.write_text('{"local":"test"}')
    path.chmod(0o644)
    with pytest.raises(BridgeError):
        private_json(path)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(OSError):
        private_json(link)


async def test_stdio_proxy_reaches_existing_daemon_without_second_dispatcher(http_bridge, tmp_path):  # noqa: F811
    bridge, endpoint = http_bridge
    credentials = tmp_path / "credentials.json"
    credentials.write_text(json.dumps({"local": "local-test-" + "a" * 40}))
    credentials.chmod(0o600)
    config = tmp_path / "proxy.toml"
    config.write_text(
        "port=" + endpoint.split(":")[-1].split("/")[0] + "\n"
        "credentials_file=" + json.dumps(str(credentials)) + "\n"
        '[principals.local]\ntoken_env="PROXY_TEST_TOKEN"\n'
    )
    async with MCPClientPool() as pool:
        await pool.connect(
            Peer(
                "proxy",
                command=sys.executable,
                args=("-m", "kirabridge.cli", "--config", str(config), "connect"),
            )
        )
        health = await pool.call("proxy", "bridge_health", {})
        assert health.structuredContent["dispatcher_active"]
        tools = (await pool.sessions["proxy"].list_tools()).tools
        assert "task_request" in {tool.name for tool in tools}
        assert "approve" not in {tool.name for tool in tools}
