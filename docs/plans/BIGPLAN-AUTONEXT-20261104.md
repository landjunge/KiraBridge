> **Nicht maßgeblich. Maßgeblich ist ThreadDesk-Thread `6b5b73b9de36` (Master mit Etappen E01–E09; Status im Board `188ce4729a62`; Nutzerbeschluss 09.11.2026). Diese Datei ist Archiv bzw. technischer Spiegel.**

# Begrenzte automatische Fortsetzung aus dem vorhandenen Whiteboard

Aktuelle Arbeitsgrundlage: gemeinsamer Big-Plan-Skill **1.2.0 vom 05.11.2026**.
Die folgende Mechanismuskennung bezeichnet dessen bestehende Implementierung,
keine Produktversion. Windows für Dirk ist der nächste priorisierte Folgeauftrag.

Paket `BIGPLAN-AUTONEXT-20261104-V1`, einziger schreibender Bearbeiter Codex.
Branch `feat/bigplan-autonext-20261104`, Basis
`bcb3b756f1b8dc8e62a27489d54f5be0445096e9`. Koordination und Freigabe:
ThreadDesk-Board `482f593429ad`, Notiz „Automatische Fortsetzung aus
ThreadDesk-Whiteboard“, tatsächlich gelesene Threadrevision 22. Die historischen
Boards `188ce4729a62` und `1b7530de7c5f` wurden als Kontext gelesen.

**Stand 05.11.2026: installiert als RC39@8d33131; globale produktive Aktivierung
weiter deaktiviert.** Die begrenzte reale native Abnahme mit zwei gepinnten
read-only-Karten, echten Providerturns und Empfangs-/Abschlussnachweisen ist
bestanden. Die getestete Reparatur ist regulär mit Rollback installiert.
Nachweise und verbleibende Produktionsgrenzen stehen in
[BIGPLAN-UNBLOCK-20261105](../BIGPLAN-UNBLOCK-20261105.md).
Eine konkrete unveränderlich freigegebene fachliche produktive READY-Liste und
passende Workerroute für einen Folgegrant liegen weiterhin nicht vor. Alte
Ideen und unbewiesene UNKNOWNs wurden nicht in ausführbare Aufträge umgewandelt.
Windows-Angleichung und Dirks Testpaket bleiben danach priorisiert.

## Vorhandener Ablauf und der fehlende Schritt

TeamManager besitzt bereits dauerhafte Teamaufträge, idempotente Claims und
einen festen Core-Task pro Turn. TeamDispatcher erreicht den konfigurierten
Codex-Worker über dessen authentifizierte vorhandene MCP-Verbindung und
`agent.execute`. MessageReceiver und HandoffManager bleiben bestehende eigene
Wege. Ein beendeter Modellturn bestätigt bisher ausdrücklich keine gesamte
Produktaufgabe (`completion_scope=agent_turn`).

Es fehlte die begrenzte Verbindung von **vorher freigegebenen Boardkarten** zu
diesem Dispatcher und einer nachweisbaren Aufgabenabnahme vor dem nächsten
Claim. `autonext` ergänzt diesen Koordinator im bestehenden Bridge-Prozess,
ohne Server, neue MCP-Endpunkte, Provider oder Shellinterpretation von Boardtext.
Es liest ausschließlich konfigurierte Entry-IDs und prüft deren exakte
UTF-8-Inhaltshashes. Die globale Auftrags-ID bleibt auch über neue Grants hinweg
einmalig. Der Modellprompt enthält nur die freigegebene Karte, keinen historischen
Team-/Boardkontext. Vom Modell verlangte Folgeaktionen/Delegationen sind für
diese Aufträge gesperrt; Grok wird nicht automatisch als Ersatz gestartet.

## Freigabevertrag und Grenzen

`AutoNextConfig` in `bridge_core.config.Config.autonext` ist die lokale
Operatorfreigabe, standardmäßig `enabled=false`. Ein aktivierter Grant bindet:

