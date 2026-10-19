import json
import sys
from pathlib import Path

import pytest

from kirabridge.agent_manager.gemini import GeminiAdapter, isolated_gemini_environment
from kirabridge.bridge_core.config import AgentConfig
from kirabridge.bridge_core.models import AgentInput, BridgeError, UncertainExecution
from kirabridge.terminal_manager import TerminalManager


def fake_cli(tmp_path, events=(), *, ending="", body=""):
    path = tmp_path / "fake-gemini"
    source = f"#!{sys.executable}\nimport json,sys\nsys.stdin.read()\n"
    for event in events:
        source += f"print({json.dumps(event)!r},flush=True)\n"
    source += body + "\n" + ending + "\n"
    path.write_text(source)
    path.chmod(0o700)
    return str(path)


def options(tmp_path, executable, **kwargs):
    config = AgentConfig(
        kind="gemini_cli", executable=executable, api_key_env="TEST_GEMINI_KEY", **kwargs
    )
    args = AgentInput(agent="gemini", prompt="Harmless test", cwd=str(tmp_path), timeout=2)
    return config, args


async def execute(tmp_path, config, args, *, terminal=None):
    observed = {"running": [], "progress": []}

    async def running(value):
        observed["running"].append(value)

    async def progress(value):
        observed["progress"].append(value)

    result = await GeminiAdapter(terminal or TerminalManager()).execute(
        {"id": "gemini-test", "principal": "owner"},
        args,
        config,
        [str(tmp_path)],
        running,
        progress,
    )
    return result, observed


@pytest.fixture(autouse=True)
def fake_key(monkeypatch):
    # Every provider subprocess is a synthetic local executable, never Gemini.
    monkeypatch.setenv("TEST_GEMINI_KEY", "synthetic-key-only")


@pytest.mark.parametrize(
    "status,exit_code,expected",
    [("success", 0, True), ("success", 7, False), ("error", 0, False), ("error", 1, False)],
)
async def test_gemini_requires_native_result_and_successful_exit(
    tmp_path, status, exit_code, expected
):
    events = [
        {"type": "init", "session_id": "gemini-session-1"},
        {"type": "message", "role": "user", "content": "not a response"},
        {"type": "message", "role": "assistant", "content": "Grüße\n", "delta": True},
        {"type": "message", "role": "assistant", "content": "Finished", "delta": True},
        {"type": "result", "status": status, "error": {"message": "SECRET_NATIVE_ERROR"}},
    ]
    config, args = options(tmp_path, fake_cli(tmp_path, events, ending=f"sys.exit({exit_code})"))
    result, observed = await execute(tmp_path, config, args)
    assert result["success"] is expected
    assert result["text"] == "Grüße\nFinished"
    assert result["evidence"]["session_id"] == "gemini-session-1"
    assert result["evidence"]["execution_mode"] == "text-only"
    assert not result["project_completion_verified"]
    assert len(observed["running"]) == 1
    assert "SECRET_NATIVE_ERROR" not in json.dumps(result)
    assert "SECRET_NATIVE_ERROR" not in json.dumps(observed)


async def test_gemini_session_and_user_echo_never_imply_execution(tmp_path):
    config, args = options(
        tmp_path,
        fake_cli(
            tmp_path,
            [
                {"type": "init", "session_id": "session-only"},
                {"type": "message", "role": "user", "content": "echo"},
            ],
        ),
    )
    calls = []

    async def running(value):
        calls.append(value)

    async def progress(value):
        pass

    terminal = TerminalManager()
    with pytest.raises(UncertainExecution, match="No native Gemini result"):
        await GeminiAdapter(terminal).execute(
            {"id": "session-only", "principal": "owner"},
            args,
            config,
            [str(tmp_path)],
            running,
            progress,
        )
    assert calls == []
    assert terminal.sessions == {}


async def test_gemini_completion_without_session_is_unknown(tmp_path):
    config, args = options(tmp_path, fake_cli(tmp_path, [{"type": "result", "status": "success"}]))
    with pytest.raises(UncertainExecution) as error:
        await execute(tmp_path, config, args)
    assert error.value.code == "agent_unconfirmed"


