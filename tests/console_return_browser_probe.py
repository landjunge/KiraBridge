"""Real keyboard tests against isolated console assets and synthetic HTTP.

Run with an existing Playwright Python environment and already installed browsers.
No application, package, user profile or Terminal window is installed or opened.
Use --case/--engine to rerun only affected failures; --output retains exact evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src/kirabridge/console_assets"
ORIGIN = "http://127.0.0.1:9971"
PANE = "terminal:999:ttys099"
ALT_PANE = "terminal:998:ttys098"
CURSOR = "a" * 64
OTHER_CURSOR = "b" * 64
SESSION = {"pane_id": PANE, "expected_pid": 12345, "agent_pid": 999, "busy": True}
STATUS = {
    "services": [
        {
            "id": "bridge",
            "name": "KiraBridge",
            "state": "active",
            "detail": "fixture",
            "active": True,
            "restart_available": True,
        }
    ],
    "bridge": {"dispatcher_active": True, "terminal_access": {"policy_authorized": True}},
    "observed_at": 1,
    "settings_loaded": True,
    "permissions_consistent": True,
    "permission_details": {"chatgpt": {"label": "Voll erlaubt", "exceptions": []}},
    "permission_choices": {"full": "Voll erlaubt", "medium": "Mittel", "ask": "Nur mit Erlaubnis"},
    "level": "full",
    "peers_connected": True,
    "pending": [],
    "maintenance": None,
}
CONNECTIONS = {
    "chatgpt_url": "https://chatgpt.invalid",
    "grok_url": "https://grok.invalid",
    "checks": [],
    "grok": {"url": "", "pending": []},
}
CASES = [
    "typed_enter",
    "empty_enter",
    "held_enter",
    "double_click",
    "return_button",
    "send_button_enter",
    "return_button_enter",
    "empty_send_button",
    "whitespace_text",
    "missing_observation",
    "freeze_displayed_view_before_queue",
    "freeze_selection_before_queue",
    "pending_until_terminal",
    "failed_preserves_draft",
    "unknown_preserves_intent",
    "network_error_preserves_intent",
    "ack_pending_preserves_intent",
    "completed_missing_result",
    "completed_explicit_false",
    "legacy_shell_text_result",
    "key_requires_return_proof",
    "new_draft_while_pending",
    "same_value_new_draft_while_pending",
    "mobile_empty_enter",
    "output_enter",
    "composition_enter",
]


async def wait_for(predicate, *, seconds=5):
    async with asyncio.timeout(seconds):
        while not predicate():
            await asyncio.sleep(0.01)


class Fixture:
    def __init__(self, name):
        self.name = name
        self.posts = []
        self.status_reads = []
        self.errors = []
        self.tasks = {}
        self.cursor = CURSOR
        self.agent = 456
        self.state = "completed"
        self.result = {"return_sent": True, "input_handed_to_transport": True, "submitted": True}
        self.completion_pending = False
        self.post_network_error = False
        self.status_network_error = False
        self.gate = asyncio.Event()
        self.doctor_gate = asyncio.Event()
        self.gate.set()
        self.doctor_gate.set()
        self.doctor_started = False
        if name in {
            "held_enter",
            "double_click",
            "new_draft_while_pending",
            "same_value_new_draft_while_pending",
        }:
            self.gate.clear()
        if name == "pending_until_terminal":
            self.state = "running"
        if name == "failed_preserves_draft":
            self.state = "failed"
        if name == "unknown_preserves_intent":
            self.state = "unknown"
        if name == "network_error_preserves_intent":
            self.state = "running"
            self.post_network_error = self.status_network_error = True
        if name == "ack_pending_preserves_intent":
            self.completion_pending = True
        if name == "completed_missing_result":
            self.result = None
        if name == "completed_explicit_false":
            self.result = {
                "return_sent": False,
                "input_handed_to_transport": True,
                "submitted": True,
            }
        if name in {"legacy_shell_text_result", "key_requires_return_proof"}:
            self.result = {"input_handed_to_transport": True, "submitted": True}
            self.agent = None

    def delivery(self, action):
        body = self.tasks[action]
        stale = (
            self.name == "freeze_displayed_view_before_queue"
            and body.get("expected_cursor") != self.cursor
        )
        state = "failed" if stale else self.state
        error = (
            {"code": "stale_terminal_observation"}
            if stale
            else {"code": "visible_target_unknown"}
            if state == "failed"
            else {"code": "input_unknown"}
            if state == "unknown"
            else None
        )
        return {
            "id": "input-" + action,
            "operation": "session.input",
            "state": state,
            "args": body,
            "result": self.result if state == "completed" else None,
            "error": error,
            "evidence": {"terminal_input_attempted": state != "failed"},
            "ui_completion": {"pending": self.completion_pending},
        }

    async def route(self, route):
        request = route.request
        path = urlparse(request.url).path
        if not request.url.startswith(ORIGIN):
            await route.abort()
            return
        if path in {"/", "/center.js", "/center.css", "/networkpunkt.css"}:
            file = ASSETS / ({"/": "center.html"}.get(path, path.lstrip("/")))
            kind = (
                "text/html"
                if file.suffix == ".html"
                else "application/javascript"
                if file.suffix == ".js"
                else "text/css"
            )
            await route.fulfill(status=200, content_type=kind, body=file.read_bytes())
            return
        if path == "/api/control/status":
            data = STATUS
        elif path == "/api/control/connections":
            data = CONNECTIONS
        elif path == "/api/control/terminals":
            data = {
                "sessions": [SESSION, {"pane_id": ALT_PANE, "expected_pid": 9876, "busy": False}]
            }
        elif path == "/api/control/terminal/read":
            body = json.loads(request.post_data)
            data = {
                "pane_id": body["pane_id"],
                "expected_pid": body["expected_pid"],
                "text": "Displayed " + self.cursor,
            }
            if self.name != "missing_observation":
                data["next_cursor"] = self.cursor
                if self.agent is not None:
                    data["input_readiness"] = {"binding": {"agent_pid": self.agent}}
        elif path == "/api/control/terminal/input":
            body = json.loads(request.post_data)
            self.posts.append(body)
            self.tasks[body["action_id"]] = body
            if self.post_network_error:
                await route.abort()
                return
            await self.gate.wait()
            data = self.delivery(body["action_id"])
        elif path.startswith("/api/control/terminal/input/"):
            action = path.rsplit("/", 1)[1]
            self.status_reads.append(action)
            if self.status_network_error:
                await route.abort()
                return
            assert action in self.tasks
            data = {"task": self.delivery(action)}
        elif path == "/api/control/doctor":
            self.doctor_started = True
            await self.doctor_gate.wait()
            data = {"checks": [], "repaired": []}
        else:
            await route.fulfill(
                status=404,
                content_type="application/json",
                body='{"error":"fixture route missing"}',
            )
            return
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(data),
            headers={"Cache-Control": "no-store"},
        )


async def run_case(browser, engine, name):
    fixture = Fixture(name)
    context = await browser.new_context(
        viewport={
            "width": 390 if name == "mobile_empty_enter" else 1180,
            "height": 844 if name == "mobile_empty_enter" else 900,
        }
    )
    await context.route("**/*", fixture.route)
    page = await context.new_page()
    page.on("pageerror", lambda error: fixture.errors.append(str(error)))
    await page.add_init_script(
        "localStorage.setItem('kirabridge.session','synthetic-return-ui-fixture');window.keyEvents=[];document.addEventListener('keydown',e=>window.keyEvents.push({key:e.key,repeat:e.repeat,isComposing:e.isComposing}),true);"
    )
    observation = {"engine": engine, "name": name, "passed": False}
    field = page.locator("#terminal-text")

    async def idle():
        await page.wait_for_function(
            "document.querySelector('#terminal-form').getAttribute('aria-busy')==='false'",
            timeout=5000,
        )

    async def refresh():
        await page.locator("#terminal-refresh").click()
        await page.evaluate("actionQueue")
        await page.wait_for_timeout(30)

    try:
        await page.goto(ORIGIN)
        await page.locator('[data-view="terminals"]').click()
        await page.wait_for_function(
            "document.querySelector('#terminal-output').textContent.startsWith('Displayed ')"
        )
        if name in {"freeze_displayed_view_before_queue", "freeze_selection_before_queue"}:
            fixture.doctor_gate.clear()
            await page.locator('[data-view="doctor"]').click()
            await wait_for(lambda: fixture.doctor_started)
            await page.locator('[data-view="terminals"]').click()
            await page.wait_for_function(
                "document.querySelector('#terminal-output').textContent==="
                "'Displayed ' + 'a'.repeat(64)"
            )
            # Reopening the view starts a new read. The old displayed text can
            # already match while its observation has deliberately been revoked.
            await page.locator("#terminal-return").wait_for(state="visible")
            await page.wait_for_function("!document.querySelector('#terminal-return').disabled")
            await field.press("Enter")
            assert not fixture.posts
            if name == "freeze_displayed_view_before_queue":
                fixture.cursor = OTHER_CURSOR
                fixture.agent = 789
                await page.locator('[data-view="overview"]').click()
                await page.locator('[data-view="terminals"]').click()
                await page.wait_for_function(
                    "document.querySelector('#terminal-output').textContent==="
                    "'Displayed ' + 'b'.repeat(64)"
                )
            else:
                await page.locator("#terminal-select").select_option(ALT_PANE)
            fixture.doctor_gate.set()
            await wait_for(lambda: len(fixture.posts) == 1)
            await idle()
            assert fixture.posts[0]["pane_id"] == PANE and fixture.posts[0]["expected_pid"] == 12345
            assert (
                fixture.posts[0]["expected_cursor"] == CURSOR
                and fixture.posts[0]["expected_agent_pid"] == 456
            )
        elif name == "composition_enter":
            await field.fill("prefix")
            cdp = await context.new_cdp_session(page)
            await cdp.send(
                "Input.imeSetComposition", {"text": "に", "selectionStart": 1, "selectionEnd": 1}
            )
            await field.press("Enter")
            await page.wait_for_timeout(80)
            assert not fixture.posts
            assert any(event["isComposing"] for event in await page.evaluate("window.keyEvents"))
            assert await field.input_value() == "prefixに"
        elif name in {"empty_send_button", "missing_observation"}:
            if name == "empty_send_button":
                await page.locator("#terminal-send").click()
                assert "Text eingeben" in await page.locator("#notice").inner_text()
            else:
                await field.press("Enter")
                assert "Terminalansicht prüfen" in await page.locator("#notice").inner_text()
                assert await page.locator("#terminal-return").is_disabled()
            assert not fixture.posts
        else:
            key = name in {
                "empty_enter",
                "return_button",
                "return_button_enter",
                "key_requires_return_proof",
                "mobile_empty_enter",
                "output_enter",
            }
            draft = (
                ""
                if name in {"empty_enter", "mobile_empty_enter"}
                else "  "
                if name == "whitespace_text"
                else "/resume"
            )
            await field.fill(draft)
            if name == "output_enter":
                await page.locator("#terminal-output").focus()
                await page.keyboard.down("Enter")
                await page.keyboard.down("Enter")
                await page.keyboard.up("Enter")
            elif name in {"return_button", "key_requires_return_proof"}:
                await page.locator("#terminal-return").click()
            elif name == "return_button_enter":
                await page.locator("#terminal-return").focus()
                await page.keyboard.press("Enter")
            elif name == "send_button_enter":
                await page.locator("#terminal-send").focus()
                await page.keyboard.press("Enter")
            elif name == "held_enter":
                await field.focus()
                await page.keyboard.down("Enter")
                await page.keyboard.down("Enter")
                await page.keyboard.up("Enter")
                await wait_for(lambda: len(fixture.posts) == 1)
                fixture.gate.set()
            elif name == "double_click":
                box = await page.locator("#terminal-send").bounding_box()
                await page.mouse.dblclick(
                    box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, delay=30
                )
                await wait_for(lambda: len(fixture.posts) == 1)
                fixture.gate.set()
            else:
                await field.press("Enter")
            await wait_for(lambda: len(fixture.posts) == 1)
            body = fixture.posts[0]
            if key:
                assert (
                    body["key"] == "enter"
                    and body["text"] == ""
                    and body["expected_cursor"] == CURSOR
                )
                if fixture.agent is not None:
                    assert body["expected_agent_pid"] == 456
                else:
                    assert "expected_agent_pid" not in body
            else:
                assert body["text"] == draft
                assert not ({"key", "expected_cursor", "expected_agent_pid"} & body.keys())
            if name in {"new_draft_while_pending", "same_value_new_draft_while_pending"}:
                await field.fill("new draft")
                if name == "same_value_new_draft_while_pending":
                    await field.fill(draft)
                fixture.gate.set()
                await idle()
                assert await field.input_value() == (
                    draft if name == "same_value_new_draft_while_pending" else "new draft"
                )
            elif name in {
                "pending_until_terminal",
                "unknown_preserves_intent",
                "network_error_preserves_intent",
                "ack_pending_preserves_intent",
            }:
                await wait_for(lambda: len(fixture.status_reads) > 0)
                assert (
                    await field.input_value() == draft
                    and await page.locator("#terminal-send").is_disabled()
                )
                await field.press("Enter")
                assert len(fixture.posts) == 1
                if name == "unknown_preserves_intent":
                    await refresh()
                    assert await page.locator("#terminal-send").is_disabled()
                fixture.state = "completed"
                fixture.completion_pending = fixture.status_network_error = False
                await refresh()
                await idle()
                assert await field.input_value() == ""
                assert set(fixture.status_reads) == {body["action_id"]}
            elif name in {
                "completed_missing_result",
                "completed_explicit_false",
                "key_requires_return_proof",
            }:
                await wait_for(lambda: len(fixture.status_reads) > 0)
                assert (
                    await field.input_value() == draft
                    and await page.locator("#terminal-send").is_disabled()
                )
                assert "nicht bestätigt" in await page.locator("#notice").inner_text()
                await field.press("Enter")
                await refresh()
                assert len(fixture.posts) == 1 and set(fixture.status_reads) == {body["action_id"]}
            else:
                await idle()
                assert await field.input_value() == (
                    draft if key or name == "failed_preserves_draft" else ""
                )
                if name == "legacy_shell_text_result":
                    assert "an das Terminal übergeben" in await page.locator("#notice").inner_text()
            assert len(fixture.posts) == 1
            if name == "mobile_empty_enter":
                # The preexisting app-wide mobile header width is measured
                # separately. These controls must fit their existing form.
                assert await page.locator("#terminal-form").evaluate(
                    "form=>form.scrollWidth<=form.clientWidth"
                )
        assert not fixture.errors
        observation["passed"] = True
    except Exception as error:
        observation["error"] = str(error)
    finally:
        observation.update(
            requests=fixture.posts, status_reads=fixture.status_reads, script_errors=fixture.errors
        )
        try:
            observation.update(
                field_value=await field.input_value(),
                notice=await page.locator("#notice").inner_text(),
                keys=await page.evaluate("window.keyEvents"),
            )
        finally:
            fixture.gate.set()
            fixture.doctor_gate.set()
            await context.close()
    return observation


async def run(args):
    out = args.output or ROOT / "dist/return-ui-checks" / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    out.mkdir(parents=True, exist_ok=False)
    result = {
        "scope": "Actual console assets, owned headless browsers, intercepted synthetic HTTP only",
        "source_hashes": {
            name: hashlib.sha256((ASSETS / name).read_bytes()).hexdigest()
            for name in ["center.html", "center.js"]
        },
        "cases": [],
        "engine_errors": [],
        "engines": {},
    }
    async with async_playwright() as play:
        for engine in args.engine or ["chromium", "webkit"]:
            try:
                if engine == "chromium":
                    browser = await play.chromium.launch(
                        headless=True,
                        **(
                            {"executable_path": str(args.chromium_executable)}
                            if args.chromium_executable
                            else {"channel": "chrome"}
                        ),
                    )
                else:
                    executable = args.webkit_executable or Path(play.webkit.executable_path)
                    browser = await play.webkit.launch(
                        headless=True, executable_path=str(executable)
                    )
                result["engines"][engine] = browser.version
            except Exception as error:
                result["engine_errors"].append({"engine": engine, "error": str(error)})
                continue
            try:
                for name in args.case or CASES:
                    if name == "composition_enter" and engine != "chromium":
                        continue
                    case = await run_case(browser, engine, name)
                    result["cases"].append(case)
                    print(engine, name, "passed" if case["passed"] else "FAILED", flush=True)
            finally:
                await browser.close()
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    passed = sum(case["passed"] for case in result["cases"])
    print(
        json.dumps(
            {
                "output": str(out),
                "passed": passed,
                "failed": len(result["cases"]) - passed,
                "engine_errors": result["engine_errors"],
            }
        )
    )
    return (
        0
        if result["cases"] and passed == len(result["cases"]) and not result["engine_errors"]
        else 1
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--engine", choices=["chromium", "webkit"], action="append")
    parser.add_argument("--case", choices=CASES, action="append")
    parser.add_argument("--chromium-executable", type=Path)
    parser.add_argument("--webkit-executable", type=Path)
    raise SystemExit(asyncio.run(run(parser.parse_args())))
