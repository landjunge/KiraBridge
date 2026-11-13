# Geladener eigener Stopp · Betreiberstand 19.10.2026

Historischer Installations- und Prüfbericht. Aktuelle Planung und Paketstatus
stehen in ThreadDesk: maßgeblicher Master `6b5b73b9de36`, aktiver Arbeitsplan
`7fb455b083f7` und Status im Arbeitsboard `188ce4729a62`.

Installierte Version0.5.2 mit geprüftem Quellbackport `f3f1302`;
zugehöriger Main-Quellpin `612a5c8f34a01d4280ce665dbf9d380a9e45a2c3`.
Dies ist kein neuer öffentlicher Download. Version/CLI/Setup der bestehenden
Installation wurden erhalten; der private eingefrorene RC2 ist ein anderer Stand.

Geladene Runtime `74e26c460e464de697be4920106f6189`, Python-Quell-SHA256
`250ad1efc3b00c755d680ff141bc0c5ae99ef5c413aa2abb489c3cd40ad7b559`.
Konfiguration `~/.config/kirabridge/config.toml`,0600,
SHA256 `f0a8b0f5dc6554bc7d8f706b42d01e7ccde88866ec0c05a05c0bbc718b3cfa1b`.
Die sieben festen Projektzuordnungen und `workflow.stop` nur für local/chatgpt
ergänzen bestehende Rechte; engere Bot-/Codex-Principals wurden nicht erweitert.

Der damalige Bedienweg und seine technischen Belege lagen im privaten
Projekt unter `/Users/landjunge/KiraBridge-project-control-20261018/docs/`:

- `WORKFLOW-CONTROL-CONFIGURATION.md`: Configschema, Rechte, Stopwunsch,
  Barriere/Prozessende und sicherer Rückweg.
- `SEVEN-TOOLS-FORTSETZUNG-20261019.md`: tatsächliche App-/Codex-/Neustartbelege.
- `evidence/workflow-stop-chatgpt-20261019.json`: zwölf ursprüngliche App-Tasks.
- `evidence/workflow-stop-worktree-restart-20261019.json`: aktueller zusätzlicher
  Source-/Restartbeleg, kein wiederholter Agenten-/Stop-/Antwortauftrag.
- Die frühere Paketmatrix ist zusammen mit den alten Planquellen unverändert
  in ThreadDesk archiviert: Datei `bb32567e949c` am Arbeitsboard
  `188ce4729a62`; sie ist kein aktueller GitHub-Plan.

Die tatsächlich ausgeführte lokale Vorprüfung:

```sh
kirabridge --principal chatgpt readiness --operation workflow.stop
```

Sie trennt `owned_abort_available` von `durable_barrier_prerequisites` und meldet
`barrier_confirmed=false`: noch kein Stoppaufruf. Manche ältere App-Kataloge zeigen
readiness/diagnose nicht als separate Tools; `task_get` enthält vorhandene Diagnose
und den damaligen Preflight. Health allein beweist keine Arbeitsfähigkeit.

`workflow.stop` über eine neue stabile Taskkennung ausdrücklich für eigenen
`handoff_id`, `revision`, `stop_id` beauftragen. Annahme/queued ist kein Erfolg.
Danach genau dieselbe Taskkennung abfragen. Unklare Schreibaufträge niemals mit
neuer Kennung wiederholen. Weitere Turns gestoppter Arbeit bleiben gesperrt;
keine automatische Wiederfreigabe durch Neustart oder Konfigurationswechsel.

TollGate ist aus dem separat sauberen lokalen Pin
`/Users/landjunge/tollgate/.worktrees/kirabridge-process-control-pinned-20261019`
eingebunden, Source `53fc57cc2e082d022e65e5929cb2a1e186fba852`. Diesen verwendeten
Worktree nicht als erledigte Arbeitskopie entfernen. Der tatsächliche Paket-SHA256
`c05981485abd3cb666942a8c83d00cb4337b82d7aefa644e6798cc1bd4562aa5` wird geprüft.
Keine automatische Installation/Freigabe beim Taskstart; fehlende optionale
Assembly sperrt kontrollierte Starts, erhält aber eigenen Abort und Leser.

Private Sicherung/Zeilenerhaltungsbelege:
`~/.local/share/kirabridge/workflow-control-20261019/` (0700, Configkopie0600).
413 vorherige Tasks,2 Bindungen,5 Nachrichten und4 Jobs sowie Schlüssel und
LaunchAgents beim letzten Laden unverändert. Kein ganzer Mac-Neustart behauptet.
Die LaunchAgents bleiben unabhängig von dieser interaktiven Codex-Sitzung aktiv.

Funktionsrückweg: optionale Assembly deaktivieren, aktuelle Stop-/Historienguards
beibehalten, nach Queueprüfung nur eigene Bridge-Dienste kontrolliert laden.
Keine Journale/Queue löschen und keine alte ungesicherte Software gestoppte
Historie ausführen lassen. Der vorherige unklare Adminversuch wird nicht wiederholt;
Root-/sudo-Funktion benötigt weiterhin tatsächliche lokale macOS-Bestätigung.

Kosten bleiben unbekannt, `stop_only`, kein harter Dollarcap. Eine EFFECTIVE-
Barriere ist kein Beweis für Prozessende oder Rücknahme externer Wirkungen.
Im App-Beleg endete der eine Codex-Turn bereits mit einer Rückfrage; ein Livekill
wird nicht behauptet. Eigene Dummy-Prozesse und Spawn-/Journalrennen sind getrennt
gezielt geprüft. Keine Aussage über geschützte fremde Konten oder globale
Kontrolle aller Standalone-Terminalaufrufe.

## English

This installed0.5.2 backport uses the checked source pins above, separately from
private frozen RC2 artifacts. Existing setup, permissions, tasks, credentials and
services were preserved. The actual App confirmed one owned Codex question turn,
effective stop and blocked continuation across controlled service reloads.
No live in-flight kill, whole-Mac reboot, administrator approval, global hard
money cap or protected-account browser access is claimed. Keep the pinned local
TollGate source directory and durable journals. Disable optional control while
retaining stop/history guards for rollback; never replay uncertain writes.
