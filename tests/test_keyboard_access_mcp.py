"""Existing full grants and direct typed MCP input, without native keyboard effects."""

import asyncio
import hashlib

import pytest
from test_mcp import http_bridge  # noqa: F401 -- real authenticated HTTP fixture

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import PrincipalConfig, load_config
from kirabridge.bridge_core.models import BridgeError, TaskRequest
from kirabridge.discovery import snapshot
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.permissions import decision

KEYBOARD_CAPABILITIES = {
    "keyboard.inspect",
    "keyboard.shortcuts.read",
    "keyboard.execute",
    "keyboard.profiles.read",
    "keyboard.profiles.manage",
    "apps.list",
    "app.focus",
}
KEYBOARD_OPERATIONS = {
    "keyboard.system_inventory",
    "keyboard.system_key",
    "keyboard.inspect",
    "keyboard.shortcuts.discover",
    "keyboard.key",
    "keyboard.chord",
    "keyboard.text",
    "keyboard.control",
    "keyboard.sequence",
    "keyboard.action",
    "keyboard.profiles.list",
    "keyboard.profiles.get",
    "keyboard.profiles.put",
    "keyboard.profiles.delete",
    "keyboard.profiles.resolve",
}


def old_full_config(tmp_path, *, name="chatgpt", token_env=None):
    import json

    path = tmp_path / "old-full.toml"
    path.write_text(
        f"data_dir={json.dumps(str(tmp_path / 'state'))}\n"
        f"[principals.{name}]\n"
        'permission_level="full"\napproval_mode="automatic"\n'
        'allow_any_executable=true\nroots=["/"]\n'
        'capabilities=["bridge.health","task.read","bridge.health"]\n'
        + (f"token_env={json.dumps(token_env)}\n" if token_env else "")
    )
    return path


def test_old_full_grant_authorizes_keyboard_without_persisting_or_creating_profiles(tmp_path):
    path = old_full_config(tmp_path)
    original = path.read_bytes()
    config = load_config(str(path))
    expected = KEYBOARD_CAPABILITIES | {"bridge.health", "task.read"}
    assert config.principals["chatgpt"].capabilities == sorted(expected)
    assert path.read_bytes() == original
    assert config._source_sha256 == hashlib.sha256(original).hexdigest()
    bridge = Bridge(config)
    try:
        policy = config.principals["chatgpt"]
        for operation in KEYBOARD_OPERATIONS:
            assert bridge.security.principal("chatgpt", operation) is policy
            verdict = decision(config, "chatgpt", operation)
            assert verdict["authorized"] and verdict["automatic"]
            assert not verdict["approval_required"]
        discovery = snapshot(bridge, "chatgpt")
        assert discovery["capabilities"] == sorted(expected)
        assert discovery["keyboard"]["permission"] == decision(
            config, "chatgpt", "keyboard.control"
        )
        assert discovery["keyboard"]["profile_required"] is False
        assert discovery["keyboard"]["event_subscription_required"] is False
        assert not (config.state_path / "keyboard").exists()
        assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    finally:
        bridge.store.close()
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "level,allow_any,roots",
    [
        ("medium", True, ["/"]),
        ("ask", True, ["/"]),
        (None, True, ["/"]),
        ("full", False, ["/"]),
        ("full", True, ["/limited"]),
    ],
)
def test_keyboard_extension_does_not_upgrade_other_policies(
    config, bridge, level, allow_any, roots
):
    policy = PrincipalConfig(
        permission_level=level,
        approval_mode="automatic",
        allow_any_executable=allow_any,
        roots=roots,
        capabilities=["bridge.health", "task.read"],
    )
    config.principals["local"] = policy
    assert policy.capabilities == ["bridge.health", "task.read"]
    for operation in KEYBOARD_OPERATIONS:
        assert not decision(config, "local", operation)["authorized"]
        with pytest.raises(BridgeError, match="Capability not granted"):
            bridge.security.principal("local", operation)
    assert snapshot(bridge, "local")["keyboard"]["permission"]["authorized"] is False


@pytest.mark.parametrize("missing", ["keyboard.inspect", "apps.list", "app.focus"])
def test_keyboard_control_declares_its_target_resolution_dependencies(bridge, config, missing):
    config.principals["local"] = PrincipalConfig(
        capabilities=sorted(KEYBOARD_CAPABILITIES - {missing})
    )
    verdict = decision(config, "local", "keyboard.control")
    assert verdict["missing_capabilities"] == [missing]
    assert not verdict["authorized"]
    with pytest.raises(BridgeError, match="Capability not granted: " + missing):
        bridge.prepare(
            "local",
            TaskRequest(
                task_id="keyboard-missing-dependency",
                idempotency_key="keyboard-missing-dependency",
                operation="keyboard.control",
                arguments={"text": "never posted"},
            ),
        )
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


