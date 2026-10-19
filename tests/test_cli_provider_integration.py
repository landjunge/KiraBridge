"""Provider additions retain Bridge authentication, task ownership and replay bounds."""

import json
import sys
from pathlib import Path

import pytest
from conftest import request, submit

from kirabridge.bridge_core.config import AgentConfig
from kirabridge.bridge_core.models import BridgeError

PROVIDERS = {
    "opencode": ("opencode", "OpenCodeAdapter"),
    "gemini": ("gemini_cli", "GeminiAdapter"),
    "claude": ("claude_code", "ClaudeCodeAdapter"),
    "copilot": ("copilot_cli", "CopilotCLIAdapter"),
}


def configured_agent(config, name, executable):
    kind, _ = PROVIDERS[name]
    config.agents[name] = AgentConfig(
        kind=kind, executable=executable, model="opencode/integration-fixture"
    )
    return config.agents[name]


def provider_request(config, name="opencode", *, prompt="Harmless integration fixture"):
    return request(
        "agent.execute",
        {
            "agent": name,
            "prompt": prompt,
            "cwd": config.principals["local"].roots[0],
            "timeout": 3.0,
        },
        task_id="provider-integration",
        key="provider-once",
    )


@pytest.mark.parametrize("name", PROVIDERS)
def test_provider_is_registered_but_inventory_does_not_claim_a_login_or_running_task(
    bridge, config, name, monkeypatch
):
    settings = configured_agent(config, name, sys.executable)
    monkeypatch.setenv(settings.api_key_env, "synthetic-presence-is-not-authentication")
    kind, class_name = PROVIDERS[name]
    adapter = bridge.agents.adapters[kind]
    assert adapter.interface_version == "1" and type(adapter).__name__ == class_name
    assert len({id(bridge.agents.adapters[kind]) for kind, _ in PROVIDERS.values()}) == 4
    agent = bridge.agents.inventory([name])["agents"]
    assert len(agent) == 1 and agent[0]["id"] == name and agent[0]["kind"] == kind
    assert agent[0]["executable_present"]
    assert agent[0]["execution_mode"] == "isolated_text_only"
    assert not agent[0]["supports_local_tools"] and not agent[0]["supports_owned_resume"]
    for status in ("authentication_status", "daemon_status", "session_status", "task_status"):
        assert agent[0][status] == "unknown"
    assert bridge.agents.inventory([])["agents"] == []


@pytest.mark.parametrize("name", PROVIDERS)
async def test_each_new_provider_requires_the_authenticated_principals_agent_grant(
    bridge, config, name
):
    configured_agent(config, name, "must-not-start")
    # A known configured provider and an approved task do not grant agent identity.
    config.principals["local"].agents = []
    value = provider_request(config, name)
    submit(bridge, value)
    async with bridge:
        final = await bridge.tasks.wait("local", value.task_id)
    assert final["state"] == "failed" and final["started"] is None
    assert final["error"]["code"] == "agent_denied"
    assert not bridge.terminal.sessions


@pytest.mark.parametrize("name", PROVIDERS)
async def test_private_provider_workspace_does_not_bypass_original_cwd_scope(
    bridge, config, name, tmp_path
):
    configured_agent(config, name, sys.executable)
    config.principals["local"].agents = [name]
    value = provider_request(config, name)
    value.arguments["cwd"] = str(tmp_path)
    submit(bridge, value)
    async with bridge:
        final = await bridge.tasks.wait("local", value.task_id)
    assert final["state"] == "failed" and final["started"] is None
    assert final["error"]["code"] == "path_denied"
    assert not bridge.terminal.sessions


def opencode_fixture(tmp_path, counter):
    executable = tmp_path / "opencode-integration-fixture"
    events = [
        {"type": "step_start", "sessionID": "ses_integration", "part": {"type": "step-start"}},
        {
            "type": "text",
            "sessionID": "ses_integration",
            "part": {"type": "text", "text": "INTEGRATION_OK"},
        },
        {
            "type": "step_finish",
            "sessionID": "ses_integration",
            "part": {"type": "step-finish", "reason": "stop"},
        },
    ]
    executable.write_text(
        f"#!{sys.executable}\n"
        "import sys\nfrom pathlib import Path\n"
        "sys.stdin.read()\n"
        f"counter=Path({str(counter)!r})\n"
        "counter.write_text(counter.read_text()+'x' if counter.exists() else 'x')\n"
        + "\n".join(f"print({json.dumps(event)!r},flush=True)" for event in events)
        + "\n"
    )
    executable.chmod(0o700)
    return str(executable)


async def test_provider_turn_is_idempotent_owned_and_evidenced_end_to_end(
    bridge, config, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "kirabridge.agent_manager.opencode._managed_configuration_present", lambda: False
    )
    counter = Path(config.principals["local"].roots[0]) / "fixture-execution-count"
    configured_agent(config, "opencode", opencode_fixture(tmp_path, counter))
    config.principals["local"].agents = ["opencode"]
    value = provider_request(config)
    initial = submit(bridge, value)
    assert initial["state"] == "queued"
    assert initial["receipt"] is None and initial["started"] is None
    assert bridge.submit("local", value, "approval-already-consumed")["id"] == initial["id"]
    changed = provider_request(config, prompt="Different payload must not reuse this key")
    with pytest.raises(BridgeError) as conflict:
        submit(bridge, changed)
    assert conflict.value.code == "idempotency_conflict"
    for access in (bridge.task, bridge.events):
        with pytest.raises(BridgeError) as foreign:
            access("other", value.task_id)
        assert foreign.value.code == "not_found"

    async with bridge:
        final = await bridge.tasks.wait("local", value.task_id)
        assert bridge.submit("local", value, "")["state"] == "completed"
        states = [event["state"] for event in bridge.events("local", value.task_id)["events"]]
        assert bridge.list_tasks("other")["tasks"] == []
        with pytest.raises(BridgeError) as foreign:
            bridge.task("other", value.task_id)
        assert foreign.value.code == "not_found"

    assert final["state"] == "completed" and final["agent"] == "opencode"
    assert final["created"] <= final["accepted"] <= final["started"] <= final["finished"]
    assert final["receipt"] and final["result"]["text"] == "INTEGRATION_OK"
    evidence = final["result"]["evidence"]
    assert evidence["adapter"] == "opencode" and evidence["session_id"] == "ses_integration"
    assert evidence["turn_completed"] and evidence["exit_code"] == 0
    assert evidence["requested_cwd_validated"] and not evidence["requested_workspace_access"]
    assert counter.read_text() == "x"
    assert not bridge.terminal.sessions
    assert states[0:3] == ["created", "queued", "accepted"]
    assert "running" in states and states[-1] == "completed"
