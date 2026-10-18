# Begrenzter Audit-Leseexport / Bounded audit observation export

AA-C03 / KB-C05, 18.10.2026. Additive Quellcodevorbereitung auf
`583c000a8f226d5d9e71c51310fb0a81a3bafb49`; privates KiraBridge-Repository.
Keine Laufzeit-, Konfigurations-, CLI-Hauptbefehl- oder MCP-Wireänderung. Keine
zweite Warteschlange, Auditwelt, Serverinstanz, Ausführung oder Freigabeinstanz.
Tatsächlicher Teilnachweis: [Belege](evidence/workflow-observation-export-20261018/STATUS.md).

## Deutsch

### Was gelesen wird

Der Export liest ausschließlich das vorhandene `bridge.sqlite3` der konfigurierten
Installation. `mode=ro`, `PRAGMA query_only=ON` und eine SQLite-Lesetransaktion
werden verwendet; weder `Bridge()` noch `Store()` wird vom Leser erzeugt. Keine
Migration, Auftragsannahme/-änderung, Grantvergabe, Agentenstart, Stopp,
Löschung oder automatische Wiederholung. SQLite-interne Lesesperren/WAL-Nutzung
sind kein zusätzlicher Task-/Auditstore.

`export_workflow_observations(bridge, principal, *, task_ids, cursor=0, limit=100,
through_seq=None)` prüft die bestehende `task.read`-Berechtigung der Bridge.
Die spätere MCP-Verdrahtung muss `principal` aus dem **authentifizierten Transport**
liefern, niemals aus frei wählbaren Auftragsargumenten. Diese Verdrahtung ist hier
nicht implementiert. Das lokale Skript nutzt
`export_configured_observations(config, principal, ...)` mit derselben
konfigurierten Fähigkeit; es authentifiziert keine entfernte Identität. Ein
vertrauenswürdiger lokaler Betreiber wählt seinen bestehenden Principal.
Unbeschränkter SameUID-Dateizugriff wird dadurch nicht isoliert.

- Explizit 1–16 verschiedene eigene Bridge-Task-IDs. Jede ausgewählte Aufgabe muss
  existieren und genau dem Principal gehören. Fremd/fehlend bleibt `not_found`;
  ohne konfigurierte Lesefähigkeit verweigert der Leser vor Datenbankzugriff.
- Bestehende State-Datei als reguläre Datei, keine Symlink-Pfadkomponente;
  Unix-Eigentümer muss die eigene UID sein, State-Verzeichnis0700/Datei0600.
  Vorhandene SQLite-WAL/SHM-Dateien müssen ebenfalls regulär, owner-private und
  ohne Symlink sein.
  Fehlende/unsichere Voraussetzungen werden **nicht** automatisch eingerichtet.
- Auditabfragen sind zusätzlich principal- und taskgefiltert, einschließlich
  historischer Preflights und persistenter Handoff-Korrelationen. Kein globaler
  Fremdtask-Dump oder generischer `SELECT *`-Export.
- `args`, `result`, `error`, rohe Event-Evidence, Prompts, Ergebnisse, Dateiinhalte,
  Pfade, Credentials und Konfigurations-/Umgebungsdumps werden nicht abgefragt oder
  exportiert. Aus Auditmetadaten kommt nur die feste Kennungs-/Revisions-/Hash-
  Positivliste in die Ausgabe. Referenzen müssen selbst geheimnisfrei sein;
  eine Positivliste ist keine universelle DLP-Prüfung.

### Ereignisse und ehrliche Herkunft

Jede Datenzeile nutzt unverändert den vorhandenen AA-Vertrag
`agent-authority-workflow-event-v1`, `source_tool=kirabridge`. Keine konkurrierende
Ereignisschemawelt und keine verpflichtende Cross-Repo-Installation. Die
optionale lokale Abnahme gegen den festgepinnten bestehenden AA-Leser ist im
Test/Beleg dokumentiert; normale CI benötigt dafür keinen neuen Token.

`event_id=audit-SEQ-HASH`, `ordinal`, `event_hash` und `previous_event_hash`
erhalten die ursprüngliche Auditsequenz und ihre Hashbezüge. Die Quelle ist ein
stabiler opaker Fingerprint aus lokalem DB-Bezug und Principal, keine Pfadausgabe
und keine Personen-/Modellidentitätsbestätigung. Gleiche DB/Principal/Ereignisse
bleiben bei Wiederholung/Neustart gleich; eine DB-Kopie an anderem Ort wird nicht
als dieselbe attestierte Quelle behauptet. Exportierte Ereignisse werden nicht
neu fortlaufend nummeriert. Filter-/Vorverlaufs-/Retentionlücken bleiben sichtbar;
der Ursprung einer Lücke (Filter vs. Verlust) bleibt unbekannt. Ein einzelner
Recordhash wird geprüft; eine vollständige fremd-principalübergreifende
Auditkettenbeglaubigung wird nicht behauptet.

