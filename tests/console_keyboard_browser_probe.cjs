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
const cases = ["profiles_and_discovery", "one_run", "lost_response", "lost_response_preparation", "completed_preparation", "failed_intent", "failed_main", "missing_post_proof", "candidate"];

async function check(browser, name) {
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
        case "apps.list": result = { applications: [{ pid: 12345, started_at: 123.5, bundle_id: document.app.bundle_id, name: '<img src=x onerror="window.injected=1">' }] }; break;
        case "keyboard.profiles.get": result = snapshot(); break;
        case "keyboard.profiles.put": result = { ...snapshot(), profile: body.args.profile }; break;
        case "keyboard.profiles.resolve": result = { context_verified: false, execution_authorized: false, effect: "none", status: "resolved" }; break;
        case "keyboard.shortcuts.discover": result = { revision, entries: [{ name: '<img src=x onerror="window.injected=1">', candidate_only: true }], coverage: "partial", reasons: ["menu_identity_attribute_unavailable"], cached: false }; break;
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
    assert.equal(posts.length, 0, "Opening the tab must not dispatch anything");
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
