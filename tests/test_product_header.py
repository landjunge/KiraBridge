"""Original header assets must load under the console's real CSP and MIME guard."""

import hashlib
import json
from pathlib import Path

import httpx

from kirabridge.approval_console import ORIGIN, ApprovalConsole
from kirabridge.operator_application import operator_application


async def test_all_five_original_images_are_served_under_existing_console_boundary(bridge):
    app = ApprovalConsole(operator_application(bridge), "isolated-five-tool-key-" + "x" * 48)
    assets = Path(__file__).resolve().parents[1] / "src/kirabridge/console_assets"
    manifest = json.loads((assets / "networkpunkt-appbar-assets.json").read_text())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        page = await client.get("/")
        assert page.text.count("data-product-header") == 1
        assert "img-src 'self'" in page.headers["content-security-policy"]
        assert "unsafe-inline" not in page.headers["content-security-policy"]
        for item in manifest["files"]:
            response = await client.get("/" + item["file"])
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/png"
            assert hashlib.sha256(response.content).hexdigest() == item["sha256"]
        assert (await client.get("/networkpunkt-product-header.js")).status_code == 200
        wordmark = await client.get("/kirabridge-wordmark.svg")
        assert wordmark.headers["content-type"] == "image/svg+xml"
        original = assets.parents[2] / "assets/design/wordmarks/KiraBridge-dark.svg"
        assert wordmark.content == original.read_bytes()
        assert (await client.get("/api/control/status")).status_code == 401