@pytest.mark.parametrize("identifier", ["different", "", None, 4, "line\nnew"])
async def test_gemini_rejects_changed_or_invalid_session(tmp_path, identifier):
    config, args = options(
        tmp_path,
        fake_cli(
            tmp_path,
            [
                {"type": "init", "session_id": "original"},
                {"type": "init", "session_id": identifier},
            ],
        ),
    )
    with pytest.raises(UncertainExecution) as error:
        await execute(tmp_path, config, args)
    assert error.value.code == "agent_identity"


@pytest.mark.parametrize("kind", ["tool_use", "tool_result"])
async def test_gemini_fails_closed_on_any_tool_event(tmp_path, kind):
    config, args = options(
        tmp_path,
        fake_cli(
            tmp_path,
            [
                {"type": "init", "session_id": "original"},
                {
                    "type": kind,
                    "tool_name": "run_shell_command",
                    "parameters": {"secret": "not logged"},
                },
                {"type": "result", "status": "success"},
            ],
        ),
    )
    terminal = TerminalManager()
    with pytest.raises(UncertainExecution) as error:
        await execute(tmp_path, config, args, terminal=terminal)
    assert error.value.code == "agent_tool_denied"
    assert "not logged" not in str(error.value)
    assert terminal.sessions == {}


async def test_gemini_timeout_is_unknown_and_reaps_process(tmp_path):
    config, args = options(
        tmp_path,
        fake_cli(
            tmp_path,
            [
                {"type": "init", "session_id": "original"},
            ],
            body="import time\ntime.sleep(10)",
        ),
    )
    args.timeout = 0.1
    terminal = TerminalManager()
    with pytest.raises(UncertainExecution) as error:
        await execute(tmp_path, config, args, terminal=terminal)
    assert error.value.code == "agent_unconfirmed"
    assert terminal.sessions == {}


async def test_gemini_native_errors_are_sanitized(tmp_path):
    config, args = options(
        tmp_path,
        fake_cli(
            tmp_path,
            [
                {"type": "error", "severity": "warning", "message": "SECRET_WARNING"},
                {"type": "error", "severity": "error", "message": "SECRET_TOKEN"},
                {"type": "result", "status": "error", "error": {"message": "SECRET_KEY"}},
            ],
        ),
    )
    result, observed = await execute(tmp_path, config, args)
    assert not result["success"]
    assert result["evidence"]["warning_count"] == 1
    assert result["evidence"]["fatal_error_observed"]
    assert observed["running"] == []
    assert "SECRET" not in json.dumps((result, observed))


@pytest.mark.parametrize("has_session", [False, True])
async def test_gemini_known_startup_auth_rejection_is_sanitized_and_scoped(tmp_path, has_session):
    events = [{"type": "init", "session_id": "already-started"}] if has_session else []
    diagnostic = (
        "Error authenticating: IneligibleTierError: This client is no longer supported "
        "for Gemini Code Assist for individuals. SECRET_AUTH_URL_AND_TOKEN"
    )
    executable = fake_cli(
        tmp_path,
        events,
        body=f"print({diagnostic!r},file=sys.stderr,flush=True)",
        ending="sys.exit(1)",
    )
    config, args = options(tmp_path, executable)
    calls = []

    async def observed(value):
        calls.append(value)

    with pytest.raises(BridgeError) as error:
        await GeminiAdapter(TerminalManager()).execute(
            {"id": "auth-rejected", "principal": "owner"},
            args,
            config,
            [str(tmp_path)],
            observed,
            observed,
        )
    if has_session:
        assert isinstance(error.value, UncertainExecution)
        assert error.value.code == "agent_unconfirmed"
    else:
        assert not isinstance(error.value, UncertainExecution)
        assert error.value.code == "agent_auth_unsupported_client"
        assert any(e.get("failure_code") == "agent_auth_unsupported_client" for e in calls)
    assert "SECRET" not in json.dumps(calls)
    assert "SECRET" not in str(error.value)


