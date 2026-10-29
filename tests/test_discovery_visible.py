"""Regressions for advertised grants, discovery generations and exact visible work."""

import asyncio
import copy

import pytest
from conftest import request
from test_mcp import http_bridge  # noqa: F401 -- shared real HTTP fixture

from kirabridge import __version__
from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.permissions import decision
from kirabridge.session_manager import SessionOpen
from kirabridge.visible_terminal import VisibleTerminalInput, empty_shell_prompt


async def test_real_http_initialization_and_fresh_catalog_agree_with_grants(
    http_bridge,  # noqa: F811 -- imported real HTTP fixture
    config,
    monkeypatch,
):
    bridge, endpoint = http_bridge
    policy = config.principals["local"]
    policy.capabilities += ["session.inspect"]
    policy.permission_level = "full"
    # Legacy approval_mode still says manual. Effective full grant must win.
    assert policy.approval_mode == "manual"
    rows = [
        {
            "pane_id": "terminal:123:ttys004",
            "expected_pid": 345,
            "tty": "/dev/ttys004",
            "transport": "terminal_app",
            "busy": False,
        }
    ]

    async def catalog(principal):
        bridge.security.principal(principal, "session.inspect")
        return {"status": "available", "sessions": copy.deepcopy(rows)}

    monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    async with MCPClientPool() as pool:
        await pool.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        assert pool.initializations["local"].serverInfo.version == __version__
        tools = await pool.list_tools("local")
        assert "terminal_control" in {tool.name for tool in tools}
        assert all(tool.meta["kirabridge"]["version"] == __version__ for tool in tools)
        health = (
            await pool.call("local", "bridge_health", {"observe_terminals": True})
        ).structuredContent
        catalog_result = (await pool.call("local", "operation_catalog", {})).structuredContent
        inventory = (await pool.call("local", "agent_inventory", {})).structuredContent
        assert not health["approval_required"]
        assert not catalog_result["operations"]["session.open"]["approval_required"]
        assert not catalog_result["operations"]["terminal.visible"]["approval_required"]
        assert health["discovery"]["revision"] == catalog_result["discovery"]["revision"]
        assert inventory["discovery"]["revision"] == health["discovery"]["revision"]
        before = health["discovery"]["revision"]
        rows[0]["expected_pid"] = 346
        await pool.call("local", "bridge_health", {"observe_terminals": True})
        tools = await pool.list_tools("local")
        assert tools[0].meta["kirabridge"]["revision"] != before
        changed = (
            await pool.call("local", "bridge_health", {"observe_terminals": True})
        ).structuredContent
        assert changed["discovery"]["terminal_observation"]["sessions"][0]["expected_pid"] == 346
        connection_id = pool.connection_ids["local"]
        await pool.disconnect("local")
        assert "local" not in pool.catalogs
        await pool.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        assert pool.connection_ids["local"] != connection_id
        assert (await pool.list_tools("local"))[0].meta["kirabridge"]["revision"] != before


async def test_window_request_uses_existing_full_grant_without_second_local_token(
    bridge, config, monkeypatch
):
    config.principals["local"].permission_level = "full"
    config.principals["local"].capabilities.append("session.inspect")
    calls = []

    async def opened(command):
        calls.append(command)
        return {"tty": "/dev/ttys022"}

    async def catalog():
        return [{"pane_id": "terminal:222:ttys022", "expected_pid": 456, "tty": "/dev/ttys022"}]

    monkeypatch.setattr(bridge.sessions.terminal_app, "open", opened)
    monkeypatch.setattr(bridge.sessions.terminal_app, "catalog", catalog)
    value = request(
        "session.open", {"cwd": config.principals["local"].roots[0]}, task_id="window-full"
    )
    assert not decision(config, "local", "session.open")["approval_required"]
    async with bridge:
        assert bridge.prepare("local", value)["state"] == "queued"
        result = await bridge.tasks.wait("local", value.task_id, 5)
        assert result["state"] == "completed", result
        assert result["result"]["pane_id"] == "terminal:222:ttys022"
        bridge.prepare("local", value)
    assert len(calls) == 1


async def test_manual_window_task_waits_for_exact_operator_approval(bridge, config, monkeypatch):
    calls = []

    async def opened(command):
        calls.append(command)
        return {"tty": "/dev/ttys022"}

    async def catalog():
        return [{"pane_id": "terminal:222:ttys022", "expected_pid": 456, "tty": "/dev/ttys022"}]

    monkeypatch.setattr(bridge.sessions.terminal_app, "open", opened)
    monkeypatch.setattr(bridge.sessions.terminal_app, "catalog", catalog)
    value = request(
        "session.open", {"cwd": config.principals["local"].roots[0]}, task_id="window-ask"
    )
    async with bridge:
        assert bridge.prepare("local", value)["state"] == "created"
        with pytest.raises(BridgeError, match="approved window task"):
            await bridge.sessions.open(
                "local", SessionOpen.model_validate(value.arguments), task_id=value.task_id
            )
        assert not calls
        bridge.tasks.approve(value.task_id)
        result = await bridge.tasks.wait("local", value.task_id, 5)
        assert result["state"] == "completed", result
    assert len(calls) == 1


