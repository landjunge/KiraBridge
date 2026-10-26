# Queue management / Warteschlangenverwaltung · unreleased repair

**Development after RC16, not part of the RC16 draft artifacts. Production RC14
is unchanged. These tools require the reviewed queue-aware code.**

## Deutsch

Die Live-Diagnose zu `dc52c315-b9d5-48c5-8de6-3fdf69970b9b` zeigt `queued`,
keine Zustellung/Quittung und `terminal_input_attempted=false`. Der reservierende
Handoff `channel-dae0da0ab69449999007d02ef3c137d5` vom 21.10. hat dagegen einen
Eingabeversuch und anschließend `unknown / session_transport_unavailable`.
Ein interner `message.delivered`-Beleg beweist keine Terminalzustellung. Es gibt
keinen Beleg, dass der neue Bibliotheksauftrag ausgeführt wurde. Nicht neu senden.
Details ohne Nachrichteninhalte: [Live-Diagnose](evidence/queue-live-diagnosis-20261024.json).

### Werkzeuge und Status

- `queue_catalog`: alle in diesem Bridge-Store für die authentifizierte Identität
  lesbaren Queue-Familien und Unterqueues samt aktivem Zähler und Snapshot-Revision.
- `queue_entries(queue_id, after, limit, active_only)`: paginierte Übersicht mit
  Position innerhalb der berechtigten Ansicht, Ziel, Erstellzeit, Zustand,
  Zustellaktivität, Revision und Hinweis auf den vollständigen Inhalt. Maximal 100
  Einträge pro Seite; mit `next_cursor` fortsetzen, solange `has_more` gilt.
- `queue_entry(queue_id, item_id, content_offset, max_chars, expected_revision)`:
  vollständiger Inhalt/Argumente und gespeicherte Fehler-/Zustell-/Ausführungsbelege
  als verlustfreie JSON-Abschnitte. `detail_json_chunk` zusammenfügen, Offset jeweils
  aus `next_content_offset`, Revision nach der ersten Seite festhalten. Bei
  `has_more_content=false` JSON dekodieren und UTF-8-SHA-256 prüfen. Kein stilles
  Abschneiden langer Inhalte. Maximal 16.384 Unicode-Zeichen pro Abschnitt.
- `queue_control`: exakter Task mit `queue_id`, `action`, `item_id` (bei `clear`
  leer), `revision` und `reason`; eigene Task-ID und Idempotenzschlüssel erforderlich.
  Bestehende `task.cancel`- und quellbezogene Rechte bleiben notwendig. Manuelle
  Policies erfordern weiterhin eine exakt genehmigte Aufgabe; keine neuen Grants.
- `queue_stop`: eigener expliziter `process.terminate`-Task für einen bereits
  verwalteten eigenen Prozess, niemals ein beliebiger PID-Kill. Stop-Task und
  Originaltask prüfen: erst ein tatsächlicher Exitcode belegt Prozessende. Ein
  Antrag oder `termination_requested` allein genügt nicht. Für verwaltete Workflows
  bleibt der eigenständige, revisionsgebundene `workflow.stop`-Ablauf zuständig.

Queue-Familien: `tasks` (Unterqueues `normal`, `read`, `stop`),
`messages` (je Empfänger), `handoffs` (je Ziel), `completions` (je Rückkanal),
`team-work`, `team-messages`, historische `voice-buffers`, `session-input`.
Team-Leser dürfen dadurch keine fremde Arbeit stornieren. Inhaltslesen wird weder
als Zustellung noch als Empfangsquittung verbucht. Separate Provider-Queues können
nicht aus diesem Store behauptet werden. Der optionale Chat-Events-Adapter bietet
separat `event_queue_entries`/`event_queue_control` für seine eigene authentifizierte
Webhook-Outbox; Callback-Secrets, URLs und Receipt-Tokens werden dort nicht ausgegeben.

### Sicherer Ablauf

1. Queue und Einträge einschließlich Historie prüfen. `queued` ist keine Ausführung.
2. Einzelnen nie begonnenen Eintrag mit dessen Revision `cancel` aus der aktiven
   Zustellung nehmen. Der unveränderte Nachrichteninhalt und Audit bleiben erhalten.
