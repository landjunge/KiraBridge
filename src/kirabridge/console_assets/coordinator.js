"use strict";

(() => {
  const panel = $("agents");
  const team = $("coordinator-team");
  const statusLine = $("coordinator-status");
  const list = $("coordinator-candidates");
  const labels = {
    de: {
      loading: "Koordination wird geprüft …",
      unavailable: "Koordination konnte nicht geprüft werden.",
      noTeam: "Kein Team verfügbar.",
      noCoordinator: "Noch kein Koordinator festgelegt.",
      current: "Aktueller Koordinator",
      waiting: "Wartet auf Bestätigung von",
      noSessions: "Keine Agentensitzungen beobachtet.",
      submitting: "Übergabe wird angefordert …",
      rejected: "Die Übergabe wurde nicht bestätigt. Der aktuelle Koordinator bleibt zuständig.",
      unresolved: "Die Anfrage konnte noch nicht bestätigt werden.",
      set: "Als Koordinator festlegen",
      model: "Modell", role: "Rolle", host: "Rechner", session: "Sitzung", work: "Auftrag",
      terminal: "Terminal", generation: "Generation", requested: "Angefordert",
      unknown: "Unbestätigt", local: "Dieser Rechner", observed: "Prozess im Terminal gesehen",
      states: {
        active: "Aktiv", running: "Läuft", idle: "Bereit", completed: "Abgeschlossen",
        failed: "Fehlgeschlagen", cancelled: "Abgebrochen", blocked: "Blockiert",
        accepted: "Empfang bestätigt", starting: "Start bestätigt",
        processing_result: "Ergebnis wird verarbeitet",
        unknown: "Ungeklärt"
      },
      roles: {coordinator: "Koordinator", worker: "Worker", observer: "Beobachter", reviewer: "Prüfer"}
    },
    en: {
      loading: "Checking coordination …",
      unavailable: "Coordination could not be checked.",
      noTeam: "No team available.",
      noCoordinator: "No coordinator selected.",
      current: "Current coordinator",
      waiting: "Waiting for confirmation from",
      noSessions: "No agent sessions observed.",
      submitting: "Requesting handover …",
      rejected: "The handover was not confirmed. The current coordinator remains in charge.",
      unresolved: "The request could not yet be confirmed.",
      set: "Set as coordinator",
      model: "Model", role: "Role", host: "Host", session: "Session", work: "Assignment",
      terminal: "Terminal", generation: "Generation", requested: "Requested",
      unknown: "Unverified", local: "This computer", observed: "Process observed in Terminal",
      states: {
        active: "Active", running: "Running", idle: "Ready", completed: "Completed",
        failed: "Failed", cancelled: "Cancelled", blocked: "Blocked",
        accepted: "Receipt confirmed", starting: "Start confirmed",
        processing_result: "Processing result", unknown: "Unknown"
      },
      roles: {coordinator: "Coordinator", worker: "Worker", observer: "Observer", reviewer: "Reviewer"}
    }
  };

  let snapshot = null;
  let terminalObservations = [];
  let catalogLoaded = false;
  let unavailable = false;
  let submitting = false;
  let reading = false;
  let readVersion = 0;
  let rendered = "";
  let lastIntent = null;

  const words = () => labels[document.documentElement.lang === "en" ? "en" : "de"];
  const name = principal => Object.hasOwn(names, principal) ? names[principal] : principal;
  const route = id => "/api/team/" + encodeURIComponent(id) + "/coordinator";
  const sessionKey = item => JSON.stringify([item.host_id, item.session_id, item.generation]);

  function sessionLabel(session) {
    return name(session.principal) + " · " + session.session_id.slice(-12);
  }

  function makeCard(session, eligible, text) {
    const current = snapshot?.session;
    const isCurrent = current && current.principal === session.principal &&
      current.session_id === session.session_id && current.generation === session.generation &&
      (!current.host_id || current.host_id === session.host_id);
    const title = name(session.agent || session.principal) || text.unknown;
    const state = session.observed === true ? text.observed :
      Object.hasOwn(text.states, session.state) ? text.states[session.state] : text.unknown;
    const role = isCurrent ? text.roles.coordinator :
      Object.hasOwn(text.roles, session.role) ? text.roles[session.role] : text.unknown;
    const card = node("li", undefined, "agent-session");
    const heading = node("header");
    heading.append(node("strong", title), node("span", state, "small"));
    const facts = node("dl");
    const assignment = [session.work_title, session.work_id].filter(Boolean).join(" · ");
    const model = session.model || (session.requested_model ?
      text.requested + " · " + session.requested_model : null);
    const identity = session.session_id && Number.isInteger(session.generation) ?
      session.session_id + " · " + text.generation + " " + session.generation : session.session_id;
    const fields = [
      [text.model, model], [text.role, role],
      [text.host, session.observed === true ? text.local : session.host_label || session.host_id],
      [text.session, identity], [text.work, assignment]
    ];
    if (session.observed === true) fields.push([text.terminal, session.observation[0]]);
    for (const [label, value] of fields) {
      facts.append(node("dt", label), node("dd", value || text.unknown));
    }
    card.append(heading, facts);
    if (eligible && !isCurrent && snapshot?.can_manage === true && snapshot.lifecycle_enabled) {
      const button = node("button", text.set);
      button.type = "button";
      button.disabled = submitting || Boolean(snapshot.pending);
      button.setAttribute("aria-label", text.set + " · " + sessionLabel(eligible));
      button.addEventListener("click", () => requestHandoff(eligible));
      card.append(button);
    }
    return card;
  }

  function render() {
    const text = words();
    const fingerprint = JSON.stringify([
      document.documentElement.lang, snapshot, terminalObservations, catalogLoaded,
      unavailable, submitting, team.value, team.options.length
    ]);
    if (rendered === fingerprint) return;
    rendered = fingerprint;
    list.replaceChildren();
    team.disabled = submitting || team.options.length === 0;

    const status = [];
    if (snapshot?.coordinator) {
      const label = snapshot.session ? sessionLabel(snapshot.session) : name(snapshot.coordinator);
      status.push(text.current + " · " + label + ".");
    } else if (snapshot) {
      status.push(text.noCoordinator);
    } else if (unavailable) {
      status.push(text.unavailable);
    } else {
      status.push(catalogLoaded && !team.value ? text.noTeam : text.loading);
    }
    if (snapshot?.pending) {
      status.push(text.waiting + " " + sessionLabel(snapshot.pending) + ".");
    } else if (snapshot?.last_handoff?.state === "not_accepted") {
      status.push(text.rejected);
    } else if (submitting) {
      status.push(text.submitting);
    }

    const eligible = new Map((snapshot?.candidates || []).map(session => [sessionKey(session), session]));
    const known = new Map((snapshot?.inventory || []).map(session => [sessionKey(session), session]));
    for (const [key, session] of eligible) {
      if (!known.has(key)) known.set(key, session);
    }
    for (const [key, session] of known) {
      list.append(makeCard(session, eligible.get(key), text));
    }
    for (const session of terminalObservations) {
      list.append(makeCard(session, null, text));
    }
    if (list.childElementCount === 0 && (snapshot || catalogLoaded) && !unavailable) {
      status.push(text.noSessions);
    }
    statusLine.textContent = status.join(" ");
  }

  async function loadStatus(version, loadTeams) {
    if (loadTeams || !catalogLoaded) {
      const catalog = await api("/api/team", {cache: "no-store"});
      if (version !== readVersion) return null;
      const selected = team.value;
      team.replaceChildren(...catalog.teams.map(value => {
        const option = node("option", value.name || value.id);
        option.value = value.id;
        return option;
      }));
      if (catalog.teams.some(value => value.id === selected)) team.value = selected;
      else if (catalog.teams.some(value => value.id === "kirabridge-team")) team.value = "kirabridge-team";
      catalogLoaded = true;
    }
    return team.value ? api(route(team.value), {cache: "no-store"}) : null;
  }

  function observedSessions(catalog) {
    return (catalog.sessions || [])
      .filter(session => session.agent_candidate && session.agent_pid && session.pane_id)
      .map(session => ({
        agent: session.agent_candidate,
        observed: true,
        // This is a transport observation. No provider session ID is inferred.
        observation: [session.pane_id, session.expected_pid, session.agent_pid]
      }));
  }

  async function refresh({loadTeams = false, explicit = false} = {}) {
    if (submitting || (reading && !explicit)) return;
    reading = true;
    const version = ++readVersion;
    const [status, terminals] = await Promise.allSettled([
      loadStatus(version, loadTeams),
      api("/api/control/terminals", {cache: "no-store"})
    ]);
    if (version !== readVersion) return;
    reading = false;
    snapshot = status.status === "fulfilled" ? status.value : null;
    terminalObservations = terminals.status === "fulfilled" ? observedSessions(terminals.value) : [];
    unavailable = status.status === "rejected";
    render();
  }

  async function requestHandoff(session) {
    if (submitting || snapshot?.can_manage !== true || snapshot.pending) return;
    if (!snapshot.candidates.includes(session)) return;
    const selected = team.value;
    const payload = {
      principal: session.principal,
      session_id: session.session_id,
      generation: session.generation,
      expected_revision: snapshot.revision
    };
    const intent = JSON.stringify([selected, payload]);
    if (lastIntent?.id !== intent) lastIntent = {id: intent, key: uuid()};
    payload.idempotency_key = lastIntent.key;
    submitting = true;
    readVersion += 1;
    render();
    try {
      await api(route(selected) + "/handoff", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      lastIntent = null;
    } catch (_) {
      notice(words().unresolved, true);
    } finally {
      submitting = false;
      // The committed role and handover are always read back from the server.
      snapshot = null;
      render();
      await refresh({explicit: true});
    }
  }

  function openPanel() {
    render();
    refresh({loadTeams: true, explicit: true});
  }

  document.querySelector('[data-view="agents"]').addEventListener("click", openPanel);
  $("coordinator-refresh").addEventListener("click", openPanel);
  team.addEventListener("change", () => {
    snapshot = null;
    render();
    refresh({explicit: true});
  });
  window.addEventListener("np-kirabridge-status", () => {
    if (!panel.hidden && !document.hidden) refresh();
  });
  window.addEventListener("np-kirabridge-language", render);
})();