async def test_chatgpt_legacy_terminal_is_visible_while_agent_internal_route_is_preserved(
    bridge, config, monkeypatch
):
    for name in ("chatgpt", "codex"):
        config.principals[name] = config.principals["local"].model_copy(deep=True)
        config.principals[name].capabilities.append("session.inspect")
    calls = []

    async def visible(task, args, running):
        calls.append((task["principal"], "visible"))
        return {"execution_route": "visible_terminal"}

    async def managed(task_id, principal, *args, **kwargs):
        calls.append((principal, "managed"))
        return {"pid": 123, "exit_code": 0, "timed_out": False, "terminated": False}

    async def callback(*args):
        pass

    monkeypatch.setattr(bridge.visible_terminal, "execute", visible)
    monkeypatch.setattr(bridge.terminal, "execute", managed)
    for principal in ("chatgpt", "codex"):
        await bridge.execute(
            {
                "id": "route-" + principal,
                "principal": principal,
                "operation": "terminal.execute",
                "args": {
                    "argv": ["/bin/echo", "test"],
                    "cwd": config.principals[principal].roots[0],
                },
            },
            callback,
            callback,
        )
    assert calls == [("chatgpt", "visible"), ("codex", "managed")]


@pytest.mark.parametrize("text", ["host project% ", "host:project user$ \n\n"])
def test_known_empty_shell_prompt(text):
    assert empty_shell_prompt(text)


@pytest.mark.parametrize(
    "text", ["host% rm -rf ", "host% text", "› ", "host% \x1b[31m", "", "host%\n"]
)
def test_unknown_or_populated_prompt_never_accepts_input(text):
    assert not empty_shell_prompt(text)


def test_visible_reference_is_an_exact_pair():
    with pytest.raises(ValueError):
        VisibleTerminalInput(argv=["/bin/echo"], cwd="/", pane_id="terminal:123:ttys004")


async def test_stale_explicit_window_cannot_receive_input(bridge, config, monkeypatch):
    config.principals["local"].capabilities.append("session.inspect")
    config.principals["local"].executables.append("/bin/echo")

    async def catalog(principal):
        return {"sessions": [{"pane_id": "terminal:123:ttys004", "expected_pid": 346}]}

    async def never(*args, **kwargs):
        pytest.fail("No input or fallback window may be sent for a stale explicit target")

    monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    monkeypatch.setattr(bridge.sessions.terminal_app, "send_confirmed", never)
    monkeypatch.setattr(bridge.sessions.terminal_app, "open", never)
    with pytest.raises(BridgeError) as error:
        await bridge.visible_terminal.execute(
            {"id": "stale", "principal": "local"},
            VisibleTerminalInput(
                argv=["/bin/echo", "test"],
                cwd=config.principals["local"].roots[0],
                pane_id="terminal:123:ttys004",
                expected_pid=345,
            ),
            never,
        )
    assert error.value.code == "session_selection_changed"


async def test_file_params_descriptor_and_signed_url_never_persist(
    http_bridge,  # noqa: F811 -- imported real HTTP fixture
    config,
    monkeypatch,
):
    import hashlib

    import httpx

    bridge, endpoint = http_bridge
    config.file_transfer.enabled = True
    config.file_transfer.allowed_projects = ["project-one"]
    config.file_transfer.source_hosts = ["files.example.org"]
    config.principals["local"].permission_level = "full"
    config.principals["local"].capabilities.append("files.inspect")
    payload = b"explicitly selected real bytes\x00\xff"
    original_register = bridge.file_sources.selected

    async def download(request):
        return httpx.Response(200, stream=httpx.ByteStream(payload))

    def register(*args):
        identifier = original_register(*args)
        bridge.file_sources.get(args[0], identifier).transport = httpx.MockTransport(download)
        return identifier

    monkeypatch.setattr(bridge.file_sources, "selected", register)
    async with MCPClientPool() as pool:
        await pool.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        tools = {tool.name: tool for tool in await pool.list_tools("local")}
        tool = tools["file_transfer_prepare"]
        assert tool.meta["openai/fileParams"] == ["file"]
        schema = tool.inputSchema["$defs"]["OpenAIFile"]
        assert set(schema["required"]) == {"download_url", "file_id"}
        assert {"download_url", "file_id", "mime_type", "file_name"} <= set(schema["properties"])
        secret_url = "https://files.example.org/selected?signature=DO_NOT_PERSIST_CAPABILITY"
        result = (
            await pool.call(
                "local",
                "file_transfer_prepare",
                {
                    "file": {
                        "download_url": secret_url,
                        "file_id": "file-explicit-selection",
                        "file_name": "selected.bin",
                    },
                    "project_id": "project-one",
                    "task_id": "from-file-param",
                    "idempotency_key": "from-file-param",
                    "expected_sha256": hashlib.sha256(payload).hexdigest(),
                },
            )
        ).structuredContent
        assert result["state"] == "queued", result
        task = await bridge.tasks.wait("local", "from-file-param", 10)
        assert task["state"] == "completed", task
        assert task["result"]["manifest"]["size"] == len(payload)
        assert not task["result"]["import_successful"]
        dump = "\n".join(bridge.store.db.iterdump())
        assert secret_url not in dump and "DO_NOT_PERSIST_CAPABILITY" not in dump
        inventory = (await pool.call("local", "file_transfer_inventory", {})).structuredContent
        assert inventory["transfers"][0]["state"] == "authorized"


