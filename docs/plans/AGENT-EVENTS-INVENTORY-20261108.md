# BP-AA-02 Agentenereignismodell: Inventar und Schemaentwurf v2

Stand 08.11.2026, Lane L5, Phase 1 (nur lesen) plus Entwurf.
Quellpins: KiraBridge `origin/main` 89595eb, ThreadDesk `origin/main`,
agent-authority-lab `origin/master`. Haupt-Worktrees nicht berührt.

**Grenzen.** Agent Authority bleibt strikt lesend (G9.9-E4). Dieses Dokument
und das Schema beschreiben nur Daten. Es gibt keinen neuen Sender, keinen
Store und keine Freigabe. Ein schemagültiges Ereignis ist weder
authentifiziert noch erlaubt. Was nicht gelesen werden konnte, steht als
UNKNOWN da.

## 1. Kernbefund in sieben Sätzen

1. Es gibt heute **zwei** Ereignisformate, nicht eines: den Authority Event
   Envelope v1 (ThreadDesk G0, gehasht, fünf Produzenten) und das
   Lab-Workflowformat `agent-authority-workflow-event-v1` (flach, sechs Tools).
2. KiraBridge sendet **keinen** Envelope v1. KiraBridge hat nur einen
   Lesehelfer `observation_export.py`, der Audit-Zeilen auf das
   Workflowformat projiziert. Er läuft nur auf Abruf.
3. ThreadDesk erzeugt **keine** Envelope-Ereignisse (`graph.imported` und
   `incident.opened` stehen im Katalog, es gibt keinen Emitter). Es validiert
   und importiert nur (`authority.import`, ohne Persistenz).
4. Das Lab erzeugt Envelope v1 nur für eigene Entscheidungen
   (`authority_emit.py`), also simulierte Lab-Agenten, keine echte Kette.
5. Der Envelope v1 kennt weder Auftrag, Delegation noch Ergebnis als Struktur.
   `source_tool` kennt `kirabridge` nicht. Das Schema ist geschlossen.
6. Zeit und Reihenfolge sind quellenabhängig (Sekunden UTC, Float-Sekunden,
   ISO-String). Eine gemeinsame Ordnung über Quellen fehlt: UNKNOWN.
7. Die Strecke Handy → ThreadDesk-Server → KiraBridge-Server ist ohne
   gemeinsame ID nicht korrelierbar. Nur `original_task_id`/`handoff_id`
   verbinden TD und KB, und nur nach einem Handoff.

## 2. Inventar je Quelle

### 2.1 agent-authority-lab

| Aspekt | Befund |
|---|---|
| Erzeuger | `lab/authority_emit.py` `emit_decision()`: je Entscheidung `authority.requested` plus `authority.allowed` oder `authority.denied`. Fail-open, schreibt nie in eine ThreadDesk-DB. |
| Persistenz | JSONL `data/authority-events.jsonl` (oder `LAB_AUTHORITY_EVENTS_PATH`). Hashkette `previous_event_hash` → `event_hash` (SHA-256 über kanonisches JSON). Unter pytest aus. |
| Felder | `schema_version "1"`, `event_id`, `timestamp` (Sekunden, `Z`), `trace_id`=`workflow_id`, `span_id`, `project_id`, `source_tool`, `event_type`, `actor{agent_id, role="lab-agent"}`, `action`, `resource`, `decision`, `reason_code`, `data_labels`. |
| Leser | `agent_authority/workflow.py` (Format `agent-authority-workflow-event-v1`, max 4096 B je Zeile, max 10 000 Zeilen, 64 Segmente), `workflow_rules.py` (Regeln über Behauptungen), `whiteboard.py`/`observations.py` (Whiteboard-Dateien als `Entry`). |
| Eigenheit | Der Leser setzt je Behauptung fest `assertion_basis=producer_report_only`, `identity_authenticated=false`, `effect_verified=false`. Deckung: `coverage_of_all_activity = "UNBEKANNT"`. |
| Event-Typen Leser | 47 Typen (`capability.*`, `work.*`, `task.*`, `handoff.*`, `return.*`, `budget.*`, `control.*`, `dispatch.*`, `access.*`, `job.*`, `design.*`, `request.blocked` u. a.). |
| Bindungen Leser | 23 Referenzfelder, u. a. `project_id`, `workflow_id`, `thread_id`, `handoff_id`, `original_task_id`, `bridge_task_id`, `run_id`, `attempt_id`, `return_id`, `session_id`, `principal_ref`, `operator_scope`, `actor_claim`, `gate_event_id`. Plus Revisionen, `request_hash`, `source_hash`, Budget in Mikro-USD, `stop_state`, `reported_status`. |

