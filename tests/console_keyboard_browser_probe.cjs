/* Isolated real-browser keyboard UI checks; synthetic HTTP only, no OS input.
 * KB_PLAYWRIGHT_MODULE may point to an already installed Playwright module.
 * Usage: node tests/console_keyboard_browser_probe.cjs OUTPUT.json [case ...]
 */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const { chromium } = require(process.env.KB_PLAYWRIGHT_MODULE || "playwright");
const assets = path.resolve(__dirname, "../src/kirabridge/console_assets");
const origin = "http://127.0.0.1:9972";
const revision = "a".repeat(64);
const profile = {
  schema: "kirabridge.keyboard-profile.v1", id: "fixture",
  app: { bundle_id: "com.example.KeyboardFixture" },
  actions: { select_all: { key: { character: "a" }, modifiers: ["command"], provenance: "user" } }
};
const status = {
  services: [], bridge: { dispatcher_active: true }, observed_at: 1,
  settings_loaded: true, permissions_consistent: true,
  permission_choices: { full: "Voll erlaubt" }, level: "full",
  permission_details: { chatgpt: { label: "Voll erlaubt", exceptions: [] } },
  pending: [], peers_connected: true, maintenance: null
};
const automaticCases = ["automatic_text_return", "automatic_key_combination", "automatic_lost_response", "automatic_limit_and_draft", "automatic_advanced", "automatic_app_visibility"];
const cases = ["profiles_and_discovery", "one_run", "lost_response", "lost_response_preparation", "completed_preparation", "failed_intent", "failed_main", "missing_post_proof", "candidate", ...automaticCases];

