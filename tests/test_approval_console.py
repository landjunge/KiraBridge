import json
import re
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from conftest import request

from kirabridge.approval_console import ORIGIN, ApprovalConsole, signed_token, valid_token
from kirabridge.bridge_core.models import BridgeError, State
from kirabridge.console_runtime import console_key, open_console, probe

KEY = "console-test-key-" + "x" * 48


def client(app, **kwargs):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, **kwargs), base_url=ORIGIN)


def authenticated():
    return {"Authorization": "Bearer " + signed_token(KEY, "session"), "Origin": ORIGIN}


async def test_console_denies_unauthenticated_external_and_cross_origin_access(bridge):
    app = ApprovalConsole(bridge, KEY)
    async with client(app) as browser:
        assert (await browser.get("/")).status_code == 200
        assert (await browser.get("/api/tasks")).status_code == 401
        assert (
            await browser.get("/api/tasks", headers={"Host": "attacker.example"})
        ).status_code == 403
        headers = {**authenticated(), "Origin": "https://attacker.example"}
        result = await browser.post("/api/tasks/missing/approve", headers=headers, json={})
        assert result.status_code == 403
        assert "access-control-allow-origin" not in result.headers
        assert "frame-ancestors 'none'" in result.headers["content-security-policy"]
    async with client(app, client=("198.51.100.1", 1234)) as remote:
        assert (await remote.get("/", headers=authenticated())).status_code == 403


async def test_private_login_ticket_is_short_lived_one_use_and_bound_to_server(bridge):
    app = ApprovalConsole(bridge, KEY)
    ticket = signed_token(KEY, "login:" + app.instance)
    async with client(app) as browser:
        headers = {"Origin": "null"}
        result = await browser.post("/login", headers=headers, data={"ticket": ticket})
        assert result.status_code == 200
        token = re.search(r'data-session="([^"]+)"', result.text).group(1)
        assert valid_token(KEY, "session", token, 30 * 24 * 3600)
        assert KEY not in result.text
        assert result.headers["cache-control"] == "no-store"
        assert (
            await browser.post("/login", headers=headers, data={"ticket": ticket})
        ).status_code == 401
        expired = signed_token(KEY, "login:" + app.instance, now=time.time() - 130)
        assert (
            await browser.post("/login", headers=headers, data={"ticket": expired})
        ).status_code == 401
        other = signed_token(KEY, "login:different-instance")
        assert (
            await browser.post("/login", headers=headers, data={"ticket": other})
        ).status_code == 401


async def test_approval_executes_once_only_after_review_and_records_local_console(bridge, config):
    root = config.principals["local"].roots[0]
    value = request("file.list", {"path": root}, task_id="browser-approval")
    bridge.prepare("other", value)
    app = ApprovalConsole(bridge, KEY)
    async with bridge, client(app) as browser:
        headers = authenticated()
        listing = (await browser.get("/api/tasks", headers=headers)).json()
        assert listing["pending"] == 1
        assert bridge.store.get(value.task_id)["state"] == "created"
        detail = (await browser.get("/api/tasks/" + value.task_id, headers=headers)).json()
        endpoint = "/api/tasks/" + value.task_id + "/approve"
        bad = await browser.post(endpoint, headers=headers, json={"request_hash": "0" * 64})
        assert bad.status_code == 409
        assert bridge.store.get(value.task_id)["state"] == "created"
        result = await browser.post(
            endpoint, headers=headers, json={"request_hash": detail["request_hash"]}
        )
        assert result.status_code == 200
        assert result.json()["task"]["state"] == "queued"
        final = await bridge.tasks.wait("other", value.task_id, timeout=5)
        assert final["state"] == "completed" and final["receipt"] and final["finished"]
        replay = await browser.post(
            endpoint, headers=headers, json={"request_hash": detail["request_hash"]}
        )
        assert replay.status_code == 409
        assert (
            bridge.store.db.execute(
                "SELECT count(*) FROM events WHERE task_id=? AND state='accepted'", (value.task_id,)
            ).fetchone()[0]
            == 1
        )
        audit = bridge.store.db.execute(
            "SELECT metadata FROM audit WHERE task_id=? AND kind='task.approved'", (value.task_id,)
        ).fetchone()[0]
        assert json.loads(audit)["source"] == "local_console"