async def test_gemini_bounded_text_and_malformed_result(tmp_path):
    config, args = options(
        tmp_path,
        fake_cli(
            tmp_path,
            [
                {"type": "init", "session_id": "bounded"},
                {"type": "message", "role": "assistant", "content": "ü" * 50000},
                {"type": "result", "status": "success"},
            ],
        ),
    )
    result, _ = await execute(tmp_path, config, args)
    assert len(result["text"].encode()) <= 65536
    assert "\ufffd" not in result["text"]
    assert result["evidence"]["output_truncated"]


@pytest.mark.parametrize("event", [[], {"type": "result", "status": "unknown"}])
async def test_gemini_invalid_event_is_unknown(tmp_path, event):
    config, args = options(tmp_path, fake_cli(tmp_path, [event]))
    with pytest.raises(UncertainExecution) as error:
        await execute(tmp_path, config, args)
    assert error.value.code == "agent_protocol"


async def test_gemini_denies_local_tools_and_foreign_workspace_before_start(tmp_path):
    config, args = options(
        tmp_path,
        fake_cli(tmp_path, body="raise Exception('must not start')"),
        allow_local_tools=True,
        sandbox_mode="workspace-write",
    )
    args.local_tools = True
    with pytest.raises(BridgeError) as error:
        await execute(tmp_path, config, args)
    assert error.value.code == "agent_tools_unsupported"
    args.local_tools = False
    args.cwd = str(tmp_path.parent)
    with pytest.raises(BridgeError) as error:
        await execute(tmp_path, config, args)
    assert error.value.code == "path_denied"


async def test_gemini_isolates_native_configuration_and_environment(tmp_path, monkeypatch):
    executable = tmp_path / "fake-gemini"
    executable.write_text(
        f"#!{sys.executable}\n"
        + """
import json,os,sys
from pathlib import Path
prompt=sys.stdin.read()
settings=json.loads(Path(os.environ['GEMINI_CLI_SYSTEM_SETTINGS_PATH']).read_text())
details={'argv':sys.argv[1:],'env':dict(os.environ),'cwd':os.getcwd(),'settings':settings,
         'prompt':prompt,'policy':Path(sys.argv[sys.argv.index('--admin-policy')+1]).read_text()}
for value in [{'type':'init','session_id':'config'},
              {'type':'message','role':'assistant','content':json.dumps(details)},
              {'type':'result','status':'success'}]:
    print(json.dumps(value),flush=True)
"""
    )
    executable.chmod(0o700)
    (tmp_path / ".env").write_text("OTHER_PROVIDER_SECRET=workspace-secret\n")
    native = tmp_path / ".gemini"
    native.mkdir()
    (native / "settings.json").write_text(
        json.dumps(
            {
                "tools": {"discoveryCommand": "must-never-run"},
                "hooksConfig": {"enabled": True},
                "mcpServers": {"evil": {"command": "must-never-run"}},
            }
        )
    )
    monkeypatch.setenv("OTHER_PROVIDER_SECRET", "not inherited")
    monkeypatch.setenv("NODE_OPTIONS", "--require=malicious-file")
    monkeypatch.setenv("GEMINI_CLI_SYSTEM_SETTINGS_PATH", "/untrusted/settings.json")
    config, args = options(tmp_path, str(executable), model="explicit-model")
    args.prompt = "/custom-command\n@/etc/passwd\nuser@example.org\n!touch unsafe"
    result, _ = await execute(tmp_path, config, args)
    details = json.loads(result["text"])
    assert details["cwd"] != str(tmp_path)
    assert not Path(details["cwd"]).exists()  # Ephemeral native state removed after reap.
    assert details["env"]["GEMINI_API_KEY"] == "synthetic-key-only"
    assert "OTHER_PROVIDER_SECRET" not in details["env"]
    assert "NODE_OPTIONS" not in details["env"]
    assert details["env"]["HOME"] == details["env"]["GEMINI_CLI_HOME"]
    assert details["env"]["GEMINI_CLI_SYSTEM_SETTINGS_PATH"] != "/untrusted/settings.json"
    assert details["settings"]["tools"]["core"] == []
    assert not details["settings"]["hooksConfig"]["enabled"]
    assert details["settings"]["mcp"]["allowed"] == details["settings"]["mcp"]["excluded"]
    assert len(details["settings"]["mcp"]["allowed"]) == 1
    assert details["argv"][details["argv"].index("--extensions") + 1] == "none"
    assert not details["settings"]["experimental"]["enableAgents"]
    assert details["settings"]["billing"]["overageStrategy"] == "never"
    assert details["settings"]["general"]["maxAttempts"] == 1
    assert not details["settings"]["general"]["retryFetchErrors"]
    assert 'toolName = "*"' in details["policy"] and 'decision = "deny"' in details["policy"]
    assert "--yolo" not in details["argv"]
    assert args.prompt not in " ".join(details["argv"])
    assert details["argv"][-2:] == ["--model", "explicit-model"]
    assert details["prompt"].startswith("KiraBridge literal text-only request:")
    assert "\\@/etc/passwd" in details["prompt"]
    assert "user\\@example.org" in details["prompt"]