async def test_direct_keyboard_mcp_uses_old_full_grant_and_exactly_once_task_route(
    http_bridge,  # noqa: F811 -- imported real HTTP fixture
    config,
    monkeypatch,
    tmp_path,
):
    bridge, endpoint = http_bridge
    path = old_full_config(tmp_path, name="local", token_env="BRIDGE_TEST_TOKEN")
    original = path.read_bytes()
    config.principals["local"] = load_config(str(path)).principals["local"]
    bridge.macos.capability_probe.facts.update(platform="darwin", os_version="15.7.4")
    bridge.macos.capability_probe.native_metadata = lambda: {
        "available": True,
        "keyboard_protocol": 1,
    }
    calls = []

    async def isolated_execute(task, running, progress):
        calls.append(task)
        assert task["operation"] == "keyboard.control"
        assert task["principal"] == "local"
        await running({"native_input_attempted": False})
        return {"post_calls_returned": 2, "app_processing_confirmed": False}

    monkeypatch.setattr(bridge.tasks, "executor", isolated_execute)
    monkeypatch.setattr(bridge.tasks, "preflight", None)
    value = {
        "request": {"app": "Example Editor", "text": "Äpfel\n日本語", "submit": False},
        "task_id": "keyboard-direct-http",
        "idempotency_key": "keyboard-direct-http",
        "completion_target": "keyboard-http-test",
    }
    async with MCPClientPool() as clients:
        await clients.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        tools = {tool.name: tool for tool in await clients.list_tools("local")}
        tool = tools["keyboard_control"]
        assert set(tool.inputSchema["required"]) == {"request", "task_id", "idempotency_key"}
        assert "completion_target" in tool.inputSchema["properties"]
        assert "completion_subscription" not in tool.inputSchema["properties"]
        assert "profile_id" not in tool.inputSchema["$defs"]["KeyboardControlInput"]["properties"]
        catalog = (await clients.call("local", "operation_catalog", {})).structuredContent
        assert set(catalog["operations"]) == KEYBOARD_OPERATIONS | {
            "platform.status",
            "apps.list",
            "app.focus",
        }
        assert catalog["discovery"]["principal"] == "local"
        assert catalog["discovery"]["keyboard"]["permission"]["automatic"] is True
        for operation in KEYBOARD_OPERATIONS:
            assert catalog["operations"][operation]["approval_required"] is False
        accepted = (await clients.call("local", "keyboard_control", value)).structuredContent
        assert accepted["id"] == value["task_id"] and not accepted["approval_required"]
        assert accepted["state"] == "completed"
        assert accepted["result"]["post_calls_returned"] == 2
        assert accepted["completion_channel"]["target"] == "keyboard-http-test"
        completed = await bridge.tasks.wait("local", value["task_id"], timeout=3)
        assert completed["state"] == "completed", completed
        assert completed["args"]["text"] == "Äpfel\n日本語"
        assert completed["args"]["app"] == "Example Editor"
        assert completed["args"]["submit"] is False
        duplicate = (await clients.call("local", "keyboard_control", value)).structuredContent
        assert duplicate["id"] == value["task_id"]
    assert len(calls) == 1
    assert path.read_bytes() == original
    assert not (config.state_path / "keyboard").exists()


async def test_keyboard_inline_timeout_preserves_one_running_task_without_cancel_or_replay(
    http_bridge,  # noqa: F811 -- imported real HTTP fixture
    config,
    monkeypatch,
):
    from kirabridge.mcp_gateway.server import inline_task_timeout

    assert inline_task_timeout("keyboard.control") == 13
    monkeypatch.setattr(
        "kirabridge.mcp_gateway.server.inline_task_timeout", lambda _operation: 0.03
    )
    bridge, endpoint = http_bridge
    policy = config.principals["local"]
    policy.approval_mode = "automatic"
    policy.capabilities += sorted(KEYBOARD_CAPABILITIES)
    entered, release = asyncio.Event(), asyncio.Event()
    calls, cancelled = [], []

    async def executor(task, running, progress):
        calls.append(task["id"])
        await running({"native_input_attempted": False})
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.append(task["id"])
            raise
        return {"post_calls_returned": 2, "app_processing_confirmed": False}

    monkeypatch.setattr(bridge.tasks, "executor", executor)
    monkeypatch.setattr(bridge.tasks, "preflight", None)
    value = {
        "request": {"app": "Owned Test Editor", "text": "one write"},
        "task_id": "keyboard-inline-timeout",
        "idempotency_key": "keyboard-inline-timeout",
    }
    try:
        async with MCPClientPool() as pool:
            await pool.connect(Peer("caller", url=endpoint, token="local-test-" + "a" * 40))
            pending = (await pool.call("caller", "keyboard_control", value)).structuredContent
            assert entered.is_set() and not cancelled
            assert pending["id"] == value["task_id"] and pending["state"] == "running"
            assert calls == [value["task_id"]]
            release.set()
            duplicate = (await pool.call("caller", "keyboard_control", value)).structuredContent
            assert duplicate["id"] == value["task_id"]
            assert duplicate["state"] == "completed"
            observed = (
                await pool.call("caller", "task_get", {"task_id": value["task_id"]})
            ).structuredContent
            assert observed["state"] == "completed"
            assert observed["result"]["post_calls_returned"] == 2
            assert calls == [value["task_id"]] and not cancelled
            assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
    finally:
        release.set()
