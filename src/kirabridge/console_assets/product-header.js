import {mountProductHeader} from "./networkpunkt-product-header.js";
let latest = null;
const slot = document.querySelector("[data-product-header]");
const header = slot ? mountProductHeader(slot, {selfId:"kirabridge", readSelf:async () => {
  if (!latest || performance.now() - latest.time >= 8000) return {state:"unknown"};
  const data = latest.data, bridge = data.bridge;
  return {state:bridge?.error ? "error" : data.maintenance ? "busy" : bridge?.dispatcher_active === true ? "confirmed" : bridge?.dispatcher_active === false ? "disconnected" : "unknown",
    version:bridge?.runtime?.version};
}}) : null;
window.addEventListener("np-kirabridge-status", event => {latest = {data:event.detail,time:performance.now()}; header?.refresh();});
window.addEventListener("np-kirabridge-unreachable", () => {latest = null; header?.refresh();});
