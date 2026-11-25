"""Bounded real HTTP/browser layout probe; native switch is explicitly simulated.

No dispatcher, product CLI, user config or application inventory is started/read.
The browser sees the actual CSP/assets and four production page templates.
"""

import argparse
import asyncio
import hashlib
import json
import socket
import tempfile
from pathlib import Path

import uvicorn
from playwright.async_api import async_playwright

import kirabridge.approval_console as console
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config, PrincipalConfig
from kirabridge.operator_application import operator_application


async def run(output, browser, receipt_only=False):
    output.mkdir(parents=True, exist_ok=True)
    errors, checks, screenshots = [], [], []
    with tempfile.TemporaryDirectory(prefix="kb-family-header-") as temporary:
        bridge = Bridge(
            Config(
                data_dir=str(Path(temporary).resolve() / "state"),
                principals={"local": PrincipalConfig()},
            )
        )
        app = console.ApprovalConsole(operator_application(bridge), "fixture-only-" + "x" * 48)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        url = "http://127.0.0.1:" + str(listener.getsockname()[1])
        console.PORT, console.ORIGIN = listener.getsockname()[1], url
        server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="error"))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            while not server.started:
                await asyncio.sleep(0.02)
            async with async_playwright() as play:
                instance = await play.chromium.launch(
                    executable_path=browser,
                    headless=True,
                    args=["--single-process", "--no-zygote", "--disable-gpu"],
                )
                context = await instance.new_context(reduced_motion="reduce")
                page = await context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                viewports = [] if receipt_only else [(940, 636), (1358, 664), (320, 664)]
                for width, height in viewports:
                    await page.set_viewport_size({"width": width, "height": height})
                    for route, name in [
                        ("/", "control"),
                        ("/team", "team"),
                        ("/protocol", "protocol"),
                        ("/grok-connector", "connector"),
                    ]:
                        await page.goto(url + route)
                        await page.wait_for_function(
                            "() => document.querySelectorAll('.np-appbar-button').length===5"
                        )
                        await page.wait_for_function(
                            "() => [...document.querySelectorAll('.np-appbar-ring img')]"
                            ".every(e=>e.complete&&e.naturalWidth===256)"
                        )
                        geometry = await page.evaluate("""() => {
                          const rect = s => {
                            const r=document.querySelector(s).getBoundingClientRect();
                            return {x:r.x,y:r.y,width:r.width,height:r.height};
                          };
                          return {bar:rect('.np-appbar'),wordmark:rect('.kb-wordmark'),
                            language:rect('.kb-language'),
                            overflow:document.documentElement.scrollWidth>innerWidth,
                            buttons:[...document.querySelectorAll('.np-appbar-button')].map(e=>({width:e.offsetWidth,height:e.offsetHeight})),
                            main:document.querySelector('.main-panel')?.getBoundingClientRect().height};
                        }""")
                        assert not geometry["overflow"], (route, width, geometry)
                        assert all(r == {"width": 44, "height": 44} for r in geometry["buttons"])
                        if width >= 940:
                            assert (
                                abs(geometry["bar"]["x"] + geometry["bar"]["width"] / 2 - width / 2)
                                <= 1
                            ), geometry
                            assert (
                                geometry["wordmark"]["x"] + geometry["wordmark"]["width"]
                                <= geometry["bar"]["x"]
                            )
                            assert (
                                geometry["language"]["x"]
                                >= geometry["bar"]["x"] + geometry["bar"]["width"]
                            )
                            if route == "/":
                                assert geometry["main"] > 250, geometry
                        for language in ["en", "de"]:
                            await page.locator(
                                f'.kb-language button[data-language="{language}"],'
                                f'.kb-language button[data-kb-language="{language}"]'
                            ).click()
                            await page.wait_for_function(
                                "value=>document.documentElement.lang===value", arg=language
                            )
                            await page.wait_for_function(
                                "value=>document.querySelector('.np-appbar').lang===value",
                                arg=language,
                            )
                        await page.locator('[data-app-id="threaddesk"]').focus()
                        await page.keyboard.press("Enter")
                        await page.wait_for_function(
                            "() => document.querySelector('[data-app-id=threaddesk]')"
                            ".getAttribute('aria-label').includes('Öffnen nicht verfügbar')"
                        )
                        assert (
                            await page.locator('[data-app-id="threaddesk"]').get_attribute(
                                "data-state"
                            )
                            == "unknown"
                        )
                        checks.append(
                            {
                                "route": route,
                                "width": width,
                                "height": height,
                                "passed": True,
                                "geometry": geometry,
                            }
                        )
                        if width == 940:
                            file = output / (name + "-940.png")
                            await page.screenshot(path=str(file))
                            screenshots.append(
                                {
                                    "file": file.name,
                                    "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
                                }
                            )
                # Receipt delay exceeds the old 2s renderer timeout. The stub
                # simulates native completion only; it never invokes a product.
                await context.add_init_script(
                    "window.__kbFamilyCalls=[];window.__kbFamilySwitch=id=>{"
                    "window.__kbFamilyCalls.push(id);"
                    "return new Promise(r=>setTimeout(()=>r('focused'),3500));}"
                )
                await page.goto(url)
                await page.locator('[data-app-id="threaddesk"]').click()
                await page.wait_for_function(
                    "() => document.querySelector('[data-app-id=threaddesk]')"
                    ".getAttribute('aria-label').includes('App fokussiert')",
                    timeout=7000,
                )
                assert await page.evaluate("window.__kbFamilyCalls") == ["threaddesk"]
                assert (
                    await page.locator('[data-app-id="threaddesk"]').get_attribute("data-state")
                    == "unknown"
                )
                assert not errors, errors
                checks.append(
                    {
                        "name": "simulated 3.5s native receipt accepted without peer confirmation",
                        "passed": True,
                    }
                )
                await instance.close()
        finally:
            server.should_exit = True
            await serving
            bridge.store.close()
    result = {
        "checks": checks,
        "screenshots": screenshots,
        "page_errors": errors,
        "native_switch_simulated": True,
        "product_window_effects": 0,
        "installed_runtime_acceptance": False,
    }
    (output / "result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({"checks": len(checks), "page_errors": errors, "output": str(output)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser", required=True)
    parser.add_argument("--receipt-only", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.output, args.browser, args.receipt_only))