def test_gemini_auth_missing_does_not_start_login_or_read_foreign_settings(tmp_path, monkeypatch):
    from kirabridge.agent_manager import gemini

    monkeypatch.setattr(gemini, "cli_environment", lambda *_: {"HOME": str(tmp_path)})
    config = AgentConfig(kind="gemini_cli", api_key_env="TEST_GEMINI_KEY")
    with (
        pytest.raises(BridgeError) as error,
        isolated_gemini_environment(config, TerminalManager()),
    ):
        pytest.fail("Missing authentication must fail before native dispatch")
    assert error.value.code == "agent_auth_required"


def test_gemini_copies_only_named_authentication_caches_privately(tmp_path, monkeypatch):
    from kirabridge.agent_manager import gemini

    original = tmp_path / ".gemini"
    original.mkdir()
    (original / "oauth_creds.json").write_text('{"synthetic":"oauth"}')
    (original / "google_accounts.json").write_text('{"synthetic":"account"}')
    (original / "settings.json").write_text('{"hooksConfig":{"enabled":true}}')
    (original / "unrelated-secret.txt").write_text("must never be copied")
    monkeypatch.setattr(gemini, "cli_environment", lambda *_: {"HOME": str(tmp_path)})
    config = AgentConfig(kind="gemini_cli")
    with isolated_gemini_environment(config, TerminalManager()) as (
        env,
        workspace,
        policy,
        auth_type,
    ):
        native = Path(env["GEMINI_CLI_HOME"]) / ".gemini"
        assert auth_type == "oauth-personal"
        assert set(p.name for p in native.iterdir()) == {"oauth_creds.json", "google_accounts.json"}
        assert (native / "oauth_creds.json").stat().st_mode & 0o777 == 0o600
        assert (native / "google_accounts.json").read_text() == '{"synthetic":"account"}'
        assert workspace.is_dir() and policy.is_file()
    assert not native.exists()
    assert (original / "settings.json").read_text() == '{"hooksConfig":{"enabled":true}}'


def test_gemini_rejects_symlinked_authentication_cache(tmp_path, monkeypatch):
    from kirabridge.agent_manager import gemini

    original = tmp_path / ".gemini"
    original.mkdir()
    (tmp_path / "other-token").write_text("must not read")
    (original / "oauth_creds.json").symlink_to(tmp_path / "other-token")
    monkeypatch.setattr(gemini, "cli_environment", lambda *_: {"HOME": str(tmp_path)})
    with (
        pytest.raises(BridgeError) as error,
        isolated_gemini_environment(AgentConfig(kind="gemini_cli"), TerminalManager()),
    ):
        pytest.fail("Symlinked authentication must fail before native dispatch")
    assert error.value.code == "agent_auth"