Unterstützte damalige Audits:

| Bestehender Audittyp | AA-Beobachtung |
|---|---|
| task.accepted | task.accepted |
| task.transition mit to=running/completed/failed/unknown/cancelled | Entsprechender task-Typ, damaliger Status |
| handoff.bound | handoff.bound |
| handoff.agent_started / handoff.question | task.started / task.question |
| handoff.turn_ended | task.completed, reported_status=turn_completed |
| handoff.delivered | return.received, delivered_unverified |
| handoff.decided | return.reviewed, checked; keine Funktionsprüfung/Projektabnahme |

`task.completed` eines generischen Datei-/Hilfsauftrags wird nicht als Agententurn
benannt. Nur `agent.execute` und ausdrücklich gemeldetes `handoff.turn_ended`
verwenden `turn_completed`. Ankunft, Review und Turnende bleiben getrennt von
verifizierter Gesamtauftragserfüllung. `handoff.answer_claimed` vor TD-Rückbeleg
wird **nicht** als zugestellte Antwort projiziert. Queued/Approval/Preflight und
andere nicht unterstützte Audittypen werden gezählt, nicht in einen angeblich
belegten Start umgedeutet. Fehlende Artefaktbelege werden nicht aus Volltexten
konstruiert. Rechte-/Budget-/Stopwirkungen bleiben unverifiziert.

Historische Kennungen kommen aus dem jeweiligen Auditereignis. Originale
`thread:task`-ID und Bridge-ID bleiben getrennt; eine Session ersetzt sie nicht.
Der generische Task-Requesthash stammt aus dem bestehenden Taskdatensatz. Bei
Handoffereignissen wird **kein** Hash des aktuellen Bridge-Schritts als
Workflow-Requesthash ausgegeben; nur ein ausdrücklich auditierter entsprechender
Hash ist zulässig. Unterschiedliche Hashbedeutungen nicht vermischen.

`provenance.execution_runtime` verwendet ausschließlich einen vorhandenen,
hashgeprüften `task.preflight` bis zur jeweiligen Ereignissequenz. Fehlender oder
ungültiger alter Preflight bleibt unbekannt. Aktuelle Leser-/Servicefingerprints
werden historischen Ereignissen niemals nachträglich angeheftet. Nur gewählte
Runtime-Instanz-/Versions-/Konfigurations-/Quellfingerprints werden ausgegeben;
keine Runtimepfade, PID-/Argv-/Env-/Credentialdaten.

`current_correlations` ist ausdrücklich der **aktuelle persistente**
`handoff_bindings`-Bezug, kein historischer Beweis. Nur eigene Datensätze und
opake `correlation_ref`, operator_ref, Handoffrevision/-ID, erste Task-ID und
`binding_request_hash`; keine aktuellen Kontexte/Antworten/CWDs. Er überschreibt
keine historischen Lauf-/Quell-/Revisionsfelder. Vorhandene historische Audits
haben oft keine `project_id`/`workflow_id`: diese Businessidentitäten bleiben
unbekannt. Ein Binding-/Workspacehash oder eine Session wird nicht zum Projekt
umbenannt. Quelle, Identität, unabhängige Wirkung, Gesamtabdeckung und unbeobachtete
Tunnelereignisse bleiben UNKNOWN; auch null Ereignisse ist kein Sicherheitsbeweis.

### Grenzen und Fortsetzung

`limit` zählt untersuchte Auditzeilen (1–500), plus eine begrenzte Vorschauzeile
zur Fortsetzungserkennung; nicht ausschließlich projizierte
Ereignisse. Maximal4096Byte je JSONL-Record, 65536Byte Ereignisdaten je Seite;
64 Diagnosen und16 aktuelle Korrelationen, weitere Diagnosen/Bezüge sind begrenzt
bzw. als ausgelassen erkennbar. Audits/Preflights werden bis16KiB aufgenommen;
größere/ungültige Records werden mit stabiler Diagnose übersprungen. Kein
unbegrenzter Log-/Dateiinhaltsexport. SQL-Wartezeit0.2s; SQLite-VM-Fortschrittsprüfung
nach2s. Das ist kein harter Abbruch blockierter Betriebssystem-/Dateisystemaufrufe.

`through_seq` friert den beim ersten Aufruf vorhandenen eigenen Auswahlumfang ein.
Für Folgeseiten **denselben** Wert und `next_cursor` übergeben. Währenddessen neu
hinzukommende Audits werden erst in einer neuen Auswahl ohne `through_seq`
gelesen. Jede untersuchte/übersprungene Zeile bewegt den Cursor, selbst ohne
projizierbares Ereignis; Bytegrenze lässt die noch nicht ausgegebene Zeile für die
nächste Seite liegen. `has_more` bezieht sich auf tatsächlich weitere ausgewählte
Zeilen, nicht nur eine größere numerische Grenzsequenz; eine Grenze innerhalb
einer gefilterten Lücke führt nicht zum leeren Endloslauf. Kein automatischer
Arbeitsstart oder Schreib-Replay.
Aufnahmegrenze/unklare Quelle ist keine Erlaubnis, den ursprünglichen Auftrag
neu auszuführen. Die vorhandene Quellaufbewahrung bleibt erhalten; keine
Rotation/Löschung oder wachsende zweite Exportdatenbank wird angelegt. Der
Betreiber entscheidet über ausdrücklich gespeicherte Metadatenseiten.

