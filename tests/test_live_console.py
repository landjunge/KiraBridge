"""KiraBridge Live page and the authorized control endpoint expose the real projection.

The console endpoint runs the real ``project()``/``logs.live`` path; only the
daemon socket transport is replaced with an in-process call, so a regression that
stops projecting or drops the capability check fails here.
"""

from types import SimpleNamespace

import httpx
from test_keyboard_console import console

from kirabridge.approval_console import ORIGIN
from kirabridge.live_status import project

STABLE = ("task_id", "principal", "family", "state", "step", "source")


def _app(bridge, config, monkeypatch):
    app, _, _, headers = console(bridge, config, monkeypatch)
    service = app.control_center.service

    async def call(name, **_kwargs):
        if name == "live_status":
            return project(bridge, "local")
        raise AssertionError(name)

    async def rpc(*args, **kwargs):
        return await service.daemon.call(*args, **kwargs)

    # The shared test helper replaces rpc with a keyboard fixture; restore the
    # real daemon path so this test exercises project()/logs.live, not a mock.
    service.daemon = SimpleNamespace(call=call)
    service.rpc = rpc
    if "logs.live" not in config.principals["local"].capabilities:
        config.principals["local"].capabilities.append("logs.live")
    return app, headers


async def test_live_page_assets_and_real_projection(bridge, config, monkeypatch):
    app, headers = _app(bridge, config, monkeypatch)
    bridge.live_logs.open("t1", "local", operation="agent.execute", agent="codex")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        page = await client.get("/live", headers=headers)
        assert page.status_code == 200 and "KiraBridge Live" in page.text
        assert (await client.get("/live.js", headers=headers)).status_code == 200
        live_js = (await client.get("/live.js", headers=headers)).text
        assert "nicht wiederholt" in live_js
        assert (await client.get("/live.css", headers=headers)).status_code == 200
        assert (await client.get("/api/control/live")).status_code == 401
        result = await client.get("/api/control/live", headers=headers)
        direct = project(bridge, "local")
        assert result.status_code == 200
        assert [{k: a[k] for k in STABLE} for a in result.json()["agents"]] == [
            {k: a[k] for k in STABLE} for a in direct["agents"]
        ]
        assert result.json()["summary_text"] == direct["summary_text"]


async def test_console_live_endpoint_denies_without_the_capability(bridge, config, monkeypatch):
    app, headers = _app(bridge, config, monkeypatch)
    config.principals["local"].capabilities.remove("logs.live")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        denied = await client.get("/api/control/live", headers=headers)
        assert denied.status_code == 503
        assert denied.json()["error"]["code"] == "forbidden"


async def test_page_separates_turn_end_from_acceptance_and_names_gaps(bridge, config, monkeypatch):
    app, headers = _app(bridge, config, monkeypatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        page = await client.get("/live", headers=headers)
        assert "keine bestätigte Facharbeit" in page.text
        assert "Fachliche Abnahme: nicht bewertet" in page.text
        assert 'id="live-gap"' in page.text


async def test_endpoint_shows_a_nonzero_exit_as_blocked_not_completed(bridge, config, monkeypatch):
    app, headers = _app(bridge, config, monkeypatch)
    bridge.live_logs.open("bad", "local", operation="agent.execute", agent="codex")
    bridge.live_logs.close("bad", exit_code=2)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        result = await client.get("/api/control/live", headers=headers)
        agent = result.json()["agents"][0]
        assert agent["state"] == "blocked" and agent["exit_code"] == 2
        assert agent["failure"] == "exit_code" and agent["acceptance"] == "not_evaluated"
        assert result.json()["coverage"]["observed_sources"] == [
            "live_observation",
            "durable_task",
        ]
