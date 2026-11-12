/* KiraBridge Live: read-only poll of the same compact projection the MCP read
 * returns. It shows only family/process state/step/task/time — never prompts or
 * logs — and never presents a process or turn end as a fachliche Abnahme. */
(() => {
  const list = document.getElementById("live-list");
  const observed = document.getElementById("live-observed");
  const hint = document.getElementById("live-hint");
  let timer = null;

  const STATE_LABEL = {
    queued: "eingereiht",
    working: "arbeitet",
    waiting: "wartet",
    blocked: "Fehlschlag",
    unknown: "unbekannt",
    completed: "Turn beendet",
  };

  function token() {
    try { return localStorage.getItem("kirabridge.session") || ""; } catch { return ""; }
  }

  function age(seconds) {
    if (!Number.isFinite(seconds)) return "";
    if (seconds < 90) return `${Math.round(seconds)}s`;
    if (seconds < 5400) return `${Math.round(seconds / 60)}min`;
    return `${Math.round(seconds / 3600)}h`;
  }

  function failureText(agent) {
    if (!agent.failure) return "";
    if (Number.isInteger(agent.exit_code)) return `Fehlschlag, exit ${agent.exit_code}`;
    return "Fehlschlag gemeldet";
  }

  function row(agent) {
    const item = document.createElement("li");
    item.className = "live-row";
    item.dataset.family = agent.family || "unknown";
    item.dataset.state = agent.state || "unknown";
    const dot = document.createElement("span");
    dot.className = "live-dot";
    dot.setAttribute("aria-hidden", "true");
    const main = document.createElement("span");
    main.className = "live-main";
    const title = document.createElement("span");
    title.className = "live-title";
    title.textContent = agent.family || "unknown";
    const step = document.createElement("span");
    step.className = "live-step";
    const detail = [failureText(agent), agent.step, `${age(agent.age_seconds)} ago`]
      .filter(Boolean)
      .join(" · ");
    step.textContent = agent.state === "completed"
      ? `${detail} · keine fachliche Abnahme`
      : detail;
    main.append(title, step);
    const state = document.createElement("span");
    state.className = "live-state";
    state.textContent = STATE_LABEL[agent.state] || agent.state || "unbekannt";
    if (agent.stale) {
      const stale = document.createElement("span");
      stale.className = "live-stale";
      stale.textContent = "stale";
      state.append(stale);
    }
    item.append(dot, main, state);
    return item;
  }

  async function refresh() {
    let value;
    try {
      const response = await fetch("/api/control/live", {
        cache: "no-store",
        headers: { Authorization: "Bearer " + token() },
      });
      value = await response.json();
      if (!response.ok || value.ok === false) {
        hint.textContent = `Live-Stand nicht verfügbar (${value?.error?.code || response.status}).`;
        return;
      }
    } catch {
      hint.textContent = "Live-Stand nicht erreichbar.";
      return;
    }
    hint.textContent = "";
    list.replaceChildren();
    if (!value.agents || value.agents.length === 0) {
      const empty = document.createElement("li");
      empty.className = "live-empty";
      empty.textContent = "Gerade keine beobachtete Agentenarbeit.";
      list.append(empty);
    } else {
      for (const agent of value.agents) list.append(row(agent));
    }
    const at = new Date((value.observed_at || 0) * 1000);
    observed.textContent = `beobachtet ${at.toLocaleTimeString()}`;
    const excluded = value.excluded_principals || [];
    const scope = document.getElementById("live-scope");
    if (scope) {
      scope.textContent =
        `Beobachtet: ${(value.observed_principals || []).join(", ")}` +
        (excluded.length ? ` · nicht beobachtet: ${excluded.join(", ")}` : "") +
        ` · ${value.scope_note || "nur lesende Live-Anzeige."}`;
    }
    const gap = document.getElementById("live-gap");
    if (gap) {
      const coverage = value.coverage || {};
      gap.textContent = `${coverage.not_observed || ""} ${coverage.acceptance || ""}`.trim();
    }
  }

  refresh();
  timer = setInterval(refresh, 2000);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      clearInterval(timer);
      timer = null;
    } else if (timer === null) {
      refresh();
      timer = setInterval(refresh, 2000);
    }
  });
})();
