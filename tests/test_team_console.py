"""Local browser authentication and real durable team operations, without models."""

import json

import httpx
import pytest
from conftest import request

from kirabridge.approval_console import ORIGIN, ApprovalConsole, signed_token
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import AgentConfig, PrincipalConfig, TeamConfig, TeamWorkerConfig
from kirabridge.operator_application import operator_application
from kirabridge.team_console import MAX_REQUEST_BYTES
from kirabridge.team_manager.models import TeamCreate, TeamMessageSend, TeamWorkCreate

KEY = "team-browser-tests-" + "x" * 48


@pytest.fixture
def team_bridge(config):
    capabilities = ["team.manage", "team.read", "team.write", "task.read"]
    for name in ("local", "chatgpt", "codex", "grok", "other"):
        config.principals[name] = PrincipalConfig(
            approval_mode="automatic", capabilities=capabilities.copy()
        )
    config.team = TeamConfig(
        enabled=True,
        workers={name: TeamWorkerConfig() for name in config.principals},
    )
    instance = Bridge(config)
    yield instance
    instance.store.close()


def browser(bridge, **kwargs):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=ApprovalConsole(operator_application(bridge), KEY), **kwargs
        ),
        base_url=ORIGIN,
    )


def headers():
    return {"Authorization": "Bearer " + signed_token(KEY, "session"), "Origin": ORIGIN}


def new_team(bridge, team_id="test-team", owner="local"):
    return bridge.teams.create(
        owner,
        TeamCreate(
            team_id=team_id,
            name="Test team",
            members={owner: "coordinator", "codex": "worker", "grok": "reviewer"},
            coordinator=owner,
            idempotency_key="create-" + team_id,
        ),
    )


async def test_team_routes_retain_local_auth_origin_and_csp_boundaries(team_bridge):
    async with browser(team_bridge) as client:
        page = await client.get("/team")
        assert page.status_code == 200
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert page.headers["cache-control"] == "no-store"
        assert (await client.get("/api/team")).status_code == 401
        assert (
            await client.get("/api/team", headers={**headers(), "Host": "attacker.example"})
        ).status_code == 403
        bad = await client.post(
            "/api/team",
            headers={**headers(), "Origin": "https://attacker.example"},
            json={},
        )
        assert bad.status_code == 403
        assert "access-control-allow-origin" not in bad.headers
    async with browser(team_bridge, client=("203.0.113.4", 1234)) as remote:
        assert (await remote.get("/team", headers=headers())).status_code == 403
    assert team_bridge.store.db.execute("SELECT count(*) FROM teams").fetchone()[0] == 0


async def test_browser_creates_team_as_local_and_changes_coordinator_with_revision(team_bridge):
    payload = {
        "team_id": "browser-team",
        "name": "Our team",
        "members": {"local": "worker", "chatgpt": "coordinator", "codex": "worker"},
        "coordinator": "chatgpt",
        "idempotency_key": "create-once",
    }
    async with browser(team_bridge) as client:
        first = await client.post("/api/team", headers=headers(), json=payload)
        assert first.status_code == 200
        team = first.json()
        assert team["owner"] == "local" and team["coordinator"] == "chatgpt"
        repeated = await client.post("/api/team", headers=headers(), json=payload)
        assert repeated.json()["id"] == team["id"]
        endpoint = "/api/team/browser-team/roles"
        change = {
            "member": "codex",
            "role": "coordinator",
            "expected_revision": team["revision"],
            "idempotency_key": "choose-codex",
        }
        changed = (await client.post(endpoint, headers=headers(), json=change)).json()
        assert changed["coordinator"] == "codex"
        assert changed["members"]["chatgpt"]["role"] == "worker"
        assert changed["owner"] == "local"
        stale = {**change, "member": "chatgpt", "idempotency_key": "stale-revision"}
        denied = await client.post(endpoint, headers=headers(), json=stale)
        assert denied.json()["error"] == "team_revision_conflict"
        current = (await client.get("/api/team/browser-team", headers=headers())).json()
        assert current["coordinator"] == "codex"
    assert team_bridge.store.db.execute("SELECT count(*) FROM teams").fetchone()[0] == 1


