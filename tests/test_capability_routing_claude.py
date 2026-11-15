"""Claude starter only; metadata and model execution are mocked."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from kirabridge.capability_routing.hook import (
    before_delegation,
    command_for,
    subscription_environment,
)
from kirabridge.capability_routing.launcher import launch
from kirabridge.capability_routing.router import (
    Access,
    Capability,
    Matrix,
    Model,
    RoutingError,
    Runtime,
    Task,
)


@pytest.fixture
def profile(tmp_path, monkeypatch):
    exe = tmp_path / "claude"
    exe.write_text("fixture only")
    exe.chmod(0o700)
    now = datetime.now(timezone.utc)
    start = (now - timedelta(minutes=1)).isoformat()
    end = (now + timedelta(minutes=30)).isoformat()
    matrix = Matrix(
        schema_version="bigplan.cli-matrix.v1",
        checked_at=start,
        expires_at=end,
        clis=[
            Capability(
                id="claude",
                installed_version="2.1.322 (Claude Code)",
                capabilities=["headless", "coding"],
                models=[
                    Model(
                        id="opus",
                        provider="anthropic",
                        efforts=["xhigh"],
                        fit={"security": 5, "review": 5},
                        cost_rank=3,
                        evidence="official per-model contract plus local help, alias only",
                    )
                ],
                documented_models=[],
                sources=["https://code.claude.com/docs/en/model-config"],
                limitations="effective ID unknown",
            )
        ],
    )
    runtime = Runtime(
        schema_version="bigplan.cli-runtime.v1",
        allowed_roots=[str(tmp_path)],
        state_dir=str(tmp_path / "receipts"),
        access=[
            Access(
                cli="claude",
                executable=str(exe),
                version="2.1.322 (Claude Code)",
                models=["opus"],
                access_kind="subscription",
                verified_at=start,
                expires_at=end,
                evidence="isolated fixture",
            )
        ],
    )
    task = Task(
        task_id="claude-fixture",
        workload="security",
        prompt="Self-contained pinned source review.",
        cwd=str(tmp_path),
        ownership_ref="isolated fixture",
        allowed_clis=["claude"],
        explicit_cli="claude",
        explicit_model="opus",
        explicit_effort="xhigh",
        min_effort="xhigh",
    )

    class Source:
        def load(self):
            return matrix, {"thread_id": "fixture", "revision": 1}

    calls = []
    status = {
        "loggedIn": True,
        "authMethod": "claude.ai",
        "apiProvider": "firstParty",
        "subscriptionType": "pro",
        "email": "private-identity",
        "access_token": "private-token",
    }

    def metadata(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[1:] == ["--version"]:
            return SimpleNamespace(returncode=0, stdout="2.1.322 (Claude Code)\n", stderr="")
        assert argv[1:] == ["auth", "status", "--json"]
        return SimpleNamespace(returncode=0, stdout=json.dumps(status), stderr="")

    monkeypatch.setattr("kirabridge.capability_routing.hook.subprocess.run", metadata)
    return Source(), runtime, task, calls, status


def test_plan_metadata_only_no_runner_no_receipt(profile):
    source, runtime, task, calls, _ = profile
    result = launch(source, runtime, task, runner=lambda *a, **k: pytest.fail("model invoked"))
    assert result["state"] == "planned" and result["starts_model"] is False
    assert (
        result["observed_auth_route"] == "claude.ai"
        and result["per_model_access_attested"] is False
    )
    assert result["effective_model"] == result["effective_effort"] == "unverified"
    assert "private-" not in json.dumps(result)
    assert len(calls) == 2 and not Path(runtime.state_dir).exists()


def test_exact_text_review_argv_and_stdin(profile):
    source, runtime, task, _, _ = profile
    decision = before_delegation(source, runtime, task)
    argv, stdin = command_for(decision, task)
    assert stdin == task.prompt.encode() and task.prompt not in argv
    assert argv[argv.index("--model") + 1] == "opus" and argv[argv.index("--effort") + 1] == "xhigh"
    assert argv[argv.index("--tools") + 1] == ""
    assert json.loads(argv[argv.index("--mcp-config") + 1]) == {"mcpServers": {}}
    assert json.loads(argv[argv.index("--settings") + 1]) == {"switchModelsOnFlag": False}
    assert {
        "--restricted",
        "--safe-mode",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
    } <= set(argv)
    assert argv[argv.index("--max-turns") + 1] == "1"
    assert not {
        "--bare",
        "--continue",
        "--resume",
        "--dangerously-skip-permissions",
        "--fallback-model",
        "--allowed-tools",
    } & set(argv)


@pytest.mark.parametrize(
    "change", [{"read_only": False}, {"explicit_model": "sonnet"}, {"explicit_effort": "high"}]
)
def test_nonprofile_or_minimum_effort_denied(profile, change):
    source, runtime, task, _, _ = profile
    changed = task.model_copy(update=change)
    if change == {"read_only": False}:
        decision = before_delegation(source, runtime, task)
        with pytest.raises(RoutingError):
            command_for(decision, changed)
    else:
        with pytest.raises(RoutingError):
            before_delegation(source, runtime, changed)


@pytest.mark.parametrize(
    "change",
    [
        {"loggedIn": False},
        {"authMethod": "api_key"},
        {"authMethod": "oauth_token"},
        {"authMethod": "api_key_helper"},
        {"apiProvider": "bedrock"},
        {"subscriptionType": None},
    ],
)
def test_auth_route_change_denied_without_identity_output(profile, change):
    source, runtime, task, _, status = profile
    status.update(change)
    with pytest.raises(RoutingError, match="subscription authentication changed") as error:
        before_delegation(source, runtime, task)
    assert "private-" not in str(error.value)


def test_claude_environment_removes_api_provider_effort_plugin_overrides(monkeypatch):
    monkeypatch.setenv("HOME", "/existing-home")
    for name in [
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CONFIG_DIR",
        "CLAUDE_CODE_EFFORT_LEVEL",
        "CLAUDE_CODE_SIMPLE",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_PLUGIN_ROOT",
        "OPENAI_API_KEY",
    ]:
        monkeypatch.setenv(name, "synthetic-unwanted")
    env = subscription_environment("claude")
    assert env["HOME"] == "/existing-home" and "synthetic-unwanted" not in env.values()
    # Existing Codex/Grok filtering is not replaced by Claude's new allowlist.
    monkeypatch.setenv("EXISTING_UNRELATED_SETTING", "retained")
    assert subscription_environment("codex")["EXISTING_UNRELATED_SETTING"] == "retained"
    assert subscription_environment("grok")["EXISTING_UNRELATED_SETTING"] == "retained"


def test_existing_receipt_boundary_once_and_requested_identity_only(profile):
    source, runtime, task, _, _ = profile
    called = []

    def fixture_runner(argv, **kwargs):
        receipt = Path(runtime.state_dir) / (task.task_id + ".json")
        assert json.loads(receipt.read_text())["state"] == "admitted"
        assert kwargs["input"] == task.prompt.encode() and "ANTHROPIC_API_KEY" not in kwargs["env"]
        called.append(argv)
        return SimpleNamespace(returncode=0, stdout=b'{"result":"fixture"}', stderr=b"")

    # execute=True is restricted to this mocked runner; no CLI/model call occurs.
    result = launch(source, runtime, task, execute=True, runner=fixture_runner)
    assert result["state"] == "process_completed" and result["effective_model"] == "unverified"
    with pytest.raises(RoutingError, match="already admitted"):
        launch(source, runtime, task, execute=True, runner=fixture_runner)
    assert len(called) == 1


def test_failed_auth_exit_or_malformed_json_denied(profile, monkeypatch):
    source, runtime, task, _, _ = profile
    for code, body in [(1, "{}"), (0, "not-json"), (0, "[]")]:

        def metadata(argv, code=code, body=body, **kwargs):
            return (
                SimpleNamespace(returncode=0, stdout="2.1.322 (Claude Code)", stderr="")
                if argv[1:] == ["--version"]
                else SimpleNamespace(returncode=code, stdout=body, stderr="private-token")
            )

        monkeypatch.setattr("kirabridge.capability_routing.hook.subprocess.run", metadata)
        with pytest.raises(RoutingError, match="subscription authentication changed"):
            before_delegation(source, runtime, task)


def test_imported_owned_candidate_source():
    from kirabridge.capability_routing import hook

    assert Path(hook.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1])
