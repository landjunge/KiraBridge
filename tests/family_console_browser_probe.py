"""Running browser acceptance for the KiraBridge family console P1 preview.

The local Bridge and all agent/version data are synthetic and isolated. No CLI is
started, no host service or user DB is touched, and the Play button is not clicked.
"""

from __future__ import annotations

import asyncio
import json
import socket
import tempfile
import time
from pathlib import Path

import uvicorn
from playwright.async_api import async_playwright

import kirabridge.approval_console as console
from kirabridge.approval_console import ApprovalConsole, signed_token
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import (
    AgentConfig,
    Config,
    PrincipalConfig,
    TeamConfig,
    TeamWorkerConfig,
)
from kirabridge.bridge_core.models import BridgeError
from kirabridge.operator_application import operator_application
from kirabridge.team_manager.models import TeamCreate

ROOT = Path(__file__).resolve().parents[1]
KEY = "family-console-browser-probe-" + "x" * 48
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
OUTPUT = ROOT / "docs/evidence/family-console-p1-20261126"


def fixture_profile(kind, model=None):
    return AgentConfig(kind=kind, executable="/bin/echo", model=model)


async def run():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kb-family-console-", dir="/private/tmp") as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        (root / "state").chmod(0o700)
        capabilities = ["bridge.health", "team.read", "team.manage", "team.write", "agent.execute"]
        principals = {
            name: PrincipalConfig(
                approval_mode="automatic",
                permission_level="full" if name == "local" else "medium",
                capabilities=capabilities.copy(),
                roots=[str(root)],
            )
            for name in ("local", "codex", "claude", "qwen")
        }
        config = Config(
            data_dir=str(root / "state"),
            principals=principals,
            agents={
                "codex": fixture_profile("codex", "gpt-5-codex"),
                "claude": fixture_profile("claude_code", "sonnet"),
                "qwen": fixture_profile("qwen_acp", "qwen3.8-flash"),
            },
            team=TeamConfig(
                enabled=True,
                workers={
                    name: TeamWorkerConfig(agent=name, cwd=str(root))
                    for name in ("local", "codex", "claude", "qwen")
                },
            ),
        )
        bridge = Bridge(config)
        bridge.teams.create(
            "local",
            TeamCreate(
                team_id="kirabridge-team",
                name="KiraBridge visual fixture",
                members={"local": "worker", "codex": "coordinator"},
                coordinator="codex",
                idempotency_key="family-console-fixture",
            ),
        )
        application = operator_application(bridge)
        control = application.control
        now = time.time()
        health = {
            "dispatcher_active": True,
            "runtime": {"version": "0.8.0rc81", "source_commit": "fixture-only"},
            "terminal_access": {"policy_authorized": True},
        }
        services = [
            {
                "id": "bridge",
                "name": "KiraBridge",
                "active": True,
                "state": "active",
                "detail": "Aktiv",
            },
            {
                "id": "codex",
                "name": "Codex",
                "active": False,
                "state": "inactive",
                "installed": True,
                "detail": "Inaktiv",
            },
            {
                "id": "claude",
                "name": "Claude",
                "active": False,
                "state": "inactive",
                "installed": True,
                "detail": "Inaktiv",
            },
            {
                "id": "qwen",
                "name": "Qwen",
                "active": False,
                "state": "inactive",
                "installed": True,
                "detail": "Inaktiv",
            },
            {
                "id": "console",
                "name": "Konsole",
                "active": True,
                "state": "active",
                "detail": "Aktiv",
            },
        ]

        async def snapshot(*, fresh=False):
            return {
                "observed_at": now,
                "services": services,
                "bridge": health,
                "release": {"version": "0.8.0rc81", "source_commit": "fixture-only"},
                "maintenance": None,
                "permission_levels": {"local": "medium", "chatgpt": "medium"},
                "permission_choices": {
                    "full": "Voll erlaubt",
                    "medium": "Mittel",
                    "ask": "Nur mit Erlaubnis",
                },
                "permission_details": {
                    "chatgpt": {"label": "Mittel"},
                    "local": {"label": "Mittel"},
                },
                "settings_loaded": True,
                "permissions_consistent": True,
                "level": "medium",
                "pending": [],
                "busy": False,
                "peers_connected": True,
            }

        async def rpc(tool, arguments=None, **kwargs):
            if tool == "agent_inventory":
                return {
                    "cli_inventory": [
                        {
                            "cli": "codex",
                            "agent_id": "codex",
                            "executable": "/bin/echo",
                            "version": "0.68.0-fixture",
                            "search_order": 0,
                            "probe_status": "observed",
                            "compatibility": {"status": "unknown"},
                        },
                        {
                            "cli": "claude",
                            "agent_id": "claude",
                            "executable": "/bin/echo",
                            "version": "2.1.332-fixture",
                            "search_order": 0,
                            "probe_status": "observed",
                            "compatibility": {"status": "unknown"},
                        },
                        {
                            "cli": "qwen",
                            "agent_id": "qwen",
                            "executable": "/bin/echo",
                            "version": "0.28.0-fixture",
                            "search_order": 0,
                            "probe_status": "observed",
                            "compatibility": {"status": "unsupported"},
                        },
                    ]
                }
            if tool == "bridge_health":
                return health
            raise BridgeError("fixture_read_only", "This visual probe does not perform actions")

        async def no_processes():
            return []

        async def no_host_command(*args, **kwargs):
            return 1, "Isolated fixture", ""

        control.snapshot = snapshot
        control.rpc = rpc
        control.processes = no_processes
        control.command = no_host_command
        control.connections = lambda: {
            "grok": {"enabled": True, "pending": []},
            "checks": [{"principal": "chatgpt", "device": "browser", "mode": "text"}],
            "chatgpt_url": "https://chatgpt.com",
            "grok_url": "https://grok.com",
        }
        app = ApprovalConsole(application, KEY)
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        console.PORT, console.ORIGIN = port, url
        server = uvicorn.Server(
            uvicorn.Config(app, log_level="error", access_log=False, lifespan="off")
        )
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            for _ in range(150):
                if server.started:
                    break
                await asyncio.sleep(0.02)
            assert server.started
            async with async_playwright() as play:
                browser = await play.chromium.launch(executable_path=str(CHROME), headless=True)
                page = await browser.new_page(
                    viewport={"width": 1728, "height": 1240}, device_scale_factor=1
                )
                errors, posts = [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "request",
                    lambda request: posts.append(request.url) if request.method == "POST" else None,
                )
                await page.add_init_script(
                    "localStorage.setItem('kirabridge.session', %s)"
                    % json.dumps(signed_token(KEY, "session"))
                )
                await page.goto(url, wait_until="networkidle")
                await page.wait_for_function(
                    "document.querySelectorAll('.voice-card').length===2 && "
                    "document.querySelectorAll('.cli-card').length===3"
                )
                assert await page.locator(".np-appbar-button").count() == 5
                assert (
                    await page.locator(
                        '.cli-card[data-agent="codex"] .coordinator[aria-pressed="true"]'
                    ).count()
                    == 1
                )
                assert (
                    "Kompatibilität nicht bestätigt"
                    in await page.locator(
                        '.cli-card[data-agent="qwen"] .compatibility'
                    ).inner_text()
                )
                effort_options = (
                    '.cli-card[data-agent="qwen"] .cli-controls select[aria-label="Denkstufe"] '
                    "option"
                )
                assert await page.locator(effort_options).count() == 1
                assert await page.locator('.cli-card[data-agent="codex"] .play').is_enabled()
                await page.locator('[data-go="settings"]').click()
                assert await page.locator("#settings").is_visible()
                assert "Darstellung" in await page.locator("#settings").inner_text()
                await page.locator('#settings [data-go="overview"]').click()
                left = page.locator('[data-resize="left"]')
                await left.focus()
                await page.keyboard.press("ArrowRight")
                assert await left.get_attribute("aria-valuenow") == "216"
                await page.keyboard.press("ArrowLeft")
                assert await left.get_attribute("aria-valuenow") == "208"
                await page.locator('.kb-header-actions [data-panel-toggle="left"]').click()
                assert "left-collapsed" in (
                    await page.locator("#family-workspace").get_attribute("class")
                )
                await page.locator('.kb-header-actions [data-panel-toggle="left"]').click()
                await page.locator('.kb-header-actions [data-panel-toggle="right"]').click()
                assert "right-collapsed" in (
                    await page.locator("#family-workspace").get_attribute("class")
                )
                await page.locator('.kb-header-actions [data-panel-toggle="right"]').click()
                await page.wait_for_timeout(100)
                geometry = await page.locator("#family-workspace").evaluate(
                    """e => {
                      const box = (selector) => e.querySelector(selector).getBoundingClientRect();
                      const w = e.getBoundingClientRect();
                      return {
                        viewport: [innerWidth, innerHeight], workspace: [w.width, w.height],
                        left: box('#process-panel').width, center: box('.main-panel').width,
                        right: box('#details-panel').width,
                        bodyBg: getComputedStyle(document.body).backgroundColor,
                        rounding: getComputedStyle(e.querySelector('.cli-card')).borderRadius
                      };
                    }"""
                )
                assert (
                    176 <= geometry["left"] <= 220
                    and geometry["center"] >= 670
                    and 292 <= geometry["right"] <= 370
                ), geometry
                assert geometry["bodyBg"] == "rgb(18, 19, 22)" and geometry["rounding"] == "0px", (
                    geometry
                )
                assert not posts and not errors, {"posts": posts, "errors": errors}
                screenshot = OUTPUT / "kirabridge-console-p1-1728x1240.png"
                await page.screenshot(path=str(screenshot), full_page=False)
                await browser.close()
            return {
                "status": "passed",
                "screenshot": str(screenshot),
                "window": "1728x1240",
                "synthetic_data": True,
                "no_cli_started": True,
                "geometry": geometry,
            }
        finally:
            server.should_exit = True
            await asyncio.wait_for(serving, timeout=15)
            bridge.store.close()
            listener.close()


if __name__ == "__main__":
    result = asyncio.run(run())
    print(json.dumps(result, ensure_ascii=False, indent=2))