async def test_browser_cannot_impersonate_a_member_or_override_routed_team(team_bridge):
    new_team(team_bridge)
    async with browser(team_bridge) as client:
        endpoint = "/api/team/test-team/messages"
        payload = {
            "recipient": "codex",
            "body": "Question",
            "idempotency_key": "one-question",
        }
        for extra in ({"sender": "grok"}, {"principal": "grok"}, {"team_id": "other-team"}):
            result = await client.post(endpoint, headers=headers(), json={**payload, **extra})
            assert result.status_code == 400
        sent = (await client.post(endpoint, headers=headers(), json=payload)).json()
        assert sent["sender"] == "local" and sent["recipient"] == "codex"
        assert (await client.post(endpoint, headers=headers(), json=payload)).json()["id"] == sent[
            "id"
        ]
        assert (
            await client.post(endpoint, headers=headers(), json={**payload, "body": "Changed"})
        ).json()["error"] == "idempotency_conflict"
    assert team_bridge.store.db.execute("SELECT count(*) FROM team_messages").fetchone()[0] == 1


async def test_large_unicode_message_and_only_actual_recipient_acknowledgement(team_bridge):
    new_team(team_bridge)
    body = "Nachricht mit Umlauten äöü\n" * 220
    async with browser(team_bridge) as client:
        sent = await client.post(
            "/api/team/test-team/messages",
            headers=headers(),
            json={"recipient": "codex", "body": body, "idempotency_key": "unicode"},
        )
        assert sent.status_code == 200 and sent.json()["body"] == body
        forbidden = await client.post(
            "/api/team/test-team/messages/" + sent.json()["id"] + "/ack",
            headers=headers(),
            json={},
        )
        assert forbidden.status_code == 404
        incoming = team_bridge.teams.send(
            "codex",
            TeamMessageSend(
                team_id="test-team",
                recipient="local",
                body="<script>window.untrustedExecuted = true</script>",
                idempotency_key="incoming",
            ),
        )
        endpoint = "/api/team/test-team/messages/" + incoming["id"] + "/ack"
        first = (await client.post(endpoint, headers=headers(), json={})).json()
        second = (await client.post(endpoint, headers=headers(), json={})).json()
        assert first["acknowledged"] == second["acknowledged"]
        assert first["acknowledged"] is not None
        history = (await client.get("/api/team/test-team/messages", headers=headers())).json()
        assert [value["body"] for value in history["messages"]] == [body, incoming["body"]]
    assert team_bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


async def test_external_local_work_can_be_claimed_reported_and_shared_with_evidence(team_bridge):
    new_team(team_bridge)
    value = team_bridge.teams.delegate(
        "grok",
        TeamWorkCreate(
            team_id="test-team",
            assignee="local",
            title="Review result",
            body="Review this intentionally shared text.",
            idempotency_key="external-work",
        ),
    )
    endpoint = "/api/team/test-team/work/" + value["id"]
    async with browser(team_bridge) as client:
        claimed = await client.post(
            endpoint + "/claim", headers=headers(), json={"idempotency_key": "claim"}
        )
        assert claimed.json()["state"] == "accepted_manual"
        complete = {"result": "Checked äöü", "success": True, "idempotency_key": "result"}
        final = (await client.post(endpoint + "/complete", headers=headers(), json=complete)).json()
        assert final["state"] == "completed" and final["result"] == "Checked äöü"
        assert final["evidence"]["kind"] == "assignee_report"
        assert final["evidence"]["project_completion_verified"] is False
        assert final["core_task_id"] is None
        assert (await client.get(endpoint, headers=headers())).json() == final
        assert (
            await client.post(endpoint + "/complete", headers=headers(), json=complete)
        ).json() == final
    assert team_bridge.teams.work_get("codex", "test-team", value["id"])["result"] == "Checked äöü"
    assert team_bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


async def test_browser_cannot_report_other_assignees_or_import_private_tasks(team_bridge):
    new_team(team_bridge)
    value = team_bridge.teams.delegate(
        "local",
        TeamWorkCreate(
            team_id="test-team",
            assignee="codex",
            title="Shared work",
            body="Visible to team",
            idempotency_key="owned-by-codex",
        ),
    )
    team_bridge.config.principals["other"].capabilities.append("file.read")
    team_bridge.config.principals["other"].approval_mode = "manual"
    private = request("file.read", {"path": "/private-only-secret"}, task_id="private-task")
    team_bridge.prepare("other", private)
    async with browser(team_bridge) as client:
        endpoint = "/api/team/test-team/work/" + value["id"]
        denied = await client.post(
            endpoint + "/complete",
            headers=headers(),
            json={"result": "Fake success", "idempotency_key": "false-report"},
        )
        assert denied.json()["error"] == "team_assignee_denied"
        listing = await client.get("/api/team/test-team/work", headers=headers())
        assert "private-task" not in listing.text
        assert "private-only-secret" not in listing.text
        assert (await client.get(endpoint, headers=headers())).json()["state"] == "queued_manual"
    assert team_bridge.store.get("private-task")["state"] == "created"


