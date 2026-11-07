/* KiraBridge host adapter: reuse authenticated control snapshots on every operator view. */
import {createElapsed} from "./networkpunkt-appbar-state.js";
import {mountProductHeader} from "./networkpunkt-product-header.js";
let latest = null;
const slot = document.querySelector("[data-product-header]");
const eventSource = slot?.dataset.statusSource === "control-events";
function metadata(data) {
  const bridge = data?.bridge;
  if (!bridge || typeof bridge !== "object") return {state:"unknown"};
  return {state:bridge.error ? "error" : data.maintenance ? "busy" : bridge.dispatcher_active === true ? "confirmed" : bridge.dispatcher_active === false ? "disconnected" : "unknown",
    version:bridge.runtime?.version};
}
const header = slot ? mountProductHeader(slot, {selfId:"kirabridge", locale:document.documentElement.lang,
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