async function checkAutomatic(page, name, posts, gets) {
  const controls = () => posts.filter(p => p.operation === "keyboard.control");
  const target = { pid: 12345, expected_started_at: 123.5 };
  await page.waitForFunction(() => document.querySelector("#keyboard-apps").options.length === 3 && !document.querySelector("#keyboard-apps").disabled);
  assert.deepEqual(posts.map(p => p.operation), ["apps.list"], "Opening the tab only discovers programs");
  assert.equal(await page.locator("#keyboard-apps").inputValue(), "", "The console browser must not become an implicit target");
  assert.ok(await page.locator("#keyboard-send").isDisabled());
  assert.equal(await page.locator("#keyboard-advanced").getAttribute("open"), null);
  assert.match(await page.locator("#keyboard-apps").innerText(), /Notizen/);
  assert.doesNotMatch(await page.locator("#keyboard-apps").innerText(), /PID|com\.example/);
  await page.locator('[data-view="overview"]').click();
  await page.locator('[data-view="keyboard"]').click();
  assert.equal(posts.length, 1, "The discovery has no recurring polling loop");
  await page.locator("#keyboard-apps").selectOption("12345:123.5");

  if (name === "automatic_app_visibility") {
    assert.deepEqual(await page.locator("#keyboard-apps option").evaluateAll(options => options.map(option => option.value)), ["", "12345:123.5", "23456:234.5"], "Keep normal apps and older-server entries; omit explicit background helpers");
    assert.doesNotMatch(await page.locator("#keyboard-apps").innerText(), /Hintergrundhelfer/);
    assert.equal(controls().length, 0);
  } else if (name === "automatic_text_return") {
    const text = "Hallo 👋\nzweite Zeile";
    await page.locator("#keyboard-text").fill(text);
    await page.locator("#keyboard-text").press("Enter");
    assert.equal(controls().length, 0, "Enter in the text field must not send");
    await page.locator("#keyboard-text").fill(text);
    await page.locator("#keyboard-text").dispatchEvent("compositionstart");
    assert.ok(await page.locator("#keyboard-send").isDisabled(), "IME composition must not send a partial input");
    await page.locator("#keyboard-text").dispatchEvent("compositionend");
    await page.locator("#keyboard-send").click();
    await page.waitForFunction(() => document.querySelector("#notice").textContent.includes("Text im Zielprogramm bestätigt"));
    assert.deepEqual(controls()[0].args, { ...target, text, submit: false });
    await page.locator("#keyboard-submit").check();
    await page.locator("#keyboard-send").click();
    await page.waitForFunction(() => document.querySelector("#notice").textContent.includes("Return wurde gesendet"));
    assert.deepEqual(controls()[1].args, { ...target, text, submit: true });
    assert.equal(await page.locator("#keyboard-text").inputValue(), text);
    const screenshot = process.argv[2].replace(/\.json$/, "") + "-text.png";
    await page.screenshot({ path: screenshot, fullPage: true });
  } else if (name === "automatic_key_combination") {
    await page.locator("#keyboard-kind").selectOption("key");
    assert.ok(await page.locator("#keyboard-text-fields").isHidden());
    await page.locator("#keyboard-key").selectOption("character");
    await page.locator("#keyboard-character").fill("a");
    await page.locator('.keyboard-modifiers input[value="command"]').check();
    await page.locator("#keyboard-character").press("Enter");
    assert.equal(controls().length, 0, "A key field's Enter must not submit its form");
    await page.locator("#keyboard-send").evaluate(button => { button.click(); button.click(); });
    await page.waitForFunction(() => document.querySelector("#notice").textContent.includes("Native Tastendruck-Aufrufe bestätigt"));
    assert.equal(controls().length, 1, "Double-click may create only one native input intent");
    assert.deepEqual(controls()[0].args, { ...target, key: { character: "a" }, modifiers: ["command"] });
    assert.equal(gets.length, 1, "An open task is resolved by the existing GET status path");
    await page.locator("#keyboard-key").selectOption("escape");
    await page.locator("#keyboard-send").click();
    await page.waitForFunction(() => document.querySelector("#notice").textContent.includes("nicht vollständig bestätigt"));
    assert.ok(await page.locator("#keyboard-send").isDisabled(), "Missing native receipt must retain the input intent");
    await page.locator("#keyboard-status").click();
    await page.waitForFunction(() => !document.querySelector("#keyboard-status").disabled);
    assert.equal(controls().length, 2, "Status does not replay a missing receipt");
  } else if (name === "automatic_lost_response") {
    const draft = "Diese Eingabe genau einmal senden.";
    await page.locator("#keyboard-text").fill(draft);
    await page.locator("#keyboard-send").evaluate(button => { button.click(); button.click(); });
    await page.waitForFunction(() => document.querySelector("#keyboard-task").textContent.includes("ungewiss"));
    assert.equal(await page.locator("#keyboard-text").inputValue(), draft, "A lost response must keep the current draft");
    const sent = controls()[0].id, count = posts.length;
    await page.reload();
    await page.locator('[data-view="keyboard"]').click();
    assert.ok(await page.locator("#keyboard-send").isDisabled());
    assert.equal(posts.length, count, "A restored unknown intent must suppress automatic discovery and sends");
    await page.locator("#keyboard-status").click();
    await page.waitForFunction(() => document.querySelector("#keyboard-task").textContent.includes("unknown"));
    assert.equal(controls().length, 1);
    assert.equal(posts.length, count);
    assert.deepEqual(gets, ["/api/control/keyboard/task/ui-keyboard-" + sent.replaceAll("-", "") + "-main"]);
    assert.ok(await page.locator("#keyboard-send").isDisabled());
    assert.equal(await page.evaluate(() => JSON.parse(sessionStorage.getItem("kirabridge.keyboard.intent")).id), sent);
  } else if (name === "automatic_limit_and_draft") {
    // The literal is under 32 KiB; JSON escaping makes the actual body exceed it.
    const large = '"'.repeat(17000);
    await page.locator("#keyboard-text").fill(large);
    await page.locator("#keyboard-send").click();
    await page.waitForFunction(() => document.querySelector("#notice").textContent.includes("32 KiB"));
    assert.equal(controls().length, 0, "Oversized JSON must be rejected before transport");
    assert.equal(await page.locator("#keyboard-text").inputValue(), large);
    assert.ok(await page.locator("#keyboard-send").isEnabled(), "A local size error must not create an unknown lock");
    assert.equal(await page.evaluate(() => JSON.parse(sessionStorage.getItem("kirabridge.keyboard.intent")).operation), "apps.list");
    await page.locator("#keyboard-text").fill("Kleiner Entwurf bleibt erhalten.");
    await page.locator("#keyboard-apps-refresh").click();
    await page.waitForFunction(() => !document.querySelector("#keyboard-apps-refresh").disabled);
    assert.equal(await page.locator("#keyboard-text").inputValue(), "Kleiner Entwurf bleibt erhalten.");
    await page.locator("#keyboard-send").click();
    await page.waitForFunction(() => document.querySelector("#notice").textContent.includes("Text im Zielprogramm bestätigt"));
    assert.equal(controls().length, 1);
  } else if (name === "automatic_advanced") {
    await page.locator("#keyboard-advanced summary").click();
    for (const id of ["profiles", "load", "new", "actions", "run", "discover", "menu-next", "editor", "save", "delete", "context", "preview", "preview-result"]) {
      assert.equal(await page.locator("#keyboard-" + id).count(), 1, "Existing advanced control remains: " + id);
    }
    await page.locator("#keyboard-refresh").click();
    await page.waitForFunction(() => document.querySelector("#keyboard-profiles").options.length === 2 && !document.querySelector("#keyboard-refresh").disabled);
    await page.locator("#keyboard-profiles").selectOption("fixture");
    await page.locator("#keyboard-load").click();
    await page.waitForFunction(() => document.querySelector("#keyboard-editor").value.includes('"select_all"'));
    await page.locator("#keyboard-actions").selectOption("select_all");
    const draft = JSON.stringify({ ...profile, id: "edited_fixture" });
    await page.locator("#keyboard-editor").fill(draft);
    assert.ok(await page.locator("#keyboard-run").isDisabled(), "Dirty profiles remain blocked");
    await page.locator("#keyboard-apps-refresh").click();
    await page.waitForFunction(() => !document.querySelector("#keyboard-apps-refresh").disabled);
    assert.equal(await page.locator("#keyboard-editor").inputValue(), draft);
    await page.locator("#keyboard-discover").click();
    await page.waitForFunction(() => document.querySelector("#keyboard-menu").textContent.includes("onerror"));
    assert.equal(await page.locator("#keyboard img").count(), 0);
    assert.equal(await page.evaluate(() => window.injected), undefined);
    assert.equal(controls().length, 0);
  }
  if (name !== "automatic_advanced") assert.ok(posts.every(p => ["apps.list", "keyboard.control"].includes(p.operation)), "Direct input does not require any profile operation");
}

