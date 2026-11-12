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
  de:{tagline:"Deine Agenten. Ein Überblick.",protocol:"Protokoll ↗",processes:"Prozesse",overview:"Übersicht",terminals:"Terminals",keyboard:"Tastatur",doctor:"Doktor",permissions:"Rechte",identity:"Mit wem arbeitest du?",peers:"Agenten untereinander",currentPermission:"Aktuelle Freigabe",help:"Etwas funktioniert nicht?",openDoctor:"Doktor öffnen →",yourTerminals:"Deine Terminals",repairDoctor:"Reparatur-Doktor",protocolTitle:"Was tatsächlich passiert",older:"Ältere Einträge"},
  en:{tagline:"Your agents. One overview.",protocol:"Activity log ↗",processes:"Processes",overview:"Overview",terminals:"Terminals",keyboard:"Keyboard",doctor:"Doctor",permissions:"Permissions",identity:"Who are you working with?",peers:"Agent communication",currentPermission:"Current permission",help:"Something not working?",openDoctor:"Open doctor →",yourTerminals:"Your terminals",repairDoctor:"Repair doctor",protocolTitle:"What actually happened",older:"Older entries"}
};
function setLanguage(value) {
  locale = value === "en" ? "en" : "de";
  document.documentElement.lang = locale;
  try { localStorage.setItem("kirabridge.locale", locale); } catch { /* Cosmetic only. */ }
  document.querySelectorAll("[data-kb-language]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.kbLanguage === locale)));
  document.querySelectorAll("[data-kb-text]").forEach(element => {
    const value = labels[locale][element.dataset.kbText]; if (value) element.textContent = value;
  });
}
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