Beispielschema (synthetisch, Envelope v1, Lab-Erzeuger):

```json
{"schema_version":"1","event_id":"<16hex>","timestamp":"2026-11-08T10:01:00Z",
 "trace_id":"wf-x","span_id":"<8hex>","workflow_id":"wf-x","project_id":"agent-authority-lab",
 "source_tool":"agent-authority-lab","event_type":"authority.denied",
 "actor":{"agent_id":"a1","role":"lab-agent"},"action":"external.send","resource":"res:x",
 "decision":"DENY","reason_code":"CODE","previous_event_hash":null,"data_labels":["PUBLIC"],
 "event_hash":"<sha256>"}
```

### 2.2 ThreadDesk

| Aspekt | Befund |
|---|---|
| Envelope-Spezifikation | `docs/authority/AUTHORITY_EVENT.md`, `authority-event-v1.schema.json`, Validator `core/authority_event.py`. Fünf Produzenten vorgesehen (gnom-hub-v1, Lab, TollGate, 4AllPass, ThreadDesk). |
| Import | `services/commands/authority.py` `authority.import`: prüft Schema und Hashes, baut ein inertes Graphabbild, **persistiert nichts**, vergibt keine Rechte. |
| Whiteboard-Eintrag | `core/models.py` `WhiteboardEntry`, Tabelle `whiteboard_entries` (SQLite) bzw. JSON-Log je Thread. Append-only, Korrekturen als neue Einträge. |
| Felder Eintrag | `id`, `thread_id`, `created_at` (ISO, UTC), `ordinal`, `actor`, `actor_type`, `entry_type` (note, task, claimed, progress, result, decision, problem, question, system), `content` (Freitext, nicht übernehmen), `task_id`, `handoff_id`, `run_id`, `external_key`, `actor_id`, `instance_id`, `room_id`, `content_hash`, `metadata`. |
| Rückgabe | `whiteboard.append_from_return`: `return_id`, `handoff_revision`, `worker`, `files`, `pull_request`, `test_results`, `open_issues`, `delivery_status`. |
| Übergabe | Tabelle `issued_handoffs` (`id`, `payload`): Revision, Inhaltsdigest, Laufbindung. |
| Graphereignis | `graph_events` (`id`, `name`, `entity_id`, `entity_type`, `revision`, `occurred_at`, `payload`), Namen wie `node.created`, `relation.created`, `thread.updated`. Das sind Änderungsereignisse des Wissensgraphen, keine Agentenereignisse. |
| Server | Whiteboard-POST setzt den Akteur aus `request.state.user`. Gespeichertes `READY` ist kein KiraBridge-Recht (Remote-Vertrag 1). |
| Grenze | `whiteboard.state=open/closed` ist gespeicherter Zustand (`visibility_evidence=saved_state_only`), kein Fensterbeleg. |

Beispiel (synthetisch, Whiteboard-Eintrag):

```json
{"id":"<12hex>","thread_id":"<12hex>","created_at":"2026-11-08T10:00:00+00:00","ordinal":7,
 "actor":"claude","actor_type":"claude","entry_type":"claimed","task_id":"thread:task",
 "handoff_id":"hnd-1","run_id":"run-1","content_hash":"<sha256>","content":"<Freitext>","metadata":{}}
```

### 2.3 KiraBridge