- eindeutige `grant_id`, Operator `local` oder `chatgpt`, vorhandenes Team und
  dessen beobachtete Revision;
- genau ein vorhandenes Board und eine geordnete Liste von höchstens 16
  `task_id`/`entry_id`/`content_sha256`-Pins;
- einen vorher unabhängig bestätigten Teamauftrag `after_work_id` plus exakten
  `after_result_sha256` als Startanker;
- festes Codex-Profil, Worker, Arbeitsverzeichnis, Sandbox, Rechte und Route;
- `max_tasks` (Standard 2, höchstens 16), endliche Lease und eine frische,
  zeitlich begrenzte Budgetbeobachtung mit Quellen-/Abrechnungsbeleg.

Eine Karte ist ein vollständiges JSON-Objekt, beispielsweise:

```json
{
  "autonext": 1,
  "task_id": "eindeutiger-freigegebener-auftrag",
  "state": "READY",
  "product": "KiraBridge",
  "cwd": "/absoluter/bereits-freigegebener/worktree",
  "sandbox": "workspace-write",
  "title": "Konkreter begrenzter Auftrag",
  "instruction": "Nur der ausdrücklich freigegebene Umfang mit Abnahmekriterien.",
  "acceptance": {"kind": "operator_receipt"}
}
```

Unbekannte Felder, unpassende Identität, Inhaltshash oder Rechte führen zum STOP.
`IDEA`, `HOLD`, `UNKNOWN`, `STALE`, `CANCELLED` werden nicht ausgeführt. Eine
ungelistete READY-Karte bleibt ebenso inert. Text allein erteilt keine Rechte.
Die erste Version bindet ein bereits konfiguriertes Codex-Arbeitsverzeichnis;
sie verteilt nicht eigenmächtig Aufträge auf neue Worktrees/Provider/Accounts.

Für Schreibaufträge muss ein unabhängiger Operator den fertig belegten Core-
und Teamauftrag durch `operator_receipt` bestätigen. Ein Modelltext „fertig“
reicht nicht. Für begrenzte reine Antwortprüfungen in `read-only` kann stattdessen
ein **vorab** freigegebener exakter Ergebnis-SHA256 dienen. Auch dann sind ein
erfolgreicher abgeschlossener Core-Task und belegtes Turnende erforderlich.
Der Mechanismus prüft keinen beliebigen fachlichen Erfolg selbstständig.

Budgetzustand `unknown`/`exhausted`, abgelaufene Beobachtung, fehlende Belegreferenz
oder gesetzte effektive API-Schlüssel stoppen vor dem nächsten Provideraufruf.
Auch der konfigurierte Schlüsselname wird berücksichtigt. Die Budgetbeobachtung
ist höchstens eine Stunde gültig; der nächste Turn muss vollständig in das
verbleibende Lease-/Budgetfenster passen. Das ersetzt keine echte Quota- oder
Subscription-Prüfung. Es gibt keinen neuen kostenpflichtigen Fallback und keine
automatische Modell-, Tarif-, Account- oder Rechteänderung.

## Claim, Restart und bestehende Arbeit

Claim, Teamdelegation, Worktree-Lease und Board-Outbox werden in **einer**
vorhandenen SQLite-Transaktion gespeichert. Der Dispatcher darf erst nach
separatem Rücklesen der Board-Claimquittung starten. Der Abschluss bekommt
ebenfalls eine dauerhaft gespeicherte Quittung und einen unabhängig gelesenen
Boardbeleg, bevor die nächste Karte beansprucht wird. Boardnotizen enthalten nur
IDs, Phasen, Hashes und feste Fehlercodes; keine Prompts, Ergebnisse, Geheimnisse
oder unbearbeitete Exceptions.

