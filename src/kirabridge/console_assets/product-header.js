/* KiraBridge host adapter: reuse authenticated control snapshots and the native
 * family switch. Only a catalog ID crosses the web→native boundary here; no
 * URL, argv, PID or shell is ever accepted from this renderer. */
import {createElapsed} from "./networkpunkt-appbar-state.js";
import {APP_CATALOG} from "./networkpunkt-appbar-catalog.js";
import {mountProductHeader} from "./networkpunkt-product-header.js";
let latest = null;
const slot = document.querySelector("[data-product-header]");
const eventSource = slot?.dataset.statusSource === "control-events";
let locale = document.documentElement.lang;
try { const saved = localStorage.getItem("kirabridge.locale"); if (["de","en"].includes(saved)) locale = saved; } catch { /* Existing cosmetic preference is optional. */ }
const labels = {
  de:{tagline:"Deine Agenten. Ein Überblick.",protocol:"Protokoll ↗",processes:"Prozesse",overview:"Übersicht",terminals:"Terminals",keyboard:"Tastatur",doctor:"Doktor",permissions:"Rechte",identity:"Mit wem arbeitest du?",peers:"Agenten untereinander",currentPermission:"Aktuelle Freigabe",help:"Etwas funktioniert nicht?",openDoctor:"Doktor öffnen →",yourTerminals:"Deine Terminals",agents:"Agenten",agentSessions:"Agentensitzungen",coordinatorRefresh:"Aktualisieren",coordinatorTeam:"Team",repairDoctor:"Reparatur-Doktor",protocolTitle:"Was tatsächlich passiert",older:"Ältere Einträge",voiceAssistants:"Sprachassistenten",voiceStatusNote:"Status aus den letzten Prüfungen",cliAgents:"Agenten-CLIs",reload:"Neu laden",details:"Details",placeholder:"Vorschau",agentDetails:"Agentendetails",selectAgentHint:"Wähle eine Karte, um den Status zu sehen. Weitere Inhalte folgen.",workContext:"Arbeitskontext",workContextPlaceholder:"Auftrag, Sitzungs-ID und Rechner werden hier ergänzt.",settingsHeading:"Einstellungen",settingsButton:"⚙ Einstellungen",rightsButton:"◈ Rechte",backToOverview:"Zur Übersicht",displaySettings:"Darstellung",displaySettingsHelp:"Sprache und Seitenleisten werden lokal für diese Konsole gespeichert. Berechtigungen werden separat verwaltet.",language:"Sprache",appearance:"Farbschema",light:"Hell",dark:"Dunkel",sidebars:"Seitenleisten",processSidebar:"Prozesse",detailsSidebar:"Details",layout:"Layout",resetLayout:"Standardlayout wiederherstellen",coordinatorUnknown:"Koordinator ungeprüft",coordinatorUnavailable:"Koordinatorstatus nicht verfügbar",protocolWindowHint:"Nur das Protokoll öffnet ein eigenes Fenster."},
  en:{tagline:"Your agents. One overview.",protocol:"Activity log ↗",processes:"Processes",overview:"Overview",terminals:"Terminals",keyboard:"Keyboard",doctor:"Doctor",permissions:"Permissions",identity:"Who are you working with?",peers:"Agent communication",currentPermission:"Current permission",help:"Something not working?",openDoctor:"Open doctor →",yourTerminals:"Your terminals",agents:"Agents",agentSessions:"Agent sessions",coordinatorRefresh:"Refresh",coordinatorTeam:"Team",repairDoctor:"Repair doctor",protocolTitle:"What actually happened",older:"Older entries",voiceAssistants:"Voice assistants",voiceStatusNote:"Status from recent checks",cliAgents:"Agent CLIs",reload:"Reload",details:"Details",placeholder:"Preview",agentDetails:"Agent details",selectAgentHint:"Select a card to inspect its status. More details will follow.",workContext:"Work context",workContextPlaceholder:"Assignment, session ID, and host will be added here.",settingsHeading:"Settings",settingsButton:"⚙ Settings",rightsButton:"◈ Permissions",backToOverview:"Back to overview",displaySettings:"Display",displaySettingsHelp:"Language and sidebars are saved locally for this console. Permissions are managed separately.",language:"Language",appearance:"Color scheme",light:"Light",dark:"Dark",sidebars:"Sidebars",processSidebar:"Processes",detailsSidebar:"Details",layout:"Layout",resetLayout:"Restore default layout",coordinatorUnknown:"Coordinator not checked",coordinatorUnavailable:"Coordinator status unavailable",protocolWindowHint:"Only the activity log opens in a separate window."}
};
function setLanguage(value) {
  locale = value === "en" ? "en" : "de";
  document.documentElement.lang = locale;
  try { localStorage.setItem("kirabridge.locale", locale); } catch { /* Cosmetic only. */ }
  document.querySelectorAll("[data-kb-language]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.kbLanguage === locale)));
  document.querySelectorAll("[data-kb-text]").forEach(element => {
    const value = labels[locale][element.dataset.kbText]; if (value) element.textContent = value;
  });
  window.dispatchEvent(new Event("np-kirabridge-language"));
}
// The native desktop shell owns the visible DE/EN segment and drives this one switcher.
window.kbSetLanguage = setLanguage;
document.querySelectorAll("[data-kb-language]").forEach(button => button.addEventListener("click", () => setLanguage(button.dataset.kbLanguage)));
if (document.querySelector("[data-kb-language]")) setLanguage(locale);
function metadata(data) {
  const bridge = data?.bridge;
  if (!bridge || typeof bridge !== "object") return {state:"unknown"};
  return {state:bridge.error ? "error" : data.maintenance ? "busy" : bridge.dispatcher_active === true ? "confirmed" : bridge.dispatcher_active === false ? "disconnected" : "unknown",
    version:bridge.runtime?.version};
}

/** Native family-switch bridge. The native host injects `window.__kbFamilySwitch`
 * which accepts exactly one catalog ID and resolves to one of
 * "focused" | "failed" | "uncertain" | "missing".
 * No URL/argv/PID leaves the renderer; a missing bridge is an honest "missing". */
async function openTarget(appId) {
  if (!APP_CATALOG.some((app) => app.id === appId)) return "failed";
  const bridge = window.__kbFamilySwitch;
  if (typeof bridge !== "function") return "missing";
  try {
    const outcome = await bridge(appId);
    return ["focused","failed","uncertain","missing"].includes(outcome)
      ? outcome : "uncertain";
  } catch {
    return "uncertain";
  }
}

const header = slot ? mountProductHeader(slot, {selfId:"kirabridge", locale, openTarget,
  readSelf:async ({signal}) => {
    if (eventSource) return !latest || latest.age() >= 8000 ? {state:"unknown"} : metadata(latest.data);
    let token;
    try { token = localStorage.getItem("kirabridge.session") || ""; } catch { return {state:"unknown"}; }
    if (!token) return {state:"unknown"};
    const response = await fetch("/api/control/status", {signal,cache:"no-store",headers:{Authorization:"Bearer "+token}});
    if (response.status === 401 || response.status === 403) return {state:"unknown"};
    if (!response.ok) throw Error("Control status unavailable");
    return metadata(await response.json());
  }}) : null;
window.addEventListener("np-kirabridge-status", event => {
  latest = {data:event.detail,age:createElapsed(()=>performance.now(),()=>Date.now())};
  if (eventSource) header?.refresh();
});
window.addEventListener("np-kirabridge-unreachable", () => {latest = null; if (eventSource) header?.refresh();});