async function check(browser, name) {
  const automatic = automaticCases.includes(name);
  const context = await browser.newContext({ viewport: { width: 1180, height: 900 } });
  const posts = [], gets = [], errors = [], tasks = new Map();
  let networkLost = false;
  const document = structuredClone(profile);
  if (name === "candidate") document.actions.select_all.provenance = "observed_menu";
  const snapshot = () => ({ profile_id: "fixture", revision, profile: document });
  const page = await context.newPage();
  page.setDefaultTimeout(5000);
  page.on("pageerror", e => errors.push(String(e)));
  await context.addInitScript(() => localStorage.setItem("kirabridge.session", "synthetic-only"));
  await page.route("**/*", async route => {
    const request = route.request(), url = new URL(request.url());
    assert.equal(url.origin, origin, "External HTTP must not leave the isolated fixture");
    const asset = { "/": "center.html", "/center.js": "center.js", "/keyboard.js": "keyboard.js", "/center.css": "center.css", "/networkpunkt.css": "networkpunkt.css" }[url.pathname];
    if (asset) return route.fulfill({ body: await fs.readFile(path.join(assets, asset)), contentType: asset.endsWith(".js") ? "application/javascript" : asset.endsWith(".css") ? "text/css" : "text/html" });
    const json = value => route.fulfill({ json: value });
    if (url.pathname === "/api/control/status") return json(status);
    if (url.pathname === "/api/control/connections") return json({ chatgpt_url: "https://chatgpt.invalid", grok_url: "https://grok.invalid", checks: [], grok: { url: "", pending: [] } });
    if (url.pathname === "/api/control/keyboard/request") {
      assert.equal(request.method(), "POST");
      const body = request.postDataJSON(); posts.push(body);
      const id = "ui-keyboard-" + body.id.replaceAll("-", "") + "-main";
      let result = {}, state = "completed", primary = true;
      switch (body.operation) {
        case "keyboard.profiles.list": result = { profiles: [{ profile_id: "fixture", revision, app: document.app }] }; break;
        case "apps.list":
          result = { applications: automatic ? [{ pid: 12345, started_at: 123.5, bundle_id: document.app.bundle_id, name: "Notizen", active: false }, { pid: 23456, started_at: 234.5, bundle_id: "org.example.Browser", name: "Webbrowser", active: true, user_application: true }] : [{ pid: 12345, started_at: 123.5, bundle_id: document.app.bundle_id, name: '<img src=x onerror="window.injected=1">' }] };
          if (name === "automatic_app_visibility") result.applications.push({ pid: 34567, started_at: 345.5, bundle_id: document.app.bundle_id, name: "Hintergrundhelfer", user_application: false });
          break;
        case "keyboard.profiles.get": result = snapshot(); break;
        case "keyboard.profiles.put": result = { ...snapshot(), profile: body.args.profile }; break;
        case "keyboard.profiles.resolve": result = { context_verified: false, execution_authorized: false, effect: "none", status: "resolved" }; break;
        case "keyboard.shortcuts.discover": result = { revision, entries: [{ name: '<img src=x onerror="window.injected=1">', candidate_only: true }], coverage: "partial", reasons: ["menu_identity_attribute_unavailable"], cached: false }; break;
        case "keyboard.control":
          result = { automatic_target: true, resolved_application: { pid: 12345, started_at: 123.5, name: "Notizen" }, app_processing_confirmed: false };
          if (body.args.text !== undefined) Object.assign(result, { text_verified: true, selection_verified: true, return_posted: body.args.submit === true });
          else if (body.args.key.named !== "escape") result.post_calls_returned = 2;
          if (name === "automatic_key_combination" && body.args.key.character) state = "running";
          break;
        case "run_profile":
          state = name.startsWith("failed_") ? "failed" : ["completed_preparation", "missing_post_proof"].includes(name) ? "completed" : "running";
          primary = !["completed_preparation", "failed_intent"].includes(name);
          result = primary ? { profile_binding_verified: true, post_calls_returned: 2, profile_binding: { id: "fixture", revision, action: "select_all" } } : snapshot();
          if (name === "missing_post_proof") delete result.post_calls_returned;
          break;
        default: throw Error("Unexpected operation " + body.operation);
      }
      const task = { id, state, result, error: state === "failed" ? { code: "keyboard_profile_conflict" } : null, ui_primary: primary, ui_incomplete: !primary, ui_stage: primary ? "main" : "profile", ui_workflow_status: primary ? "primary" : "halted", ui_halted: !primary || state === "failed" };
      tasks.set(id, { request_id: body.id, task, status_url: "/api/control/keyboard/task/" + id });
      if (name.startsWith("lost_response") && body.operation === "run_profile") { networkLost = true; return route.abort("failed"); }
      if (name === "automatic_lost_response" && body.operation === "keyboard.control") { networkLost = true; return route.abort("failed"); }
      return json(tasks.get(id));
    }
    if (url.pathname.startsWith("/api/control/keyboard/task/")) {
      assert.equal(request.method(), "GET"); gets.push(url.pathname);
      const value = structuredClone(tasks.get(url.pathname.split("/").pop()));
      assert.ok(value, "Lost response must retain a deterministic task identity");
      value.task.state = networkLost && name !== "lost_response_preparation" ? "unknown" : "completed";
      if (name === "lost_response_preparation" && gets.length === 1) {
        value.task.id = value.task.id.replace(/-main$/, "-focus");
        Object.assign(value.task, { ui_primary: false, ui_incomplete: true, ui_halted: false, ui_workflow_status: "unconfirmed", result: {} });
      }
      return json(value);
    }
    throw Error("Unexpected fixture request " + url.pathname);
  });
  try {
    await page.goto(origin);
    await page.locator('[data-view="keyboard"]').click();
    if (automatic) {
      await checkAutomatic(page, name, posts, gets);
      assert.deepEqual(errors, []);
      return { name, passed: true, keyboard_posts: posts.length, status_gets: gets.length };
    }
    await page.waitForFunction(() => document.querySelector("#keyboard-apps").options.length === 2 && !document.querySelector("#keyboard-apps").disabled);
    assert.deepEqual(posts.map(p => p.operation), ["apps.list"], "Opening the tab only discovers programs");
    await page.locator("#keyboard-advanced summary").click();
    await page.locator("#keyboard-refresh").click();
    await page.waitForFunction(() => document.querySelector("#keyboard-apps").options.length === 2);
    await page.locator("#keyboard-profiles").selectOption("fixture");
    await page.locator("#keyboard-load").click();
    await page.waitForFunction(() => document.querySelector("#keyboard-editor").value.includes('"select_all"'));
    await page.locator("#keyboard-apps").selectOption("12345:123.5");
    await page.locator("#keyboard-actions").selectOption("select_all");
    if (name === "profiles_and_discovery") {
      const edited = JSON.stringify({ ...profile, id: "fixture", actions: { ...profile.actions, left: { key: { named: "left" }, modifiers: [], provenance: "user" } } });
      await page.locator("#keyboard-editor").fill(edited);
      assert.ok(await page.locator("#keyboard-run").isDisabled());
      await page.locator("#keyboard-refresh").click();
      await page.waitForFunction(() => !document.querySelector("#keyboard-refresh").disabled);
      assert.equal(await page.locator("#keyboard-editor").inputValue(), edited, "Refresh must preserve a dirty draft");
      await page.locator("#keyboard-save").click();
      await page.waitForFunction(() => document.querySelector("#keyboard-dirty").textContent === "Unverändert");
      assert.equal(posts.find(p => p.operation === "keyboard.profiles.put").args.expected_revision, revision);
      await page.locator("#keyboard-preview").click();
      await page.waitForFunction(() => document.querySelector("#keyboard-preview-result").textContent.includes('"context_verified": false'));
      await page.locator("#keyboard-discover").click();
      await page.waitForFunction(() => document.querySelector("#keyboard-menu").textContent.includes("onerror"));
      assert.match(await page.locator("#keyboard-coverage").innerText(), /partial/);
      assert.equal(await page.locator("#keyboard img").count(), 0);
      assert.equal(await page.evaluate(() => window.injected), undefined);
      await page.locator("#keyboard-editor").press("Enter");
      assert.equal(posts.filter(p => p.operation === "run_profile").length, 0);
    } else if (name === "candidate") {
      assert.ok(await page.locator("#keyboard-run").isDisabled());
      assert.match(await page.locator("#keyboard-actions").innerText(), /Kandidat/);
    } else {
      await page.locator("#keyboard-run").evaluate(button => { button.click(); button.click(); });
      await page.waitForFunction(() => !document.querySelector("#keyboard-task").textContent.includes("wird einmalig gesendet"));
      if (name.startsWith("lost_response")) {
        await page.waitForFunction(() => document.querySelector("#keyboard-task").textContent.includes("ungewiss"));
        assert.ok(await page.locator("#keyboard-run").isDisabled());
        await page.reload();
        await page.locator('[data-view="keyboard"]').click();
        await page.locator("#keyboard-status").click();
        await page.waitForFunction(value => document.querySelector("#keyboard-task").textContent.includes(value === "lost_response_preparation" ? "completed" : "unknown"), name);
        assert.ok(await page.locator("#keyboard-run").isDisabled());
        if (name === "lost_response_preparation") {
          await page.locator("#keyboard-status").click();
          await page.waitForFunction(() => document.querySelector("#notice").textContent.includes("Profilbindung und native"));
          assert.ok(gets.every(url => url.endsWith("-main")), "Recovery must keep looking for the primary task");
        }
      } else if (name === "completed_preparation") {
        await page.waitForFunction(() => document.querySelector("#notice").textContent.includes("Nur eine Vorstufe"));
        assert.ok(await page.locator("#keyboard-run").isEnabled(), "A proven halted workflow may release the UI without reporting action success");
      } else if (name.startsWith("failed_")) {
        await page.waitForFunction(() => document.querySelector("#notice").textContent.includes("keyboard_profile_conflict"));
        assert.ok(await page.locator("#keyboard-run").isEnabled(), "A confirmed failure must not lock the UI permanently");
      } else if (name === "missing_post_proof") {
        await page.waitForFunction(() => document.querySelector("#notice").textContent.includes("nicht bestätigt"));
        assert.ok(await page.locator("#keyboard-run").isDisabled(), "A missing native receipt must retain the intent");
      } else {
        await page.waitForFunction(() => document.querySelector("#notice").textContent.includes("Profilbindung und native"));
        assert.equal(gets.length, 1);
      }
      const runs = posts.filter(p => p.operation === "run_profile");
      assert.equal(runs.length, 1, "Double-click, polling and reload must not replay input");
      assert.deepEqual(runs[0].args, { pid: 12345, expected_started_at: 123.5, profile_id: "fixture", expected_revision: revision, action: "select_all" });
    }
    assert.deepEqual(errors, []);
    return { name, passed: true, keyboard_posts: posts.length, status_gets: gets.length };
  } finally { await context.close(); }
}

(async () => {
  assert.ok(process.argv[2], "An output path is required");
  const selected = process.argv.length > 3 ? process.argv.slice(3) : cases;
  assert.ok(selected.every(name => cases.includes(name)), "Unknown case");
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const evidence = { scope: "isolated assets and synthetic HTTP; no native input", results: [] };
  try {
    for (const name of selected) {
      try { evidence.results.push(await check(browser, name)); }
      catch (error) { evidence.results.push({ name, passed: false, error: error.stack || String(error) }); process.exitCode = 1; break; }
    }
  } finally {
    await browser.close();
    await fs.writeFile(process.argv[2], JSON.stringify(evidence, null, 2), { flag: "wx", mode: 0o600 });
    console.log(JSON.stringify(evidence));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
