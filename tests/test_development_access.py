import json
import sys
from pathlib import Path

import pytest
from conftest import request, submit

from kirabridge.admin_manager import authorization_script
from kirabridge.bridge_core.config import AgentConfig, TerminalConfig, load_config
from kirabridge.bridge_core.models import BridgeError
from kirabridge.readiness import ReadinessInput, readiness
from kirabridge.terminal_manager import TerminalManager, check_executable


def test_full_terminal_is_explicit_and_still_checks_executable():
    with pytest.raises(BridgeError, match="explicitly allowed"):
        check_executable(sys.executable, [])
    check_executable(sys.executable, [], True)
    with pytest.raises(BridgeError):
        check_executable("python", [], True)
    with pytest.raises(BridgeError):
        check_executable("/does/not/exist", [], True)


def test_development_environment_does_not_inherit_secrets(monkeypatch):
    monkeypatch.setenv("KIRABRIDGE_CHATGPT_TOKEN", "NEVER_INHERIT")
    monkeypatch.setenv("XAI_API_KEY", "NEVER_INHERIT")
    terminal = TerminalManager(
        TerminalConfig(search_path=["/usr/local/bin", "/usr/bin"], home="/owned")
    )
    assert terminal.environment["HOME"] == "/owned"
    assert terminal.environment["PATH"] == "/usr/local/bin:/usr/bin"
    assert "NEVER_INHERIT" not in json.dumps(terminal.environment)
    with pytest.raises(BridgeError):
        TerminalManager(TerminalConfig(search_path=["relative"]))


async def test_full_terminal_is_principal_specific_not_a_file_grant(bridge, config, tmp_path):
    policy = config.principals["local"]
    policy.allow_any_executable = True
    policy.terminal_roots = [str(tmp_path)]
    policy.executables = []
    outside = tmp_path / "outside"
    outside.mkdir()
    async with bridge:
        value = request(
            "terminal.execute",
            {"argv": [sys.executable, "-V"], "cwd": str(outside)},
            task_id="full",
        )
        submit(bridge, value)
        assert (await bridge.tasks.wait("local", "full"))["state"] == "completed"
        policy_other = config.principals["other"]
        policy_other.executables = []
        other = request("terminal.execute", value.arguments, task_id="other")
        submit(bridge, other, "other")
        rejected = await bridge.tasks.wait("other", "other")
        assert rejected["state"] == "failed" and rejected["started"] is None
        assert rejected["error"]["code"] == "executable_denied"
        read = request("file.list", {"path": str(outside)}, task_id="file")
        submit(bridge, read)
        assert (await bridge.tasks.wait("local", "file"))["error"]["code"] == "path_denied"
        check = readiness(
            bridge,
            "local",
            ReadinessInput(working_directories=[str(outside)], executables=[sys.executable]),
        )
        assert check["requested_prerequisites_ready"]


def test_loaded_configuration_keeps_authorization_across_reloads(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[terminal]\nhome="/owned"\nsearch_path=["/usr/bin"]\n[principals.chatgpt]\napproval_mode="automatic"\nallow_any_executable=true\nterminal_roots=["/"]\n'
    )
    for _ in range(2):
        loaded = load_config(str(path))
        assert loaded.principals["chatgpt"].allow_any_executable
        assert loaded.principals["chatgpt"].terminal_roots == ["/"]
        assert loaded.terminal.home == "/owned"


def test_admin_command_quotes_data_and_requires_no_password():
    script = authorization_script(["/usr/bin/printf", "%s", "$(touch nope); ' \""], "/owned space")
    assert script.startswith("do shell script ")
    assert script.endswith(" with administrator privileges")
    command = json.loads(script[len("do shell script ") : -len(" with administrator privileges")])
    import shlex

    assert shlex.split(command.split(" && exec ", 1)[1]) == [
        "/usr/bin/printf",
        "%s",
        "$(touch nope); ' \"",
    ]
    assert "password" not in script


def test_policy_update_backs_up_preserves_rights_and_survives_repeat(tmp_path):
    import hashlib
    import runpy

    configure = runpy.run_path(
        str(Path(__file__).parents[1] / "scripts/configure_development_access.py")
    )["configure"]
    path = tmp_path / "config.toml"
    project = tmp_path / "project"
    project.mkdir()
    raw = '[principals.chatgpt]\nroots=[]\n[principals.codex]\nroots=["/original"]\n'
    path.write_text(raw)
    path.chmod(0o600)
    backup = tmp_path / "backup"
    for _ in range(2):
        before = path.read_bytes()
        result = configure(
            path,
            backup,
            [str(project)],
            ["/usr/bin"],
            full_terminal=True,
            expected_sha256=hashlib.sha256(before).hexdigest(),
        )
        assert Path(result["backup"]).read_bytes() == before
        assert path.stat().st_mode & 0o777 == 0o600
        loaded = load_config(str(path))
        assert loaded.principals["codex"].roots == ["/original"]
        assert not loaded.principals["codex"].allow_any_executable
        assert loaded.principals["chatgpt"].allow_any_executable
        assert loaded.principals["chatgpt"].roots == [str(project)]
    with pytest.raises(ValueError, match="changed"):
        configure(path, backup, [], [], full_terminal=True, expected_sha256="outdated")
    unchanged = path.read_bytes()
    with pytest.raises(BridgeError, match="absolute"):
        configure(
            path,
            backup,
            [],
            ["relative"],
            full_terminal=True,
            expected_sha256=hashlib.sha256(unchanged).hexdigest(),
        )
    assert path.read_bytes() == unchanged
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="regular file"):
        configure(link, backup, [], [], full_terminal=True, expected_sha256="outdated")