Ein Lease schützt den gesamten Git-Worktree einschließlich seiner Unterordner
und gilt auch gegenüber direkten AgentManager-, Handoff- und Receiveraufrufen.
Vor dem Claim werden bereits vorhandene Team-/Core-/Handoff-/Receiveraufträge
berücksichtigt. Receiver speichern `execution_cwd` beim Claim in der bestehenden
`message_jobs`-Tabelle. Die additive Migration lässt alte unbekannte Scopes leer;
diese werden nicht aus einer inzwischen geänderten Konfiguration rekonstruiert.
Sichtbare unbestätigte Handoffs ohne dauerhafte CWD-Zuordnung sperren konservativ
die Fortsetzung. Fremde Arbeit wird weder abgebrochen noch verändert.

Ein Neustart beobachtet denselben gespeicherten Auftrag/Core-Task. Ein fehlender
Core-Task, verlorene Ausführungsantwort, verändertes Programm/Profil/Rechte,
Timeout, abgelaufener Lease oder unbekannter Zustand erlaubt **keinen** zweiten
Start. STOPs bleiben dauerhaft, alte/abgelaufene Leases werden nicht gestohlen.
Nur bei eindeutig noch nicht ausgeführtem Claim wird der vorhandene einmalige
Auftrag nach Wiederherstellung seiner Boardquittung weitergereicht. Eine verlorene
Board-Antwort wird über denselben `external_key` und Rücklesen abgeglichen.
Die Zusicherung lautet höchstens einmal auslösen; ein Crash kann sicheren STOP
statt einer garantierten Ausführung bedeuten.

Der Koordinator reagiert auf vorhandene Teamereignisse, einen Startabgleich und
höchstens einen aktuellen Lease-/Budgettimer. Er führt keine regelmäßigen
Whiteboard-/Providerabfragen aus. Fehler seiner Admission-Prüfung sperren seine
Aufträge, ohne den vorhandenen Dispatcher für unabhängige Arbeit zu beenden.

## Vorhandene Bedienoberfläche

`bridge_health` zeigt unter `autonext` Status und Grenze. Es gibt genau eine neue
semantische Operation unter dem vorhandenen `action_request`, kein neues Tool:

```json
{
  "request": {
    "task_id": "eindeutige-operator-quittung",
    "idempotency_key": "eindeutige-operator-quittung",
    "operation": "autonext.control",
    "arguments": {
      "action": "confirm",
      "grant_id": "konfigurierter-grant",
      "task_id": "eindeutiger-freigegebener-auftrag",
      "result_sha256": "<64-kleinbuchstabige-Hexzeichen-des-geprueften-Teamresultats>",
      "evidence_ref": "<Referenz-auf-unabhaengige-Abnahme>"
    }
  }
}
```

Nur der konfigurierte Operator mit `team.manage` darf bestätigen. Die Bestätigung
bindet exakt Auftrag, Grant, Core-Nachweis und Ergebnis; sie ist unveränderlich
und über den normalen Taskstatus rücklesbar. `action=wake` mit ausschließlich
`grant_id` weckt den begrenzten Abgleich, erweitert keinen Grant und hebt keinen
STOP auf. Board-/Team-/Corequittungen bleiben über die vorhandenen Lesepfade
zugänglich; `AutoNextManager.receipt` liefert die lokale Abnahmequittung.
Sichtbare Terminalroute und strukturierter Agentenweg bleiben getrennt. Es gibt
keinen automatischen Queue-/API-Ersatz für eine blockierte sichtbare Eingabe.

## Prüfbelege und Aktivierung

`tests/test_autonext.py` nutzt isolierte Boards, die echte authentifizierte lokale
HTTP-/MCP-/Task-/Team-Kette und ausführbare **deterministische Test-CLIs**. Diese
sind keine Codex-/Grok-Modelle und verursachen keine Provideraufrufe. Es gibt
keinen nativen Terminal-, Browserchat-, Subscription- oder produktiven Board-
E2E-Nachweis. Die Testquittungen werden nach dem Schreiben unabhängig gelesen.