| Aspekt | Befund |
|---|---|
| Auditlog | Tabelle `audit` in `bridge.sqlite3` (`task_manager/store.py`): `seq`, `at` (Float-Sekunden), `kind`, `principal`, `task_id`, `metadata` (JSON), `previous`, `hash`. Hashkette über `{at, kind, principal, task_id, metadata, previous}`. Append-only. |
| Audit-Arten | `task.queued/requested/accepted/approved/auto_approved/transition/progress/cancel/preflight`, `approval.granted`, `handoff.issue/claimed/bound/agent_started/question/turn_ended/delivered/decided/receipt_observed/reconcile/rejected`, `workflow.stop`, `diagnostic.*`. |
| Task | Tabelle `tasks`: `state`, `created/updated/accepted/started/finished` (Float), `receipt`, `evidence`, `result`, `error`, `agent`, `parent_id`, `attempt`, `lease_*`. `events(seq, task_id, at, state, evidence)` je Zustandswechsel. |
| Freigabe | Tabelle `approvals` (nur `token_hash`, `request_hash`, `expires`, `used`). Principal aus Authentifizierung (SecurityManager). |
| Nachrichten | `messages`, `message_jobs`, `message_events` mit `delivered`, `receipt`, `acknowledged`, `run_id`, `evidence`. |
| Projektion | `observation_export.py` `export_workflow_observations()`: bis 16 Tasks, 500 Zeilen, setzt `source_tool="kirabridge"`, `ordinal`=`audit.seq`, `event_hash`, `previous_event_hash`, `principal_ref`=Digest, getrennte `original_task_id`/`bridge_task_id`, `stop_state`, `reported_status`. Verwirft ungültige Hashes. Kein Sender. |
| Zeitmeta | `mcp_gateway/timing.py`: Schlüssel `de.netzwerkpunkt.kirabridge/timing`, `trace_id` (uuid), je Schicht `handler_started_unix_ns`, `result_ready_unix_ns`, `duration_ms`. Nur im MCP-Ergebnis, nicht gespeichert. Keine Subtraktion über Uhren. |
| Zeiten Task | `autonext/timings.py`: Dauern nur aus aufgezeichneten Endpunkten, sonst `None`. |
| Diagnose | `diagnostics.py`: `diagnostic.connection` im Audit mit `connection_id`, `phase`, `error_code`, `notification_receipt`, `external_tunnel`. `task_report()` liefert Zustand, `error_code`, Ausführungsvorprüfung. |
| Remote-Vertrag | `docs/contracts/remote-task.v1.schema.json`: `intent`, `execution_binding`, `execution_receipt` (`event_seq`, `state`, `binding{task_id, request_sha256, device_ref, envelope_sha256}`), `acceptance_receipt`, `display_receipt`. Nur Entwurf, kein Endpoint. |
| chat-events | `docs/CHATGPT-EVENTS-*.md`, `examples/chat-events/`: Abschlussbenachrichtigung an ChatGPT. Payload-Quittung beweist keine Anzeige im Chat (`chat_delivery: NOT_VERIFIED`). Kein Agentenereignis. |
| Envelope v1 | Im Quellcode kein Emitter (`authority_emit` nicht vorhanden). |

Beispiel (synthetisch, Audit-Zeile):

```json
{"seq":42,"at":1794045630.2,"kind":"task.transition","principal":"<principal>","task_id":"team-work-1",
 "metadata":{"to":"completed","run_id":"run-1","original_task_id":"thread:task"},
 "previous":"<sha256>","hash":"<sha256>"}
```

## 3. Feldabdeckung

J = vorhanden und strukturiert, T = teilweise/indirekt, N = nein, U = UNKNOWN
(nicht prüfbar oder nicht belegt).

