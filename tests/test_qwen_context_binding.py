"""Identity and final-setting regressions; transport is in memory, no provider process."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_qwen_recovery import recovery

from kirabridge.agent_manager import qwen_acp
from kirabridge.bridge_core.models import BridgeError


@pytest.mark.parametrize("version", ["0.27.2", "0.27.3"])
@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "foreign_session",
        "foreign_cwd",
        "missing_session",
        "missing_cwd",
        "missing_auth",
        "conflicting_auth",
        "foreign_effort_then_low",
        "effort_changed_to_low",
    ],
)
async def test_context_identity_and_final_effort_before_prompt(
    tmp_path, monkeypatch, version, resume, case
):
    binding, task, args, config = recovery(tmp_path, monkeypatch)
    cwd = Path(args.cwd)
    cwd.mkdir()
    config.executable = "/fixture/never-spawned"
    config.qwen_reasoning_effort = "medium"
    binding = binding.model_copy(update={"effort": "medium"})
    option = {
        "id": "reasoning_effort",
        "category": "thought_level",
        "currentValue": "medium",
        "options": [{"value": "medium"}, {"value": "low"}],
    }
    calls = []
    context_count = 0

    async def request(method, params, timeout):
        nonlocal context_count
        calls.append(method)
        if method == "initialize":
            return {
                "protocolVersion": 1,
                "agentInfo": {"name": "qwen-code", "version": version},
                "agentCapabilities": {"loadSession": True},
            }
        if method in {"session/new", "session/load"}:
            return {"sessionId": "session", "configOptions": [option]}
        if method == "session/set_mode":
            return {}
        if method == "session/set_config_option":
            return {"configOptions": [option]}
        if method == "qwen/status/session/context":
            context_count += 1
            value = {
                "v": 1,
                "sessionId": "session",
                "workspaceCwd": str(cwd) + "/.",
                "state": {
                    "_meta": {"authType": "qwen-subscription"},
                    "models": {"currentModelId": "model(qwen-subscription)"},
                    "modes": {"currentModeId": "plan"},
                    "configOptions": [dict(option)],
                },
            }
            if case == "foreign_session":
                value["sessionId"] = "foreign"
            elif case == "foreign_cwd":
                value["workspaceCwd"] = str(tmp_path)
            elif case == "missing_session":
                value.pop("sessionId")
            elif case == "missing_cwd":
                value.pop("workspaceCwd")
            elif case == "missing_auth":
                value["state"]["_meta"].pop("authType")
            elif case == "conflicting_auth":
                value["state"]["_meta"]["authType"] = "openai"
            elif case == "foreign_effort_then_low":
                if context_count == (2 if resume else 1):
                    value["sessionId"] = "foreign"
                else:
                    value["state"]["configOptions"][0]["currentValue"] = "low"
            elif case == "effort_changed_to_low" and context_count == (3 if resume else 2):
                value["state"]["configOptions"][0]["currentValue"] = "low"
            return value
        if method == "session/prompt":
            return {"stopReason": "end_turn"}
        raise AssertionError(method)

    client = SimpleNamespace(
        request=request,
        start=lambda: None,
        bind_session=lambda value: value,
        begin_turn=lambda: None,
        aclose=AsyncMock(),
        cancel=AsyncMock(),
        started=False,
        session_id="session",
        text="FIXTURE_ONLY",
        truncated=False,
    )
    spawn = AsyncMock(return_value=SimpleNamespace(pid=-1))
    monkeypatch.setattr(qwen_acp, "spawn_process", spawn)
    monkeypatch.setattr(qwen_acp, "reap_process", AsyncMock())
    monkeypatch.setattr(qwen_acp, "ACPClient", lambda process: client)
    progress = AsyncMock()
    execute = qwen_acp.QwenACPAdapter().execute(
        task,
        args,
        config,
        [str(cwd)],
        AsyncMock(),
        progress,
        **({"recovery_binding": binding} if resume else {}),
    )
    if case == "valid":
        result = await execute
        assert result["evidence"]["session_reasoning_effort"] == "medium"
        assert result["evidence"]["session_auth_type"] == "qwen-subscription"
        assert result["evidence"]["version"] == version
        assert calls.count("session/prompt") == 1
    else:
        with pytest.raises(BridgeError) as error:
            await execute
        assert error.value.code in {"agent_identity", "agent_selection_unsupported"}
        assert calls.count("session/prompt") == 0
        assert not any(
            call.args[0]["event"] == "session_settings_confirmed"
            for call in progress.await_args_list
        )


@pytest.mark.parametrize(
    "case", ["response_list", "bool_version", "cwd_list", "relative_cwd", "state_list", "meta_list"]
)
async def test_context_envelope_types_fail_closed(tmp_path, case):
    response = {
        "v": 1,
        "sessionId": "session",
        "workspaceCwd": str(tmp_path),
        "state": {"_meta": {"authType": "qwen-subscription"}},
    }
    if case == "response_list":
        response = []
    elif case == "bool_version":
        response["v"] = True
    elif case == "cwd_list":
        response["workspaceCwd"] = []
    elif case == "relative_cwd":
        response["workspaceCwd"] = "."
    elif case == "state_list":
        response["state"] = []
    elif case == "meta_list":
        response["state"]["_meta"] = []
    client = SimpleNamespace(request=AsyncMock(return_value=response))
    with pytest.raises(BridgeError) as error:
        await qwen_acp.QwenACPAdapter()._session_context(
            client, "session", str(tmp_path), "qwen-subscription", 3
        )
    assert error.value.code == "agent_identity"
