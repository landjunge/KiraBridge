"""Conflict-boundary checks; adapters are stubbed, with no provider or GUI effects."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kirabridge.agent_manager import AgentManager
from kirabridge.agent_manager.opencode_http import OpenCodeHTTPAdapter
from kirabridge.agent_manager.opencode_http_v2 import OpenCodeHTTPV2Adapter
from kirabridge.agent_manager.qwen_acp import QwenACPAdapter
from kirabridge.bridge_core.config import AgentConfig, Config
from kirabridge.bridge_core.models import AgentInput, digest
from kirabridge.team_manager import RESUME_ADAPTERS, TRACKED_SESSION_ADAPTERS
from kirabridge.terminal_manager import TerminalManager


@pytest.mark.parametrize(
    "kind,adapter_type",
    [("opencode_http", OpenCodeHTTPAdapter), ("opencode_http_v2", OpenCodeHTTPV2Adapter)],
)
async def test_merged_http_registration_auth_and_resume_survive_qwen(kind, adapter_type, tmp_path):
    profile = AgentConfig(
        kind=kind, model="deepseek/deepseek-flash", server_url="http://127.0.0.1:19191"
    )
    raw = profile.model_dump()
    restored = AgentConfig.model_validate_json(profile.model_dump_json())
    assert restored.server_url == profile.server_url
    assert restored.server_username_env == "OPENCODE_SERVER_USERNAME"
    assert restored.server_password_env == "OPENCODE_SERVER_PASSWORD"
    assert digest(raw) == digest(restored.model_dump())
    assert not any(key.startswith("qwen_") for key in raw)

    manager = AgentManager(Config(agents={"http": profile}), TerminalManager())
    assert isinstance(manager.adapters[kind], adapter_type)
    assert isinstance(manager.adapters["qwen_acp"], QwenACPAdapter)
    assert {kind, "qwen_acp"} <= RESUME_ADAPTERS
    assert {kind, "qwen_acp"} <= TRACKED_SESSION_ADAPTERS

    adapter = SimpleNamespace(interface_version="1", execute=AsyncMock(return_value={"ok": True}))
    manager.adapters[kind] = adapter
    manager.visible_handoffs = SimpleNamespace(execute=AsyncMock())
    principal = SimpleNamespace(
        agents=["http"], permission_level=None, roots=[str(tmp_path)], capabilities=[]
    )
    args = AgentInput(
        agent="http", prompt="fixture", cwd=str(tmp_path), timeout=1, resume_session="ses_owned"
    )
    result = await manager.execute(
        {"id": "fixture", "principal": "local"}, args, principal, AsyncMock(), AsyncMock()
    )
    assert result == {"ok": True}
    adapter.execute.assert_awaited_once()
    assert adapter.execute.await_args.kwargs == {"resume_session": "ses_owned"}
    manager.visible_handoffs.execute.assert_not_awaited()