| Dimension | Lab-Envelope | TD Whiteboard | TD Übergabe/Rückgabe | KB Audit/Task | KB Timing/Diagnose |
|---|---|---|---|---|---|
| Akteur | T (`agent_id`, Rolle fest) | T (`actor`, `actor_type`, `actor_id`; Server setzt Nutzer) | T (`worker`) | T (`principal`, `agent`; Principal authentifiziert) | N |
| Auftrag | T (nur `workflow_id`) | J (`task_id`, `handoff_id`, `run_id`) | J (Handoff, Revision, `return_id`) | J (`task_id`, `parent_id`, `attempt`, `metadata`-Bindungen) | T (`task_id` in Diagnose) |
| Delegation | N | T (Eintrag `task`/`claimed`) | J (Handoff ausgegeben, gebunden) | T (`handoff.*`, Teamdelegation `team-`+work_id) | N |
| Berechtigung | J (`decision`, `reason_code`; nur Lab) | N | N | T (`approval.granted`, `task.auto_approved`, Hash statt Token) | N |
| Zeitstempel | T (Sekunden, UTC) | J (ISO, `ordinal`) | T (Revision) | J (Float-Sekunden, `seq`) | T (Ns, nur lokal je Schicht) |
| Ergebnis | T (ALLOW/DENY) | T (`result`, `delivery_status`) | T (`test_results`, PR) | J (`state`, `result`, `error`) | T (`error_code`) |
| Evidenz | J (Hashkette lokal) | T (`content_hash`) | T (Digest) | J (Hashkette, `receipt`, `evidence`) | T (`notification_receipt`) |

Ausdrückliche Lücken (UNKNOWN):

- **U1** Gemeinsame Kennung für die Strecke Handy → TD-Server → KB-Server. Es gibt keine End-zu-End-`trace_id`; `trace_id` im MCP-Timing ist nur lokal.
- **U2** Uhrenbezug. TD (ISO/UTC), KB (Unix-Float), Lab (Sekunden). Ob Server und Mac synchron sind, ist nicht belegt.
- **U3** Authentizität des Akteurs. Alle Quellen melden nur; Lab-Leser setzt `identity_authenticated=false`.
- **U4** Wirkung. `saved_state_only`, `delivered_unverified`, `turn_completed` belegen keine Ausführung oder Anzeige.
- **U5** Ereignisse, die niemand erfasst (Handy-Ebene, Agent-intern). Deckung unbekannt.
- **U6** Persistenter Sender. Weder KB noch TD sendet laufend an Agent Authority.
- **U7** Aufbewahrung, Datenschutz, Umfang für den Flugschreiber (Plan 9.6, offen).
- **U8** Mapping der Kosten (`TollGate`) auf Aufträge: nur über `consumer_id`, ungeprüft.

## 4. Abgleich mit Envelope v1

| Passt | Fehlt oder stört |
|---|---|
| Hashkette `previous_event_hash`/`event_hash`, deckt sich mit KB-Audit (`previous`/`hash`). | `source_tool` ohne `kirabridge`, `blockdesigner`. Schema geschlossen: KB-Projektion wird abgelehnt. |
| `trace_id`, `span_id`, `parent_span_id` tragen eine Kette. | Keine Strukturfelder für Auftrag (`task_id`, `handoff_id`, `run_id`, `original_task_id`/`bridge_task_id`). |
| `actor`, `action`, `resource`, `decision`, `reason_code`, `capability_id` | Keine Delegation (von, an). `delegation.created` ist Typ, ohne Felder. |
| Verbotene Schlüssel, `data_labels`, `result_ref`, `budget_ref` | Kein Ergebnisstatus, kein Fehlercode, keine Revisionen. |
| `schema_version` als Versionshaken | `event_type` als geschlossene Aufzählung (21): `task.*`, `handoff.*`, `return.*` fehlen, obwohl das Lab sie liest. |
|  | `timestamp` nur als String, keine Zeitquelle, keine Ordnungszahl. |
|  | Kein Ehrlichkeitsblock (`identity_authenticated`, `effect_verified`). |
|  | `event_hash` ist Pflicht; Whiteboard-Einträge haben keinen Ereignishash. |
|  | Kein Feld für die Kettenposition. |

