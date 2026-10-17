"use strict";
const labels = {
  created: "Wartet auf Freigabe", queued: "Freigegeben · wartet auf Ausführung",
  accepted: "Empfang bestätigt", running: "Ausführung läuft", completed: "Abgeschlossen",
  failed: "Fehlgeschlagen", unknown: "Status unklar · wird nicht erneut ausgeführt",
  cancelled: "Abgelehnt oder abgebrochen", blocked: "Gesperrt"
};
const operations = {
  "file.list": "Ordner anzeigen", "file.read": "Datei lesen", "file.write": "Datei schreiben",
  "file.mkdir": "Ordner erstellen", "file.move": "Datei oder Ordner verschieben", "file.delete": "Datei löschen",
  "terminal.execute": "Befehl ausführen", "agent.execute": "KI-Agent beauftragen",
  "clipboard.read": "Zwischenablage lesen", "clipboard.write": "Zwischenablage schreiben",
  "clipboard.info": "Zwischenablage prüfen", "process.list": "Prozesse anzeigen",
  "process.inspect": "Prozess prüfen", "process.terminate": "Prozess beenden"
};
const fieldNames = {
  path: "Datei oder Ordner", destination: "Ziel", text: "Text", overwrite: "Vorhandenen Inhalt ersetzen",
  argv: "Befehl und Argumente", cwd: "Arbeitsordner", timeout: "Zeitlimit (Sekunden)",
  max_output: "Ausgabegrenze (Bytes)", max_bytes: "Lesegrenze (Bytes)", agent: "Agent",
  prompt: "Auftrag an den Agenten", task_id: "Betroffener Auftrag"
};
const principals = {chatgpt: "ChatGPT", codex: "Codex", grok: "Grok", local: "diesem Mac"};
const messages = {
  unauthorized: "Öffne „KiraBridge Freigaben.command“ auf deinem Schreibtisch, um diesen Browser anzumelden.",
  state_conflict: "Der Auftrag hat inzwischen seinen Zustand geändert. Bitte aktualisieren.",
  review_conflict: "Der angezeigte Auftrag stimmt nicht überein. Bitte aktualisieren und erneut prüfen.",
  csrf: "Bitte öffne die Freigaben direkt auf diesem Mac.",
  forbidden: "Dieser Auftrag ist durch die eingerichteten Berechtigungen nicht erlaubt."
};
const message = document.getElementById("message");
let loading = false;
let hadRefreshError = false;
async function api(path, options = {}) {
  const token = localStorage.getItem("kirabridge.session") || "";
  const response = await fetch(path, { ...options, cache: "no-store", headers: {
    "Authorization": "Bearer " + token, "Content-Type": "application/json"
  }});
  const data = await response.json();
  if (!response.ok) throw new Error(messages[data.error] || "Die Anfrage konnte nicht abgeschlossen werden.");
  return data;
}
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function card(task) {
  const node = element("article", undefined, "card");
  node.dataset.taskId = task.id;
  node.dataset.state = task.state;
  const line = element("div", undefined, "line");
  line.append(element("strong", operations[task.operation] || task.operation), element("span", labels[task.state] || task.state, "state " + task.state));
  node.append(line, element("p", "Von " + (principals[task.principal] || task.principal) + (task.agent ? " · Agent " + task.agent : ""), "meta"), element("p", task.id, "identifier"));
  const details = element("details");
  details.append(element("summary", "Auftrag und Ergebnis ansehen"));
  const content = element("div");
  details.append(content);
  node.append(details);
  let busy = false;
  async function loadDetails() {
    if (!details.open || content.childElementCount || busy) return;
    busy = true;
    try {
      const data = await api("/api/tasks/" + encodeURIComponent(task.id));
      const value = data.task;
      content.append(element("h3", "Auftragsdetails"));
      for (const [name, argument] of Object.entries(value.args)) {
        content.append(element("p", fieldNames[name] || name, "field-label"), element("pre", typeof argument === "string" ? argument : JSON.stringify(argument, null, 2)));
      }
      if (value.parent_id) content.append(element("p", "Übergeordneter Auftrag: " + value.parent_id, "meta"));
      if (value.receipt) content.append(element("p", "Empfangsbestätigung: " + value.receipt, "meta"));
      if (value.result !== null) content.append(element("h3", "Ergebnis"), element("pre", JSON.stringify(value.result, null, 2)));
      if (value.error) content.append(element("h3", "Fehler"), element("pre", JSON.stringify(value.error, null, 2)));
      if (value.evidence && Object.keys(value.evidence).length) content.append(element("h3", "Ausführungsnachweis"), element("pre", JSON.stringify(value.evidence, null, 2)));
      const actions = element("div", undefined, "actions");
      const choices = value.state === "created" ? [["approve", "Auftrag freigeben"], ["deny", "Ablehnen"]] : value.state === "queued" ? [["deny", "Abbrechen"]] : [];
      for (const [decision, title] of choices) {
        const button = element("button", title, decision === "approve" ? "primary" : "secondary");
        button.type = "button";
        button.addEventListener("click", async () => {
          for (const control of actions.children) control.disabled = true;
          try {
            const answer = await api("/api/tasks/" + encodeURIComponent(task.id) + "/" + decision, {
              method: "POST", body: JSON.stringify({request_hash: data.request_hash})
            });
            message.textContent = decision === "approve" ? "Auftrag freigegeben. Der aktuelle Ausführungsstatus steht beim Auftrag." : "Auftrag abgelehnt oder abgebrochen.";
            await refresh(false, true);
          } catch (error) { message.textContent = error.message; }
        });
        actions.append(button);
      }
      content.append(actions);
    } catch (error) { message.textContent = error.message; }
    finally { busy = false; }
  }
  details.addEventListener("toggle", loadDetails);
  node.addEventListener("task-update", event => {
    const current = event.detail;
    const badge = node.querySelector(".state");
    badge.textContent = labels[current.state] || current.state;
    badge.className = "state " + current.state;
    if (node.dataset.state !== current.state) {
      node.dataset.state = current.state;
      content.replaceChildren();
      loadDetails();
    }
  });
  return node;
}
async function refresh(announce = true, force = false) {
  if (loading || (document.hidden && !announce)) return;
  loading = true;
  try {
    const data = await api("/api/tasks");
    const automatic = Object.entries(data.approval_modes || {})
      .filter(([, mode]) => mode === "automatic")
      .map(([name]) => principals[name] || name);
    document.getElementById("approval-mode").textContent = automatic.length
      ? "Ohne Freigabeklick: " + automatic.join(", ") + ". Erlaubte Aufträge starten automatisch."
      : "Neue Aufträge benötigen eine Freigabe.";
    document.getElementById("count").textContent = data.pending;
    const pending = document.getElementById("pending");
    const recent = document.getElementById("recent");
    const retained = new Map();
    if (!announce && !force) {
      for (const node of document.querySelectorAll("article[data-task-id]")) {
        if (node.querySelector("details[open]")) retained.set(node.dataset.taskId, node);
      }
    }
    pending.replaceChildren(); recent.replaceChildren();
    for (const task of data.tasks) {
      const node = retained.get(task.id) || card(task);
      node.dispatchEvent(new CustomEvent("task-update", {detail: task}));
      (task.state === "created" ? pending : recent).append(node);
    }
    if (!data.pending) pending.append(element("p", "Keine offene Freigabe. Neue Anfragen aus ChatGPT erscheinen hier automatisch.", "empty"));
    if (!recent.childElementCount) recent.append(element("p", "Noch keine Aufträge vorhanden.", "empty"));
    if (announce || hadRefreshError) message.textContent = "Mit KiraBridge auf diesem Mac verbunden.";
    hadRefreshError = false;
  } catch (error) { message.textContent = error.message; hadRefreshError = true; }
  finally { loading = false; }
}
document.getElementById("refresh").addEventListener("click", () => refresh(true));
setInterval(() => refresh(false), 5000);
refresh();
