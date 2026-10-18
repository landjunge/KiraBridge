"""Only console assets and operator presentation; no runtime or grants."""

import hashlib

import httpx

from kirabridge.approval_console import ORIGIN, ApprovalConsole


async def test_shared_design_is_exact_local_asset_with_existing_security(bridge):
    app = ApprovalConsole(bridge, "isolated-console-design-key-" + "x" * 48)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        index = await client.get("/")
        core = await client.get("/networkpunkt.css")
        assert '<link rel="stylesheet" href="/networkpunkt.css">' in index.text
        assert core.status_code == 200 and core.headers["content-type"].startswith("text/css")
        assert hashlib.sha256(core.content).hexdigest() == (
            "98371bd9edc96fb940a0e0de34933740fed1062b510aa516498fcb53e112591e"
        )
        assert "frame-ancestors 'none'" in core.headers["content-security-policy"]
        assert "unsafe-inline" not in core.headers["content-security-policy"]
        assert (await client.get("/api/tasks")).status_code == 401
        assert (await client.get("/../../bridge_core/config.py")).status_code == 404