## 5. Schemaentwurf v2

Datei: `docs/contracts/agent-event-v2.draft.schema.json` (Draft 2020-12,
nur dokumentlokal). Test: `tests/test_agent_event_v2_draft.py`.

Entwurfsregeln:

- **Abwärtskompatibel.** `schema_version "1"` gilt unverändert nach v1-Regeln
  (Pflichtfelder, 21 Typen, fünf Tools, kein v2-Block). Jedes v1-Ereignis
  bleibt gültig.
- **Obermenge.** `"2"` ergänzt Blöcke `task`, `delegation`, `permission`,
  `result`, `evidence`, `timing`, `chain`, `assertion`, `unknown_fields`.
  Alle Blöcke sind geschlossen. Pflicht in v2: `trace_id`, `evidence`,
  `assertion`.
- **Keine Geheimnisse.** Nur Referenzen und Digests. Klartext und Inhalte
  sind verboten (geschlossene Objekte). Prinzipal nur als Digest.
- **Ehrlich.** `assertion` verlangt `identity_authenticated` und
  `effect_verified` ausdrücklich. `unknown_fields` benennt Lücken, statt zu raten.
- **Offene Typen.** `event_type` ist ein Muster. Unbekannte Typen liest der
  Verbraucher als UNKNOWN.
- **Kein Zwang zum Hash.** In v2 ist `event_hash` optional;
  `evidence.basis` sagt, wie belegt wird.

### 5.1 Kettenposition

`chain.hop` ∈ `phone`, `threaddesk_server`, `kirabridge_server`, `mac_bridge`,
`agent`, `return` mit `hop_seq` 0 bis 5. Eine durchgehende `trace_id` muss
der erste Hop erzeugen und alle weiteren übernehmen (Entscheidung offen, E1).
Bis dahin korreliert nur `task.original_task_id`/`task.handoff_id`.

### 5.2 Mapping je Quelle

| v2-Feld | Lab (Envelope v1) | TD Whiteboard/Handoff | KB Audit/Task |
|---|---|---|---|
| `schema_version` | `"1"` unverändert | `"2"` | `"2"` |
| `event_id` | `event_id` | `wb-`+`id` (12hex) | `audit-<seq>-<hash>` (wie Export) |
| `timestamp` | `timestamp` | `created_at` | `at` → ISO UTC |
| `timing.clock` | `producer` | `server` | `device` |
| `trace_id` | `trace_id` (=`workflow_id`) | UNKNOWN, bis E1 entschieden | UNKNOWN, bis E1 (MCP-Timing `trace_id` nur lokal) |
| `source_tool` / `source_id` | `agent-authority-lab` | `threaddesk` / Serverinstanz | `kirabridge` / Bridge-Instanz |
| `event_type` | `authority.*` | `entry_type`: `task`→`handoff.created`, `claimed`→`task.accepted`, `progress`→`task.running`, `result`→`return.received`, `decision`→`return.reviewed`, `problem`→`task.failed`, `question`→`task.question` | `task.transition.to`→`task.*`, `handoff.*` (Tabelle in `observation_export.HANDOFF_TYPES`), `workflow.stop`→`control.*` |
| `actor.*` | `actor.agent_id`, `role` | `actor`→`actor_claim`, `actor_type`, `actor_id`→`agent_id`; Servernutzer→`principal_ref` | `principal`→`principal_ref` (Digest), `tasks.agent`→`agent_id` |
| `task.*` | `workflow_id` | `task_id`→`original_task_id`, `handoff_id`, `run_id`, `thread_id`, `handoff_revision`, `return_id` | `task_id`→`bridge_task_id`, `metadata.original_task_id`, `run_id`, `attempt`→`attempt_id`, `parent_id`→`parent_task_id`, `request_hash` |
| `delegation` | N | Handoff ausgegeben: von Nutzer, an Empfänger | `handoff.bound`, Team-Claim: von `original_task_id`, an `bridge_task_id` |
| `permission` | `decision`, `reason_code` | UNKNOWN (kein Recht) | `approval.granted`→`approval_ref`, `task.auto_approved`→`decided_by=policy` |
| `result` | `decision` | `delivery_status`, `test_results` als `result_ref` | `tasks.state`, `error.code`→`error_code`, `result` als `result_ref` |
| `evidence` | `basis=audit_hash_chain` (lokale JSONL) | `saved_state_only`, `content_hash`→`sha256`, `ordinal` | `audit_hash_chain`, `hash`→`sha256`, `seq`→`ordinal` |
| `assertion` | beide `false` | beide `false` | beide `false` |
| `chain.hop` | `agent` | `threaddesk_server` | `kirabridge_server` oder `mac_bridge`, `agent` |

