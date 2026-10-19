import os

import pytest
from pydantic import ValidationError

from kirabridge.agent_manager.cli_support import BoundedText, bind_session, cli_environment
from kirabridge.bridge_core.config import AgentConfig, TerminalConfig
from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.terminal_manager import TerminalManager


@pytest.mark.parametrize(
    "kind,key",
    [
        ("opencode", "OPENCODE_API_KEY"),
        ("gemini_cli", "GEMINI_API_KEY"),
        ("claude_code", "ANTHROPIC_API_KEY"),
        ("copilot_cli", "COPILOT_GITHUB_TOKEN"),
        ("grok_api", "XAI_API_KEY"),
        ("codex", "XAI_API_KEY"),
    ],
)
def test_provider_default_never_forwards_another_providers_secret(kind, key, monkeypatch):
    for name in ("OPENCODE_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY"):
        monkeypatch.setenv(name, "synthetic-" + name)
    config = AgentConfig(kind=kind)
    assert config.api_key_env == key
    env = cli_environment(config)
    assert set(env).intersection(
        {"OPENCODE_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY"}
    ) <= {key}


def test_selected_auth_only_and_operator_home(monkeypatch, tmp_path):
    monkeypatch.setenv("SYNTHETIC_SELECTED_KEY", "selected")
    monkeypatch.setenv("UNRELATED_TEST_SECRET", "must-not-leak")
    monkeypatch.setenv("NODE_OPTIONS", "must-not-inherit")
    terminal = TerminalManager(TerminalConfig(home=str(tmp_path)))
    env = cli_environment(
        AgentConfig(kind="opencode", api_key_env="SYNTHETIC_SELECTED_KEY"), terminal
    )
    assert env["SYNTHETIC_SELECTED_KEY"] == "selected"
    assert env["HOME"] == str(tmp_path)
    assert "UNRELATED_TEST_SECRET" not in env and "NODE_OPTIONS" not in env


@pytest.mark.parametrize("key", ["NODE_OPTIONS", "HOME", "PATH", "bad-key", "A\x00B"])
def test_runtime_injection_is_not_a_credential_name(key):
    with pytest.raises(BridgeError, match="dedicated credential"):
        cli_environment(AgentConfig(kind="opencode", api_key_env=key))


def test_bounded_utf8_text_and_stable_session_identity():
    output = BoundedText(5)
    output.append("😀😀")
    output.append("more")
    assert output.text == "😀" and output.truncated
    assert len(output.text.encode()) <= 5
    assert bind_session("one", "one") == "one"
    with pytest.raises(UncertainExecution):
        bind_session("one", "two")
    with pytest.raises(UncertainExecution):
        bind_session(None, "invalid\nidentity")


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/v1",
        "https://127.0.0.1@evil.example/v1",
        "http://user:password@127.0.0.1:11434/v1",
        "file:///tmp/model",
        "http://127.0.0.1:0/v1",
        "http://127.0.0.1/v1?key=secret",
    ],
)
def test_local_provider_endpoint_rejects_remote_and_credentials(url):
    with pytest.raises(ValidationError):
        AgentConfig(kind="opencode", base_url=url)


def test_loopback_provider_and_invalid_kind():
    value = AgentConfig(kind="opencode", base_url="http://127.0.0.1:11434/v1")
    assert value.base_url == "http://127.0.0.1:11434/v1"
    with pytest.raises(ValidationError):
        AgentConfig(kind="gemini_cli", base_url=value.base_url)
    with pytest.raises(ValidationError):
        AgentConfig.model_validate({"kind": []})


def test_cli_uses_only_operator_search_path_and_fixed_runtime_directories(tmp_path):
    terminal = TerminalManager(TerminalConfig(search_path=["/usr/bin", "/bin"]))
    config = AgentConfig(kind="opencode", executable=str(tmp_path / "opencode"))
    paths = cli_environment(config, terminal)["PATH"].split(os.pathsep)
    assert paths[:2] == ["/usr/bin", "/bin"]
    assert str(tmp_path) in paths