Geprüft werden zwei freigegebene READY-Aufgaben der Reihe nach genau einmal,
null unfreigegebene Aufgaben, Leerlauf, geänderte Quelle/Identität/Rechte,
überlappende Worktrees, bestehende Handoff-/Receiverarbeit, Modell-Delegations-
Ablehnung, Operatorquittung über `action_request`, begrenztes Budget/Timeout,
Crash/Restart und verlorene Transport-/Boardantworten. Der Crashfall beendet
einen eigenen Controller-Subprozess mit `os._exit` und startet die gespeicherte
Kette danach neu. Historische UNKNOWNs bleiben erhalten.

Private Sicherung und detaillierte Test-/Reviewbelege:
`~/.local/share/kirabridge/backups/bigplan-autonext-20261104-v1/`.
Sie enthält Ausgangszustand, Freigabequelle, Patch **und unversionierte Dateien**,
Testlogs, ausgelesene E2E-Quittungen und unabhängige Reviewbefunde. Boardcheckpoints
haben stabile Paketkennungen und werden zurückgelesen. Keine Performance- oder
Cloudbeschleunigung wird aus diesem lokalen Replay abgeleitet.

Vor einer regulären produktiven Aktivierung fehlen weiterhin:

1. eine ausdrücklich freigegebene konkrete READY-Liste mit IDs, unveränderlichen
   Inhalts-Pins und bestätigtem Vorgänger; keine Umdeutung der alten Boardideen;
2. aktuelle reale Identitäts-/Route-/Budget-/Zugangsbelege und freie Worktrees;
3. gezielter echter Test dieser belegten Route und anschließende reguläre lokale
   Installation mit Backup, Integritäts-, Idle- und Rückweggates.

Dies war der historische Aktivierungsstand der Erstimplementierung am 04.11.2026:
damals lief RC39 `d9b0c0a770ca08ec951af78b87e687bf43eeded0`, der Chat-Gate-Fix
`147e6f85f8a87485156eeeae9c83bacf19349602` war noch separat und nicht installiert.
Am 05.11.2026 wurden die bestehenden Reparaturen integriert, real begrenzt
abgenommen und als RC39@8d33131 installiert; siehe den Status am Dokumentanfang.
Es wurden keine alten Marker erneut gesendet und keine externe Sicherheitsprüfung
umgangen. Dieses Paket löst keine Release-, Plattforminstallations- oder
Cloud-Build-Schleife aus.

## Historische Receiver-Scope-Pins (2026-11-05)

`autonext.legacy_scope_pins` ist standardmäßig leer. Ein ausdrücklich
konfigurierter Pin kann ausschließlich den fehlenden Arbeitsordner eines alten
`UNKNOWN`-Receiverjobs mit `agent_timeout` belegen: Nachrichten-/Run-/Empfänger-
und Session-ID sowie der SHA-256 der ursprünglichen Beobachtung müssen zum
gespeicherten `message.agent_progress` passen. Eine private, eigene, reguläre
Datei bindet dieselbe Identität und die exakten Hashes der ursprünglichen lokalen
Grok-Sessionmetadaten bzw. Codex-Rollout-Metadaten. Diese Quellen müssen Session
und absoluten Arbeitsordner unabhängig bestätigen; Symlinks, Mehrdeutigkeit,
fehlende oder geänderte Quellen bleiben STOP. Die Prüfung erfolgt bei Aufnahme
und nochmals vor Ausführung.

Der belegte Ordner unterliegt unverändert der normalen Überlappungssperre.
Pins gewähren keine Ausführung und ändern weder `UNKNOWN`, Auditgeschichte noch
Zustellzustand; sie schließen, retirieren oder wiederholen keinen alten Auftrag.
Heutige Receiverkonfiguration und freie Operatorerklärungen gelten nicht als
historischer Scopebeleg. Die isolierten Regressionen stehen in
`tests/test_autonext_legacy_scope.py`; private, inhaltsarme Belegdateien für die
sieben untersuchten Altjobs liegen unter
`~/.local/share/kirabridge/backups/autonext-legacy-scope-20261105/`.
