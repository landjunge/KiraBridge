const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag, text = "") {
    this.tag = tag;
    this.textContent = text;
    this.children = [];
    this.value = "";
    this.listeners = {};
  }

  append(...children) { this.children.push(...children); }
  replaceChildren(...children) {
    this.children = children;
    if (this.tag === "select") this.value = children[0]?.value || "";
  }

  setAttribute() {}
  addEventListener(event, listener) { this.listeners[event] = listener; }
  get childElementCount() { return this.children.length; }
  get options() { return this.children; }
  get text() { return this.textContent + this.children.map(child => child.text).join(" "); }
}

const element = {
  "agents": new Element("section"),
  "coordinator-team": new Element("select"),
  "coordinator-status": new Element("p"),
  "coordinator-candidates": new Element("ul"),
  "coordinator-refresh": new Element("button"),
};
const tab = new Element("button");
const first = {
  host_id: "mac", host_label: "Developer Mac", agent: "claude", principal: "claude",
  model: "opus", role: "coordinator", session_id: "provider-session-A",
  generation: 1, work_id: "tw-A", work_title: "<Analyse A>", state: "idle"
};
const second = {
  ...first, model: "sonnet", role: "worker", session_id: "provider-session-B",
  generation: 2, work_id: "tw-B", work_title: "Analyse B", state: "running"
};
const remote = {
  ...second, host_id: "debian", host_label: "Debian CI", work_id: null, work_title: null,
  model: null, requested_model: "sonnet", state: "unknown"
};
const data = {
  can_manage: true, lifecycle_enabled: true, coordinator: "claude",
  session: first, revision: 12, inventory: [first, second, remote], candidates: [first, second],
  pending: null,
};
let post = null;
let resolvePost = null;
let loseResponse = false;
let operations = 0;
let observedTerminals = [{agent_candidate: "claude", agent_pid: 110, expected_pid: 14,
  pane_id: "terminal:3:ttys003"}];
const context = {
  $: id => element[id],
  names: {claude: "Claude"},
  node: (tag, text) => new Element(tag, text),
  uuid: () => "operation-" + (++operations),
  notice: () => {},
  document: {
    hidden: false,
    documentElement: {lang: "de"},
    querySelector: () => tab
  },
  window: new Element("window"),
  api: async (route, options) => {
    if (route === "/api/team") return {teams: [{id: "kirabridge-team", name: "KiraBridge"}]};
    if (route === "/api/control/terminals") {
      return {sessions: observedTerminals};
    }
    if (route === "/api/team/kirabridge-team/coordinator") return structuredClone(data);
    if (route === "/api/team/kirabridge-team/coordinator/handoff") {
      assert.equal(options.method, "POST");
      post = JSON.parse(options.body);
      if (loseResponse) throw new Error("Connection lost");
      return new Promise(resolve => { resolvePost = resolve; });
    }
    throw new Error(`Unexpected API target ${route}`);
  }
};

const cards = () => element["coordinator-candidates"].children;
const role = () => element["coordinator-status"].textContent;
const button = card => card.children.find(child => child.tag === "button");
const settle = () => new Promise(resolve => setImmediate(resolve));

async function run() {
  vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), context);
  tab.listeners.click();
  await settle();
  assert.equal(cards().length, 4);
  assert.match(cards()[0].text, /opus.*provider-session-A.*<Analyse A>.*tw-A/);
  assert.match(cards()[1].text, /sonnet.*provider-session-B.*Analyse B.*tw-B/);
  assert.match(cards()[2].text, /Ungeklärt.*Debian CI.*provider-session-B/);
  assert.match(cards()[2].text, /Angefordert · sonnet/);
  assert.match(cards()[3].text, /Prozess im Terminal gesehen.*terminal:3:ttys003/);
  assert.equal(button(cards()[0]), undefined);
  assert.equal(button(cards()[2]), undefined);
  assert.equal(button(cards()[3]), undefined);

  // A lost response keeps the same operation key and never changes the role locally.
  loseResponse = true;
  await button(cards()[1]).listeners.click();
  assert.match(role(), /er-session-A/);
  assert.equal(post.idempotency_key, "operation-1");
  loseResponse = false;

  const pending = button(cards()[1]).listeners.click();
  assert.equal(button(cards()[1]).disabled, true);
  assert.match(role(), /er-session-A.*Übergabe wird angefordert/);
  assert.deepEqual(post, {
    principal: "claude", session_id: "provider-session-B", generation: 2,
    expected_revision: 12, idempotency_key: "operation-1"
  });
  data.pending = second;
  resolvePost({state: "pending"});
  await pending;
  assert.match(role(), /er-session-A.*Wartet auf Bestätigung.*er-session-B/);
  assert.equal(button(cards()[1]).disabled, true);

  data.session = second;
  data.pending = null;
  data.revision = 13;
  data.inventory = [
    {...first, role: "worker", state: "completed"},
    {...second, role: "coordinator"},
    remote
  ];
  context.window.listeners["np-kirabridge-status"]();
  await settle();
  assert.match(role(), /er-session-B/);
  assert.match(cards()[0].text, /Abgeschlossen/);
  assert.equal(button(cards()[1]), undefined);

  data.can_manage = false;
  data.inventory[0] = {...first, role: "worker", state: "failed"};
  observedTerminals = [];
  context.window.listeners["np-kirabridge-status"]();
  await settle();
  assert.equal(cards().length, 3);
  assert.match(cards()[0].text, /Fehlgeschlagen/);
  assert.equal(button(cards()[0]), undefined);
}

run().catch(error => { console.error(error); process.exitCode = 1; });
