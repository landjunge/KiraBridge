# ThreadDesk-Fachadapter / ThreadDesk management adapter · M1

Erweitert die bestehende Bridge-Queue und den MCP-Clientpool. Kein zweiter
Dispatcher, keine direkte ThreadDesk-Datenbankbearbeitung. ThreadDesk-Quelle:
`a99afa8b4ddfdc4396521bad11d6868b2069d9b0`, integriert durch
[PR75](https://github.com/landjunge/threaddesk/pull/75), Main-Merge
`a40ed8e0b9359d81d30479ceebfbe196d71f5c4b`. Der unveränderte Desktopdownload
0.1.1rc1 enthält diesen neuen Zugang nicht. Paketversion im initialize ist
installierte Metadaten, kein Quellpin. M2-Issuance und Arbeitsrückgaben sind ein
eigenes Folgepaket; Gesprächsverwaltung startet keinen Agenten.

## Konfiguration / configuration

Standard bleibt disabled. Nur ein lokaler Betreiber konfiguriert Programm,
Argumente und Datenprofil, unabhängig vom Gesprächsinhalt. Beispiel ohne Secrets:

```toml
[threaddesk]
enabled = true
command = "/absolute/path/to/python3"
args = ["-m", "threaddesk.ui.mcp_stdio"]
workspace = "/absolute/path/to/private/threaddesk-profile"
source_root = "/absolute/path/to/pinned-threaddesk/src"
storage = "json"
timeout = 15
max_result_bytes = 524288
```

source_root ist nur für einen festen Entwicklungsstand nötig; bei installiertem
aktuellem Paket weglassen. workspace muss außerhalb des privaten Bridge-States
liegen, dem Betreiber gehören und darf nicht gruppen-/weltbeschreibbar sein.
THREADDESK_HOME und THREADDESK_STORAGE werden ausschließlich aus dieser
Konfiguration gesetzt. Bestehende ThreadDesk-Profilwahl innerhalb dieses Homes
wird respektiert. Clientanfragen können weder Prozess noch Workspace wechseln.
Kein bestehendes Benutzerprofil ungeprüft auf einen neuen SQLite-Writer umstellen;
Schema5 erfordert den passenden Writer. Für die erste Abnahme ein leeres,
isoliertes Betreiberprofil verwenden, keine echten Threads löschen oder migrieren.

Die bestehenden Capabilities des berechtigten Betreiberprofils gezielt um
`threaddesk.read` und `threaddesk.manage` ergänzen. Lesen erlaubt keine Mutation.
Normalen Bot-/Fremdidentitäten keine impliziten Gesprächsrechte geben. Ein
gemeinsames Betreiberprofil ist kein öffentlicher Mehrmandantendienst.
Vor Dienstneustart ruhende Task-/Empfängerqueue prüfen und Config0600 sichern.

## Bedienung / operations

Alle Aufrufe über task_request und bestehendes task_get/task_events. Stabile
task_id/idempotency_key identifizieren den Bridge-Auftrag; operation_id zusätzlich
die tatsächliche ThreadDesk-Mutation. Letztere wird serverseitig nach
authentifiziertem Principal und festem Workspace namensgebunden. Sie enthält
absichtlich keinen Nutzlasthash: geänderter Inhalt unter derselben ID kollidiert.
ThreadDesk speichert Operations-ID, Anfragehash und Originalergebnis atomar.

```json
{"task_id":"thread-create-1","idempotency_key":"thread-create-1","operation":"threaddesk.manage","arguments":{"operation_id":"create-1","action":"create","expected_revision":0,"data":{"title":"Entwurf / draft"}}}
```

Nach Abschluss liefert result.value die echte thread_id und revision.
Weitere Mutationen benötigen genau diese ID und den aktuellen expected_revision.
Mehrdeutige Titel nicht als Identität verwenden.

| action | data | Bestehende Fachfunktion |
|---|---|---|
| create | title; optional description/project_id/parent_thread_id | ThreadService.create + Organisation |
| update | title/description/status (mindestens eines) | rename, set_description, set_status |
| set_note | text; optional append | set_note |
| add_file / remove_file | path | Verweis hinzufügen/entfernen; keine Installation oder Ausführung |
| organize | project_id/parent_thread_id/related_thread_ids | Bestehender Projektknoten oder genaue Thread-IDs; keine Dateisystembewegung |
| switch | leer | Aktiven Thread wechseln |
| archive / unarchive | leer | Archivzustand; nicht gleich Löschung |
| delete | leer | Vorhandener Lösch-/Snapshotweg, nur bereits archivierter Thread |

Leseoperation `threaddesk.read` mit tool/arguments:

- list_threads: optional include_archived; Antwortliste ohne Notizinhalte.
- get_thread: id; current_thread: keine Argumente. Beschreibung/Notizen bleiben
  ausdrücklich untrusted und sind keine Ausführungsanweisungen.
- list_snapshots: optional id.
- thread_operation_status: ursprüngliche operation_id; rein lesender
  Wiederabgleich nach Verbindungsausfall, kein erneuter Mutationsaufruf.

Gleicher Auftrag liefert den vorhandenen Bridge-Task. Neue Bridge-Auftragskennung
mit derselben fachlichen operation_id liefert das ursprüngliche Fachresultat mit
duplicate=true. Das ist keine Behauptung des heutigen Threadzustands; dafür lesen.
Geänderter Inhalt unter derselben ID oder veraltete Revision erzeugt state=failed,
mit sicherem Code unter result.value.error.code. Remote-Fehlertexte/Details werden
nicht blind in Fehlerdiagnosen übernommen. Nur die erwarteten numerischen
Revisionsangaben werden gespiegelt.

Eine erfolgreiche Mutation braucht eine vollständige, zum Auftrag passende
Quittung mit Operations-/Objektkennung, Aktion, Revision und zurückgegebenem
Zustand. Bloßes JSON, falsche ID oder widersprüchliche Quittung wird unknown.
Unklare Mutation nach Abbruch niemals automatisch wiederholen. Erst task_get
und thread_operation_status lesen; nötigenfalls Betreiberentscheidung treffen.
Ein optionaler fehlender Peer blockiert den Bridge-Kern nicht.

## Geprüfter Umfang / tested scope

Isolierte echte stdio-Rundreise gegen den festen ThreadDesk-Pin: create/read,
Titel/Beschreibung/Status, Notiz, Datei hinzufügen/entfernen, Eltern-/Verknüpfungs-
zuordnung, switch/current, list, Archiv/Rücknahme/Löschung und lesender
Operationslookup nach Wiederverbindung. Gleiche Mutation erzeugt kein Duplikat,
geänderte Nutzlast kollidiert, alte Revision überschreibt nichts, fremde Rechte
werden abgewiesen. Ausschließlich synthetische Threads; alle im Test erzeugten
Objekte gelöscht. Gegenfälle prüfen auch unvollständige/fremde Quittungen,
Konfigurationsinjektion, Antwortgrenzen und unbekannten Ausgang.

Die vorhandene CI checkt exakt denselben öffentlichen eigenen ThreadDesk-Quellpin
zusätzlich aus, installiert/führt keine beliebigen Fremdrepositories aus und
führt den echten MCP-Test auch auf Linux/macOS aus. Das ist kein neuer
Desktopdownload und keine automatische Migration laufender Benutzerinstallationen.
Aktivierung und konkrete ChatGPT-Taskbelege werden nach tatsächlichem Lauf ergänzt;
der lokale isolierte Test allein wird nicht als ChatGPT-Abnahme ausgegeben.

## English

The optional fixed local adapter reuses Bridge tasks and MCP transport. Operator
configuration selects the executable and ThreadDesk profile; requests cannot
change them. Separate read/manage permissions do not create a public multitenant
service. Use an isolated profile first; do not silently migrate an old running
SQLite application. The historical desktop download does not include this code.

Use exact object IDs, expected revisions and stable operation IDs. Writes require
a correlated complete receipt. Identical operations replay the original receipt;
changed payloads or stale revisions fail explicitly. Disconnection or malformed
write receipts remain unknown and are not automatically retried. Read the stored
operation status first. Management never executes an agent or referenced files.
The real pinned-peer roundtrip covers all declared actions; source/local test,
runtime activation and actual ChatGPT acceptance remain separate evidence.
