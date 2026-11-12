"""KiraBridge Live page and authorized control endpoint expose the same projection."""

import httpx
from test_keyboard_console import console

from kirabridge.approval_console import ORIGIN

PROJECTION = {
    "ok": True,
    "observed_at": 1700000000.0,
    "count": 1,
    "truncated": False,
    "counts": {"working": 1},
    "agents": [
        {
            "task_id": "t1",
            "agent": "codex",
            "family": "codex",
            "transport": "codex",
            "operation": "agent.execute",
            "state": "working",
            "step": "working",
            "observed_at": 1700000000.0,
            "age_seconds": 1.0,
            "stale": False,
            "unknown": False,
            "source": "live_observation",
        }
    ],
    "summary_text": "codex · working · working · t1",
    "scope": "read-only live projection",
}


def _console(bridge, config, monkeypatch):
    app, _, _, headers = console(bridge, config, monkeypatch)

    async def live_rpc(name, **_kwargs):
        if name == "live_status":
            return PROJECTION
        raise AssertionError(name)

    monkeypatch.setattr(app.control_center.service, "rpc", live_rpc)
    return app, headers


async def test_live_page_assets_and_authorized_endpoint(bridge, config, monkeypatch):
    app, headers = _console(bridge, config, monkeypatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        page = await client.get("/live", headers=headers)
        assert page.status_code == 200 and "KiraBridge Live" in page.text
        assert (await client.get("/live.js", headers=headers)).status_code == 200
        assert (await client.get("/live.css", headers=headers)).status_code == 200
        assert (await client.get("/api/control/live")).status_code == 401
        result = await client.get("/api/control/live", headers=headers)
        assert result.status_code == 200
        assert result.json()["agents"][0]["family"] == "codex"
        assert result.json()["summary_text"] == PROJECTION["summary_text"]
