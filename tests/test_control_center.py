import json

import httpx
import pytest
from conftest import request

from kirabridge.approval_console import ORIGIN, ApprovalConsole, signed_token
from kirabridge.bridge_core.config import AgentConfig, Config, PrincipalConfig, load_config
from kirabridge.bridge_core.models import BridgeError, State
from kirabridge.control_center import configure_access, replace_section
from kirabridge.message_manager import MessageSend
from kirabridge.operator_application import operator_application
from kirabridge.permissions import LEVELS, automatic_for, level_for

KEY = "control-center-test-" + "x" * 48


def headers():
    return {"Authorization": "Bearer " + signed_token(KEY, "session"), "Origin": ORIGIN}


def test_three_levels_preserve_legacy_and_enforce_selected_approvals():
    assert list(LEVELS.values()) == ["Voll erlaubt", "Mittel", "Nur mit Erlaubnis"]
    legacy = PrincipalConfig(approval_mode="automatic")
    assert automatic_for(legacy, "file.write")
    medium = legacy.model_copy(update={"permission_level": "medium"})
    assert automatic_for(medium, "file.read")
    assert not automatic_for(medium, "file.write")
    assert not automatic_for(medium, "terminal.execute")
    assert not automatic_for(medium, "agent.execute")
    full = medium.model_copy(update={"permission_level": "full"})
    assert automatic_for(full, "terminal.execute")
    ask = full.model_copy(update={"permission_level": "ask"})
    assert not automatic_for(ask, "file.read")
    assert level_for(ask) == "ask"


def test_chatgpt_terminal_standing_grant_survives_reconfiguration_and_reload(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[principals.chatgpt]\npermission_level="full"\nautomatic_operations=["session.input"]\n'
        "[session_input_policy]\nenabled=false\nprincipals=[]\n"
        "[voice_messaging]\ntimeout_seconds=60\n"
    )
    configure_access(path, level="full")
    config = load_config(str(path))
    assert config.principals["chatgpt"].automatic_operations == ["session.input"]
    assert {"session.inspect", "session.input", "terminal.execute"} <= set(
        config.principals["chatgpt"].capabilities
    )
    configure_access(path)
    reloaded = load_config(str(path))
    assert reloaded.principals["chatgpt"].automatic_operations == ["session.input"]
    assert not reloaded.session_input_policy.enabled
    assert reloaded.voice_messaging.timeout_seconds == 60


@pytest.mark.asyncio
async def test_medium_write_waits_for_approval_then_executes_once(bridge, config):
    policy = config.principals["local"]
    policy.approval_mode = "automatic"
    policy.permission_level = "medium"
    path = __import__("pathlib").Path(policy.roots[0]) / "medium.txt"
    task = request("file.write", {"path": str(path), "text": "approved once"})
    async with bridge:
        queued = bridge.prepare("local", task)
        assert queued["state"] == "created" and not path.exists()
        bridge.tasks.approve(task.task_id)
        final = await bridge.tasks.wait("local", task.task_id, timeout=3)
        assert final["state"] == "completed" and path.read_text() == "approved once"
        assert bridge.prepare("local", task)["state"] == "completed"


