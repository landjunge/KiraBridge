# Wissensführung aus dem Gespräch / Knowledge from conversation

Der Adapter ergänzt den bestehenden Verwaltungsweg, keine zweite Wissensdatenbank.
Fester ThreadDesk-Quellpin:6c7d578a1edb612d0e8e6d99faa2953888d69bfb.
Die bisherigen Lese-/Verwaltungsaktionen und bereits ausgestellten Übergaben bleiben
erhalten. Neue Übergaben enthalten begrenzten revisionsgebundenen Wissenskontext.

## Bedienung und Grenzen

Die eigene Capability threaddesk.knowledge erlaubt ausschließlich record, supersede,
resolve_question und save_reentry am fest konfigurierten Peer. Jede Änderung benötigt
operation_id, exakte Thread-ID id, expected_revision, action und data. Derselbe
Operationsbezeichner mit geändertem Inhalt kollidiert; unbekannte Schreibausgänge
werden anhand der ursprünglichen Task und thread_operation_status gelesen.

```json
{"operation":"threaddesk.knowledge","arguments":{"operation_id":"decision-1","action":"record","id":"EXACT_THREAD_ID","expected_revision":1,"data":{"kind":"decision","title":"Konkrete Entscheidung","status":"confirmed","source_ref":"operator-decision","source_revision":"decision-1"}}}
```

Für supersede zusätzlich node_id/expected_node_revision/title, für resolve_question
node_id/expected_node_revision/text und für save_reentry summary/next_step verwenden.
Jede Aktion benötigt source_ref und source_revision. Bestätigte Entscheidungen
werden mit Vorgängerbezug ersetzt; Fragen behalten ihre ursprüngliche Formulierung.
Alte/fremde Knotenrevisionen werden abgewiesen. Der feste lokale Betreiberpeer ist
kein öffentlicher Mehrmandantendienst; normale Botkonten erhalten diese Rechte nicht.

Lesen: threaddesk.read mit tool=get_reentry und arguments={"id":"EXACT_THREAD_ID"}.
Die vorhandenen Listen trennen aktuelle, verworfene und ersetzte Beschlüsse sowie
offene/beantwortete Fragen. source_verification bleibt referenced_unverified oder
unknown; eine Referenz ist kein externer Funktionsnachweis. Kein Lese-/Wissensschritt
startet Agenten oder führt Dateien aus. Fehlende Peeroperation meldet threaddesk_version.

Gezielte Prüfung: echter gepinnter stdio-Peer, alle vier Aktionen, Wiederverbindung,
unveränderte Originalfrage, nachvollziehbarer Ersatz, Duplikat, geänderter Inhalt,
veraltete Revision, fremder Knoten und verweigerte Capability. Keine Modellaufrufe.
Der Runtime-/App-Nachweis wird getrennt ergänzt; Quelltests sind keine Nutzerabnahme.

## Tatsächliche App-Rundreise

Neun tatsächliche App-Tasks decken gemeinsam Bild-/Metadatenabruf und einen klar
synthetischen Wissensthread ab. Thread67f9698601df wurde angelegt; bestätigter
Beschluss gespeichert und nachvollziehbar ersetzt; Frage gespeichert und separat
beantwortet; Wiedereinstieg gespeichert und über get_reentry gelesen. Revision6
enthält genau den aktuellen sowie den ersetzten Beschluss und die unveränderte
Originalfrage samt Antwort. Quellenstatus bleibt referenced_unverified. Kein neuer
Agentenlauf durch Wissensverwaltung. Der synthetische Thread bleibt privat erhalten.
[Tatsächliche Quittungen](evidence/workflow-reads-chatgpt-20261018.json).

## English

Use the existing task_request/task_get path. The separate threaddesk.knowledge
capability exposes four declared revision-bound mutations on the fixed configured
ThreadDesk peer. Stable operation IDs are namespaced per principal and profile;
payload conflicts, stale revisions and foreign thread nodes fail. Superseding retains
the old decision; answering retains the original question. get_reentry is an
additional threaddesk.read action, not a new store or execution path.

Source references remain unverified. Stored context grants no tool rights and starts
no agent. Unknown writes are never automatically repeated. Targeted real-peer tests
cover all actions, replay/conflict/staleness/scope, reconnect and capability denial.
Runtime delivery, actual connected-App checks and overall user acceptance are separate.
The subsequent connected-App roundtrip exercised all four mutations and get_reentry
on one synthetic operator thread, retaining the old decision and original question.
It is loaded in the local0.5.2 backport df995f6; this is not overall user acceptance.