### 5.3 Remote-Kette

| Hop | Quelle | Heute belegbar | Typische Lücke |
|---|---|---|---|
| 0 `phone` | App / TD-Client | UNKNOWN: kein Ereignis erfasst | Absender und Zeit auf dem Gerät |
| 1 `threaddesk_server` | TD-Whiteboard, Übergabe | `handoff.created`, `ordinal`, `content_hash` | Authentifizierung nur über Sitzung; kein Hash über Ereignis |
| 2 `kirabridge_server` | KB-Remoteprofil | Entwurf `intent`/`execution_receipt`; kein Endpoint | Hop noch nicht implementiert |
| 3 `mac_bridge` | KB-Audit | `task.accepted`, `handoff.bound`, `task.transition` | Gerätebindung nur als `device_ref` |
| 4 `agent` | KB-Audit, TD-Whiteboard | `handoff.agent_started`, `task.running` | Agent-interne Schritte UNKNOWN |
| 5 `return` | KB-Audit, TD-Rückgabe | `handoff.delivered`→`return.received`, `handoff.decided`→`return.reviewed` | `display_receipt` nicht nachweisbar |

## 6. Beispiele und Prüfung

Das Schema enthält drei synthetische Beispiele im Feld `examples`:

1. TD-Server, v2: `handoff.created` mit `saved_state_only`, Berechtigung UNKNOWN.
2. KB-Mac, v2: `task.completed` mit `audit_hash_chain`, Freigabe `ALLOW` durch Operator.
3. Lab, v1 unverändert: `authority.denied` mit berechnetem Hash (Kompatibilitätsbeleg).

`tests/test_agent_event_v2_draft.py` prüft: Schema wohlgeformt, alle Beispiele
gültig, v1 lehnt v2-Blöcke ab, verbotene Schlüssel (`token`, `secret`, `prompt`,
`api_key`) werden abgelehnt, `assertion` ist in v2 Pflicht. Verwendet den
vorhandenen `SchemaValidatorCache` ohne Netzzugriff.

## 7. Offene Entscheidungen

- **E1** Wer erzeugt die End-zu-End-`trace_id`? Vorschlag: TD-Server beim Handoff, KB übernimmt sie in `task.metadata`.
- **E2** Sender oder Abruf? Vorschlag: Abruf (Leser liest Exportdatei), wie G9.9-E4.
- **E3** Wird der KB-Export `observation_export.py` auf v2 gehoben oder bleibt er beim Workflowformat? Vorschlag: Mapping-Schicht im Leser, Export unverändert.
- **E4** Soll `event_hash` in v2 für TD-Einträge berechnet werden? Dann gleicher Kanon wie Lab (`sort_keys`, ASCII).
- **E5** Aufbewahrung und Datenschutz für den Flugschreiber (Plan 9.6).
- **E6** Aufnahme von `blockdesigner` und `kirabridge` in das v1-Schema in ThreadDesk: nur, wenn ThreadDesk den Import erweitern soll.

## 8. Nicht Teil dieser Phase

Kein Sender, keine Änderung an ThreadDesk, Lab oder Observer, keine Migration,
kein Live-Lauf. Der Bericht zu einem echten BP-REMOTE-03-Lauf (BP-AA-01) bleibt
offen.