### Lokaler Bedienweg

Vorhandene Python-Umgebung/Installation verwenden, kein gesundes Profil neu
aufsetzen. Vom gepinnten Projektquellstand aus (Platzhalter selbst ersetzen):

```sh
PYTHONPATH=src python scripts/export_workflow_observations.py \
  --config /existing/private/config.toml --principal existing-owner \
  --task-id selected-owned-task --limit 100 > selected-page.jsonl
```

Nur begrenzte Ereignis-JSONL auf stdout. Cursor/Grenzen/Diagnosecodes auf stderr,
keine Exception-/Konfigurationspfade oder Geheimnisse. `--format json` liefert
stattdessen den begrenzten Gesamtblick mit Provenance/Korrelationen; dieser ist
**kein** JSONL-Eingangssegment. Folgeseite etwa mit `--cursor NEXT --through-seq
SNAPSHOT`. Ausgabe nur bewusst privat speichern. Vorhandener AA-Leser:

```sh
agent-authority workflow-inspect --input /selected/segment-directory \
  --source-tool kirabridge --source-id SOURCE_ID --format json
```

AA kann wegen ursprünglicher Filter-/Hashkettenlücken Exit2/UNKNOWN ausgeben;
das ist korrekt und keine Berechtigung zum Wiederholen einer Arbeit. Hier ist
kein neuer Hintergrunddienst, MCP-Befehl, Gesprächspush oder Sprachchat-Rückkanal
freigeschaltet. Root verdrahtet einen geeigneten authentifizierten Leseweg später
separat. Keine Produktionsdaten für die beigefügte Teilprüfung verwendet.

## English

This additive source reader exports selected existing Bridge audit metadata into
the unchanged `agent-authority-workflow-event-v1` contract. It creates no Bridge,
Store, migration, task, grant, queue, emitter, transport, agent process, stop,
background service or runtime/configuration change. KiraBridge remains private.

The authenticated facade requires existing `task.read`; future MCP wiring must
supply principal from its authenticated transport. The standalone source script
uses a trusted local operator's existing configuration/identity and does not
claim remote authentication. Every selected task (1–16) must belong to that exact
principal; foreign/missing tasks return not_found. State must be existing,
regular, no-symlink and owner-private. Read-only SQLite URI, query_only and a read
snapshot are used; owner/capability/missing-state errors never create/fix anything.

Only whitelisted IDs, revisions, hashes and known historical statuses are
projected. No arguments, results, errors, raw evidence, prompts, file contents,
paths, credentials or environment/configuration dumps. Audit sequence/hash-based
IDs stay stable across rereads/restarts; original filtered sequence gaps are not
renumbered away. Hashes do not authenticate a producer. Current task state and
current runtime never replace historical facts. Task preflight metadata must
precede the event and its local record hash must match; otherwise execution
runtime stays unknown. Only minimized fingerprint fields leave the reader.

Current handoff correlations are visibly separate from historical audit evidence.
Original and Bridge task IDs, revisions, run/session and different hash scopes
remain separate. Existing missing project/workflow identity stays unknown; a
workspace/binding hash does not establish a business project. Claimed answer
before delivery, generic file task completion, agent turn completion, return
arrival, review and project acceptance are not conflated. No artifact or actual
effect proof is fabricated. Overall activity, identity and external tunnel
lifecycle remain unknown even with no findings.

Bounds: 500 examined audit rows plus one bounded lookahead,16 owned tasks,4KiB per event,64KiB event bytes per
page,64 displayed diagnostics and16 current correlations; oversized/invalid input
is diagnosed with advancing cursor. Metadata input is bounded to16KiB/record.
Existing source audit retention is untouched; no second accumulating store.
SQLite wait is0.2s with a2s VM progress check, not a hard OS-I/O deadline. Reuse
through_seq plus next_cursor for a stable selected snapshot; later appends wait
for a new snapshot. has_more means an actual further selected row; a numeric
boundary inside a filtered gap never causes empty endless pages. Connection/read
failures never retry an uncertain write.

The command above prints data-only JSONL to stdout and minimized paging/error
codes to stderr. --format json adds provenance/correlation query metadata and is
not itself an AA JSONL segment. No mandatory private AA installation or new CI
token; a fixed-source local compatibility probe is optional and evidenced. No
new installed CLI/MCP operation, voice push or runtime activation is included.
Only isolated synthetic existing-schema data was used for actual subprocess→AA
reader acceptance; no production workflow or provider is exercised.
