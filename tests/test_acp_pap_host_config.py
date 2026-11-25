"""The opt-in ACP-PAP host adapter changes nothing unless explicitly enabled."""

import sys

import pytest
from pydantic import ValidationError

from kirabridge.agent_manager import AgentManager
from kirabridge.agent_manager.acp_pap_host import ACPPAPHostAdapter
from kirabridge.bridge_core.config import AgentConfig, Config
from kirabridge.bridge_core.models import BridgeError, digest


def test_disabled_by_default_and_config_digest_unchanged():
    config = Config()
    assert config.acp_pap_host.enabled is False
    assert "acp_pap_host" not in config.model_dump()
    assert "acp_pap_args" not in AgentConfig(kind="grok_api").model_dump()
    assert "acp_pap" not in AgentManager(config, None).adapters
    assert digest(config.model_dump()) == digest(Config().model_dump())


def test_enabling_is_strict_and_registers_the_adapter():
    with pytest.raises(ValidationError):
        Config(acp_pap_host={"enabled": "yes"})
    with pytest.raises(ValidationError):
        Config(acp_pap_host={"enabled": True, "other": 1})
    config = Config(acp_pap_host={"enabled": True})
    assert "acp_pap_host" in config.model_dump()
    assert isinstance(AgentManager(config, None).adapters["acp_pap"], ACPPAPHostAdapter)


def test_launch_arguments_only_for_the_acp_pap_kind():
    AgentConfig(kind="acp_pap", executable="/bin/x", acp_pap_args=["--acp"])
    with pytest.raises(ValidationError):
        AgentConfig(kind="grok_api", acp_pap_args=["--acp"])


async def test_missing_optional_package_is_a_clean_unavailable_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "acp_pap", None)
    with pytest.raises(BridgeError) as error:
        await ACPPAPHostAdapter().execute({}, None, None, [], None, None)
    assert error.value.code == "agent_unavailable"
