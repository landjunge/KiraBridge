"""Coordinator controls read back the actual role and authenticate handover requests."""

import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from test_team_console import KEY, headers, new_team, team_bridge  # noqa: F401

from kirabridge.approval_console import ASSETS, ORIGIN, ApprovalConsole
from kirabridge.operator_application import operator_application

ROUTE = "/api/team/test-team/coordinator"


def test_coordinator_panel_keeps_parallel_sessions_and_waits_for_confirmed_handover():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed to exercise the coordinator browser behavior")
    harness = Path(__file__).with_name("fixtures") / "coordinator_console" / "browser.cjs"
    result = subprocess.run(
        [node, str(harness), str(ASSETS / "coordinator.js")],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr


async def test_coordinator_console_retains_auth_and_local_origin(team_bridge):  # noqa: F811
    new_team(team_bridge)
    app = ApprovalConsole(operator_application(team_bridge), KEY)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as client:
        page = await client.get("/")
        assert 'data-view="agents"' in page.text
        assert (await client.get("/coordinator.js")).status_code == 200
        assert (await client.get(ROUTE)).status_code == 401
        assert (await client.post(ROUTE + "/handoff", json={})).status_code == 401
        assert (
            await client.post(
                ROUTE + "/handoff",
                headers={**headers(), "Origin": "https://outside.example"},
                json={},
            )
        ).status_code == 403
    transport = httpx.ASGITransport(app=app, client=("203.0.113.4", 4321))
    async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as remote:
        assert (await remote.get(ROUTE, headers=headers())).status_code == 403