3. `clear` nur mit der aktuellen Revision der gewählten Queue. Neue/geänderte
   Einträge verursachen `queue_changed`; sie werden nicht unbemerkt entfernt. Der
   ausführende Kontrolltask selbst wird bei seiner eigenen Queue-Prüfung ausgenommen.
   Laufende/ungeklärte Einträge werden einzeln mit `execution_unresolved` gemeldet;
   `fully_removed=false` ist kein Erfolg für ein vollständiges Leeren. Kontrollläufe
   sind auf 10.000 Einträge begrenzt; größere Bestände einzeln/paginiert verwalten.
4. `restore` ist nur für nie begonnene, zurückgehaltene Zustellungen und nur durch
   die zurücknehmende Identität erlaubt. Zugestellte/beanspruchte/ungeklärte Arbeit
   wird nicht erneut geschickt. Erledigte/fehlgeschlagene Ergebnisse bleiben unverändert.
5. `unknown` zuerst abgleichen. `retire` für einen unklaren sichtbaren Handoff
   benötigt eine **frische positive Bereitschaftsprüfung des zugewiesenen Ziels**.
   Es entfernt nur die Zustellreservierung und verknüpfte Inbox-Zustellung, lässt
   Ausführung/Ergebnis ausdrücklich `unknown`, sendet nichts und stoppt keinen Agenten.
   Beschäftigte, geänderte oder unbestätigte Fenster lassen sich damit nicht umgehen.
   Späte Quittungen reaktivieren die aufgehobene Reservierung nicht.

Jede Änderung erhält Historie/Audit. Zurückgehaltene Einträge zählen nicht weiter
als aktive Pending-Kapazität und werden weder durch Receiver-Claim noch durch Inbox-
Abruf erneut zugestellt. Andere Empfänger bleiben unabhängig. `queue.control` nutzt
saturationsgeschützte Stop-Kapazität; das bestehende direkte `task_cancel` bleibt
für eigene noch nicht angenommene Tasks verfügbar.

### Migration und Rückweg

Additive Tabelle `queue_holds`, keine entfernten oder überschriebenen Quelldatensätze.
Holds und Audit überleben Neustart. Ein alter Runtime würde Holds ignorieren und
könnte zurückgenommene Nachrichten erneut zustellen. **Deshalb blockiert der Installer
Aktivierung/Rollback auf eine Runtime ohne Queue-Unterstützung, solange Holds bestehen,
bevor er den Dienst stoppt.** Keine Datenbank zurücksetzen, Holds löschen oder alte
Installer verwenden, um die Sperre zu umgehen. Der Rückweg ist die geprüfte
Wiederfreigabe nie begonnener eigener Zustellungen oder eine Queue-kompatible Runtime;
für ungeklärte Vorgänge bleibt der Abgleich erforderlich. Ein abgewiesenes unsicheres
Downgrade wird nicht als erfolgreicher Rollback bezeichnet.

## English

This unreleased repair separates active delivery from execution outcome. Inventory
covers every authorized queue family in the Bridge store; provider queues are not
invented. Full entry content is paginated losslessly with revision/SHA-256 checks.
Cancel/clear retain immutable source records and audit. Exact revisions prevent races;
foreign or running/unknown work is never falsely stopped. Existing capabilities and
manual exact-task approvals remain. Only the withdrawing identity may restore a
never-started delivery; old results and uncertain executions are not replayed.

Uncertain visible handoffs can retire their delivery reservation only after fresh
positive assigned-target readiness. Outcome stays unknown and no process is killed.
An owned managed-process stop uses the existing termination operation and requires
actual exit evidence. Optional webhook delivery management is separately scoped and
never exposes signing secrets or claims a ChatGPT UI receipt.

Holds survive restart and free pending capacity. Old runtimes ignore them: the installer
therefore refuses unsafe activation/downgrade **before stopping the current service**.
Use a queue-aware runtime or the verified safe restoration flow; never delete holds or
restore an old database to force rollback. Production RC14 remains unchanged pending
required review/checks and explicit installation acceptance/authorization.

## Unknown-Eintrag zurücknehmen / Withdraw an unknown entry

`queue.control` unterstützt zusätzlich die Einzelaktion `withdraw`. Zulässig sind
nur eigene beziehungsweise nach bestehenden Rechten zugängliche `unknown`-Einträge
in `tasks`, `messages` und `handoffs`. Benötigt werden die frisch gelesene
Eintragsrevision und ausdrücklich `acknowledge_execution_unknown: true`; diese
Bestätigung ersetzt keine bestehenden Rechte oder notwendigen Freigaben.
Andere Zustände, insbesondere laufende oder nur wartende Aufträge, werden verweigert.
Für mehrere Einträge jede ausgewählte ID separat mit ihrer Revision bearbeiten;
`clear` bekommt keine neue Bedeutung. Nach einem Versionswechsel Revisionen neu lesen.

