"use strict";
(() => {
 const root=$("keyboard"), storage="kirabridge.keyboard.intent", finalStates=new Set(["completed","failed","rejected","blocked","cancelled","unknown"]);
 const state={saved:null,dirty:false,version:0,apps:[],appsLoaded:false,menu:null,intent:null,last:null,busy:false,polling:false,composing:false};
 const appKey=a=>a.pid+":"+a.started_at, app=()=>state.apps.find(a=>appKey(a)===$("keyboard-apps").value);
 const savedAction=()=>state.saved?.profile.actions?.[$("keyboard-actions").value];
 const bytes=s=>new TextEncoder().encode(s).length;
 function report(error){notice(error.message||String(error),true);if(/capability|permission|forbidden|nicht erlaubt|Freigabe/i.test(error.message||""))showView("permissions");}
 function persist(intent){try{sessionStorage.setItem(storage,JSON.stringify(intent));}catch(_){throw Error("Die Auftragskennung kann nicht gesichert werden. Es wurde kein neuer Auftrag gesendet.");}}
 function controls(){
  const locked=state.busy||!!state.intent;
  root.querySelectorAll("button,select").forEach(b=>b.disabled=locked);
  $("keyboard-direct-form").querySelectorAll("input,textarea").forEach(input=>input.disabled=locked);
  const textMode=$("keyboard-kind").value==="text",validKey=$("keyboard-key").value!=="character"||Array.from($("keyboard-character").value).length===1;
  $("keyboard-send").disabled=locked||!app()||state.composing||(textMode?!$("keyboard-text").value:!validKey);
  $("keyboard-destination").textContent=app()?"Ziel: "+(app().name||app().bundle_id||"Programm"):"Wähle ein Zielprogramm.";
  $("keyboard-direct-form").setAttribute("aria-busy",String(locked));
  $("keyboard-rights").disabled=false;$("keyboard-status").disabled=state.busy||state.polling||!state.intent?.task_id;
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
   const previous=$("keyboard-apps").value;state.apps=(result.applications||[]).filter(a=>Number.isInteger(a.pid)&&Number.isFinite(a.started_at)&&a.user_application!==false);
   const select=$("keyboard-apps");select.replaceChildren(node("option","Programm wählen"));select.firstChild.value="";
   for(const item of state.apps){const label=item.name||item.bundle_id||"Programm",ambiguous=state.apps.some(other=>other!==item&&(other.name||other.bundle_id||"Programm")===label),option=node("option",label+(ambiguous?(item.bundle_id?" · "+item.bundle_id:"")+" · PID "+item.pid:""));option.value=appKey(item);select.append(option);}select.value=state.apps.some(a=>appKey(a)===previous)?previous:"";
   state.appsLoaded=true;$("keyboard-app-help").textContent=state.apps.length+" laufende Programme erkannt."+(result.truncated?" Die Liste ist begrenzt.":"")+" Das gewählte Programm wird vor dem Senden aktiviert.";
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
  let actionConfirmed=!["run_profile","keyboard.control"].includes(intent.operation);
  if(task.state==="completed"){
   if(intent.operation==="run_profile"){
    const r=task.result||{},b=r.profile_binding;
    actionConfirmed=task.ui_workflow_status==="primary"&&intent.primary===true&&task.id===intent.task_id&&r.profile_binding_verified===true&&r.post_calls_returned===2&&b?.id===intent.binding.id&&b.revision===intent.binding.revision&&b.action===intent.binding.action;
    if(actionConfirmed)notice("Profilbindung und native Post-Aufrufe bestätigt. Die Programmaktion ist damit nicht bestätigt.");
    else notice("Nur eine Vorstufe ist beendet. Die Profilaktion ist nicht bestätigt; es wird nichts erneut gesendet.",true);
   }else if(intent.operation==="keyboard.control"){
    const r=task.result||{},resolved=r.resolved_application;
    actionConfirmed=task.ui_workflow_status==="primary"&&intent.primary===true&&task.id===intent.task_id&&r.automatic_target===true&&resolved?.pid===intent.pid&&resolved.started_at===intent.expected_started_at&&(intent.kind==="text"?r.text_verified===true&&r.selection_verified===true&&r.return_posted===intent.submit:r.post_calls_returned===2);
    notice(actionConfirmed?(intent.kind==="text"?"Text im Zielprogramm bestätigt."+(intent.submit?" Return wurde gesendet; die Verarbeitung im Programm ist nicht bestätigt.":""):"Native Tastendruck-Aufrufe bestätigt. Die Verarbeitung im Programm ist nicht bestätigt."):"Die Eingabe ist nicht vollständig bestätigt. Auftrag bleibt erhalten; nicht erneut senden.",!actionConfirmed);
   }else{resultView(task.result||{},intent);notice("Auftrag abgeschlossen.");}
  }else if(finalStates.has(task.state)){report(Error(task.state==="unknown"?"Ausgang ungewiss. Auftrag bleibt erhalten; nicht erneut senden.":task.error?.message||task.error?.code||"Auftrag nicht bestätigt: "+task.state));}
  else notice("Auftrag offen. Eine nötige Freigabe findest du unter Rechte.");
  const safeEnd=finalStates.has(task.state)&&task.state!=="unknown"&&(!["run_profile","keyboard.control"].includes(intent.operation)||task.ui_workflow_status==="halted"||(task.ui_workflow_status==="primary"&&(task.state!=="completed"||actionConfirmed)));
  if(finalStates.has(task.state)&&!safeEnd){intent.state="unknown";$("keyboard-task").textContent+=" · Ausgang nicht bestätigt; nur Status prüfen.";}
  if(safeEnd){intent.terminal=true;persist(intent);state.intent=null;}else persist(intent);
  controls();return finalStates.has(task.state);
 }
 async function poll(intent,automatic=false){
  if(state.polling||state.intent!==intent||!intent.task_id)return;state.polling=true;controls();
  try{const done=taskView(await api("/api/control/keyboard/task/"+encodeURIComponent(intent.task_id)),intent);if(!done&&automatic&&++intent.polls<40)setTimeout(()=>poll(intent,true),750);}
  catch(error){report(error);}finally{state.polling=false;controls();}
 }
 async function request(operation,args){
  if(state.busy||state.intent)return;
  const intent={id:crypto.randomUUID(),operation,editor_version:state.version,polls:0,pid:args.pid,expected_started_at:args.expected_started_at};
  intent.task_id="ui-keyboard-"+intent.id.replaceAll("-","")+"-main";
  if(operation==="run_profile")intent.binding={id:args.profile_id,revision:args.expected_revision,action:args.action};
  if(operation==="keyboard.control"){intent.kind=args.text!==undefined?"text":"key";intent.submit=args.submit===true;}
  const body=JSON.stringify({id:intent.id,operation,args});
  if(bytes(body)>32768)throw Error("Dieser Auftrag überschreitet 32 KiB. Bitte den Text oder das Profil kürzen. Es wurde nichts gesendet.");
  persist(intent);state.intent=intent;state.last=intent;state.busy=true;controls();
  $("keyboard-task").textContent="Anfrage "+intent.id+" wird einmalig gesendet …";
  try{const done=taskView(await api("/api/control/keyboard/request",{method:"POST",body}),intent);if(!done)setTimeout(()=>poll(intent,true),750);}
  catch(error){intent.state="unknown";persist(intent);report(error);$("keyboard-task").textContent="Anfrage "+intent.id+" · Rückmeldung ungewiss. Nicht erneut senden. "+(intent.task_id?"Status nur lesend prüfen.":"Auftragskennung im Protokoll prüfen.");}
  finally{state.busy=false;controls();}
 }
 function draft(){const text=$("keyboard-editor").value;if(bytes(text)>24576)throw Error("Der JSON-Entwurf überschreitet 24 KiB.");const doc=JSON.parse(text);if(!doc||Array.isArray(doc)||!doc.id||!doc.app||!doc.actions)throw Error("Profil benötigt id, app und actions.");return doc;}
 function changed(){state.dirty=true;state.version++;controls();}
 function discard(){return !state.dirty||confirm("Ungespeicherten Entwurf verwerfen?");}
 function bind(id,action){$(id).addEventListener("click",()=>{try{Promise.resolve(action()).catch(report);}catch(error){report(error);}});}
 function directView(){const text=$("keyboard-kind").value==="text",character=$("keyboard-key").value==="character";$("keyboard-text-fields").hidden=!text;$("keyboard-key-fields").hidden=text;$("keyboard-character").hidden=!character;$("keyboard-character-label").hidden=!character;controls();}
 function sendDirect(){
  const selected=app();if(!selected||state.composing)return;
  const args={pid:selected.pid,expected_started_at:selected.started_at};
  if($("keyboard-kind").value==="text"){
   const text=$("keyboard-text").value;if(!text)throw Error("Bitte Text eingeben.");
   if(/[\ud800-\udfff]/u.test(text))throw Error("Der Text enthält ein ungültiges Unicode-Zeichen.");
   if(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/u.test(text))throw Error("Der Text enthält nicht unterstützte Steuerzeichen.");
   args.text=text;args.submit=$("keyboard-submit").checked;
  }else{
   const key=$("keyboard-key").value,character=$("keyboard-character").value;
   if(key==="character"&&(Array.from(character).length!==1||(character!==" "&&/[\p{C}\p{Z}]/u.test(character))))throw Error("Bitte genau ein sichtbares Zeichen eingeben.");
   args.key=key==="character"?{character}:{named:key};args.modifiers=Array.from(root.querySelectorAll(".keyboard-modifiers input:checked"),input=>input.value);
  }
  return request("keyboard.control",args);
 }
 $("keyboard-form").addEventListener("submit",event=>event.preventDefault());
 $("keyboard-direct-form").addEventListener("submit",event=>event.preventDefault());
 $("keyboard-kind").addEventListener("change",directView);$("keyboard-key").addEventListener("change",directView);
 for(const id of ["keyboard-text","keyboard-character"]){$(id).addEventListener("input",controls);$(id).addEventListener("compositionstart",()=>{state.composing=true;controls();});$(id).addEventListener("compositionend",()=>{state.composing=false;controls();});}
 $("keyboard-editor").addEventListener("input",changed);
 $("keyboard-profiles").addEventListener("change",controls);$("keyboard-actions").addEventListener("change",controls);
 $("keyboard-apps").addEventListener("change",()=>{state.menu=null;$("keyboard-menu").textContent="";$("keyboard-menu-next").hidden=true;$("keyboard-coverage").textContent="Für dieses Programm noch keine Menübeobachtung.";const selected=app();$("keyboard-context").value=JSON.stringify(selected?{bundle_id:selected.bundle_id}:{},null,2);controls();});
 bind("keyboard-refresh",async()=>{await request("keyboard.profiles.list",{});if(!state.intent)await request("apps.list",{limit:250});});
 bind("keyboard-apps-refresh",()=>request("apps.list",{limit:1000}));
 bind("keyboard-send",sendDirect);
 document.querySelector('[data-view="keyboard"]').addEventListener("click",()=>{if(!state.appsLoaded&&!state.intent&&!state.busy)request("apps.list",{limit:1000}).catch(report);});
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
 controls();
})();