def test_full_access_persists_all_grants_and_mutual_peers(tmp_path):
    path = tmp_path / "config.toml"
    credentials = tmp_path / "credentials.json"
    credentials.write_text('{"local":"never-rotate-this-credential"}')
    original = credentials.read_bytes()
    config = Config(
        data_dir=str(tmp_path / "state"),
        credentials_file=str(credentials),
        principals={
            name: PrincipalConfig(roots=[str(tmp_path)])
            for name in ["local", "chatgpt", "grok_app", "codex", "grok"]
        },
        agents={"codex": AgentConfig(kind="codex", executable="/bin/echo")},
    )
    source = (
        "data_dir = "
        + json.dumps(config.data_dir)
        + "\ncredentials_file = "
        + json.dumps(str(credentials))
        + "\n"
    )
    for name, p in config.principals.items():
        source = replace_section(source, "principals." + name, p.model_dump())
    for name, p in config.agents.items():
        source = replace_section(source, "agents." + name, p.model_dump())
    path.write_text(source)
    updated = configure_access(path, level="full")
    assert credentials.read_bytes() == original
    for name, policy in updated.principals.items():
        assert policy.permission_level == "full" and policy.allow_any_executable
        assert policy.roots == policy.read_roots == policy.terminal_roots == ["/"]
        assert set(policy.message_peers) == set(updated.principals) - {name}
        assert {"session.open", "session.input", "agent.execute"} <= set(policy.capabilities)
    assert updated.agents["codex"].sandbox_mode == "danger-full-access"
    assert updated.agents["codex"].bridge_tools
    changed = configure_access(path, level="medium")
    assert changed.principals["grok_app"].roots == ["/"]
    assert not automatic_for(changed.principals["grok_app"], "terminal.execute")
    assert load_config(str(path)).principals["grok_app"].permission_level == "medium"


@pytest.mark.asyncio
async def test_control_requires_login_and_local_origin(bridge):
    app = ApprovalConsole(operator_application(bridge), KEY)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        assert (await client.get("/api/control/status")).status_code == 401
        result = await client.post(
            "/api/control/action",
            headers={**headers(), "Origin": "https://foreign.example"},
            json={},
        )
        assert result.status_code == 403
        assert (await client.get("/")).status_code == 200
        assert "center.js" in (await client.get("/")).text
        assert (await client.get("/protocol")).status_code == 200


@pytest.mark.asyncio
async def test_console_stays_up_while_bridge_status_is_inactive(bridge, monkeypatch):
    app = ApprovalConsole(operator_application(bridge), KEY)
    control = app.control_center.service

    async def no_processes():
        return []

    async def no_service(*args, **kw):
        return 1, "", "not loaded"

    async def unavailable(*args, **kw):
        raise BridgeError("unreachable", "Bridge is down")

    monkeypatch.setattr(control, "processes", no_processes)
    monkeypatch.setattr(control, "command", no_service)
    monkeypatch.setattr(control, "rpc", unavailable)
    result = await control.snapshot(fresh=True)
    assert not result["bridge"]["dispatcher_active"]
    assert next(s for s in result["services"] if s["id"] == "bridge")["state"] == "inactive"


@pytest.mark.asyncio
async def test_restart_refuses_active_work_and_never_kills_terminal(bridge, monkeypatch, tmp_path):
    path = tmp_path / "active-config.toml"
    path.write_text("data_dir=" + json.dumps(str(bridge.config.state_path)) + "\n")
    bridge.config._source_path = str(path)
    control = ApprovalConsole(operator_application(bridge), KEY).control_center.service
    control.operations.drain_timeout = 0
    loaded = load_config(str(path))

    async def health(*args, **kwargs):
        return {
            "operations": {"protocol": 1},
            "runtime": {
                **bridge.runtime,
                "config_sha256": loaded._source_sha256,
            },
        }

    monkeypatch.setattr(control, "rpc", health)
    task = request(arguments={"path": bridge.config.principals["local"].roots[0]})
    bridge.prepare("local", task)
    bridge.tasks.approve(task.task_id)
    bridge.store.claim("test-worker", 30)
    commands = []

    async def command(*args, **kw):
        commands.append(args)
        return 0, "", ""

    monkeypatch.setattr(control, "command", command)
    with pytest.raises(BridgeError, match="Auftrag"):
        await control.reload_bridge()
    assert not commands