async def test_rejection_never_executes_and_cannot_cancel_an_active_task(bridge, config):
    path = str(Path(config.principals["local"].roots[0]) / "not-created.txt")
    value = request("file.write", {"path": path, "text": "must not be written"})
    bridge.prepare("local", value)
    app = ApprovalConsole(bridge, KEY)
    async with client(app) as browser:
        headers = authenticated()
        detail = (await browser.get("/api/tasks/task-1", headers=headers)).json()
        result = await browser.post(
            "/api/tasks/task-1/deny", headers=headers, json={"request_hash": detail["request_hash"]}
        )
        assert result.json()["task"]["state"] == "cancelled"
        assert not Path(path).exists() and bridge.store.get("task-1")["receipt"] is None
        second = value.model_copy(update={"task_id": "active", "idempotency_key": "active"})
        bridge.prepare("local", second)
        bridge.tasks.approve("active")
        bridge.store.claim("worker", 30)
        detail = (await browser.get("/api/tasks/active", headers=headers)).json()
        result = await browser.post(
            "/api/tasks/active/deny", headers=headers, json={"request_hash": detail["request_hash"]}
        )
        assert result.status_code == 409
        assert bridge.store.get("active")["state"] == "accepted"


async def test_console_rejects_oversized_and_malformed_decisions(bridge):
    async with client(ApprovalConsole(bridge, KEY)) as browser:
        headers = authenticated()
        result = await browser.post(
            "/api/tasks/any/approve", headers=headers, json={"request_hash": "x" * 5000}
        )
        assert result.status_code == 413
        result = await browser.post(
            "/api/tasks/any/approve", headers=headers, json=["not-a-decision"]
        )
        assert result.status_code == 400
        result = await browser.get("/api/tasks", headers={"Authorization": "Bearer invalid"})
        assert result.status_code == 401


def test_launcher_keeps_credentials_out_of_urls_commands_and_output(tmp_path, monkeypatch):
    import kirabridge.console_runtime as runtime

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(runtime, "probe", lambda *args: "test-instance")
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    calls = []
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda argv, **kw: calls.append(argv) or SimpleNamespace(returncode=0),
    )
    config_path = tmp_path / "private/config.toml"
    result = open_console(config_path)
    key = console_key(config_path)
    assert key not in json.dumps(result) + json.dumps(calls)
    assert (config_path.parent / "console-credentials.json").stat().st_mode & 0o077 == 0
    login = config_path.parent / "approval-login.html"
    assert login.stat().st_mode & 0o077 == 0
    assert key not in login.read_text()
    ticket = re.search(r'name="ticket" value="([^"]+)"', login.read_text()).group(1)
    assert valid_token(key, "login:test-instance", ticket, 120)
    assert ticket not in json.dumps(result) + json.dumps(calls)
    assert calls == [["/usr/bin/open", str(login)]]


def test_launcher_does_not_trust_an_unrelated_local_listener():
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200, json={"name": "KiraBridge approvals", "instance": "imposter", "proof": "0" * 64}
        )
    )
    with (
        httpx.Client(transport=transport) as operator,
        pytest.raises(BridgeError, match="Port 8766"),
    ):
        probe(operator, KEY)


def test_cancel_compare_and_transition_is_atomic(bridge, config):
    value = request(arguments={"path": config.principals["local"].roots[0]})
    bridge.prepare("local", value)
    bridge.tasks.approve(value.task_id)
    bridge.store.claim("worker", 30)
    with pytest.raises(BridgeError):
        bridge.store.transition(
            value.task_id,
            State.CANCELLED,
            {"reviewed": True},
            expected_states={State.CREATED, State.QUEUED},
        )
    assert bridge.store.get(value.task_id)["state"] == "accepted"
