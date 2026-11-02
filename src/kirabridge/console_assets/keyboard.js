"use strict";
(() => {
 const root=$("keyboard"), storage="kirabridge.keyboard.intent", finalStates=new Set(["completed","failed","rejected","blocked","cancelled","unknown"]);
 const state={saved:null,dirty:false,version:0,apps:[],menu:null,intent:null,last:null,busy:false,polling:false,availability:null};
 const appKey=a=>a.pid+":"+a.started_at, app=()=>state.apps.find(a=>appKey(a)===$("keyboard-apps").value);
 const savedAction=()=>state.saved?.profile.actions?.[$("keyboard-actions").value];
 const bytes=s=>new TextEncoder().encode(s).length;
 const directErrors={
  keyboard_unsupported:"Das aktuelle Eingabefeld oder die gewünschte Eingabe wird nicht sicher unterstützt. Bitte ein normales Textfeld im Zielprogramm auswählen.",
  keyboard_application_missing:"Das Zielprogramm wurde nicht gefunden. Bitte das Programm öffnen und das Ziel neu auswählen.",
  keyboard_application_ambiguous:"Das Zielprogramm ist nicht eindeutig. Bitte die Programmliste neu prüfen und ein eindeutiges Ziel auswählen.",
  keyboard_application_catalog_incomplete:"Die Programmliste konnte nicht vollständig geprüft werden. Bitte die Programme neu prüfen.",
  keyboard_not_frontmost:"Das Zielprogramm ist noch nicht für die Eingabe bereit. Bitte das gewünschte Eingabefeld aktivieren und den Zustand neu prüfen.",
  keyboard_ui_permission_denied:"Die wirksame Tastaturfreigabe fehlt. Bitte die Freigabe unter Rechte prüfen.",
  permission_denied:"Die wirksame Tastaturfreigabe fehlt. Bitte die Freigabe unter Rechte prüfen.",
  capability_denied:"Die wirksame Tastaturfreigabe fehlt. Bitte die Freigabe unter Rechte prüfen.",
  macos_permission_denied:"Die macOS-Freigabe für die Tastatureingabe fehlt. Bitte die Bedienungshilfen und die wirksamen Rechte prüfen.",
  keyboard_target_changed:"Das Ziel oder sein Eingabefeld hat sich geändert. Bitte das gewünschte Ziel und Feld neu prüfen.",
  macos_target_changed:"Das Zielprogramm hat sich geändert. Bitte das gewünschte Ziel neu prüfen.",
  macos_element_changed:"Das Eingabefeld hat sich geändert. Bitte das gewünschte Feld neu prüfen.",
  keyboard_snapshot_invalid:"Das Eingabefeld konnte nicht sicher geprüft werden. Bitte das gewünschte Feld im Zielprogramm auswählen.",
  desktop_input_busy:"Die Tastatur ist durch einen anderen Auftrag belegt. Bitte warten, bis dieser beendet ist.",
  keyboard_input_partial_unknown:"Ein Teil der Eingabe wurde möglicherweise bereits gesendet. Der Auftrag bleibt erhalten; nur den Status prüfen und nicht erneut senden."
 };
 function directErrorMessage(task){const code=task.error?.code;if(code==="keyboard_input_partial_unknown")return directErrors[code];if(task.state==="unknown"||["keyboard_input_unknown","keyboard_text_unknown","desktop_input_unknown"].includes(code))return "Die Wirkung der Eingabe ist unklar. Der Auftrag bleibt erhalten; nur den Status prüfen und nicht erneut senden.";return directErrors[code]||"Die Eingabe konnte nicht bestätigt werden. Bitte den Status oder die Auftragsdetails prüfen.";}
 function report(error){notice(error.message||String(error),true);if(/capability|permission|forbidden|nicht erlaubt|Freigabe/i.test(error.message||""))showView("permissions");}
 function persist(intent){try{sessionStorage.setItem(storage,JSON.stringify(intent));}catch(_){throw Error("Die Auftragskennung kann nicht gesichert werden. Es wurde kein neuer Auftrag gesendet.");}}
 function controls(){
  const locked=state.busy||!!state.intent;
  root.querySelectorAll("button,select").forEach(b=>b.disabled=locked);
  $("keyboard-rights").disabled=false;$("keyboard-status").disabled=state.busy||state.polling||!state.intent?.task_id;
  const directAllowed=state.availability?.available===true;
  $("keyboard-direct-send").disabled=locked||!directAllowed;
  $("keyboard-direct-return").disabled=locked||!directAllowed;
  $("keyboard-load").disabled=locked||!$("keyboard-profiles").value;
  $("keyboard-save").disabled=locked||!state.dirty;$("keyboard-delete").disabled=locked||!state.saved||state.dirty;
  const unobserved=state.saved?Object.keys(state.saved.profile.app).filter(k=>["version","build","signing_team_id","language"].includes(k)&&state.saved.profile.app[k]!=null):[];
  $("keyboard-run").disabled=locked||state.dirty||!state.saved||!app()||!savedAction()||savedAction().provenance==="observed_menu"||unobserved.length>0;
  $("keyboard-preview").disabled=locked||!state.saved||!savedAction();$("keyboard-discover").disabled=locked||!app();
  $("keyboard-menu-next").disabled=locked||state.menu?.next_offset==null;
  $("keyboard-dirty").textContent=state.dirty?"Ungespeicherter Entwurf":"Unverändert";
  $("keyboard-binding").textContent=state.saved?"Gespeichert: "+state.saved.profile_id+" · "+state.saved.revision+(state.dirty?" · Entwurf wird nicht ausgeführt.":"")+(unobserved.length?" · Nativ nicht belegt: "+unobserved.join(", "):""):"Noch kein gespeichertes Profil geladen.";
 }
 function renderActions(){const select=$("keyboard-actions"),previous=select.value;select.replaceChildren(node("option","Aktion wählen"));select.firstChild.value="";for(const [name,action] of Object.entries(state.saved?.profile.actions||{})){const option=node("option",name+(action.provenance==="observed_menu"?" · unbestätigter Kandidat":""));option.value=name;select.append(option);}if(Object.hasOwn(state.saved?.profile.actions||{},previous))select.value=previous;}
 function acceptProfile(result,intent){
  state.saved={profile_id:result.profile_id,revision:result.revision,profile:result.profile};
  if(intent.editor_version===state.version){$("keyboard-editor").value=JSON.stringify(result.profile,null,2);state.dirty=false;}
  renderActions();
 }
 function resultView(result,intent){
  if(intent.operation==="keyboard.profiles.list"){
   const select=$("keyboard-profiles"),previous=select.value;select.replaceChildren(node("option","Profil wählen"));select.firstChild.value="";
   for(const item of result.profiles||[]){const option=node("option",item.profile_id+" · "+item.app.bundle_id);option.value=item.profile_id;select.append(option);}select.value=previous;
  }else if(intent.operation==="apps.list"){
   const previous=$("keyboard-apps").value;state.apps=(result.applications||[]).filter(a=>Number.isInteger(a.pid)&&Number.isFinite(a.started_at));
   const select=$("keyboard-apps");select.replaceChildren(node("option","Programm wählen"));select.firstChild.value="";
   for(const item of state.apps){const option=node("option",(item.name||item.bundle_id||"Programm")+" · PID "+item.pid);option.value=appKey(item);select.append(option);}select.value=previous;
   const direct=$("keyboard-direct-app"),selected=direct.value;direct.replaceChildren(node("option","Beim Senden aktives Programm"));direct.firstChild.value="";
   for(const item of state.apps){if(!item.bundle_id&&!item.name)continue;const option=node("option",item.name||item.bundle_id);option.value=appKey(item);direct.append(option);}
   if(selected&&![...direct.options].some(o=>o.value===selected)){const unavailable=node("option","Gewähltes Programm nicht mehr verfügbar · bitte neu wählen");unavailable.value=selected;unavailable.disabled=true;direct.append(unavailable);$("keyboard-target-status").textContent="Das gewählte Programm ist nicht mehr verfügbar. Bitte ausdrücklich ein neues Ziel wählen; es wird nicht an das aktive Programm umgeleitet.";}
   direct.value=selected;
  }else if(["keyboard.profiles.get","keyboard.profiles.put"].includes(intent.operation)&&result.profile&&result.revision){acceptProfile(result,intent);
  }else if(intent.operation==="keyboard.profiles.delete"){state.saved=null;renderActions();state.dirty=!!$("keyboard-editor").value;
  }else if(intent.operation==="keyboard.profiles.resolve"){$("keyboard-preview-result").textContent="Caller-Vorschau, kein nativer Ausführungsbeleg:\n"+JSON.stringify(result,null,2);
  }else if(intent.operation==="keyboard.shortcuts.discover"){
   state.menu={pid:intent.pid,expected_started_at:intent.expected_started_at,revision:result.revision,next_offset:result.next_offset};
   $("keyboard-menu-next").hidden=result.next_offset==null;
   $("keyboard-coverage").textContent="AX-Menübeobachtung: "+result.coverage+" · "+(result.cached?"gespeicherte Seite":"frischer Snapshot")+" · "+(result.reasons||[]).join(", ")+". Nicht alle App-Shortcuts; Belegungen unbestätigt.";
   $("keyboard-menu").textContent=JSON.stringify(result.entries||[],null,2);
  }
 }
 function taskView(reply,intent){
  if(reply.request_id&&reply.request_id!==intent.id)throw Error("Auftragskennung stimmt nicht. Nicht erneut senden.");
  const task=reply.task||reply;if(!task.id||!task.state)throw Error("Auftragsbeleg fehlt. Nicht erneut senden.");
  intent.task_id||=task.id;intent.last_task_id=task.id;intent.state=task.state;
  if(typeof reply.ui_primary==="boolean")intent.primary=reply.ui_primary;
  if(typeof task.ui_primary==="boolean")intent.primary=task.ui_primary;
  state.last=intent;persist(intent);
  $("keyboard-task").textContent="Anfrage "+intent.id+" · Auftrag "+task.id+" · "+task.state+(task.ui_stage?" · "+task.ui_stage:"");
  let actionConfirmed=intent.operation!=="run_profile";
  if(task.state==="completed"){
   if(intent.operation==="run_profile"){
    const r=task.result||{},b=r.profile_binding;
    actionConfirmed=task.ui_workflow_status==="primary"&&intent.primary===true&&task.id===intent.task_id&&r.profile_binding_verified===true&&r.post_calls_returned===2&&b?.id===intent.binding.id&&b.revision===intent.binding.revision&&b.action===intent.binding.action;
    if(actionConfirmed)notice("Profilbindung und native Post-Aufrufe bestätigt. Die Programmaktion ist damit nicht bestätigt.");
    else notice("Nur eine Vorstufe ist beendet. Die Profilaktion ist nicht bestätigt; es wird nichts erneut gesendet.",true);
   }else if(intent.operation==="keyboard.input"){
    const r=task.result||{};
    actionConfirmed=task.ui_primary===true&&task.id===intent.task_id&&r.requested_count===intent.repeat&&r.completed_count===intent.repeat&&r.input_attempted===true&&r.automatic_retry===false;
    if(actionConfirmed){
     const label=r.application?.name||"Zielprogramm";
     const proof=r.app_processing_confirmed===true?"Die Änderung im Eingabefeld wurde bestätigt.":r.field_change_observed===true?"Eine Änderung des Feldes wurde beobachtet; die Programmaktion ist nicht bestätigt.":"Die Übergabe wurde bestätigt; die Wirkung im Programm ist nicht bestätigt.";
     $("keyboard-direct-result").textContent=label+": "+r.completed_count+" von "+r.requested_count+" Eingaben übergeben. "+proof;
     notice($("keyboard-direct-result").textContent);
    }else{$("keyboard-direct-result").textContent="Die Eingabe ist nicht vollständig bestätigt. Nur den Status prüfen; nicht erneut senden.";notice($("keyboard-direct-result").textContent,true);}
   }else{resultView(task.result||{},intent);notice("Auftrag abgeschlossen.");}
  }else if(finalStates.has(task.state)){const direct=intent.operation==="keyboard.input",message=direct?directErrorMessage(task):task.state==="unknown"?"Ausgang ungewiss. Auftrag bleibt erhalten; nicht erneut senden.":task.error?.message||task.error?.code||"Auftrag nicht bestätigt: "+task.state;if(direct){$("keyboard-direct-result").textContent=message;if(/^[a-z][a-z0-9_]{0,79}$/.test(task.error?.code||""))$("keyboard-task").textContent+=" · "+task.error.code;}report(Error(message));}
  else notice("Auftrag offen. Eine nötige Freigabe findest du unter Rechte.");
  const guarded=["run_profile","keyboard.input"].includes(intent.operation);
  const safeEnd=finalStates.has(task.state)&&task.state!=="unknown"&&(!guarded||task.ui_workflow_status==="halted"||(task.ui_workflow_status==="primary"&&(task.state!=="completed"||actionConfirmed)));
  if(finalStates.has(task.state)&&!safeEnd){intent.state="unknown";$("keyboard-task").textContent+=" · Ausgang nicht bestätigt; nur Status prüfen.";}
  if(safeEnd){intent.terminal=true;persist(intent);state.intent=null;}else persist(intent);
  controls();return finalStates.has(task.state);
 }
 async function poll(intent,automatic=false){
  if(state.polling||state.intent!==intent||!intent.task_id)return;state.polling=true;controls();
  try{const done=taskView(await api("/api/control/keyboard/task/"+encodeURIComponent(intent.task_id)),intent);if(!done&&automatic&&++intent.polls<40)setTimeout(()=>poll(intent,true),750);}
  catch(error){if(intent.operation==="keyboard.input"){const message="Der Auftragsstatus konnte nicht geprüft werden. Der Auftrag bleibt erhalten; bitte nur den Status erneut prüfen und die Eingabe nicht erneut senden.";$("keyboard-direct-result").textContent=message;notice(message,true);}else report(error);}finally{state.polling=false;controls();}
 }
 async function request(operation,args){
  if(state.busy||state.intent)return;
  const intent={id:crypto.randomUUID(),operation,editor_version:state.version,polls:0,pid:args.pid,expected_started_at:args.expected_started_at};
  if(operation==="keyboard.input"){intent.repeat=args.repeat;$("keyboard-direct-result").textContent="Das Ziel und sein Eingabefeld werden geprüft. Der Auftrag wird einmalig gesendet …";}
  intent.task_id="ui-keyboard-"+intent.id.replaceAll("-","")+"-main";
  if(operation==="run_profile")intent.binding={id:args.profile_id,revision:args.expected_revision,action:args.action};
  persist(intent);state.intent=intent;state.last=intent;state.busy=true;controls();
  $("keyboard-task").textContent="Anfrage "+intent.id+" wird einmalig gesendet …";
  try{const done=taskView(await api("/api/control/keyboard/request",{method:"POST",body:JSON.stringify({id:intent.id,operation,args})}),intent);if(!done)setTimeout(()=>poll(intent,true),750);}
  catch(error){intent.state="unknown";persist(intent);if(operation==="keyboard.input"){$("keyboard-direct-result").textContent="Rückmeldung ungewiss. Nur den Status prüfen; nicht erneut senden.";notice($("keyboard-direct-result").textContent,true);}else report(error);$("keyboard-task").textContent="Anfrage "+intent.id+" · Rückmeldung ungewiss. Nicht erneut senden. "+(intent.task_id?"Status nur lesend prüfen.":"Auftragskennung im Protokoll prüfen.");}
  finally{state.busy=false;controls();}
 }
 function draft(){const text=$("keyboard-editor").value;if(bytes(text)>24576)throw Error("Der JSON-Entwurf überschreitet 24 KiB.");const doc=JSON.parse(text);if(!doc||Array.isArray(doc)||!doc.id||!doc.app||!doc.actions)throw Error("Profil benötigt id, app und actions.");return doc;}
 function changed(){state.dirty=true;state.version++;controls();}
 function discard(){return !state.dirty||confirm("Ungespeicherten Entwurf verwerfen?");}
 function bind(id,action){$(id).addEventListener("click",()=>{try{Promise.resolve(action()).catch(report);}catch(error){report(error);}});}
 function directFields(){const mode=$("keyboard-direct-mode").value;$("keyboard-text-controls").hidden=mode!=="text";$("keyboard-key-controls").hidden=mode==="text";$("keyboard-modifier-controls").hidden=mode!=="chord";$("keyboard-character-label").hidden=$("keyboard-direct-key").value!=="character";}
 async function availability(){
  const previous=state.availability;
  try{const result=await api("/api/control/keyboard/availability");state.availability=result;
   $("keyboard-availability").textContent=result.available?("ChatGPT: direkte Tastaturbefehle verfügbar"+(result.approval_required?" nach Freigabe":"")+" · "+(result.version||"KiraBridge")+" · "+result.operation_count+" Befehle. "+(previous&&previous.revision!==result.revision?"Der Katalog wurde aktualisiert. ":"Katalog frisch geprüft. ")+"macOS-Rechte und das Eingabefeld werden beim Senden geprüft."):result.registered?"ChatGPT fehlt die wirksame Tastaturfreigabe. Unter Rechte prüfen und nach einer bewussten Änderung erneut prüfen.":"Der laufende Katalog bietet die direkte Eingabe noch nicht an. Der bisherige Profil-Editor bleibt unter Erweitert verfügbar.";
  }catch(error){state.availability=null;$("keyboard-availability").textContent="Die Verfügbarkeit konnte nicht geprüft werden. Es wurde keine Eingabe gesendet.";report(error);}finally{controls();}
 }
 function directArgs(returnOnly=false){
  const repeat=Number($("keyboard-direct-repeat").value);if(!Number.isInteger(repeat)||repeat<1||repeat>20)throw Error("Bitte eine ganze Anzahl von 1 bis 20 wählen.");
  const args={repeat},selected=state.apps.find(a=>appKey(a)===$("keyboard-direct-app").value);
  if($("keyboard-direct-app").value&&!selected)throw Error("Bitte Programme neu prüfen und das Ziel erneut wählen.");
  if(selected)args.app=selected.bundle_id||selected.name;
  const mode=returnOnly?"key":$("keyboard-direct-mode").value;
  if(mode==="text"){const text=$("keyboard-direct-text").value;if(!text)throw Error("Bitte Text eingeben.");args.text=text;args.submit=$("keyboard-direct-submit").checked;}
  else{const key=returnOnly?"enter":$("keyboard-direct-key").value;if(key==="character"){const character=$("keyboard-direct-character").value;if([...character].length!==1)throw Error("Bitte genau einen Buchstaben oder ein Zeichen eingeben.");args.key={character};}else args.key={named:key};
   if(mode==="chord"){args.modifiers=[...$("keyboard-modifier-controls").querySelectorAll("input:checked")].map(i=>i.value);if(!args.modifiers.length)throw Error("Bitte mindestens eine zusätzliche Taste wählen.");}}
  return args;
 }
 $("keyboard-direct-form").addEventListener("submit",event=>{event.preventDefault();try{request("keyboard.input",directArgs()).catch(report);}catch(error){report(error);}});
 $("keyboard-direct-mode").addEventListener("change",directFields);$("keyboard-direct-key").addEventListener("change",directFields);
 $("keyboard-direct-app").addEventListener("change",()=>{$("keyboard-target-status").textContent=$("keyboard-direct-app").selectedOptions[0].textContent+". Das Eingabefeld wird unmittelbar vor dem Senden geprüft.";});
 bind("keyboard-direct-return",()=>request("keyboard.input",directArgs(true)));
 bind("keyboard-direct-refresh",async()=>{await availability();if(!state.intent)await request("apps.list",{limit:250});});
 document.querySelector('[data-view="keyboard"]').addEventListener("click",()=>{availability();});
 $("keyboard-form").addEventListener("submit",event=>event.preventDefault());
 $("keyboard-editor").addEventListener("input",changed);
 $("keyboard-profiles").addEventListener("change",controls);$("keyboard-actions").addEventListener("change",controls);
 $("keyboard-apps").addEventListener("change",()=>{state.menu=null;$("keyboard-menu").textContent="";$("keyboard-menu-next").hidden=true;$("keyboard-coverage").textContent="Für dieses Programm noch keine Menübeobachtung.";const selected=app();$("keyboard-context").value=JSON.stringify(selected?{bundle_id:selected.bundle_id}:{},null,2);controls();});
 bind("keyboard-refresh",async()=>{await request("keyboard.profiles.list",{});if(!state.intent)await request("apps.list",{limit:250});});
 bind("keyboard-load",()=>{if(discard())return request("keyboard.profiles.get",{profile_id:$("keyboard-profiles").value});});
 bind("keyboard-new",()=>{if(!discard())return;state.saved=null;$("keyboard-editor").value=JSON.stringify({schema:"kirabridge.keyboard-profile.v1",id:"my_profile",app:{bundle_id:app()?.bundle_id||"com.example.App"},actions:{move_left:{key:{named:"left"},modifiers:[],provenance:"user"}}},null,2);renderActions();changed();});
 bind("keyboard-save",()=>{const doc=draft();return request("keyboard.profiles.put",{profile:doc,expected_revision:state.saved?.profile_id===doc.id?state.saved.revision:null});});
 bind("keyboard-delete",()=>{if(state.saved&&!state.dirty&&confirm("Gespeichertes Profil "+state.saved.profile_id+" in genau dieser Revision löschen?"))return request("keyboard.profiles.delete",{profile_id:state.saved.profile_id,expected_revision:state.saved.revision});});
 bind("keyboard-preview",()=>request("keyboard.profiles.resolve",{profile_id:state.saved.profile_id,expected_revision:state.saved.revision,action:$("keyboard-actions").value,context:JSON.parse($("keyboard-context").value)}));
 bind("keyboard-run",()=>{const selected=app();return request("run_profile",{pid:selected.pid,expected_started_at:selected.started_at,profile_id:state.saved.profile_id,expected_revision:state.saved.revision,action:$("keyboard-actions").value});});
 bind("keyboard-discover",()=>{const selected=app();return request("keyboard.shortcuts.discover",{pid:selected.pid,expected_started_at:selected.started_at,limit:100});});
 bind("keyboard-menu-next",()=>request("keyboard.shortcuts.discover",{pid:state.menu.pid,expected_started_at:state.menu.expected_started_at,limit:100,offset:state.menu.next_offset,expected_revision:state.menu.revision}));
 bind("keyboard-status",()=>{if(state.intent){state.intent.polls=0;return poll(state.intent,true);}});
 try{const last=JSON.parse(sessionStorage.getItem(storage)||"null");if(last&&typeof last.id==="string"&&typeof last.operation==="string"){state.last=last;if(!last.terminal)state.intent=last;$("keyboard-task").textContent="Vorherige Anfrage "+last.id+(last.task_id?" · Auftrag "+last.task_id:"")+" · "+(last.state||"Rückmeldung offen")+". Nur Status prüfen, nicht erneut senden.";}}catch(_){notice("Vorherige Auftragskennung konnte nicht gelesen werden.",true);}
 directFields();controls();
})();