@pytest.mark.asyncio
async def test_action_retry_does_not_start_a_second_process(bridge, monkeypatch):
    app = ApprovalConsole(operator_application(bridge), KEY)
    calls = []

    async def start(*args):
        calls.append(args)
        return {"state": "starting"}

    monkeypatch.setattr(app.control_center.service, "service_action", start)
    value = {"service": "bridge", "action": "start", "action_id": "same-click"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        a = await client.post("/api/control/action", headers=headers(), json=value)
        b = await client.post("/api/control/action", headers=headers(), json=value)
        assert a.json() == b.json() == {"state": "starting"}
        assert len(calls) == 1
        conflict = await client.post(
            "/api/control/action", headers=headers(), json={**value, "action": "restart"}
        )
        assert conflict.status_code == 409 and len(calls) == 1


@pytest.mark.asyncio
async def test_terminal_start_keeps_configured_local_model_and_bridge(bridge, monkeypatch):
    control = ApprovalConsole(operator_application(bridge), KEY).control_center.service
    config = bridge.config
    config._source_path = "/private/config.toml"
    config.principals["local"].permission_level = "full"
    config.agents["opencode"] = AgentConfig(
        kind="opencode",
        executable="/bin/echo",
        model="ollama/local-model:latest",
        base_url="http://127.0.0.1:11434/v1",
        bridge_tools=True,
    )
    monkeypatch.setattr(control, "config", lambda: config)

    async def snapshot(**kw):
        return {"services": [{"id": "opencode", "active": False}]}

    captured = {}

    async def rpc(tool, arguments):
        captured.update(tool=tool, arguments=arguments)
        return {"state": "completed"}

    monkeypatch.setattr(control, "snapshot", snapshot)
    monkeypatch.setattr(control, "rpc", rpc)
    await control.service_action("opencode", "start", "model-start")
    assert captured["tool"] == "session_open"
    argv = captured["arguments"]["argv"]
    settings = json.loads(
        next(a.split("=", 1)[1] for a in argv if a.startswith("OPENCODE_CONFIG_CONTENT="))
    )
    assert settings["model"] == "ollama/local-model:latest"
    assert settings["provider"]["ollama"]["options"]["baseURL"] == "http://127.0.0.1:11434/v1"
    assert "opencode" in settings["mcp"]["kirabridge"]["command"]
    assert argv[argv.index("-u") + 1] == config.agents["opencode"].api_key_env
    assert argv[-2:] == ["--model", "ollama/local-model:latest"]


@pytest.mark.asyncio
async def test_protocol_uses_event_time_state_not_later_completion(bridge):
    app = ApprovalConsole(operator_application(bridge), KEY)
    path = bridge.config.principals["local"].roots[0]
    task = request(arguments={"path": path})
    bridge.prepare("local", task)
    bridge.tasks.approve(task.task_id)
    bridge.store.claim("test-worker", 30)
    bridge.store.transition(task.task_id, State.RUNNING, {"started": True}, owner="test-worker")
    bridge.store.transition(
        task.task_id,
        State.COMPLETED,
        {"ended": True},
        result={"text": "real result"},
        owner="test-worker",
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        data = (await client.get("/api/control/protocol", headers=headers())).json()
    records = [e for e in data["entries"] if e.get("task")]
    early = [
        e for e in records if e["task"]["state"] in {"created", "queued", "accepted", "running"}
    ]
    assert early and all(e["task"]["result"] is None for e in early)
    assert any(
        e["task"]["state"] == "completed" and e["task"]["result"] == {"text": "real result"}
        for e in records
    )


def test_all_agents_can_exchange_messages_even_with_ask_level(bridge, config):
    names = ["chatgpt", "grok_app", "codex", "grok", "claude", "gemini", "copilot", "opencode"]
    for name in names:
        config.principals[name] = PrincipalConfig(
            permission_level="ask",
            approval_mode="manual",
            capabilities=["message.send", "message.read", "message.ack"],
            message_peers=[other for other in names if other != name],
        )
    for sender in names:
        for recipient in names:
            if sender == recipient:
                continue
            conversation = sender + "-" + recipient
            sent = bridge.messages.send(
                sender,
                MessageSend(
                    recipient=recipient,
                    body="probe go-go-go" if sender in {"chatgpt", "grok_app"} else "probe",
                    kind="note",
                    conversation_id=conversation,
                    idempotency_key=conversation,
                ),
            )
            received = bridge.messages.receive(recipient, conversation_id=sent["conversation_id"])[
                "messages"
            ][0]
            assert received["sender"] == sender
            done = bridge.messages.ack(recipient, sent["id"], received["receipt"])
            assert done["acknowledged"]


def test_full_grant_does_not_keep_hidden_state_directory_exclusion(bridge, config):
    from kirabridge.read_query import ReadQuery, read_query
    from kirabridge.readiness import ReadinessInput, readiness

    marker = config.state_path / "operator-access-test.txt"
    marker.write_text("operator full grant")
    policy = config.principals["local"]
    policy.roots = policy.read_roots = ["/"]
    policy.allow_any_executable = True
    with pytest.raises(BridgeError, match="Bridge state"):
        read_query(bridge, "local", ReadQuery(operation="file.read", path=str(marker)))
    policy.permission_level = "full"
    actual = read_query(bridge, "local", ReadQuery(operation="file.read", path=str(marker)))
    assert "operator full grant" in str(actual)
    assert readiness(bridge, "local", ReadinessInput(read_paths=[str(marker)]))["read_path_checks"][
        0
    ]["ok"]


def test_cached_dispatch_true_still_delivers_to_external_chat_client(bridge, config):
    for name, other in [("codex", "chatgpt"), ("chatgpt", "codex")]:
        config.principals[name] = PrincipalConfig(
            permission_level="full",
            approval_mode="automatic",
            capabilities=["message.send", "message.read", "message.ack"],
            message_peers=[other],
        )
    sent = bridge.messages.send(
        "codex",
        MessageSend(
            recipient="chatgpt",
            conversation_id="cached-client",
            idempotency_key="cached-client",
            body="reply for the active client",
            dispatch=True,
        ),
    )
    assert sent["processing_route"] == "external_client_inbox" and sent["processing"] is None
    received = bridge.messages.receive("chatgpt")["messages"][0]
    assert received["id"] == sent["id"]


@pytest.mark.asyncio
async def test_reconnect_keeps_existing_gateway_and_url(bridge, monkeypatch):
    control = ApprovalConsole(operator_application(bridge), KEY).control_center.service
    reloaded = []

    async def reload():
        reloaded.append(True)
        return {"runtime": {"pid": 123}}

    async def no_gateway_restart(*args, **kwargs):
        raise AssertionError("The existing tunnel must remain running")

    monkeypatch.setattr(control, "reload_bridge", reload)
    monkeypatch.setattr(control, "command", no_gateway_restart)
    result = await control.service_action("grok_app", "restart", "reconnect")
    assert result["state"] == "reconnected" and result["gateway_preserved"]
    assert reloaded == [True]


def test_status_snapshot_names_the_installed_release_for_the_footer(tmp_path):
    import json as _json

    import kirabridge
    from kirabridge import operator_control

    identity = operator_control.release_identity()
    assert identity["version"] == kirabridge.__version__
    # A development checkout has no installed release commit.
    assert identity["source_commit"] is None

    from kirabridge.platform_adapters.macos import system_identity

    release = tmp_path / "0.0.0-abc"
    package = release / "source/.venv/lib/python3.11/site-packages/kirabridge"
    package.mkdir(parents=True)
    (release / "release.json").write_text(_json.dumps({"source_commit": "a" * 40}))
    assert system_identity.installed_source_commit(package) == "a" * 40


def test_control_center_footer_shows_a_small_version_tag():
    from pathlib import Path as _Path

    assets = _Path(__file__).parents[1] / "src/kirabridge/console_assets"
    html = (assets / "center.html").read_text()
    script = (assets / "center.js").read_text()
    css = (assets / "center.css").read_text()
    assert '<span id="footer-version" class="version-tag" hidden></span>' in html
    assert script.startswith('"use strict";') and "renderVersion(data);" in script
    assert ".version-tag{" in css
    # On small screens only the hint is hidden; the version stays visible.
    assert ".app-footer .footer-hint{display:none}" in css
    assert ".app-footer>span:last-child{display:none}" not in css
