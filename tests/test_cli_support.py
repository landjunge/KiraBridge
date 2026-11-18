import os

import pytest
from pydantic import ValidationError

from kirabridge.agent_manager.cli_support import (
    BoundedText,
    bind_session,
    cli_environment,
    safe_diagnostic,
)
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


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX account identity")
def test_agent_cli_gets_account_name_from_uid_not_environment(monkeypatch):
    import pwd

    from kirabridge.agent_manager import agent_environment

    monkeypatch.setenv("USER", "injected-user")
    monkeypatch.setenv("LOGNAME", "injected-user")
    name = pwd.getpwuid(os.getuid()).pw_name
    for env in (
        cli_environment(AgentConfig(kind="claude_code")),
        agent_environment(AgentConfig(kind="codex")),
    ):
        assert env["USER"] == env["LOGNAME"] == name


@pytest.mark.parametrize(
    "key", ["NODE_OPTIONS", "HOME", "PATH", "USER", "LOGNAME", "bad-key", "A\x00B"]
)
def test_runtime_injection_is_not_a_credential_name(key):
    with pytest.raises(BridgeError, match="dedicated credential"):
        cli_environment(AgentConfig(kind="opencode", api_key_env=key))


def test_safe_diagnostic_masks_secrets_controls_and_length():
    bearer = "B" * 30
    long_token = "Ab12_" + ("x" * 24)
    text = (
        "Please set an Auth method\x1b[31m now\n\n"
        f"Bearer {bearer}\n"
        "api_key=supersecret\n"
        f"token: {long_token}\n"
        "password=hunter2\n"
        "authorization: letmein\n"
    )
    result = safe_diagnostic(text)
    assert result.startswith("Please set an Auth method")
    assert "Bearer [redacted]" in result
    assert "api_key=[redacted]" in result
    assert "token: [redacted]" in result
    assert "password=[redacted]" in result
    assert "authorization: [redacted]" in result
    assert bearer not in result and long_token not in result
    assert "supersecret" not in result and "hunter2" not in result and "letmein" not in result
    assert "\x1b" not in result and "\n" not in result and "  " not in result
    assert len(result) <= 200
    bounded = safe_diagnostic(("auth missing " * 40) + "\x07")
    assert len(bounded) == 200
    assert bounded.startswith("auth missing")
    assert "\x07" not in bounded


def test_safe_diagnostic_masks_dotted_slash_tokens_and_long_paths():
    # Bare `key` is not an assignment name. The 18-character sample stays visible.
    # A real assignment of the same short value is still masked before the length rule.
    assert safe_diagnostic("key=sk-abc.def/ghi") == "key=sk-abc.def/ghi"
    assert safe_diagnostic("token=sk-abc.def/ghi") == "token=[redacted]"
    dotted = "sk-abc.def/ghijklmnopqrstuvwxyz0123"
    assert safe_diagnostic(dotted) == "[redacted]"
    path = "/tmp/path/with/secret-token"
    assert len(path) >= 24 and safe_diagnostic(path) == "[redacted]"
    assert safe_diagnostic("abc+def=ghijklmnopqrstuvwx") == "[redacted]"


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


def test_structured_local_team_turn_can_use_operator_bounded_output():
    configured = AgentConfig(
        kind="opencode", base_url="http://127.0.0.1:11434/v1", local_output_tokens=512
    )
    assert configured.local_output_tokens == 512
    for changes in (
        {"kind": "codex"},
        {"kind": "opencode", "base_url": "http://127.0.0.1:11434/v1", "local_output_tokens": 2049},
    ):
        with pytest.raises(ValueError):
            AgentConfig.model_validate({"local_output_tokens": 512, **changes})