async def test_nonmember_team_and_work_remain_inaccessible_to_local_browser(team_bridge):
    new_team(team_bridge, team_id="foreign", owner="other")
    value = team_bridge.teams.delegate(
        "other",
        TeamWorkCreate(
            team_id="foreign",
            assignee="codex",
            title="Private team",
            body="Foreign content",
            idempotency_key="foreign-work",
        ),
    )
    async with browser(team_bridge) as client:
        assert (await client.get("/api/team", headers=headers())).json()["teams"] == []
        for path in (
            "/api/team/foreign",
            "/api/team/foreign/messages",
            "/api/team/foreign/work/" + value["id"],
            "/api/team/foreign/events",
        ):
            response = await client.get(path, headers=headers())
            assert response.status_code == 404 and "Foreign content" not in response.text


async def test_catalog_reports_configuration_without_claiming_native_authentication(team_bridge):
    policy = team_bridge.config.principals["codex"]
    policy.capabilities.append("agent.execute")
    policy.agents = ["codex"]
    team_bridge.config.agents["codex"] = AgentConfig(kind="codex")
    team_bridge.config.team.workers["codex"] = TeamWorkerConfig(agent="codex", cwd="/tmp")
    team_bridge.config.team.workers["grok"] = TeamWorkerConfig(agent="grok", cwd="/tmp")
    async with browser(team_bridge) as client:
        result = (await client.get("/api/team", headers=headers())).json()
        rows = {value["principal"]: value for value in result["roster"]}
        assert result["principal"] == "local"
        assert rows["local"]["execution"] == "external"
        assert rows["codex"]["execution"] == "automatic"
        assert rows["codex"]["authentication_status"] == "unknown"
        assert rows["grok"]["execution"] == "blocked"
        team_bridge.config.team.enabled = False
        disabled = (await client.get("/api/team", headers=headers())).json()
        assert disabled["enabled"] is False and disabled["teams"] == []


@pytest.mark.parametrize("level,execution", [("full", "automatic"), ("ask", "blocked")])
async def test_roster_uses_effective_worker_permission_not_legacy_approval_mode(
    team_bridge, level, execution
):
    policy = team_bridge.config.principals["codex"]
    policy.permission_level = level
    policy.approval_mode = "manual"
    policy.capabilities.append("agent.execute")
    policy.agents = ["codex"]
    team_bridge.config.agents["codex"] = AgentConfig(kind="codex")
    team_bridge.config.team.workers["codex"] = TeamWorkerConfig(agent="codex", cwd="/tmp")
    async with browser(team_bridge) as client:
        result = (await client.get("/api/team", headers=headers())).json()
        assert (
            next(row for row in result["roster"] if row["principal"] == "codex")["execution"]
            == execution
        )


@pytest.mark.parametrize(
    "query", ["after=-1", "limit=51", "after=no", "after=1&after=2", "sender=grok"]
)
async def test_browser_page_parameters_are_bounded_and_unambiguous(team_bridge, query):
    new_team(team_bridge)
    async with browser(team_bridge) as client:
        result = await client.get("/api/team/test-team/messages?" + query, headers=headers())
        assert result.status_code == 400


async def test_browser_rejects_oversized_duplicate_nonobject_and_unknown_json(team_bridge):
    new_team(team_bridge)
    endpoint = "/api/team/test-team/messages"
    async with browser(team_bridge) as client:
        request_headers = {**headers(), "Content-Type": "application/json"}
        duplicate = '{"recipient":"codex","recipient":"grok"}'
        assert (
            await client.post(endpoint, headers=request_headers, content=duplicate)
        ).status_code == 400
        for invalid in ([], {"body": "x", "sender": "codex"}):
            assert (await client.post(endpoint, headers=headers(), json=invalid)).status_code == 400
        oversized = json.dumps({"body": "x" * MAX_REQUEST_BYTES})
        assert (
            await client.post(endpoint, headers=request_headers, content=oversized)
        ).status_code == 413
    assert team_bridge.store.db.execute("SELECT count(*) FROM team_messages").fetchone()[0] == 0
