"use strict";
(() => {
 const root=$("keyboard"), storage="kirabridge.keyboard.intent", finalStates=new Set(["completed","failed","rejected","blocked","cancelled","unknown"]);
 const state={saved:null,dirty:false,version:0,apps:[],appsLoaded:false,systemActions:[],inventoryLoaded:false,permissionReady:null,readQueue:[],checking:false,menu:null,intent:null,last:null,busy:false,polling:false,composing:false};
 const appKey=a=>a.pid+":"+a.started_at, app=()=>state.apps.find(a=>appKey(a)===$("keyboard-apps").value);
 const systemMode=()=>$("keyboard-kind").value==="system"||($("keyboard-kind").value==="key"&&$("keyboard-scope").value==="system");
 const repeatCount=()=>Number($("keyboard-repeat").value),validRepeat=()=>$("keyboard-repeat").value.trim()!==""&&Number.isInteger(repeatCount())&&repeatCount()>=1&&repeatCount()<=20;
 const systemAction=()=>state.systemActions.find(a=>a.action===$("keyboard-system-action").value&&a.available===true);
 const hardwareModifierActions=new Set(["volume_up","volume_down","mute","brightness_up","brightness_down","keyboard_brightness_up","keyboard_brightness_down","keyboard_brightness_toggle","play_pause","next_track","previous_track","fast_forward","rewind","eject","display_mirror","contrast_up","contrast_down","launch_panel","menu"]);
 const systemModifiersAllowed=action=>action?.accepts_modifiers===true&&hardwareModifierActions.has(action.action);
 const systemLabels={volume_up:"Lauter",volume_down:"Leiser",mute:"Ton stummschalten",brightness_up:"Bildschirm heller",brightness_down:"Bildschirm dunkler",keyboard_brightness_up:"Tastaturbeleuchtung heller",keyboard_brightness_down:"Tastaturbeleuchtung dunkler",keyboard_brightness_toggle:"Tastaturbeleuchtung umschalten",play_pause:"Wiedergabe / Pause",next_track:"Nächster Titel",previous_track:"Vorheriger Titel",fast_forward:"Vorspulen",rewind:"Zurückspulen",eject:"Medium auswerfen",display_mirror:"Bildschirmsynchronisierung umschalten",contrast_up:"Kontrast erhöhen",contrast_down:"Kontrast verringern",launch_panel:"Launchpad öffnen",menu:"Medienmenü",mission_control:"Mission Control",application_windows:"Fenster des aktuellen Programms",show_desktop:"Schreibtisch anzeigen",space_left:"Zum linken Schreibtisch wechseln",space_right:"Zum rechten Schreibtisch wechseln",spotlight:"Spotlight öffnen",spotlight_finder:"Im Finder suchen",window_next:"Nächstes Fenster",app_next:"Zum nächsten Programm wechseln",app_previous:"Zum vorherigen Programm wechseln"};
 systemLabels.caps_lock="Feststelltaste umschalten";
 const actionLabel=action=>Object.hasOwn(systemLabels,action.action)?systemLabels[action.action]:typeof action.label==="string"&&action.label.length<=240?action.label:null;
 const savedAction=()=>state.saved?.profile.actions?.[$("keyboard-actions").value];
 const bytes=s=>new TextEncoder().encode(s).length;
 function report(error){notice(error.message||String(error),true);if(/capability|permission|forbidden|nicht erlaubt|Freigabe/i.test(error.message||""))showView("permissions");}
 function persist(intent){try{sessionStorage.setItem(storage,JSON.stringify(intent));}catch(_){throw Error("Die Auftragskennung kann nicht gesichert werden. Es wurde kein neuer Auftrag gesendet.");}}
 function controls(){
  const locked=state.busy||!!state.intent||state.checking;
  root.querySelectorAll("button,select").forEach(b=>b.disabled=locked);
  $("keyboard-direct-form").querySelectorAll("input,textarea").forEach(input=>input.disabled=locked);
  const textMode=$("keyboard-kind").value==="text",validKey=$("keyboard-key").value!=="character"||Array.from($("keyboard-character").value).length===1;
  const system=systemMode(),actionMode=$("keyboard-kind").value==="system";
  const action=actionMode?systemAction():null,acceptsModifiers=systemModifiersAllowed(action);
  $("keyboard-system-modifiers").hidden=!acceptsModifiers;$("keyboard-system-modifier-help").hidden=!acceptsModifiers;
  $("keyboard-system-modifiers").querySelectorAll("input").forEach(input=>{input.disabled=locked||!acceptsModifiers;if(!acceptsModifiers)input.checked=false;});
  $("keyboard-system-modifier-help").textContent=["volume_up","volume_down","brightness_up","brightness_down"].includes(action?.action)?"Option + Shift ermöglicht bei Lautstärke und Helligkeit kleinere Schritte, sofern der Mac diese unterstützt. Andere Kombinationen können macOS-Einstellungen öffnen.":"Zusätzliche Tasten werden mit diesem Mac-Tastensignal gesendet. Ihre Wirkung hängt von Hardware, Medien-App und macOS-Einstellungen ab.";
  $("keyboard-send").disabled=locked||state.permissionReady===false||(!system&&!app())||state.composing||(textMode?!$("keyboard-text").value:!validRepeat()||(actionMode?!systemAction():!validKey));
  $("keyboard-destination").textContent=system?"Ziel: macOS · systemweit":app()?"Ziel: "+(app().name||app().bundle_id||"Programm"):"Wähle ein Zielprogramm.";
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
 function guidanceView(guidance){
  if(!guidance||!Array.isArray(guidance.checks))return;
  state.permissionReady=guidance.keyboard_ready===true?true:guidance.keyboard_ready===false?false:null;
  renderMacOSPermissions(guidance);
  $("keyboard-permission-help").textContent=(guidance.summary||"macOS-Freigaben geprüft.")+(state.permissionReady===false?" Öffne unten „Rechte“, prüfe die angezeigten Schritte und prüfe anschließend die Funktionen erneut.":"");
 }
 function inventoryView(result){
  const select=$("keyboard-system-action"),previous=select.value;
  state.systemActions=(result.actions||[]).filter(item=>item&&typeof item.action==="string"&&/^[a-z][a-z0-9_]{0,63}$/.test(item.action)&&actionLabel(item));
  select.replaceChildren(node("option","Funktion wählen"));select.firstChild.value="";
  for(const action of state.systemActions){const option=node("option",actionLabel(action)+(action.available===true?"":" · nicht verfügbar"));option.value=action.action;option.disabled=action.available!==true;select.append(option);}
  select.value=state.systemActions.some(item=>item.action===previous&&item.available===true)?previous:"";
  state.inventoryLoaded=true;
  const available=state.systemActions.filter(item=>item.available===true).length;
  $("keyboard-system-help").textContent=available+(available===1?" Tastensignal/Systemaktion erkannt.":" Tastensignale/Systemaktionen erkannt.")+" Kein Zielprogramm erforderlich. Eine Gerätewirkung ist nur bei einem entsprechenden Zustandsbeleg bestätigt; sie hängt auch von Hardware, laufender Medien-App und macOS-Einstellungen ab.";
  guidanceView(result.permission_guidance);
 }
 function renderActions(){const select=$("keyboard-actions"),previous=select.value;select.replaceChildren(node("option","Aktion wählen"));select.firstChild.value="";for(const [name,action] of Object.entries(state.saved?.profile.actions||{})){const option=node("option",name+(action.provenance==="observed_menu"?" · unbestätigter Kandidat":""));option.value=name;select.append(option);}if(Object.hasOwn(state.saved?.profile.actions||{},previous))select.value=previous;}
 function acceptProfile(result,intent){
  state.saved={profile_id:result.profile_id,revision:result.revision,profile:result.profile};
  if(intent.editor_version===state.version){$("keyboard-editor").value=JSON.stringify(result.profile,null,2);state.dirty=false;}
  renderActions();
 }
 function resultView(result,intent){
  if(intent.operation==="keyboard.system_inventory"){inventoryView(result);
  }else if(intent.operation==="system.permissions"){guidanceView(result.permission_guidance);
  }else if(intent.operation==="keyboard.profiles.list"){
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
  $("keyboard-status-summary").textContent=({completed:"Auftrag abgeschlossen.",failed:"Auftrag fehlgeschlagen.",rejected:"Auftrag abgelehnt.",blocked:"Auftrag gesperrt.",cancelled:"Auftrag abgebrochen.",unknown:"Ausgang ungewiss. Bitte nur den Auftragsstatus prüfen."})[task.state]||"Auftrag läuft. Bitte warte auf die Rückmeldung.";
  let actionConfirmed=!["run_profile","keyboard.control"].includes(intent.operation);
  if(task.state==="completed"){
   if(intent.operation==="run_profile"){
    const r=task.result||{},b=r.profile_binding;
    actionConfirmed=task.ui_workflow_status==="primary"&&intent.primary===true&&task.id===intent.task_id&&r.profile_binding_verified===true&&r.post_calls_returned===2&&b?.id===intent.binding.id&&b.revision===intent.binding.revision&&b.action===intent.binding.action;
    if(actionConfirmed)notice("Profilbindung und native Post-Aufrufe bestätigt. Die Programmaktion ist damit nicht bestätigt.");
    else notice("Nur eine Vorstufe ist beendet. Die Profilaktion ist nicht bestätigt; es wird nichts erneut gesendet.",true);
   }else if(intent.operation==="keyboard.control"){
    const r=task.result||{},resolved=r.resolved_application,repeat=intent.repeat||1,system=intent.scope==="system",nativeSystem=r.native_operation==="keyboard.system_key"&&r.event_scope==="system";
    const targetConfirmed=system?Number.isInteger(resolved?.pid)&&Number.isFinite(resolved?.started_at):resolved?.pid===intent.pid&&resolved.started_at===intent.expected_started_at;
    const repeatConfirmed=r.post_calls_returned===2*repeat&&(repeat===1||(r.requested_repeat===repeat&&r.completed_repeat===repeat));
    const actionModifiersConfirmed=!Array.isArray(intent.action_modifiers)||(Array.isArray(r.resolved?.modifiers)&&r.resolved.modifiers.length===intent.action_modifiers.length&&new Set(r.resolved.modifiers).size===r.resolved.modifiers.length&&intent.action_modifiers.every(value=>r.resolved.modifiers.includes(value)));
    const capsRequested=system&&intent.action==="caps_lock",capsVerified=capsRequested&&nativeSystem&&r.scope==="native_state_readback"&&r.modifier==="caps_lock"&&r.resolved?.route==="modifier_lock_state"&&r.resolved?.action==="caps_lock"&&r.effect_verified===true&&r.system_processing_confirmed===true&&r.requested_repeat===repeat&&r.completed_repeat===repeat&&r.state_set_calls_returned===repeat&&r.post_calls_returned===0&&typeof r.state_before==="boolean"&&typeof r.state_after==="boolean"&&r.state_after===(r.state_before!==Boolean(repeat%2));
    const receiptConfirmed=intent.kind==="text"?r.text_verified===true&&r.selection_verified===true&&r.return_posted===intent.submit:capsRequested?capsVerified:repeatConfirmed&&actionModifiersConfirmed&&(!system||nativeSystem)&&(!intent.action||r.resolved?.action===intent.action)&&(intent.scope!=="app"||!nativeSystem);
    actionConfirmed=task.ui_workflow_status==="primary"&&intent.primary===true&&task.id===intent.task_id&&r.automatic_target===true&&targetConfirmed&&receiptConfirmed;
    notice(actionConfirmed?(intent.kind==="text"?"Text im Zielprogramm bestätigt."+(intent.submit?" Return wurde gesendet; die Verarbeitung im Programm ist nicht bestätigt.":""):capsVerified?"Feststelltaste bestätigt: "+(r.state_after?"eingeschaltet.":"ausgeschaltet."):nativeSystem?"Mac-Funktion wurde gesendet. Die Wirkung auf dem Mac ist damit noch nicht bestätigt.":"Native Tastendruck-Aufrufe bestätigt. Die Verarbeitung im Programm ist nicht bestätigt."):"Die Eingabe ist nicht vollständig bestätigt. Auftrag bleibt erhalten; nicht erneut senden.",!actionConfirmed);
   }else{resultView(task.result||{},intent);notice("Auftrag abgeschlossen.");}
  }else if(finalStates.has(task.state)){report(Error(task.state==="unknown"?"Ausgang ungewiss. Auftrag bleibt erhalten; nicht erneut senden.":task.error?.message||task.error?.code||"Auftrag nicht bestätigt: "+task.state));}
  else notice("Auftrag offen. Eine nötige Freigabe findest du unter Rechte.");
  const safeEnd=finalStates.has(task.state)&&task.state!=="unknown"&&(!["run_profile","keyboard.control"].includes(intent.operation)||task.ui_workflow_status==="halted"||(task.ui_workflow_status==="primary"&&(task.state!=="completed"||actionConfirmed)));
  if(finalStates.has(task.state)&&!safeEnd){intent.state="unknown";$("keyboard-task").textContent+=" · Ausgang nicht bestätigt; nur Status prüfen.";$("keyboard-status-summary").textContent="Eingabe nicht vollständig bestätigt. Bitte nur den Auftragsstatus prüfen.";}
  if(safeEnd){intent.terminal=true;persist(intent);state.intent=null;}else persist(intent);
  controls();return finalStates.has(task.state);
 }
 function nextRead(){
  if(state.intent||state.busy)return;
  const operation=state.readQueue.shift();
  if(!operation){state.checking=false;controls();return;}
  request(operation,{}).catch(report);
 }
 async function poll(intent,automatic=false){
  if(state.polling||state.intent!==intent||!intent.task_id)return;state.polling=true;controls();
  try{const done=taskView(await api("/api/control/keyboard/task/"+encodeURIComponent(intent.task_id)),intent);if(!done&&automatic&&++intent.polls<40)setTimeout(()=>poll(intent,true),750);}
  catch(error){report(error);}finally{state.polling=false;controls();if(!state.intent&&state.checking)setTimeout(nextRead,0);}
 }
 async function request(operation,args){
  if(state.busy||state.intent)return;
  const intent={id:crypto.randomUUID(),operation,editor_version:state.version,polls:0,pid:args.pid,expected_started_at:args.expected_started_at};
  intent.task_id="ui-keyboard-"+intent.id.replaceAll("-","")+"-main";
  if(operation==="run_profile")intent.binding={id:args.profile_id,revision:args.expected_revision,action:args.action};
  if(operation==="keyboard.control"){intent.kind=args.text!==undefined?"text":"key";intent.submit=args.submit===true;intent.scope=args.scope||"auto";intent.action=args.action;intent.repeat=args.repeat||1;if(args.action&&Array.isArray(args.modifiers))intent.action_modifiers=args.modifiers.slice();}
  const body=JSON.stringify({id:intent.id,operation,args});
  if(bytes(body)>32768)throw Error("Dieser Auftrag überschreitet 32 KiB. Bitte den Text oder das Profil kürzen. Es wurde nichts gesendet.");
  persist(intent);state.intent=intent;state.last=intent;state.busy=true;controls();
  $("keyboard-task").textContent="Anfrage "+intent.id+" wird einmalig gesendet …";
  $("keyboard-status-summary").textContent="Auftrag wird einmalig gesendet …";
  try{const done=taskView(await api("/api/control/keyboard/request",{method:"POST",body}),intent);if(!done)setTimeout(()=>poll(intent,true),750);}
  catch(error){intent.state="unknown";persist(intent);report(error);$("keyboard-task").textContent="Anfrage "+intent.id+" · Rückmeldung ungewiss. Nicht erneut senden. "+(intent.task_id?"Status nur lesend prüfen.":"Auftragskennung im Protokoll prüfen.");$("keyboard-status-summary").textContent="Rückmeldung ungewiss. Nicht erneut senden; bitte nur den Auftragsstatus prüfen.";}
  finally{state.busy=false;controls();if(!state.intent&&state.checking)setTimeout(nextRead,0);}
 }
 function draft(){const text=$("keyboard-editor").value;if(bytes(text)>24576)throw Error("Der JSON-Entwurf überschreitet 24 KiB.");const doc=JSON.parse(text);if(!doc||Array.isArray(doc)||!doc.id||!doc.app||!doc.actions)throw Error("Profil benötigt id, app und actions.");return doc;}
 function changed(){state.dirty=true;state.version++;controls();}
 function discard(){return !state.dirty||confirm("Ungespeicherten Entwurf verwerfen?");}
 function bind(id,action){$(id).addEventListener("click",()=>{try{Promise.resolve(action()).catch(report);}catch(error){report(error);}});}
 function checkCapabilities(){if(state.intent||state.busy||state.checking)return;state.checking=true;state.readQueue=["keyboard.system_inventory","system.permissions"];controls();nextRead();}
 function directView(){const kind=$("keyboard-kind").value,text=kind==="text",character=$("keyboard-key").value==="character";$("keyboard-text-fields").hidden=!text;$("keyboard-key-fields").hidden=kind!=="key";$("keyboard-system-fields").hidden=kind!=="system";$("keyboard-app-target").hidden=systemMode();$("keyboard-repeat-fields").hidden=text;$("keyboard-character").hidden=!character;$("keyboard-character-label").hidden=!character;controls();if(kind==="system"&&!state.inventoryLoaded)checkCapabilities();}
 function sendDirect(){
  if(state.composing||state.checking)return;
  const system=systemMode(),selected=app();if(!system&&!selected)return;
  const args=system?{scope:"system"}:{pid:selected.pid,expected_started_at:selected.started_at};
  if($("keyboard-kind").value==="text"){
   const text=$("keyboard-text").value;if(!text)throw Error("Bitte Text eingeben.");
   if(/[\ud800-\udfff]/u.test(text))throw Error("Der Text enthält ein ungültiges Unicode-Zeichen.");
   if(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/u.test(text))throw Error("Der Text enthält nicht unterstützte Steuerzeichen.");
   args.text=text;args.submit=$("keyboard-submit").checked;
  }else{
   if(!validRepeat())throw Error("Bitte eine ganze Anzahl von 1 bis 20 wählen.");
   if(repeatCount()!==1)args.repeat=repeatCount();
   if($("keyboard-kind").value==="system"){
    const action=systemAction();if(!action)throw Error("Bitte eine verfügbare Mac-Funktion wählen.");args.action=action.action;
    if(systemModifiersAllowed(action))args.modifiers=Array.from($("keyboard-system-modifiers").querySelectorAll("input:checked"),input=>input.value);
    return request("keyboard.control",args);
   }
   if(!system&&$("keyboard-scope").value==="app")args.scope="app";
   const key=$("keyboard-key").value,character=$("keyboard-character").value;
   if(key==="character"&&(Array.from(character).length!==1||(character!==" "&&/[\p{C}\p{Z}]/u.test(character))))throw Error("Bitte genau ein sichtbares Zeichen eingeben.");
   args.key=key==="character"?{character}:{named:key};args.modifiers=Array.from(root.querySelectorAll(".keyboard-modifiers input:checked"),input=>input.value);
  }
  return request("keyboard.control",args);
 }
 $("keyboard-form").addEventListener("submit",event=>event.preventDefault());
 $("keyboard-direct-form").addEventListener("submit",event=>event.preventDefault());
 $("keyboard-kind").addEventListener("change",directView);$("keyboard-key").addEventListener("change",directView);$("keyboard-scope").addEventListener("change",directView);
 $("keyboard-repeat").addEventListener("input",controls);$("keyboard-system-action").addEventListener("change",controls);
 for(const id of ["keyboard-text","keyboard-character"]){$(id).addEventListener("input",controls);$(id).addEventListener("compositionstart",()=>{state.composing=true;controls();});$(id).addEventListener("compositionend",()=>{state.composing=false;controls();});}
 $("keyboard-editor").addEventListener("input",changed);
 $("keyboard-profiles").addEventListener("change",controls);$("keyboard-actions").addEventListener("change",controls);
 $("keyboard-apps").addEventListener("change",()=>{state.menu=null;$("keyboard-menu").textContent="";$("keyboard-menu-next").hidden=true;$("keyboard-coverage").textContent="Für dieses Programm noch keine Menübeobachtung.";const selected=app();$("keyboard-context").value=JSON.stringify(selected?{bundle_id:selected.bundle_id}:{},null,2);controls();});
 bind("keyboard-refresh",async()=>{await request("keyboard.profiles.list",{});if(!state.intent)await request("apps.list",{limit:250});});
 bind("keyboard-apps-refresh",()=>request("apps.list",{limit:1000}));
 bind("keyboard-send",sendDirect);
 bind("keyboard-capabilities",checkCapabilities);
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
 try{const last=JSON.parse(sessionStorage.getItem(storage)||"null");if(last&&typeof last.id==="string"&&typeof last.operation==="string"){state.last=last;if(!last.terminal){state.intent=last;$("keyboard-status-summary").textContent="Ein vorheriger Auftrag ist noch nicht bestätigt. Bitte nur den Auftragsstatus prüfen.";}$("keyboard-task").textContent="Vorherige Anfrage "+last.id+(last.task_id?" · Auftrag "+last.task_id:"")+" · "+(last.state||"Rückmeldung offen")+". Nur Status prüfen, nicht erneut senden.";}}catch(_){notice("Vorherige Auftragskennung konnte nicht gelesen werden.",true);}
 const keySelect=$("keyboard-key");
 for(let index=13;index<=20;index++){const option=node("option","F"+index);option.value="f"+index;keySelect.append(option);}
 const keypad={help:"Hilfe",keypad_clear:"Ziffernblock: Löschen",keypad_decimal:"Ziffernblock: Dezimalzeichen",keypad_multiply:"Ziffernblock: ×",keypad_plus:"Ziffernblock: +",keypad_divide:"Ziffernblock: ÷",keypad_minus:"Ziffernblock: −",keypad_equals:"Ziffernblock: =",keypad_comma:"Ziffernblock: Komma"};
 for(let index=0;index<=9;index++)keypad["keypad_"+index]="Ziffernblock: "+index;
 for(const [key,label] of Object.entries(keypad)){const option=node("option",label);option.value=key;keySelect.append(option);}
 controls();
})();
