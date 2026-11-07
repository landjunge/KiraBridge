"use strict";
const $=id=>document.getElementById(id);
let statusData=null,connections=null,identity="chatgpt",sessions=[],activeView="overview",busy=false;
let displayedTerminal=null,terminalIntent=null,terminalLastIntent=null,terminalDraftVersion=0,terminalComposing=false,terminalComposeEnter=false;
let serviceFingerprint="";
const names={local:"Du",chatgpt:"Kira · ChatGPT",grok_app:"Grok · App",codex:"Codex",grok:"Grok · Terminal"};
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function notice(text,error=false){$("notice").textContent=text;$("notice").classList.toggle("error",error);}
async function api(path,options={}){let token;try{token=localStorage.getItem("kirabridge.session")||"";}catch(_){throw Error("Bitte KiraBridge über den lokalen Starter öffnen.");}const response=await fetch(path,{...options,headers:{"Authorization":"Bearer "+token,"Content-Type":"application/json",...(options.headers||{})}});const data=await response.json();if(!response.ok||data.error){const e=data.error;throw Error(typeof e==="object"?(e.message||e.code||"Die Ausführung ist fehlgeschlagen."):e==="unauthorized"?"Bitte KiraBridge über den Starter öffnen, um dich anzumelden.":e||"Verbindung fehlgeschlagen");}return data;}
function uuid(){return crypto.randomUUID().replaceAll("-","");}
function showView(name){activeView=name;document.querySelectorAll(".view").forEach(n=>n.hidden=n.id!==name);document.querySelectorAll("[data-view]").forEach(n=>n.setAttribute("aria-selected",String(n.dataset.view===name)));if(name==="terminals")loadTerminals();if(name==="doctor")perform(()=>doctor(false));if(name==="permissions")loadApprovals();}
async function act(service,action){notice((action==="restart"?"Neustart":"Start")+" wird angefordert …");const result=await api("/api/control/action",{method:"POST",body:JSON.stringify({service,action,action_id:uuid()})});if(result.error)throw Error(result.error.message);notice(result.message||"Aktion angefordert. Der tatsächliche Zustand wird geprüft.");await refresh(true);return result;}
function serviceCard(item){const card=node("article",undefined,"process-card "+item.state);card.dataset.service=item.id;card.append(node("div",item.name,"name"));const row=node("div",undefined,"row"),state=node("span",undefined,"process-state");state.append(node("span",undefined,"dot"),node("span",item.detail));const actions=node("div",undefined,"process-actions");for(const action of ["start","restart"]){const b=node("button",action==="start"?"Start":(item.restart_label||"Neustart"),action);b.type="button";b.disabled=action==="start"?item.active:!item.restart_available;b.title=b.disabled&&action==="restart"?"Eine vorhandene Sitzung wird nicht beendet.":item.name+": "+b.textContent;b.addEventListener("click",()=>perform(()=>act(item.id,action)));actions.append(b);}row.append(state,actions);card.append(row);return card;}
function mobileControls(){const item=statusData?.services.find(s=>s.id===$("mobile-process").value);$("mobile-start").disabled=!item||item.active;$("mobile-restart").disabled=!item||!item.restart_available;$("mobile-restart").textContent=item?.restart_label||"Neustart";}
function renderStatus(data){window.dispatchEvent(new CustomEvent("np-kirabridge-status",{detail:data}));statusData=data;const fingerprint=JSON.stringify(data.services);if(fingerprint!==serviceFingerprint){$("processes").replaceChildren(...data.services.map(serviceCard));serviceFingerprint=fingerprint;const previous=$("mobile-process").value;$("mobile-process").replaceChildren(...data.services.map(item=>{const option=node("option",item.name);option.value=item.id;return option;}));if(data.services.some(s=>s.id===previous))$("mobile-process").value=previous;}mobileControls();const live=!!data.bridge.dispatcher_active;$("bridge-indicator").className="bridge-indicator "+(live?"active":"inactive");$("bridge-indicator").replaceChildren(node("span",undefined,"dot"),node("span",live?(data.maintenance?"KiraBridge: Wartung":"KiraBridge läuft"):data.services.find(s=>s.id==="bridge")?.active?"KiraBridge: Antwort fehlt":"KiraBridge ist inaktiv"));$("observed-at").textContent="Geprüft um "+new Date(data.observed_at*1000).toLocaleTimeString("de-DE");$("footer-state").textContent=live?"Mit KiraBridge verbunden · "+new Date(data.observed_at*1000).toLocaleTimeString("de-DE"):"Die Steuerung bleibt erreichbar. KiraBridge über Start einschalten.";$("permission-summary").textContent=!data.settings_loaded?"Noch nicht aktiv geladen":data.permissions_consistent?(data.permission_details?.chatgpt?.label||data.permission_choices[data.level]):"Unterschiedliche Freigaben";$("permission-detail").textContent=!data.settings_loaded?"Geänderte Einstellungen sind noch nicht aktiv geladen. ":data.permissions_consistent?"Aktiv: "+data.permission_choices[data.level]+". Erteilte Zugriffsrechte bleiben erhalten.":"Die Zugänge haben unterschiedliche Freigaben. Eine Auswahl vereinheitlicht sie.";if(!document.querySelector('input[name="permission"]:focus')){const checked=document.querySelector('input[name="permission"][value="'+data.level+'"]');if(checked&&!document.querySelector('input[name="permission"][data-edited]'))checked.checked=true;}if(data.bridge.terminal_access){$("permission-detail").textContent+=" "+(data.bridge.terminal_access.policy_authorized?"Terminal-Erkennung, Lesen und Eingabe sind erlaubt. Erreichbarkeit unter Terminals prüfen.":"Terminalrechte sind nicht vollständig erteilt.");}renderPermissionExceptions(data);if(data.maintenance){$("footer-state").textContent="Aktivierung: "+data.maintenance.state+" · Neue Aufträge vorübergehend gesperrt. Bestehende Arbeit bleibt erhalten.";}$("peer-summary").textContent=data.peers_connected?"Nachrichtenwege bereit":"Doktor: Verbindungen reparieren";const pending=$("pending-summary");pending.replaceChildren();if(data.pending.length){const b=node("button",data.pending.length+" Auftrag/Aufträge warten auf deine Erlaubnis");b.addEventListener("click",()=>showView("permissions"));pending.append(b);}}
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
function renderConnections(){if(!connections)return;const kira=identity==="chatgpt";$("identity-title").textContent=kira?"Kira · ChatGPT":"Grok";$("provider-open").href=kira?connections.chatgpt_url:connections.grok_url;document.querySelectorAll("[data-identity]").forEach(n=>n.setAttribute("aria-pressed",String(n.dataset.identity===identity)));const grid=$("channel-grid");grid.replaceChildren();for(const device of ["browser","mobile"]){for(const mode of ["text","live","voice"]){const found=connections.checks.find(c=>c.principal===identity&&c.device===device&&c.mode===mode);const cell=node("div",undefined,"channel"+(found?" verified":""));cell.append(node("strong",(device==="browser"?"Browser":"Handy")+" · "+({text:"Text",live:"Live",voice:"Sprache"})[mode]),node("span",found?"Aufruf bestätigt":"Noch nicht geprüft"));grid.append(cell);}}const last=connections.checks[0];$("last-identity").textContent=last?"Letzter Aufruf: "+(names[last.principal]||last.principal):"Noch kein Modus bestätigt";const actions=$("connect-actions");actions.replaceChildren();if(!kira&&connections.grok.url){const button=node("button","Verbindungsadresse kopieren");button.addEventListener("click",()=>perform(async()=>{await navigator.clipboard.writeText(connections.grok.url);notice("Grok-Verbindungsadresse kopiert.");}));actions.append(button);}if(!kira){for(const pending of connections.grok.pending||[]){const line=node("div");line.append(node("span","Grok verbinden: "+pending.id.slice(-12).toUpperCase()+" "));const b=node("button","Verbinden");b.addEventListener("click",()=>perform(async()=>{await api("/api/control/consent/"+encodeURIComponent(pending.id),{method:"POST",body:JSON.stringify({allow:true})});notice("Grok-Verbindung freigegeben.");await refresh(true);}));line.append(b);actions.append(line);}}}
async function refresh(announce=false){if(busy&&!announce)return;try{const results=await Promise.all([api("/api/control/status"),api("/api/control/connections")]);renderStatus(results[0]);connections=results[1];renderConnections();if(announce)notice(results[0].bridge.dispatcher_active?"Zustände geprüft. KiraBridge antwortet.":"KiraBridge antwortet nicht. Start ist links direkt möglich.",!results[0].bridge.dispatcher_active);}catch(e){window.dispatchEvent(new Event("np-kirabridge-unreachable"));notice(e.message,true);$("bridge-indicator").className="bridge-indicator inactive";$("bridge-indicator").replaceChildren(node("span",undefined,"dot"),node("span","Zustand nicht erreichbar"));}}
let actionQueue=Promise.resolve();function perform(callback){const pending=actionQueue.then(async()=>{busy=true;try{await callback();}catch(e){notice(e.message,true);}finally{busy=false;}});actionQueue=pending.catch(()=>{});return pending;}
async function doctor(repair){notice(repair?"Der Doktor behebt erreichbare Probleme …":"Der Doktor prüft …");const result=await api("/api/control/doctor",repair?{method:"POST",body:"{}"}:{});$("doctor-checks").replaceChildren(...result.checks.map(c=>{const n=node("div",undefined,"doctor-check");n.append(node("span",c.ok?"✓":"!",c.ok?"ok":"problem"));const t=node("div");t.append(node("strong",c.name),node("p",c.message));n.append(t);return n;}));const missing=result.checks.filter(c=>!c.ok).length;$("doctor-summary").textContent=missing?missing+" Punkt(e) brauchen Aufmerksamkeit.":"Alle geprüften Punkte funktionieren.";const peers=result.checks.find(c=>c.name==="Agenten untereinander");if(peers)$("peer-summary").textContent=peers.message;notice(result.repaired.length?result.repaired.join(" · "):missing?"Prüfung abgeschlossen. Fehlende Punkte sind sichtbar.":"Prüfung abgeschlossen: Alles Geprüfte funktioniert.");if(repair)await refresh(true);}
async function loadTerminals(){displayedTerminal=null;updateTerminalInputControls();try{const result=await api("/api/control/terminals");sessions=result.sessions||[];const previous=$("terminal-select").value;$("terminal-select").replaceChildren(...sessions.map(s=>{const n=node("option",s.pane_id+" · "+(s.busy===true?"Programm läuft":s.busy===false?"Terminal wartet":"Prozess erkannt"));n.value=s.pane_id;return n;}));if(!sessions.length)$("terminal-select").append(node("option","Keine erreichbare Sitzung"));if(sessions.some(s=>s.pane_id===previous))$("terminal-select").value=previous;$("terminal-state").textContent=sessions.length+" erreichbare Sitzung(en). Bereitschaft wird bei der Übergabe geprüft.";if(sessions.length)await readTerminal();}catch(e){notice(e.message,true);}}
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
document.querySelectorAll("[data-view]").forEach(b=>b.addEventListener("click",()=>showView(b.dataset.view)));document.querySelectorAll("[data-go]").forEach(b=>b.addEventListener("click",()=>showView(b.dataset.go)));document.querySelectorAll("[data-identity]").forEach(b=>b.addEventListener("click",()=>{identity=b.dataset.identity;renderConnections();}));document.querySelectorAll('input[name="permission"]').forEach(n=>n.addEventListener("change",()=>{document.querySelectorAll('input[name="permission"]').forEach(r=>delete r.dataset.edited);n.dataset.edited="true";}));
$("permissions-save").addEventListener("click",()=>{const chosen=document.querySelector('input[name="permission"]:checked');perform(async()=>{if(!chosen)throw Error("Bitte eine der drei Stufen wählen.");notice("Rechte werden übernommen …");const result=await api("/api/control/permissions",{method:"POST",body:JSON.stringify({level:chosen.value})});document.querySelectorAll('input[name="permission"]').forEach(n=>delete n.dataset.edited);notice(result.label+" ist jetzt aktiv.");await refresh(true);});});$("refresh").addEventListener("click",()=>refresh(true));$("doctor-check").addEventListener("click",()=>perform(()=>doctor(false)));$("doctor-repair").addEventListener("click",()=>perform(()=>doctor(true)));$("protocol-open").addEventListener("click",()=>window.open("/protocol","kirabridge-protocol","width=1000,height=750,resizable=yes,scrollbars=yes"));$("terminal-refresh").addEventListener("click",()=>perform(async()=>{await loadTerminals();await pollTerminalInput();}));$("terminal-select").addEventListener("change",()=>{displayedTerminal=null;terminalDraftVersion++;updateTerminalInputControls();const selection=selectedTerminal();perform(()=>readTerminal(selection));});for(const name of ["codex","grok"])$("terminal-new-"+name).addEventListener("click",()=>perform(async()=>{await act(name,"start");await loadTerminals();}));bindTerminalInput();setInterval(()=>{if(!document.hidden){if(terminalIntent)pollTerminalInput();refresh();if(activeView==="permissions"&&!busy)loadApprovals();if(activeView==="terminals"&&!busy)readTerminal().catch(e=>notice(e.message,true));}},4000);refresh(true);

$("mobile-process").addEventListener("change",mobileControls);$("mobile-start").addEventListener("click",()=>{const service=$("mobile-process").value;perform(()=>act(service,"start"));});$("mobile-restart").addEventListener("click",()=>{const service=$("mobile-process").value;perform(()=>act(service,"restart"));});
