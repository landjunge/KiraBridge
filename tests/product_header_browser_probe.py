"""Real browser/HTTP header acceptance with an isolated, actually running Bridge.

No operator config, installed service, existing terminal, external agent or user DB
is used. Connected/offline comes from starting/stopping only the fixture dispatcher.
Maintenance/error are explicitly marked presentation fault injections.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import socket
import tempfile
from pathlib import Path

import uvicorn
from playwright.async_api import async_playwright

import kirabridge.approval_console as console
from kirabridge import __version__
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config, PrincipalConfig
from kirabridge.bridge_core.models import BridgeError
from kirabridge.operator_application import operator_application

IDS = ["kirabridge", "threaddesk", "4allpass", "tollgate", "agent-authority"]
KEY = "isolated-header-browser-key-" + "x" * 48


async def run(output: Path, executable: str, legacy_headless: bool = False):
    output.mkdir(parents=True, exist_ok=True)
    checks, errors, screenshots, posts = [], [], [], []
    with tempfile.TemporaryDirectory(prefix="kb-design-header-", dir=output) as temporary:
        policy = PrincipalConfig(capabilities=["bridge.health"], roots=[temporary])
        bridge = Bridge(
            Config(data_dir=str(Path(temporary) / "state"), principals={"local": policy})
        )
        application = operator_application(bridge)
        control = application.control
        mode = {"value": "normal"}

        async def rpc(operation, *args, **kwargs):
            if mode["value"] == "error":
                raise BridgeError("fixture_transport_failure", "Injected isolated transport fault")
            if operation == "bridge_health":
                return bridge.health("local")
            raise BridgeError(
                "fixture_operation_disabled", "No OS/agent execution in UI acceptance"
            )

        async def no_processes():
            return []

        async def no_host_command(*args, **kwargs):
            return 1, "No host-service lookup in isolated fixture", ""

        control.rpc, control.processes, control.command = rpc, no_processes, no_host_command
        control.maintenance = lambda: (
            {"state": "isolated-presentation-fixture"} if mode["value"] == "busy" else None
        )
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        console.PORT, console.ORIGIN = port, url
        app = console.ApprovalConsole(application, KEY)
        server = uvicorn.Server(
            uvicorn.Config(app, log_level="error", access_log=False, lifespan="off")
        )
        await bridge.tasks.start()
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            for _ in range(100):
                if server.started:
                    break
                await asyncio.sleep(0.02)
            assert server.started
            async with async_playwright() as play:
                context = await play.chromium.launch_persistent_context(
                    str(Path(temporary) / "browser-profile"),
                    executable_path=executable,
                    args=["--single-process", "--no-zygote", "--disable-gpu"]
                    + (["--headless=old"] if legacy_headless else []),
                    viewport={"width": 1280, "height": 900},
                    reduced_motion="reduce",
                )
                page = context.pages[0]
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "request",
                    lambda request: posts.append(request.url) if request.method == "POST" else None,
                )

                async def header_ready(state=None):
                    await page.wait_for_function(
                        "document.querySelectorAll('.np-appbar-button').length===5"
                    )
                    await page.wait_for_function(
                        "[...document.querySelectorAll('.np-appbar-ring img')]"
                        ".every(i=>i.complete&&i.naturalWidth===256)"
                    )
                    if state:
                        await page.wait_for_function(
                            "state=>document.querySelector('[data-app-id=kirabridge]').dataset.state===state",
                            arg=state,
                            timeout=12000,
                        )
                    actual = await page.locator(".np-appbar-button").evaluate_all(
                        "es=>es.map(e=>e.dataset.appId)"
                    )
                    assert actual == IDS, actual

                async def capture(name):
                    path = output / (name + ".png")
                    await page.screenshot(path=str(path))
                    screenshots.append(
                        {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                    )

                await page.goto(url)
                await header_ready("unknown")
                assert (
                    await page.locator("[data-app-id=kirabridge] .np-appbar-version").inner_text()
                    == "v?"
                )
                unauth = await context.request.get(url + "/api/control/status")
                assert unauth.status == 401
                await capture("control-unauthenticated-1280")
                checks.append(
                    {
                        "name": "unauthenticated header is unknown; actual control API401",
                        "passed": True,
                    }
                )
                login = await context.request.post(
                    url + "/login",
                    form={"ticket": console.signed_token(KEY, "login:" + app.instance)},
                    headers={"Origin": url},
                )
                assert login.status == 200
                session = re.search(r'data-session="([^"]+)"', await login.text()).group(1)
                await page.evaluate(
                    "token=>localStorage.setItem('kirabridge.session',token)", session
                )
                await page.reload()
                await header_ready("confirmed")
                version = await page.locator(
                    "[data-app-id=kirabridge] .np-appbar-version"
                ).inner_text()
                assert version == "v" + __version__, version
                for scheme in ["dark", "light"]:
                    await page.emulate_media(color_scheme=scheme)
                    for width in [1280, 390, 320]:
                        await page.set_viewport_size({"width": width, "height": 900})
                        for route, label in [
                            ("/", "control"),
                            ("/protocol", "protocol"),
                            ("/team", "team"),
                            ("/grok-connector", "connector"),
                        ]:
                            await page.goto(url + route)
                            await header_ready("confirmed")
                            for product in IDS:
                                button = page.locator(f'[data-app-id="{product}"]')
                                bounds = await button.bounding_box()
                                assert (
                                    bounds and bounds["width"] == 44 and bounds["height"] == 56
                                ), (route, width, bounds)
                                assert (
                                    bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width
                                ), (route, width, product, bounds)
                                if product != "kirabridge":
                                    assert await button.get_attribute("data-state") == "unknown"
                                    assert (
                                        await button.locator(".np-appbar-version").inner_text()
                                        == "v?"
                                    )
                            colors = await page.locator("body").evaluate(
                                "e=>({fg:getComputedStyle(e).color,bg:getComputedStyle(e).backgroundColor})"
                            )
                            assert colors["fg"] == "rgb(237, 240, 244)", (route, scheme, colors)
                            assert colors["bg"] == "rgb(0, 0, 0)", (route, scheme, colors)
                            button = page.locator('[data-app-id="threaddesk"]')
                            await button.focus()
                            await page.keyboard.press("Enter")
                            await page.locator("dialog[open]").wait_for()
                            assert await page.locator("dialog h2").inner_text() == "ThreadDesk"
                            await page.keyboard.press("Escape")
                            assert await button.evaluate("e=>e===document.activeElement")
                            await page.keyboard.press("Tab")
                            assert await page.locator('[data-app-id="4allpass"]').evaluate(
                                "e=>e===document.activeElement"
                            )
                            await page.keyboard.press("Space")
                            await page.locator("dialog[open]").wait_for()
                            await page.keyboard.press("Escape")
                            await page.keyboard.press("Tab")
                            assert await page.locator('[data-app-id="tollgate"]').evaluate(
                                "e=>e===document.activeElement"
                            )
                            await page.keyboard.press("Enter")
                            await page.locator("dialog[open]").wait_for()
                            assert await page.locator("dialog h2").inner_text() == "TollGate"
                            await page.keyboard.press("Escape")
                            await page.keyboard.press("Tab")
                            assert await page.locator('[data-app-id="agent-authority"]').evaluate(
                                "e=>e===document.activeElement"
                            )
                            await page.keyboard.press("Space")
                            await page.locator("dialog[open]").wait_for()
                            await page.keyboard.press("Escape")
                            # Exercise actual pointer activation as well as keyboard
                            # activation on every unconfigured foreign product.
                            # Existing appbar contract debounces the same product
                            # for 600ms; this is a separate pointer action round.
                            await page.wait_for_timeout(650)
                            for peer in IDS[1:]:
                                await page.locator(f'[data-app-id="{peer}"]').click()
                                await page.locator("dialog[open]").wait_for()
                                assert await page.locator("dialog h2").inner_text()
                                await page.keyboard.press("Escape")
                            german_button = page.locator('[data-language="de"]')
                            if await german_button.count():
                                await german_button.click()
                            else:
                                await page.evaluate("document.documentElement.lang='de'")
                            await page.wait_for_function(
                                "document.querySelector('.np-appbar').lang==='de'"
                            )
                            assert "Version unbekannt" in await page.locator(
                                '[data-app-id="threaddesk"]'
                            ).get_attribute("aria-label")
                            await page.evaluate("window.scrollTo(0,document.body.scrollHeight)")
                            await page.wait_for_timeout(50)
                            for product in IDS:
                                bounds = await page.locator(
                                    f'[data-app-id="{product}"]'
                                ).bounding_box()
                                assert bounds and 0 <= bounds["y"] < 844, (route, width, bounds)
                            await page.evaluate("window.scrollTo(0,0)")
                            language_button = page.locator('[data-language="en"]')
                            if await language_button.count():
                                await language_button.click()
                            else:
                                # These existing views have no locale switch. Exercise the
                                # header's documented host-language input, not a fictional UI.
                                await page.evaluate("document.documentElement.lang='en'")
                            await page.wait_for_function(
                                "document.querySelector('.np-appbar').lang==='en'"
                            )
                            assert "Version unknown" in await page.locator(
                                '[data-app-id="threaddesk"]'
                            ).get_attribute("aria-label")
                            await capture(f"{label}-{scheme}-{width}")
                            # The actual product icon returns to the existing control route,
                            # or focuses its current main without reloading user input.
                            if route == "/":
                                await page.locator('[data-app-id="kirabridge"]').click()
                                assert await page.locator("main").evaluate(
                                    "e=>e===document.activeElement"
                                )
                            else:
                                async with page.expect_navigation():
                                    await page.locator('[data-app-id="kirabridge"]').click()
                                assert page.url.rstrip("/") == url
                            checks.append(
                                {
                                    "name": (
                                        f"{route} {scheme} {width}: five originals, "
                                        "own authenticated status/version, "
                                        "foreign unknown, DE/EN, scroll visibility, "
                                        "keys/focus/pointer"
                                    ),
                                    "passed": True,
                                }
                            )
                await page.set_viewport_size({"width": 1280, "height": 900})
                await page.goto(url)
                await header_ready("confirmed")
                await bridge.tasks.stop()
                control.cache = None
                await header_ready("disconnected")
                await capture("control-real-dispatcher-stopped")
                checks.append(
                    {
                        "name": "actual isolated dispatcher stop removes connected glow",
                        "passed": True,
                    }
                )
                await bridge.tasks.start()
                control.cache = None
                await header_ready("confirmed")
                mode["value"] = "busy"
                control.cache = None
                await header_ready("busy")
                await capture("control-synthetic-maintenance-presentation")
                mode["value"] = "error"
                control.cache = None
                await header_ready("error")
                await capture("control-injected-transport-error")
                checks.append(
                    {
                        "name": (
                            "injected maintenance/error metadata renders busy/error; "
                            "no peer state fabricated"
                        ),
                        "passed": True,
                    }
                )
                mode["value"] = "normal"
                control.cache = None
                await page.evaluate("localStorage.removeItem('kirabridge.session')")
                await header_ready("unknown")
                await capture("control-session-removed-unknown")
                checks.append(
                    {
                        "name": "removed real browser session invalidates status/version",
                        "passed": True,
                    }
                )
                assert not errors, errors
                assert all(path.endswith("/login") for path in posts), posts
                result = {
                    "status": "passed",
                    "browser": await page.evaluate("navigator.userAgent"),
                    "engine": (
                        "Chromium legacy headless, single-process persistent context; "
                        "worker sandbox unchanged"
                    )
                    if legacy_headless
                    else (
                        "Chromium headless shell single-process persistent context; "
                        "worker sandbox unchanged"
                    ),
                    "url": url,
                    "runtimeSourceVersion": __version__,
                    "views": ["/", "/protocol", "/team", "/grok-connector"],
                    "checks": checks,
                    "screenshots": screenshots,
                    "pageErrors": errors,
                    "productActionPosts": posts,
                    "productionServicesChanged": False,
                    "foreignPeerAcceptance": False,
                    "fixtureBoundary": (
                        "Real loopback HTTP/auth/UI/control handlers and actual "
                        "isolated Bridge dispatcher. OS process inventory disabled. "
                        "Only maintenance/error metadata is deliberately injected "
                        "for presentation checks."
                    ),
                }
                (output / "browser-checks.json").write_text(json.dumps(result, indent=2) + "\n")
                await context.close()
                print(
                    json.dumps(
                        {
                            "status": "passed",
                            "checks": len(checks),
                            "screenshots": len(screenshots),
                            "evidence": str(output),
                        }
                    )
                )
        except BaseException as error:
            (output / "browser-failure.json").write_text(
                json.dumps(
                    {
                        "status": "failed",
                        "error": str(error),
                        "checks": checks,
                        "screenshots": screenshots,
                        "pageErrors": errors,
                    },
                    indent=2,
                )
                + "\n"
            )
            raise
        finally:
            server.should_exit = True
            await asyncio.wait_for(serving, 10)
            if bridge.tasks.workers:
                await bridge.tasks.stop()
            bridge.store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chromium", required=True)
    parser.add_argument(
        "--legacy-headless",
        action="store_true",
        help="Existing Chromium130 legacy headless mode; no binary or OS policy changes",
    )
    args = parser.parse_args()
    asyncio.run(run(args.output.resolve(), args.chromium, args.legacy_headless))