@pytest.mark.parametrize("timed_out,terminated", [(True, False), (False, True)])
async def test_admin_timeout_is_unknown_never_an_implicit_retry(
    bridge, config, monkeypatch, timed_out, terminated
):
    from kirabridge.admin_manager import execute_admin
    from kirabridge.bridge_core.models import TerminalInput, UncertainExecution

    async def timeout(*args, **kwargs):
        return {"timed_out": timed_out, "terminated": terminated, "exit_code": -15}

    monkeypatch.setattr("kirabridge.admin_manager.sys.platform", "darwin")
    monkeypatch.setattr(bridge.terminal, "execute", timeout)
    config.principals["local"].allow_any_executable = True
    with pytest.raises(UncertainExecution, match="unknown"):
        await execute_admin(
            bridge,
            {"id": "a", "principal": "local"},
            TerminalInput(argv=[sys.executable], cwd="/"),
            config.principals["local"],
            None,
        )


@pytest.mark.parametrize("enabled,capability,requested", [(False, True, True), (True, False, True)])
async def test_grok_tools_require_both_operator_and_principal(
    bridge, config, enabled, capability, requested
):
    config.agents["grok"] = AgentConfig(
        kind="grok_acp", executable=sys.executable, allow_local_tools=enabled
    )
    if capability:
        config.principals["local"].capabilities.append("agent.local_tools")
    value = request(
        "agent.execute",
        {
            "agent": "grok",
            "cwd": config.principals["local"].roots[0],
            "prompt": "synthetic",
            "local_tools": requested,
        },
        task_id="denied-tools",
    )
    submit(bridge, value)
    async with bridge:
        result = await bridge.tasks.wait("local", "denied-tools")
        assert result["state"] == "failed" and result["started"] is None
        assert result["error"]["code"] == "agent_tools_denied"


@pytest.mark.parametrize(
    "opt_in,permission_session,kind",
    [
        (False, "test-session", "execute"),
        (True, "test-session", "execute"),
        (True, "foreign-session", "execute"),
        (True, "test-session", "other"),
    ],
)
async def test_grok_permission_is_one_request_only_not_a_receiver_escalation(
    bridge, config, tmp_path, opt_in, permission_session, kind
):
    from test_agents import fake_cli

    body = """import json,sys
for line in sys.stdin:
    msg=json.loads(line); method=msg.get("method")
    if method=="initialize": result={"protocolVersion":1,"authMethods":[{"id":"cached_token"}]}
    elif method=="authenticate": result={}
    elif method=="session/new": result={"sessionId":"test-session"}
    elif method=="session/prompt":
        options=[{"optionId":"one","kind":"allow_once"},{"optionId":"forever","kind":"allow_always"}]
        print(json.dumps({"jsonrpc":"2.0","id":999,"method":"session/request_permission","params":{"options":options,"sessionId":"test-session","toolCall":{"kind":"execute"}}}),flush=True)
        answer=json.loads(sys.stdin.readline())["result"]["outcome"]
        chunk={"sessionUpdate":"agent_message_chunk","content":{"type":"text","text":json.dumps({"permission":answer,"argv":sys.argv[1:]})}}
        print(json.dumps({"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"test-session","update":chunk}}),flush=True)
        result={"stopReason":"end_turn"}
    else: continue
    print(json.dumps({"jsonrpc":"2.0","id":msg["id"],"result":result}),flush=True)
"""
    body = body.replace(
        '"sessionId":"test-session","toolCall":{"kind":"execute"}',
        '"sessionId":'
        + json.dumps(permission_session)
        + ',"toolCall":{"kind":'
        + json.dumps(kind)
        + "}",
    )
    config.agents["grok"] = AgentConfig(
        kind="grok_acp", executable=fake_cli(tmp_path, body), allow_local_tools=True
    )
    config.principals["local"].capabilities.append("agent.local_tools")
    value = request(
        "agent.execute",
        {
            "agent": "grok",
            "prompt": "synthetic",
            "cwd": config.principals["local"].roots[0],
            "local_tools": opt_in,
        },
        task_id="permission",
    )
    submit(bridge, value)
    async with bridge:
        result = await bridge.tasks.wait("local", "permission")
    assert result["state"] == "completed"
    answer = json.loads(result["result"]["text"])
    assert answer["permission"] == (
        {"outcome": "selected", "optionId": "one"}
        if opt_in and permission_session == "test-session" and kind == "execute"
        else {"outcome": "cancelled"}
    )
    assert "forever" not in json.dumps(answer)
    argv = answer["argv"]
    pairs = list(zip(argv, argv[1:], strict=False))
    assert (("--allow", "Bash") in pairs) is opt_in
    assert (("--deny", "Bash") in pairs) is not opt_in
    assert ("--deny", "MCPTool") in pairs


@pytest.mark.parametrize("operation", ["agent.status", "policy.inspect"])
def test_status_keeps_reserved_capacity_and_can_be_claimed_during_work(bridge, config, operation):
    config.max_queued = 1
    submit(
        bridge, request("file.list", {"path": config.principals["local"].roots[0]}, task_id="busy")
    )
    submit(bridge, request(operation, {}, task_id="status"))
    status = bridge.store.claim("control-worker", 30, control=True)
    assert status["id"] == "status"
    assert bridge.store.claim("normal-worker", 30, control=False)["id"] == "busy"