def test_background_execution_is_explicit(config):
    from kirabridge.permissions import visible_execution

    assert visible_execution(config, "chatgpt", "terminal.execute")
    assert not visible_execution(config, "chatgpt", "terminal.execute", background=True)
    assert not visible_execution(config, "local", "terminal.execute")
    assert visible_execution(config, "local", "terminal.visible")


def test_trusted_custom_chatgpt_role(config):
    from kirabridge.permissions import direct_terminal_required

    assert direct_terminal_required(config, "chatgpt")
    assert not direct_terminal_required(config, "local")
    config.principals["local"].client_type = "chatgpt"
    assert direct_terminal_required(config, "local")
    config.principals["local"].client_type = "agent"
    assert not direct_terminal_required(config, "local")


async def test_health_monitors_leave_terminal_read_capacity_available(
    http_bridge,  # noqa: F811
    config,
    monkeypatch,
):
    bridge, endpoint = http_bridge
    policy = config.principals["local"]
    policy.capabilities += ["session.inspect"]
    policy.permission_level = "full"
    catalog_calls = []

    async def catalog(principal):
        catalog_calls.append(principal)
        await asyncio.sleep(0.05)
        return {"status": "available", "sessions": []}

    async def observed(principal, pane_id, expected_pid, *, max_bytes=65536, since=""):
        assert since == ""
        return {"pane_id": pane_id, "expected_pid": expected_pid, "text": "FOREGROUND"}

    monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    monkeypatch.setattr(bridge.sessions, "read_observed", observed)
    async with MCPClientPool() as pool:
        await pool.connect(Peer("local", url=endpoint, token="local-test-" + "a" * 40))
        results = await asyncio.gather(
            *(pool.call("local", "bridge_health", {}) for _ in range(6)),
            pool.call(
                "local", "session_read", {"pane_id": "terminal:123:ttys004", "expected_pid": 345}
            ),
        )
        assert catalog_calls == [], "Health polling must not probe Terminal or consume read slots"
        assert all(
            r.structuredContent["discovery"]["terminal_observation"]["freshness"] == "not_probed"
            for r in results[:-1]
        )
        assert not results[-1].isError, results[-1]
        assert isinstance(results[-1].structuredContent, dict)
        assert results[-1].structuredContent["text"] == "FOREGROUND"
        assert bridge.terminal_queries.active == 0


def test_passive_discovery_invalidates_observations_when_permissions_change(bridge, config):
    from kirabridge.discovery import snapshot
    from kirabridge.permissions import permission_revision

    policy = config.principals["local"]
    policy.capabilities += ["session.inspect"]
    policy.permission_level = "full"
    bridge.discovery_observations = {
        "local": {
            "status": "available",
            "sessions": [{"pane_id": "terminal:123:ttys004"}],
            "observed_at": 123.0,
            "revision": "old-observation",
            "permission_revision": permission_revision(config),
        }
    }
    observed = snapshot(bridge, "local")["terminal_observation"]
    assert observed["freshness"] == "cached" and observed["observed_at"] == 123.0
    assert not observed["usable_for_input"]
    policy.capabilities.remove("session.inspect")
    assert snapshot(bridge, "local")["terminal_observation"]["sessions"] == []


@pytest.mark.parametrize(
    "authorized,manual,status",
    [(False, False, "not_authorized"), (True, True, "approval_required")],
)
async def test_explicit_discovery_preserves_current_denial_without_stale_sessions(
    bridge, config, monkeypatch, authorized, manual, status
):
    from kirabridge.discovery import live

    policy = config.principals["local"]
    policy.permission_level = "ask" if manual else "full"
    if authorized:
        policy.capabilities += ["session.inspect"]

    async def forbidden(*args):
        pytest.fail("Denied discovery must not probe terminals")

    monkeypatch.setattr(bridge.sessions, "catalog", forbidden)
    bridge.discovery_observations = {
        "local": {"status": "available", "sessions": [{"pane_id": "STALE"}]}
    }
    observation = (await live(bridge, "local"))["terminal_observation"]
    assert observation["status"] == status and observation["sessions"] == []
    assert observation["freshness"] == "fresh" and not observation["usable_for_input"]
