"""Real Chrome console probe with isolated server and synthetic recorded tasks.

Uses existing compatible environments: KB_CONSOLE_TEST_PYTHON starts the fixture
server; this interpreter provides Playwright. No packages or services installed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = (
    ROOT
    / "dist/console-ui-checks"
    / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
)
OUT.mkdir(parents=True)


async def wait_message(page, fragment):
    await page.wait_for_function(
        "value => document.querySelector('#message').textContent.includes(value)", arg=fragment
    )


async def wait_state(page, task_id, state):
    await page.wait_for_function(
        "value => Array.from(document.querySelectorAll('[data-task-id]')).some("
        "node => node.dataset.taskId === value.id && node.dataset.state === value.state)",
        arg={"id": task_id, "state": state},
    )


async def task_value(context, url, session, identity):
    answer = await context.request.get(
        url + "/api/tasks/" + identity, headers={"Authorization": "Bearer " + session}
    )
    assert answer.status == 200
    return (await answer.json())["task"]


async def approve_from_other_client(context, url, session, identity):
    headers = {
        "Authorization": "Bearer " + session,
        "Origin": url,
        "Content-Type": "application/json",
    }
    details = await context.request.get(url + "/api/tasks/" + identity, headers=headers)
    payload = await details.json()
    answer = await context.request.post(
        url + "/api/tasks/" + identity + "/approve",
        headers=headers,
        data=json.dumps({"request_hash": payload["request_hash"]}),
    )
    assert answer.status == 200


async def run():
    executable = os.environ.get("KB_CONSOLE_TEST_PYTHON")
    if not executable or not Path(executable).is_file():
        raise RuntimeError("Set KB_CONSOLE_TEST_PYTHON to an existing KiraBridge interpreter.")
    with TemporaryDirectory(prefix="kirabridge-console-ui-") as temporary:
        root = Path(temporary)
        workspace = root / "workspace"
        server = await asyncio.create_subprocess_exec(
            executable,
            str(ROOT / "tests/console_fixture_server.py"),
            str(root),
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            stdout=subprocess.DEVNULL,
            stderr=(OUT / "fixture.log").open("w"),
        )
        for _ in range(150):
            if (root / "fixture.json").exists():
                break
            if server.returncode is not None:
                raise RuntimeError(
                    "Synthetic console fixture failed; inspect isolated fixture.log."
                )
            await asyncio.sleep(0.02)
        if not (root / "fixture.json").exists():
            server.terminate()
            await asyncio.wait_for(server.wait(), timeout=10)
            raise RuntimeError("Synthetic console fixture did not become ready.")
        fixture = json.loads((root / "fixture.json").read_text())
        url = fixture["url"]
        checks = []
        try:
            async with async_playwright() as play:
                browser = await play.chromium.launch(channel="chrome")
                errors = []
                posts = []
                session = None
                for theme in ("dark", "light"):
                    context = await browser.new_context(
                        color_scheme=theme,
                        reduced_motion="reduce",
                        locale="de-DE",
                        viewport={"width": 1180, "height": 900},
                    )
                    page = await context.new_page()
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    await page.goto(url)
                    await wait_message(page, "anzumelden")
                    assert await page.locator("article").count() == 0
                    if session is None:
                        ticket = fixture["ticket"]
                        login = await context.request.post(
                            url + "/login", form={"ticket": ticket}, headers={"Origin": url}
                        )
                        body = await login.text()
                        assert login.status == 200 and "synthetic-console-browser-key" not in body
                        session = re.search(r'data-session="([^"]+)"', body).group(1)
                    await page.evaluate(
                        "value => localStorage.setItem('kirabridge.session', value)", session
                    )
                    await page.reload()
                    await page.wait_for_function(
                        "() => document.querySelectorAll('article').length === 10"
                    )
                    assert (
                        "Ohne zusätzlichen Freigabeklick: ChatGPT"
                        in await page.locator("#approval-mode").inner_text()
                    )
                    assert (
                        "Mit Freigabe je neuem Auftrag: lokaler Zugang"
                        in await page.locator("#approval-mode").inner_text()
                    )
                    expected = "rgb(18, 19, 22)" if theme == "dark" else "rgb(245, 246, 248)"
                    assert (
                        await page.locator("body").evaluate(
                            "el => getComputedStyle(el).backgroundColor"
                        )
                        == expected
                    )
                    assert (
                        await page.locator("#refresh").evaluate("el => getComputedStyle(el).height")
                        == "40px"
                    )
                    assert (
                        await page.locator("h1").evaluate("el => getComputedStyle(el).fontSize")
                        == "24px"
                    )
                    assert (
                        await page.locator("#refresh").evaluate(
                            "el => getComputedStyle(el).transitionDuration"
                        )
                        == "0s"
                    )
                    assert (
                        "Gesamtauftrag ist damit nicht abgenommen"
                        in await page.locator('[data-task-id="completed-agent"]').inner_text()
                    )
                    await page.locator('[data-language="en"]').click()
                    assert await page.locator("html").get_attribute("lang") == "en"
                    assert (
                        "Agent turn ended"
                        in await page.locator('[data-task-id="completed-agent"]').inner_text()
                    )
                    assert (
                        "Do not restart automatically"
                        in await page.locator('[data-task-id="unknown-task"]').inner_text()
                    )
                    assert await page.locator('[data-task-id="unknown-task"] button').count() == 0
                    await page.screenshot(path=str(OUT / (theme + "-en.png")))
                    if theme == "dark":
                        target = page.locator('[data-task-id="pending-approve"]')
                        await target.locator(":scope > details > summary").press("Enter")
                        await target.locator("pre").first.wait_for()
                        assert "<img" in await target.inner_text()
                        assert await target.locator("pre").first.get_attribute("tabindex") == "0"
                        assert await target.locator("pre").first.get_attribute("aria-label")
                        assert await target.locator("img").count() == 0
                        assert not await page.evaluate("() => Boolean(window.__consoleInjected)")
                        await target.get_by_role(
                            "button", name="Approve this task", exact=True
                        ).click()
                        await wait_state(page, "pending-approve", "queued")
                        assert (await task_value(context, url, session, "pending-approve"))[
                            "state"
                        ] == "queued"
                        assert await page.locator("#refresh").evaluate(
                            "el => el === document.activeElement"
                        )
                        denied = page.locator('[data-task-id="pending-deny"]')
                        await denied.locator(":scope > details > summary").click()
                        await denied.get_by_role("button", name="Deny", exact=True).click()
                        await wait_state(page, "pending-deny", "cancelled")
                        assert not (workspace / "pending-deny.txt").exists()
                        stale = page.locator('[data-task-id="pending-stale"]')
                        await stale.locator(":scope > details > summary").click()
                        await stale.get_by_role(
                            "button", name="Approve this task", exact=True
                        ).wait_for()
                        await approve_from_other_client(context, url, session, "pending-stale")
                        await stale.get_by_role(
                            "button", name="Approve this task", exact=True
                        ).click()
                        await wait_message(page, "state changed")
                        await page.locator("#refresh").click()
                        lost = page.locator('[data-task-id="pending-lost"]')
                        await lost.locator(":scope > details > summary").click()
                        await lost.get_by_role(
                            "button", name="Approve this task", exact=True
                        ).wait_for()
                        posts.clear()

                        async def accepted_then_disconnected(route):
                            posts.append(route.request.post_data_json)
                            await route.fetch()
                            await route.abort()

                        await page.route(
                            "**/api/tasks/pending-lost/approve", accepted_then_disconnected
                        )
                        await lost.get_by_role(
                            "button", name="Approve this task", exact=True
                        ).click()
                        await wait_message(page, "outcome is unknown")
                        await page.wait_for_timeout(5300)  # One existing read-only poll interval.
                        assert len(posts) == 1 and set(posts[0]) == {"request_hash"}
                        assert (await task_value(context, url, session, "pending-lost"))[
                            "state"
                        ] == "queued"
                        await page.locator("#refresh").click()
                        await wait_state(page, "pending-lost", "queued")
                        assert fixture["dispatcher_started"] is False and not list(
                            workspace.iterdir()
                        )
                        checks.extend(
                            [
                                "real synthetic approve/deny with exact request hash",
                                "stale decision conflict",
                                "lost POST response never repeated",
                                "HTML arguments rendered as inert text",
                                "no dispatcher/agent/clipboard/file execution",
                            ]
                        )
                    await page.set_viewport_size({"width": 440, "height": 760})
                    assert await page.evaluate(
                        "() => document.documentElement.scrollWidth <= innerWidth"
                    )
                    await page.locator("#refresh").focus()
                    await page.keyboard.press("Tab")
                    await page.keyboard.press("Shift+Tab")
                    assert (
                        await page.locator("#refresh").evaluate(
                            "el => getComputedStyle(el).outlineStyle"
                        )
                        == "solid"
                    )
                    await page.locator('[data-language="de"]').click()
                    await page.reload()
                    await page.wait_for_function(
                        "() => document.querySelectorAll('article').length === 10"
                    )
                    assert await page.locator("html").get_attribute("lang") == "de"
                    await page.screenshot(path=str(OUT / (theme + "-small-de.png")))
                    if theme == "dark":
                        # Display-only future contract: no synthetic operation is submitted.
                        future = {
                            "id": "future-display",
                            "operation": "handoff.future<text>",
                            "principal": "local",
                            "state": "completed",
                            "updated": 0,
                            "args": {"future_field<text>": {"answer": "<img src=x>"}},
                        }

                        async def future_list(route, future=future):
                            await route.fulfill(json={"tasks": [future], "pending": 0})

                        async def future_detail(route, future=future):
                            await route.fulfill(json={"task": future})

                        await page.route(url + "/api/tasks", future_list)
                        await page.route(url + "/api/tasks/future-display", future_detail)
                        await page.locator("#refresh").click()
                        future_card = page.locator('[data-task-id="future-display"]')
                        await future_card.wait_for()
                        assert "handoff.future<text>" in await future_card.inner_text()
                        await future_card.locator(":scope > details > summary").click()
                        await future_card.locator("pre").wait_for()
                        assert "future_field<text>" in await future_card.inner_text()
                        assert await future_card.locator("img, button").count() == 0
                        checks.append("unknown future operation/fields remain inert text")
                    checks.append(
                        theme + ": authenticated DE/EN, modes, state scope, small view, "
                        "focus, reduced motion"
                    )
                    await context.close()
                assert not errors, errors
                version = browser.version
                await browser.close()
        finally:
            server.terminate()
            await asyncio.wait_for(server.wait(), timeout=10)
        return {
            "status": "passed",
            "browser": version,
            "checks": checks,
            "page_errors": errors,
            "scope": (
                "isolated console with synthetic recorded task-state fixtures; "
                "no real agent completion or live runtime acceptance"
            ),
            "assets": {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (ROOT / "src/kirabridge/console_assets").iterdir()
                if p.is_file()
            },
        }


if __name__ == "__main__":
    try:
        result = asyncio.run(run())
    except BaseException as error:
        result = {
            "status": "failed",
            "error_type": type(error).__name__,
            "error": str(error)[:1000],
        }
        (OUT / "checks.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps({**result, "evidence": str(OUT)}))
        raise
    else:
        (OUT / "checks.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps({**result, "evidence": str(OUT)}))
