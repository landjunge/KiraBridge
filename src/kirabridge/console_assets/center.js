"use strict";
// Native shell embedding: the desktop app draws the family header, the process sidebar and
// the details column itself, so the console keeps only its middle part.
if(typeof location!=="undefined"&&document.documentElement&&new URLSearchParams(location.search).get("shell")==="native")document.documentElement.classList.add("native-shell");
const $=id=>document.getElementById(id);
function renderVersion(data){const tag=$("footer-version");if(!tag)return;const release=data.release||{};const version=(data.bridge&&data.bridge.version)||release.version;if(!version){tag.hidden=true;return;}const commit=release.source_commit?String(release.source_commit).slice(0,7):"";tag.textContent="v"+version+(commit?" · "+commit:"");const consoleNote=release.version&&release.version!==version?" · Steuerfenster "+release.version:"";tag.title="KiraBridge "+version+(release.source_commit?" · Quellstand "+release.source_commit:" · Entwicklungsstand")+consoleNote;tag.setAttribute("aria-label","Installierte Version "+tag.title);tag.hidden=false;}
let statusData=null,connections=null,sessions=[],activeView="overview",busy=false,agentCatalog=null,coordinatorSnapshot=null,coordinatorPrincipal=null,coordinatorTeamId=null,coordinatorBusy=false;
let displayedTerminal=null,terminalIntent=null,terminalLastIntent=null,terminalDraftVersion=0,terminalComposing=false,terminalComposeEnter=false,terminalSelected=false;
let serviceFingerprint="";
const names={local:"Du",chatgpt:"Kira · ChatGPT",grok_app:"Grok · App",codex:"Codex",grok:"Grok · Terminal"};
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function notice(text,error=false){$("notice").textContent=text;$("notice").classList.toggle("error",error);}
async function api(path,options={}){let token;try{token=localStorage.getItem("kirabridge.session")||"";}catch(_){throw Error("Bitte KiraBridge über den lokalen Starter öffnen.");}const response=await fetch(path,{...options,headers:{"Authorization":"Bearer "+token,"Content-Type":"application/json",...(options.headers||{})}});const data=await response.json();if(!response.ok||data.error){const e=data.error;if(e==="unauthorized"||response.status===401){const failure=Error("Nicht angemeldet. Öffne die Freigaben im Terminal mit „kirabridge approvals“.");failure.unauthorized=true;throw failure;}throw Error(typeof e==="object"?(e.message||e.code||"Die Ausführung ist fehlgeschlagen."):e||"Verbindung fehlgeschlagen");}return data;}
function uuid(){return crypto.randomUUID().replaceAll("-","");}
function showView(name){activeView=name;document.querySelectorAll(".view").forEach(n=>n.hidden=n.id!==name);document.querySelectorAll("[data-view]").forEach(n=>n.setAttribute("aria-selected",String(n.dataset.view===name)));if(name==="terminals")loadTerminals();if(name==="doctor")perform(()=>doctor(false));if(name==="permissions")loadApprovals();}
async function act(service,action){notice((action==="restart"?"Neustart":"Start")+" wird angefordert …");const result=await api("/api/control/action",{method:"POST",body:JSON.stringify({service,action,action_id:uuid()})});if(result.error)throw Error(result.error.message);notice(result.message||"Aktion angefordert. Der tatsächliche Zustand wird geprüft.");await refresh(true);return result;}
function serviceCard(item){const card=node("article",undefined,"process-card np-card "+item.state);card.dataset.service=item.id;const row=node("div",undefined,"process-compact-row"),name=node("span",item.name,"name"),state=node("span",undefined,"process-state np-status"),translated={Aktiv:"Active",Inaktiv:"Inactive","Nicht verfügbar":"Unavailable","Nicht installiert":"Not installed"},detail=document.documentElement.lang==="en"?(translated[item.detail]||item.detail):item.detail;state.append(node("span",undefined,"dot np-status-dot"),node("span",detail));const actions=node("div",undefined,"process-actions");for(const action of ["start","restart"]){const restart=item.restart_label&&item.restart_label!=="Neustart"?item.restart_label:localized("Neustart","Restart"),b=node("button",action==="start"?localized("Start","Start"):restart,action+" np-button");b.type="button";b.disabled=action==="start"?item.active:!item.restart_available;b.title=b.disabled&&action==="restart"?localized("Eine vorhandene Sitzung wird nicht beendet.","An existing session will not be stopped."):item.name+": "+b.textContent;b.addEventListener("click",()=>perform(()=>act(item.id,action)));actions.append(b);}row.append(name,state,actions);card.append(row);return card;}
function mobileControls(){const item=statusData?.services.find(s=>s.id===$("mobile-process").value);$("mobile-start").disabled=!item||item.active;$("mobile-restart").disabled=!item||!item.restart_available;$("mobile-restart").textContent=item?.restart_label||"Neustart";}
function renderStatus(data){window.dispatchEvent(new CustomEvent("np-kirabridge-status",{detail:data}));statusData=data;const fingerprint=JSON.stringify(data.services);if(fingerprint!==serviceFingerprint){$("processes").replaceChildren(...data.services.map(serviceCard));serviceFingerprint=fingerprint;const previous=$("mobile-process").value;$("mobile-process").replaceChildren(...data.services.map(item=>{const option=node("option",item.name);option.value=item.id;return option;}));if(data.services.some(s=>s.id===previous))$("mobile-process").value=previous;}mobileControls();const live=!!data.bridge.dispatcher_active;$("bridge-indicator").className="bridge-indicator "+(live?"active":"inactive");$("bridge-indicator").replaceChildren(node("span",undefined,"dot"),node("span",live?(data.maintenance?"KiraBridge: Wartung":"KiraBridge läuft"):data.services.find(s=>s.id==="bridge")?.active?"KiraBridge: Antwort fehlt":"KiraBridge ist inaktiv"));$("observed-at").textContent="Geprüft um "+new Date(data.observed_at*1000).toLocaleTimeString("de-DE");renderVersion(data);$("footer-state").textContent=live?"Mit KiraBridge verbunden · "+new Date(data.observed_at*1000).toLocaleTimeString("de-DE"):"Die Steuerung bleibt erreichbar. KiraBridge über Start einschalten.";$("permission-summary").textContent=!data.settings_loaded?"Noch nicht aktiv geladen":data.permissions_consistent?(data.permission_details?.chatgpt?.label||data.permission_choices[data.level]):"Unterschiedliche Freigaben";$("permission-detail").textContent=!data.settings_loaded?"Geänderte Einstellungen sind noch nicht aktiv geladen. ":data.permissions_consistent?"Aktiv: "+data.permission_choices[data.level]+". Erteilte Zugriffsrechte bleiben erhalten.":"Die Zugänge haben unterschiedliche Freigaben. Eine Auswahl vereinheitlicht sie.";if(!document.querySelector('input[name="permission"]:focus')){const checked=document.querySelector('input[name="permission"][value="'+data.level+'"]');if(checked&&!document.querySelector('input[name="permission"][data-edited]'))checked.checked=true;}if(data.bridge.terminal_access){$("permission-detail").textContent+=" "+(data.bridge.terminal_access.policy_authorized?"Terminal-Erkennung, Lesen und Eingabe sind erlaubt. Erreichbarkeit unter Terminals prüfen.":"Terminalrechte sind nicht vollständig erteilt.");}renderPermissionExceptions(data);if(data.maintenance){$("footer-state").textContent="Aktivierung: "+data.maintenance.state+" · Neue Aufträge vorübergehend gesperrt. Bestehende Arbeit bleibt erhalten.";}$("peer-summary").textContent=data.peers_connected?"Nachrichtenwege bereit":"Doktor: Verbindungen reparieren";const pending=$("pending-summary");pending.replaceChildren();if(data.pending.length){const b=node("button",data.pending.length+" Auftrag/Aufträge warten auf deine Erlaubnis");b.addEventListener("click",()=>showView("permissions"));pending.append(b);}}
function renderPermissionExceptions(data){
 if(Object.hasOwn(data,"keyboard_permissions"))renderMacOSPermissions(data.keyboard_permissions);
 const area=$("permission-exceptions");area.replaceChildren();
 const entries=Object.entries(data.permission_details||{}).flatMap(([principal,detail])=>(detail.exceptions||[]).map(item=>({principal,...item})));
 if(!entries.length){area.textContent="Keine dauerhaften Ausnahmen.";return;}
 $("permission-detail").textContent+=" Dauerhafte Ausnahmen gelten auch unter Nur mit Erlaubnis.";
 for(const item of entries){
  const row=node("div"),button=node("button","Ausnahme widerrufen");
  row.append(node("span",(names[item.principal]||item.principal)+": Terminaleingabe "+(item.authorized?"dauerhaft freigegeben. ":"durch fehlende Rechte gesperrt. ")));
  button.addEventListener("click",()=>perform(async()=>{
   await api("/api/control/permissions",{method:"POST",body:JSON.stringify({revoke_operations:{[item.principal]:[item.operation]}})});
   notice("Dauerhafte Ausnahme widerrufen. Die gewählte Rechtestufe bleibt wirksam.");await refresh(true);
  }));row.append(button);area.append(row);
 }
}
function renderMacOSPermissions(guidance){
 const host=$("permission-exceptions")?.parentElement;if(!host)return;
 let area=$("macos-keyboard-permissions");
 if(!area){area=node("section");area.id="macos-keyboard-permissions";area.setAttribute("aria-live","polite");host.append(area);}
 area.replaceChildren();area.hidden=!guidance||!Array.isArray(guidance.checks);if(area.hidden)return;
 area.append(node("h3","macOS-Freigaben für die Tastatur"),node("p",guidance.summary||"Noch nicht geprüft."));
 const links={accessibility:"x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",post_events:"x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",input_monitoring:"x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",screen_capture:"x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",automation:"x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"};
 for(const check of guidance.checks){
  if(!check||!Object.hasOwn(links,check.resource))continue;
  const row=node("div",undefined,"doctor-check"),content=node("div");
  const label=check.required_for_keyboard?(check.state==="granted"?"Freigegeben":check.state==="not_granted"?"Freigabe fehlt":"Noch nicht geprüft"):"Für Tastatureingaben nicht erforderlich";
  content.append(node("strong",(check.label||"")+": "+label),node("p",check.reason||""));
  if(check.required_for_keyboard&&check.state!=="granted"){
   const link=node("a","In Systemeinstellungen prüfen");link.href=links[check.resource];content.append(link,node("p",check.manual_steps||"Systemeinstellungen → Datenschutz & Sicherheit"));
  }
  row.append(content);area.append(row);
 }
 area.append(node("p",guidance.instructions||"macOS entscheidet über diese Freigaben."));
}
function renderConnections(){
 if(!connections)return;
 const host=$("voice-cards");if(!host)return;host.replaceChildren();
 const locale=document.documentElement.lang==="en"?"en":"de";
 const labels=locale==="en"?{open:"Open conversation",confirmed:"Recent request confirmed",unverified:"No recent access check",ready:"Connection details available",connect:"Approve"}:{open:"Gespräch öffnen",confirmed:"Letzter Aufruf bestätigt",unverified:"Noch kein Zugriff geprüft",ready:"Verbindungsdaten vorhanden",connect:"Freigeben"};
 const voice=[{id:"chatgpt",name:"ChatGPT",url:connections.chatgpt_url,mark:"ChatGPT"},{id:"grok_app",name:"Grok",url:connections.grok_url,mark:"Grok"}];
 for(const item of voice){
  const card=node("article",undefined,"voice-card np-card"),lockup=node("div",undefined,"provider-lockup"),mark=node("span",item.id==="chatgpt"?"GPT":"G","provider-mark");
  mark.setAttribute("aria-label",item.name+" Wortmarke");const title=node("div");title.append(node("div",item.name,"provider-name"),node("div",localized("Sprachassistent","Voice assistant"),"provider-family"));lockup.append(mark,title);card.append(lockup);
  const link=node("a",labels.open,"provider-link np-button");link.href=item.url;link.target="_blank";link.rel="noopener noreferrer";card.append(link);
  const check=(connections.checks||[]).find(row=>row.principal===item.id),grokConfigured=item.id==="grok_app"&&connections.grok?.enabled===true;
  const state=node("div",undefined,"voice-state np-status");state.dataset.state=check?"success":"warning";state.append(node("span",undefined,"dot np-status-dot"),node("span",check?labels.confirmed:grokConfigured?localized("Konfiguriert · nicht live geprüft","Configured · not live-checked"):labels.unverified));card.append(state);
  if(item.id==="grok_app")for(const pending of connections.grok?.pending||[]){const approve=node("button",labels.connect,"np-button");approve.type="button";approve.addEventListener("click",()=>perform(async()=>{await api("/api/control/consent/"+encodeURIComponent(pending.id),{method:"POST",body:JSON.stringify({allow:true})});notice("Grok-Verbindung freigegeben.");await refresh(true);}));card.append(approve);}
  host.append(card);
 }
}
function localized(de,en){return document.documentElement.lang==="en"?en:de;}
function setTheme(theme){const selected=theme==="light"?"light":"dark";document.documentElement.dataset.theme=selected;try{localStorage.setItem("kirabridge.theme",selected);}catch(_){/* Appearance preference is optional. */}document.querySelectorAll("[data-theme-choice]").forEach(button=>button.setAttribute("aria-pressed",String(button.dataset.themeChoice===selected)));}
function initTheme(){let theme="dark";try{theme=localStorage.getItem("kirabridge.theme")||theme;}catch(_){/* Appearance preference is optional. */}setTheme(theme);document.querySelectorAll("[data-theme-choice]").forEach(button=>button.addEventListener("click",()=>setTheme(button.dataset.themeChoice)));}
function addOption(select,value,label){const option=node("option",label);option.value=value;select.append(option);}
function compatibilityText(agent){const status=agent.compatibility?.status;if(status==="compatible")return localized("Version kompatibel","Version compatible");if(!agent.version)return localized("Kompatibilität unbekannt","Compatibility unknown");return localized("Version erkannt · Kompatibilität nicht deklariert","Version observed · compatibility not declared");}
function agentCard(agent,coordinator,canSelectCoordinator){
 const card=node("article",undefined,"cli-card np-card");card.dataset.agent=agent.cli;card.setAttribute("aria-selected","false");
 const kindNames={codex:"OpenAI Codex",claude_code:"Claude Code",qwen_acp:"Qwen Code"};
 const symbols={codex:"CX",claude:"CL",qwen:"QW"};
 const head=node("div",undefined,"cli-card-header"),lockup=node("div",undefined,"provider-lockup"),mark=node("span",symbols[agent.cli],"provider-mark");mark.setAttribute("aria-label",agent.name+" Wortmarke");const identity=node("div");identity.append(node("div",agent.name,"cli-card-title"),node("div",kindNames[agent.kind]||localized("Nicht konfiguriert","Not configured"),"cli-card-subtitle"));lockup.append(mark,identity);
 const state=node("div",undefined,"agent-state np-status");state.dataset.state=agent.active?"success":agent.installed?"warning":"danger";state.append(node("span",undefined,"dot np-status-dot"),node("span",agent.active?localized("Aktiv","Active"):agent.installed?localized("Bereit","Ready"):localized("Nicht verfügbar","Unavailable")));head.append(lockup,state);card.append(head);
 const detail=node("div",agent.version?"v"+agent.version:localized("Version nicht erkannt","Version not observed"),"model-detail");detail.title=agent.executable||"";card.append(detail);
 const controls=node("div",undefined,"cli-controls"),model=node("select");model.className="np-dropdown";model.setAttribute("aria-label",localized("Modell","Model"));if(agent.model){addOption(model,"configured",localized("Konfiguriert: ","Configured: ")+agent.model);addOption(model,"cli-default",localized("CLI-Standard","CLI default"));}else addOption(model,"cli-default",localized("CLI-Standard","CLI default"));const modelLabel=node("label");modelLabel.append(node("span",localized("Modell","Model")),model);controls.append(modelLabel);
 const effort=node("select");effort.className="np-dropdown";effort.setAttribute("aria-label",localized("Denkstufe","Reasoning effort"));const efforts=agent.cli==="claude"?["default","low","medium","high","xhigh","max"]:agent.cli==="codex"?["default","low","medium","high","xhigh"]:["default"];for(const value of efforts)addOption(effort,value,value==="default"?localized("CLI-Standard","CLI default"):value);const effortLabel=node("label");effortLabel.append(node("span",localized("Denkstufe","Effort")),effort);controls.append(effortLabel);
 const permission=node("select");permission.className="np-dropdown";permission.setAttribute("aria-label",localized("Berechtigungsmodus","Permission mode"));addOption(permission,"policy",localized("KiraBridge-Regeln","KiraBridge policy"));addOption(permission,"plan",localized("Plan · nur lesen","Plan · read-only"));const permissionLabel=node("label");permissionLabel.append(node("span",localized("Rechte","Access")),permission);controls.append(permissionLabel);card.append(controls);
 const compatibility=node("div",compatibilityText(agent),"compatibility");compatibility.dataset.state="neutral";card.append(compatibility);
 const actions=node("div",undefined,"cli-card-actions"),play=node("button",localized("▶ Start","▶ Start"),"play np-button");play.type="button";play.disabled=!agent.configured||!agent.installed||agent.active;play.title=agent.active?localized("Die vorhandene Sitzung bleibt erhalten.","Existing session is preserved."):!agent.installed?localized("CLI ist nicht verfügbar.","CLI is unavailable."):"";
 play.addEventListener("click",()=>perform(async()=>{const actionId=uuid();notice(agent.name+" wird mit den gewählten Vorgaben im Terminal geöffnet …");const result=await api("/api/control/action",{method:"POST",body:JSON.stringify({service:agent.id,action:"start",action_id:actionId,launch_options:{model:model.value,effort:effort.value,permission:permission.value}})});if(result.state==="failed"||result.error)throw Error(result.error?.message||"Start wurde nicht bestätigt.");notice(result.message||"Terminalstart angefordert. Zustand wird neu geprüft.");await refresh(true);await loadAgentCards(true);}));
 const coordinatorMark=node("button","K","coordinator np-button");coordinatorMark.type="button";coordinatorMark.disabled=coordinator||coordinatorBusy;coordinatorMark.setAttribute("aria-disabled",String(!canSelectCoordinator));coordinatorMark.title=coordinator?localized("Aktueller Koordinator laut Teamrolle","Current coordinator from team role"):localized("Als Koordinator wählen","Set as coordinator");coordinatorMark.setAttribute("aria-label",coordinatorMark.title);coordinatorMark.setAttribute("aria-pressed",String(coordinator));if(!coordinatorMark.disabled)coordinatorMark.addEventListener("click",()=>perform(()=>requestCoordinatorHandoff(agent)));
 const reload=node("button","↻","reload-one np-button");reload.type="button";reload.title=localized("Status und CLI-Version neu prüfen","Refresh status and CLI version");reload.addEventListener("click",()=>perform(()=>loadAgentCards(true)));actions.append(play,coordinatorMark,reload);card.append(actions);return card;
}
async function loadAgentCards(fresh=false){
 const host=$("cli-cards");if(!host)return;if(fresh)host.replaceChildren(node("p",localized("Agentenstatus und CLI-Versionen werden geprüft …","Checking agent status and CLI versions …"),"small"));
 const data=await api("/api/cli"+(fresh?"?fresh=1":""),{cache:"no-store"});agentCatalog=data;coordinatorSnapshot=null;coordinatorPrincipal=null;coordinatorTeamId=null;
 try{const teams=await api("/api/team",{cache:"no-store"}),first=(teams.teams||[]).find(team=>team.id==="kirabridge-team")||(teams.teams||[])[0];if(first){coordinatorTeamId=first.id;coordinatorSnapshot=await api("/api/team/"+encodeURIComponent(first.id)+"/coordinator",{cache:"no-store"});coordinatorPrincipal=coordinatorSnapshot.coordinator||null;}}catch(_){coordinatorSnapshot=null;}
 const summary=$("coordinator-summary");if(summary)summary.textContent=coordinatorSnapshot?(coordinatorPrincipal?localized("Koordinator: ","Coordinator: ")+coordinatorPrincipal:localized("Koordinator: keiner festgelegt","Coordinator: none selected")):localized("Koordinatorstatus nicht verfügbar","Coordinator status unavailable");
 host.replaceChildren(...data.agents.map(agent=>{const current=coordinatorPrincipal===agent.cli||coordinatorPrincipal===agent.id;const candidate=(coordinatorSnapshot?.candidates||[]).find(session=>session.principal===agent.id||session.agent===agent.id||session.agent===agent.cli);const canSelect=Boolean(coordinatorSnapshot?.can_manage===true&&coordinatorSnapshot.lifecycle_enabled===true&&!coordinatorSnapshot.pending&&candidate);return agentCard(agent,current,canSelect);}));
 if(!data.cli_inventory_available)host.append(node("p",localized("Versionsprüfung derzeit nicht verfügbar.","Version check is currently unavailable."),"small"));
}
async function requestCoordinatorHandoff(agent){
 if(coordinatorBusy||!coordinatorSnapshot||!coordinatorTeamId)throw Error(localized("Koordinatorstatus ist nicht verfügbar.","Coordinator status is unavailable."));
 const session=(coordinatorSnapshot.candidates||[]).find(item=>item.principal===agent.id||item.agent===agent.id||item.agent===agent.cli);
 if(!session||coordinatorSnapshot.can_manage!==true||coordinatorSnapshot.lifecycle_enabled!==true||coordinatorSnapshot.pending)throw Error(localized("Für diese CLI gibt es keine bestätigte, übernehmbare Sitzung.","There is no confirmed eligible session for this CLI."));
 coordinatorBusy=true;document.querySelectorAll(".coordinator").forEach(button=>button.disabled=true);
 try{await api("/api/team/"+encodeURIComponent(coordinatorTeamId)+"/coordinator/handoff",{method:"POST",body:JSON.stringify({principal:session.principal,session_id:session.session_id,generation:session.generation,expected_revision:coordinatorSnapshot.revision,idempotency_key:uuid()})});notice(localized("Koordinatorwechsel angefordert; Übernahme wird geprüft.","Coordinator handoff requested; confirmation is being checked."));}
 finally{coordinatorBusy=false;await loadAgentCards(true);}
}
function updateAgentCardStatuses(){
 if(!agentCatalog||!statusData)return;
 for(const card of document.querySelectorAll(".cli-card[data-agent]")){
  const agent=agentCatalog.agents.find(item=>item.cli===card.dataset.agent),service=statusData.services?.find(item=>item.id===agent?.id);if(!agent||!service)continue;
  agent.active=Boolean(service.active);agent.installed=Boolean(service.installed);
  const state=card.querySelector(".agent-state"),label=state?.querySelector("span:last-child"),play=card.querySelector(".play");if(!state||!label||!play)continue;
  state.dataset.state=agent.active?"success":agent.installed?"warning":"danger";label.textContent=agent.active?localized("Aktiv","Active"):agent.installed?localized("Bereit","Ready"):localized("Nicht verfügbar","Unavailable");play.disabled=!agent.configured||!agent.installed||agent.active;
 }
}
async function refresh(announce=false){if(busy&&!announce)return;try{const results=await Promise.all([api("/api/control/status"),api("/api/control/connections")]);renderStatus(results[0]);updateAgentCardStatuses();connections=results[1];renderConnections();if(announce)notice(results[0].bridge.dispatcher_active?"Zustände geprüft. KiraBridge antwortet.":"KiraBridge antwortet nicht. Start ist links direkt möglich.",!results[0].bridge.dispatcher_active);}catch(e){window.dispatchEvent(new Event("np-kirabridge-unreachable"));notice(e.message,true);$("bridge-indicator").className="bridge-indicator inactive";$("bridge-indicator").replaceChildren(node("span",undefined,"dot"),node("span",e.unauthorized?"Nicht angemeldet":"Zustand nicht erreichbar"));}}
let actionQueue=Promise.resolve();function perform(callback){const pending=actionQueue.then(async()=>{busy=true;try{await callback();}catch(e){notice(e.message,true);}finally{busy=false;}});actionQueue=pending.catch(()=>{});return pending;}
async function doctor(repair){notice(repair?"Der Doktor behebt erreichbare Probleme …":"Der Doktor prüft …");const result=await api("/api/control/doctor",repair?{method:"POST",body:"{}"}:{});$("doctor-checks").replaceChildren(...result.checks.map(c=>{const n=node("div",undefined,"doctor-check");n.append(node("span",c.ok?"✓":"!",c.ok?"ok":"problem"));const t=node("div");t.append(node("strong",c.name),node("p",c.message));n.append(t);return n;}));const missing=result.checks.filter(c=>!c.ok).length;$("doctor-summary").textContent=missing?missing+" Punkt(e) brauchen Aufmerksamkeit.":"Alle geprüften Punkte funktionieren.";const peers=result.checks.find(c=>c.name==="Agenten untereinander");if(peers)$("peer-summary").textContent=peers.message;notice(result.repaired.length?result.repaired.join(" · "):missing?"Prüfung abgeschlossen. Fehlende Punkte sind sichtbar.":"Prüfung abgeschlossen: Alles Geprüfte funktioniert.");if(repair)await refresh(true);}
const terminalPlaceholderText=()=>localized("Wähle eine erreichbare Sitzung aus.","Select an available session.");
async function loadTerminals(){displayedTerminal=null;updateTerminalInputControls();try{const result=await api("/api/control/terminals");sessions=result.sessions||[];const previous=$("terminal-select").value;const hadSelection=terminalSelected&&sessions.some(s=>s.pane_id===previous);const placeholder=node("option",sessions.length?localized("Bitte Sitzung auswählen","Select a session"):localized("Keine erreichbare Sitzung","No session available"));placeholder.value="";$("terminal-select").replaceChildren(placeholder,...sessions.map(s=>{const n=node("option",s.pane_id+" · "+(s.busy===true?"Programm läuft":s.busy===false?"Terminal wartet":"Prozess erkannt"));n.value=s.pane_id;return n;}));if(hadSelection){$("terminal-select").value=previous;await readTerminal();}else{terminalSelected=false;$("terminal-select").value="";$("terminal-output").textContent=terminalPlaceholderText();}$("terminal-state").textContent=sessions.length+" erreichbare Sitzung(en). Bereitschaft wird bei der Übergabe geprüft.";}catch(e){notice(e.message,true);}}
function selectedTerminal(){return sessions.find(s=>s.pane_id===$("terminal-select").value);}
async function readTerminal(selected=selectedTerminal()){if(!selected)return;const result=await api("/api/control/terminal/read",{method:"POST",body:JSON.stringify({pane_id:selected.pane_id,expected_pid:selected.expected_pid})});if(selectedTerminal()?.pane_id!==selected.pane_id||selectedTerminal()?.expected_pid!==selected.expected_pid)return;$("terminal-output").textContent=result.text;$("terminal-output").scrollTop=$("terminal-output").scrollHeight;const agent=result.input_readiness?.binding?.agent_pid;displayedTerminal=typeof result.next_cursor==="string"&&result.next_cursor?{pane_id:selected.pane_id,expected_pid:selected.expected_pid,cursor:result.next_cursor,agent_pid:Number.isSafeInteger(agent)&&agent>0?agent:null}:null;updateTerminalInputControls();}
function displayedTerminalFor(selected=selectedTerminal()){
 return selected&&displayedTerminal?.pane_id===selected.pane_id&&displayedTerminal?.expected_pid===selected.expected_pid?displayedTerminal:null;
}
function updateTerminalInputControls(){
 const waiting=!!terminalIntent;
 $("terminal-send").disabled=waiting||terminalComposing;
 $("terminal-return").disabled=waiting||terminalComposing||!displayedTerminalFor();
 $("terminal-form").setAttribute("aria-busy",String(waiting));
}
function terminalDeliveryConfirmed(intent,delivery){
 if(delivery.state!=="completed")return false;
 const result=delivery.result;
 return result?.return_sent===true||(intent.kind==="text"&&result?.input_handed_to_transport===true&&result?.submitted===true&&result?.return_sent!==false);
}
function terminalDeliveryMessage(intent,delivery){
 const label=intent.kind==="key"?"Tastendruck":"Eingabe";
 if(delivery.ui_completion?.pending)return "Die Rückmeldung wird noch abgeglichen. Deine Eingabe bleibt erhalten.";
 if(delivery.state==="completed")return terminalDeliveryConfirmed(intent,delivery)?(intent.kind==="key"?"Return zugestellt.":"Eingabe an das Terminal übergeben.")+" Die Terminalausgabe zeigt das Ergebnis.":"Der Auftrag ist beendet, die Übergabe aber noch nicht bestätigt. Eingabe und Auftrag bleiben erhalten.";
 if(delivery.state==="unknown")return "Die Zustellung ist unklar. Eingabe und Auftrag bleiben erhalten. Bitte das Protokoll prüfen; nicht erneut senden.";
 if(["failed","rejected","blocked","cancelled"].includes(delivery.state)){
  const error=delivery.error?.message||delivery.error?.code;
  return label+" wurde nicht bestätigt"+(error?" ("+error+")":"")+". Deine Eingabe bleibt erhalten.";
 }
 return delivery.state==="created"?"Der Auftrag wartet unter Rechte auf deine Erlaubnis.":label+" wird zugestellt. Deine Eingabe bleibt bis zur Bestätigung erhalten.";
}
async function applyTerminalDelivery(intent,value){
 const delivery=value.task||value;
 if(terminalIntent!==intent)return;
 if(delivery.id!=="input-"+intent.actionId)throw Error("Die Rückmeldung konnte dem Eingabeauftrag nicht zugeordnet werden.");
 intent.delivery=delivery;
 const finished=["completed","failed","rejected","unknown","cancelled","blocked"].includes(delivery.state);
 if(!finished||delivery.ui_completion?.pending||delivery.state==="unknown"||(delivery.state==="completed"&&!terminalDeliveryConfirmed(intent,delivery))){notice(terminalDeliveryMessage(intent,delivery),!!delivery.ui_completion?.error||delivery.state==="unknown"||(delivery.state==="completed"&&!terminalDeliveryConfirmed(intent,delivery)));return;}
 intent.settling=true;
 const selected=selectedTerminal(),same=selected?.pane_id===intent.body.pane_id&&selected?.expected_pid===intent.body.expected_pid;
 let readError=null;
 if(same){try{await readTerminal(selected);}catch(e){displayedTerminal=null;readError=e;}}
 if(terminalIntent!==intent)return;
 if(terminalDeliveryConfirmed(intent,delivery)&&intent.kind==="text"&&same&&terminalDraftVersion===intent.draftVersion&&$("terminal-text").value===intent.draft){$("terminal-text").value="";terminalDraftVersion++;}
 terminalIntent=null;updateTerminalInputControls();
 notice(terminalDeliveryMessage(intent,delivery)+(readError?" Die Terminalausgabe konnte noch nicht aktualisiert werden.":""),delivery.state!=="completed"||!!readError);
}
async function pollTerminalInput(intent=terminalIntent){
 if(!intent||terminalIntent!==intent||intent.polling||intent.settling)return;
 intent.polling=true;
 try{await applyTerminalDelivery(intent,await api("/api/control/terminal/input/"+encodeURIComponent(intent.actionId),{cache:"no-store"}));}
 catch(e){if(terminalIntent===intent)notice("Der Zustellstatus ist noch unklar. Eingabe und Auftrag bleiben erhalten. "+e.message,true);}
 finally{intent.polling=false;}
}
function sendTerminalInput(kind){
 if(terminalIntent||terminalComposing||terminalComposeEnter)return;
 const selected=selectedTerminal();
 if(!selected){notice("Bitte zuerst eine Sitzung wählen.",true);return;}
 const draft=$("terminal-text").value;
 if(kind==="text"&&draft===""){notice("Text eingeben oder Return verwenden.",true);return;}
 const body={pane_id:selected.pane_id,expected_pid:selected.expected_pid,text:kind==="key"?"":draft,action_id:uuid()};
 if(kind==="key"){
  const observed=displayedTerminalFor(selected);
  if(!observed){notice("Bitte zuerst die aktuelle Terminalansicht prüfen.",true);return;}
  body.key="enter";body.expected_cursor=observed.cursor;
  if(observed.agent_pid!==null)body.expected_agent_pid=observed.agent_pid;
 }
 // Freeze the displayed view and identity at the physical intent, before the
 // shared action queue can run another refresh or selection change.
 const intent={kind,body:Object.freeze(body),actionId:body.action_id,draft,draftVersion:terminalDraftVersion,polling:false,settling:false};
 terminalIntent=intent;terminalLastIntent=intent;updateTerminalInputControls();notice("Eingabe wird zugestellt …");
 perform(async()=>{
  try{await applyTerminalDelivery(intent,await api("/api/control/terminal/input",{method:"POST",body:JSON.stringify(intent.body)}));}
  catch(e){if(terminalIntent===intent)notice("Die Zustellung ist noch unklar. Eingabe und Auftrag bleiben erhalten. "+e.message,true);}
  if(terminalIntent===intent)pollTerminalInput(intent);
 });
}
function bindTerminalInput(){
 const form=$("terminal-form");
 $("terminal-text").addEventListener("input",()=>{terminalDraftVersion++;});
 form.addEventListener("compositionstart",()=>{terminalComposing=true;updateTerminalInputControls();});
 form.addEventListener("compositionend",()=>{terminalComposing=false;updateTerminalInputControls();});
 form.addEventListener("keydown",event=>{
  if(event.key!=="Enter")return;
  if(event.isComposing||terminalComposing||event.keyCode===229){terminalComposeEnter=true;setTimeout(()=>{terminalComposeEnter=false;},0);return;}
  event.preventDefault();
  if(event.repeat||terminalIntent)return;
  sendTerminalInput(event.target===$("terminal-return")||(event.target===$("terminal-text")&&$("terminal-text").value==="")?"key":"text");
 });
 form.addEventListener("submit",event=>{event.preventDefault();sendTerminalInput("text");});
 $("terminal-return").addEventListener("click",()=>sendTerminalInput("key"));
 $("terminal-output").addEventListener("keydown",event=>{
  if(event.key!=="Enter")return;
  event.preventDefault();
  if(event.repeat||event.isComposing||event.keyCode===229||terminalComposing||terminalIntent)return;
  sendTerminalInput("key");
 });
 updateTerminalInputControls();
}
async function loadApprovals(){
  try{
    const data=await api("/api/tasks");
    $("approvals").replaceChildren();
    for(const task of data.tasks.filter(t=>t.state==="created")){
      const detail=await api("/api/tasks/"+encodeURIComponent(task.id));
      const item=node("div",undefined,"approval"),buffer=detail.task.input_buffer;
      const waiting=buffer?.state==="waiting";
      item.append(node("p",(names[task.principal]||task.principal)+" · "+task.operation+" · "+JSON.stringify(detail.task.args||{})));
      if(waiting)item.append(node("p","Im Puffer · noch nicht zugestellt · verfällt um "+new Date(buffer.expires*1000).toLocaleTimeString("de-DE")));
      for(const decision of ["approve","deny"]){
        const b=node("button",decision==="approve"?(waiting?"Jetzt senden":"Erlauben"):"Ablehnen");
        b.addEventListener("click",()=>perform(async()=>{
          await api("/api/tasks/"+encodeURIComponent(task.id)+"/"+decision,{method:"POST",body:JSON.stringify({request_hash:detail.request_hash})});
          await loadApprovals();await refresh(true);
        }));
        item.append(b);
      }
      $("approvals").append(item);
    }
  }catch(e){notice(e.message,true);}
}
function initFamilyLayout(){
 const workspace=$("family-workspace");if(!workspace)return;const key="kirabridge.family-layout.v1";let saved={};try{saved=JSON.parse(localStorage.getItem(key)||"{}");}catch(_){saved={};}
 const state={left:Math.min(220,Math.max(176,Number(saved.left)||208)),right:Math.min(370,Math.max(292,Number(saved.right)||320)),leftCollapsed:saved.leftCollapsed===true,rightCollapsed:typeof saved.rightCollapsed==="boolean"?saved.rightCollapsed:window.innerWidth<=1320};
 const persist=()=>{workspace.style.setProperty("--family-left",state.left+"px");workspace.style.setProperty("--family-right",state.right+"px");workspace.classList.toggle("left-collapsed",state.leftCollapsed);workspace.classList.toggle("right-collapsed",state.rightCollapsed);workspace.classList.toggle("right-user-expanded",!state.rightCollapsed);document.querySelectorAll("[data-panel-toggle]").forEach(button=>button.setAttribute("aria-expanded",String(button.dataset.panelToggle==="left"?!state.leftCollapsed:!state.rightCollapsed)));workspace.querySelectorAll("[data-resize]").forEach(handle=>handle.setAttribute("aria-valuenow",String(handle.dataset.resize==="left"?state.left:state.right)));try{localStorage.setItem(key,JSON.stringify(state));}catch(_){/* Layout preference is optional. */}};persist();
 document.querySelectorAll("[data-panel-toggle]").forEach(button=>button.addEventListener("click",()=>{if(button.dataset.panelToggle==="left")state.leftCollapsed=!state.leftCollapsed;else state.rightCollapsed=!state.rightCollapsed;persist();}));
 for(const handle of workspace.querySelectorAll("[data-resize]")){const side=handle.dataset.resize;const resize=x=>{const rect=workspace.getBoundingClientRect();if(side==="left")state.left=Math.max(176,Math.min(220,x-rect.left));else state.right=Math.max(292,Math.min(370,rect.right-x));persist();};handle.addEventListener("pointerdown",event=>{if((side==="left"&&state.leftCollapsed)||(side==="right"&&state.rightCollapsed))return;handle.setPointerCapture(event.pointerId);resize(event.clientX);});handle.addEventListener("pointermove",event=>{if(handle.hasPointerCapture(event.pointerId))resize(event.clientX);});handle.addEventListener("pointerup",event=>{if(handle.hasPointerCapture(event.pointerId))handle.releasePointerCapture(event.pointerId);});handle.addEventListener("keydown",event=>{if(!["ArrowLeft","ArrowRight"].includes(event.key))return;event.preventDefault();const delta=event.key==="ArrowRight"?8:-8;if(side==="left")state.left=Math.max(176,Math.min(220,state.left+delta));else state.right=Math.max(292,Math.min(370,state.right-delta));persist();});}
}
document.querySelectorAll("[data-view]").forEach(b=>b.addEventListener("click",()=>showView(b.dataset.view)));document.querySelectorAll("[data-go]").forEach(b=>b.addEventListener("click",()=>showView(b.dataset.go)));document.querySelectorAll('input[name="permission"]').forEach(n=>n.addEventListener("change",()=>{document.querySelectorAll('input[name="permission"]').forEach(r=>delete r.dataset.edited);n.dataset.edited="true";}));
$("reset-family-layout").addEventListener("click",()=>{try{localStorage.removeItem("kirabridge.family-layout.v1");}catch(_){/* Layout preference is optional. */}location.reload();});
$("permissions-save").addEventListener("click",()=>{const chosen=document.querySelector('input[name="permission"]:checked');perform(async()=>{if(!chosen)throw Error("Bitte eine der drei Stufen wählen.");notice("Rechte werden übernommen …");const result=await api("/api/control/permissions",{method:"POST",body:JSON.stringify({level:chosen.value})});document.querySelectorAll('input[name="permission"]').forEach(n=>delete n.dataset.edited);notice(result.label+" ist jetzt aktiv.");await refresh(true);});});$("refresh").addEventListener("click",()=>refresh(true));$("doctor-check").addEventListener("click",()=>perform(()=>doctor(false)));$("doctor-repair").addEventListener("click",()=>perform(()=>doctor(true)));$("protocol-open").addEventListener("click",()=>window.open("/protocol","kirabridge-protocol","width=1000,height=750,resizable=yes,scrollbars=yes"));$("terminal-refresh").addEventListener("click",()=>perform(async()=>{await loadTerminals();await pollTerminalInput();}));$("terminal-select").addEventListener("change",()=>{displayedTerminal=null;terminalDraftVersion++;updateTerminalInputControls();const selection=selectedTerminal();terminalSelected=Boolean(selection);if(!selection){$("terminal-output").textContent=terminalPlaceholderText();return;}perform(()=>readTerminal(selection));});for(const name of ["codex","grok"])$("terminal-new-"+name).addEventListener("click",()=>perform(async()=>{await act(name,"start");await loadTerminals();}));bindTerminalInput();initTheme();initFamilyLayout();$("agents-reload").addEventListener("click",()=>perform(()=>loadAgentCards(true)));loadAgentCards().catch(e=>notice(e.message,true));window.addEventListener("np-kirabridge-language",()=>{renderConnections();if(agentCatalog)loadAgentCards(false).catch(()=>{});});setInterval(()=>{if(!document.hidden){if(terminalIntent)pollTerminalInput();refresh();if(activeView==="permissions"&&!busy)loadApprovals();if(activeView==="terminals"&&!busy)readTerminal().catch(e=>notice(e.message,true));}},4000);refresh(true);

$("mobile-process").addEventListener("change",mobileControls);$("mobile-start").addEventListener("click",()=>{const service=$("mobile-process").value;perform(()=>act(service,"start"));});$("mobile-restart").addEventListener("click",()=>{const service=$("mobile-process").value;perform(()=>act(service,"restart"));});