Die aktive Queueansicht zeigt danach `delivery_active: false` und Metadaten unter
`withdrawal`. `state` und `execution_state` bleiben `unknown`; die Historie ist über
`queue_entry` und `queue_entries(active_only=false)` weiterhin lesbar. Die Antwort
meldet ausdrücklich `execution_stop_claimed: false` und
`execution_reservation_released: false`. Dies beendet weder Prozess noch Auftrag,
quittiert keine Nachricht und erlaubt kein Wiederholen. Unabhängige wartende
Nachrichten werden nicht storniert. Receiver-/Inbox-Protokolle bleiben unverändert.
Ein unbekannter Handoff kann weiterhin die Ausführungsreservierung halten:
`withdraw` umgeht diese Sicherheitssperre nicht. `retire` bleibt eine getrennte
Aktion mit eigener frischer positiver Bereitschaftsprüfung.

Die additive Tabelle `queue_withdrawals` enthält nur Queue/ID, Akteur, Zeit und
SHA-256 des Grundes. Ein neuer Audit-Eintrag hält die Rücknahme fest; Quelldatensätze,
Evidenz, Nachrichten-/Handoff-/Taskhistorie und `queue_holds` werden nicht verändert.
Ein erneuter Aufruf mit aktueller Revision verändert eine vorhandene Rücknahme nicht.
Alte Runtime-Versionen ignorieren diese Tabelle: Die Ansicht kann dort erneut
auftauchen, aber der ursprüngliche Status bleibt `unknown`, nicht `queued` oder
`cancelled`. Vorhandene Hold-/Rollback-Sicherheitsprüfungen bleiben bestehen.

**English:** The individual `withdraw` action requires an observed entry revision,
existing owner/capability/approval checks, and explicit
`acknowledge_execution_unknown: true`. Only unknown tasks, messages and handoffs
are eligible. It hides the active queue view while retaining the unknown execution
state, original evidence and complete history. It never stops execution, releases a
handoff reservation, acknowledges a message, replays work or bulk-cancels pending
messages. `queue_withdrawals` is separate from `queue_holds`; older runtimes may show
the entry again but still see its original unknown state and execution reservation.

### Reservierung eines nachweislich verschwundenen Originalziels aufgeben

`retire` ohne zusätzliche Bestätigung behält seine bisherige frische Idle-Prüfung
am zugewiesenen Ziel. `retire` mit `acknowledge_execution_unknown: true` wählt
stattdessen ausdrücklich den strengeren Abwesenheitsnachweis der unveränderlichen
Originalbindung im gespeicherten `unknown`-Handoff: vollständige frische native
Terminalfenster-Inventur ohne ursprüngliche Window-ID sowie zwei erfolgreiche globale
PID-Inventuren vor und nach dieser Inventur, in denen ursprüngliche Shell- und
Agent-PID beide fehlen. Ein noch existierender oder wiederverwendeter PID, ein
noch vorhandenes Fenster, mehrdeutige Bindung oder Beobachtungs-/Berechtigungsfehler
verweigert die Rücknahme. Ein bloß veralteter Katalog oder ein anderes aktuelles
Fenster genügt nicht; tmux ist für diesen nativen Nachweis kein Ersatz.

Der vorhandene Handoff und dessen Originalnachricht erhalten Zustell-Holds; ihre
Ausführungszustände bleiben unverändert. Der Auditbeleg nennt
`retirement_basis: original_target_gone` und Beobachtungszeiten, ausdrücklich keinen
Idle-Nachweis. Die Originalreservierung wird damit aufgegeben, ohne irgendeinen
Prozess zu beenden, Terminaleingabe zu senden oder einen Auftrag erneut auszuführen.
Bestehende Eigentümer-, Capability-, Freigabe- und Revisionsprüfungen gelten weiter;
nach den Beobachtungen wird die gespeicherte Revision erneut geprüft.

**English:** Explicit `retire` with `acknowledge_execution_unknown: true` selects
proof that the persisted original native window and both original PIDs are gone.
Complete native window inventory and two successful global PID snapshots are
required; reused/existing PIDs, ambiguity and observation/permission errors refuse.
It places holds on only the original handoff/message and records an absence-based
audit, preserving unknown execution. The original fresh-idle retire path remains
unchanged when this flag is absent. Neither path sends terminal input or kills an agent.
