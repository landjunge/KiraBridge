# Big Plan: vorhandene Aufgaben selbstständig fortsetzen

Auftrag `BP-COORD-CONTINUATION-20261106`, Nutzerweisung vom 6. November 2026.
Der bisherige Supervisor überwachte ausschließlich zwei erledigte Testkarten.
Sein `complete/no_authorized_ready_card` beschrieb diesen Testbatch, obwohl in
ThreadDesk weitere Arbeit vorhanden war.

## Auftrag und Zuordnung

Das vorhandene Loopprofil kann eine `continuation`-Regel enthalten:

- `authority_ref`: konkrete Quelle des bestehenden Nutzerauftrags;
- `allowed_cwds`, `products`: zugeordnete Arbeitsbereiche und Produkte;
- `checks`: von der Koordination gewählte Abnahmebefehle mit literalem argv;
- `sources`: zugeordnete Eintragskennungen und Inhalts-Hashes.

Die beauftragte Koordination bewertet vorhandene Aufgaben, Claims und Ergebnisse
und ordnet passende Arbeit selbst zu. Ein Prosahandoff bleibt Kontext. Eine
ausführbare Zuordnung verwendet die bestehende vollständige `ReadyCard` mit
fachlicher Aufgaben-ID, Arbeitsbereich und Abnahmevertrag:

```sh
bigplan-loop adopt --entry-id VORHANDENE_AUFGABENKARTE
bigplan-loop status
```

`adopt` ist ein interner Zuordnungsschritt im bereits erteilten Auftrag, keine
weitere Nutzerfreigabe. Fremder Boardtext kann sich durch READY oder einen
Agentennamen nicht selbst zuordnen. Der bisherige `approve`-Weg bleibt für
explizite Einzelbatches erhalten. Es entsteht keine zusätzliche Aufgabenqueue.

## Fortsetzung und Doppelarbeitschutz

Der Supervisor verwendet bestehende AutoNext-Items, Grants, TeamWorks,
Core-Requests, Leases, Outbox und Receipts:

| Beobachtung | Verhalten |
| --- | --- |
| Bereits angenommene Aufgaben-ID | Überspringen, auch aus einem früheren Grant. |
| Bestehender Claim oder UNKNOWN | Ursprüngliche Bindung behalten; kein Replay. |
| Fremder Claim, Fortschritt oder geliefertes Resultat | Zuständigkeit beziehungsweise offene Prüfung abgleichen; nicht erneut bearbeiten. Strukturierte Taskreferenzen und historische Textverweise berücksichtigen. |
| Gleiche Aufgaben-ID mit verschiedenen Quellenbytes | Nur diese Aufgabe als Konflikt halten. |
| Verschwundener unabhängiger Worktree | Betroffene Karte halten; andere Bereiche weiterführen. |
| Passende zugeordnete Karte | Automatisch pinnen, regulär claimen und ausführen. |

Jede Aufgabe erhält einen deterministischen Einzelgrant. Ein Fehler blockiert
keine unabhängige Aufgabe. UNKNOWN-Leases bleiben im ursprünglichen Bereich
wirksam. Fehlende gemeinsame Rechte, unklare Abrechnung oder tatsächlich
erschöpftes Kontingent bleiben reale Grenzen.

Der taskstabile gemeinsame Claimkey wird unter ThreadDesks bestehender
`.append.lock` geschrieben und exakt zurückgelesen. Zwei kooperierende
Koordinatoren können dieselbe Karte dadurch nicht unter verschiedenen Grants
starten. Verlorene Appendbestätigungen werden am gleichen Key abgeglichen.

Arbeitsbereich und Sandbox werden nur zwischen eigenen Ausführungen gebunden.
Die CWD alter Haupt- und Reviewaufträge stammt aus ihrem gespeicherten Kontext.
Globale sichtbare Terminalrouten bleiben eingeschaltet; eigene Worker verwenden
versiegelte `separate_managed_session`-Aufträge.

## Wiederanlauf, Modellwahl und Rückmeldungen

Ein unfinished Grant wird vor dem Workerstart mit denselben Work-/Corekennungen
restauriert. `enabled=false` erhält einen publizierten queued Auftrag, ohne ihn
auszuführen oder als fehlgeschlagen zu verbrauchen. Einschalten übernimmt diese
Kennung. Unklare begonnene Wirkungen erhalten keine neue Ausführungs-ID.

Die optionalen Profilfelder `routing` und `worker_routing` verbinden den
vorhandenen nativen C2-Router mit tatsächlichen Modell-/Effortparametern. Matrix,
Zugang, versiegelte Requests und aktuelle Budget-/Leasebelege bleiben maßgeblich.
Die Koordination wählt passende Profile; Modelltext schaltet nichts um.

`worker_timeouts` setzt vorhandene Core-Zeitprofile pro Worker ausdrücklich,
beispielsweise Codex300s und Verifikation180s für einen Codingabschnitt. Ohne
Angabe bleibt der frühere Wert120s erhalten. Die bestehende Core-Obergrenze und
die Abdeckung der gesamten Review-/Checkkette durch Lease und Kontingentbeleg
werden weiter geprüft. Ein Profilwechsel verlängert keinen bereits versiegelten
Auftrag und wiederholt keinen UNKNOWN.

`quota_events` kann ausdrücklich zugeordnete native Codex-Sitzungslogs enthalten.
Nur tatsächliche `event_msg/token_count/rate_limits` innerhalb der letzten fünf
Minuten zählen: neuester Beleg, Abonnementplan, gültige Grenzen und Resetzeit,
keine API-Schlüssel. Herkunft wird als SHA256 referenziert; Transkripte werden
nicht übernommen. Alte oder in Modelltext eingebettete Werte zählen nicht.
Ohne frischen nativen Beleg bleibt die bestehende Konto-RPC-Abfrage maßgeblich.
Ein RPC-Fehler beweist weder Quotaende noch eine neue Abrechnungsberechtigung.

Der Supervisor konsumiert das bestehende Completion-Postfach und quittiert nach
Abgleich von ursprünglicher Outbox und ThreadDesk-Readback. Ungeklärte Meldungen
bleiben ohne neue Modellturns anhängig. `status` zeigt Auftrag, Quellenrevision,
gehaltene Aufgaben und AutoNext-Ausführung getrennt. Im Leerlauf gibt es keinen
Modellaufruf. Vor Claim, Haupt-/Reviewausführung und jedem neuen Prüfbefehl wird
die aktuelle Zuordnung geprüft. Entzug verhindert weitere Wirkungen; laufende
Prozesse werden dadurch nicht als beendet ausgegeben.

## Prüfung und Betrieb

Gezielte Tests verwenden tatsächliche lokale Core-/MCP-/Dispatcherprozesse mit
deterministischen CLI-Fixtures. Dazu gehören Fortsetzung ohne approve, alte
Abschlüsse, Fremdclaims, Quellenkonflikte, fehlende Bereiche, UNKNOWN-Isolation,
atomare Claimkeys, verlorenes Readback und Quellenentzug zwischen Checks. Ein
frischer Supervisorprozess übernimmt einen gespeicherten versiegelten queued
Coreauftrag; aktiver und deaktivierter Neustart sind getrennte Fälle. Das ist
keine Provider-, Desktop-, Windows- oder Mobileabnahme.

Lokale Aktivierung betrifft ausschließlich den vorhandenen Dienst
`de.threaddesk.bigplan-coordinator`, mit Sicherung von Profil, Launcher, Plist und
konsistentem lesenden Datenbanksnapshot. Ein Rückfall ersetzt keine neuen
Aufgaben-/Auditdaten. Der primäre Bridge-Dienst und fremde Sitzungen werden dafür
nicht neu gestartet. Quellpins, Tests, native Folgeaufträge und Readbacks stehen
im Entwicklungsboard `188ce4729a62`, Startclaim `e13bed64b3c8`. Lokaler
Installationsstand und öffentliches Produktrelease sind getrennt.

## English

The existing supervisor continues coordinator-assigned board tasks under a
standing user mandate. Assignment is an internal action without another user
approval. It reuses immutable source pins, singleton AutoNext grants, shared
board claims, TeamWork/Core seals, leases and acceptance receipts. Completed,
reserved, delivered and unknown tasks are reconciled rather than re-executed.
A task-local problem leaves independent scopes available.

Restart restores the original execution identity before workers start. Disabled
profiles preserve queued work. The native model router and durable completion
consumer remain the execution and return paths. Local deterministic tests,
provider runs, service activation and public releases have separate evidence.

## Lokaler Nachweis am 6. November 2026

Der Supervisor `4b821c6` wurde im eigenen bestätigten Terminalfenster mit
Sicherung aktualisiert. Anschließend wurden zwei unabhängige Routinetextaufgaben
über echte Codex-Hauptturns, separate Codex-Verifikation und gepinnte Checks
angenommen. Genau vier native Coreturns und zwei Annahmequittungen; der zweite
Hauptturn begann 10,13 Sekunden nach der ersten Annahme. Beide dauerhaften
Completionmeldungen wurden nach geprüftem Boardreadback quittiert. Der Router
setzte tatsächlich Luna/low für Routine und Sol/high für Verifikation;
anbieterintern effektive Werte wurden nicht separat attestiert.

Ein vorheriger Codingturn endete nach 120 Sekunden Bestandslektüre als
UNKNOWN/agent_timeout. Originalkennungen und Lease bleiben erhalten, der Prozess
ist beendet und der Checkout unverändert. Dies ist kein erfolgreicher nativer
Schreibnachweis und wurde nicht wiederholt. Die fachliche Zeitprojektion wurde
anschließend in einem disjunkten Checkout fertiggestellt und unabhängig geprüft.
Der primäre Bridge-Dienst und fremde Sitzungen blieben unverändert.

Die neue lesende Statusprojektion liefert pro aktueller Aufgabe gespeicherte
Corezeitpunkte, Receipt-Abnahmezeit und daraus geordnete endliche Dauern für
Queue, Ausführung, Abnahme und Gesamtzeit. Fehlende Daten bleiben `null`, ohne
Hochrechnung auf die aktuelle Uhrzeit oder Ersatz aus fremden Teamzeitpunkten.
Owner-, Grant- und Teamrechte bleiben maßgeblich. Dies ist ein weiterer geprüfter
Quellschritt; die lokale Supervisoraktivierung bleibt an ihren eigenen Pin
gebunden. Evidenz: `~/.local/state/coordinator-continuation-20261106/`,
ThreadDesk `188ce4729a62/9336dde91791` und der dort folgende Quellenabschluss.

## Abschluss- und Übergabe-Hook (11.11.2026)

`kirabridge completion` verbindet den tatsächlichen Abschluss eines Auftrags mit
dem ThreadDesk-Whiteboard und der nächsten freigegebenen Aufgabe. Der Hook
schreibt zuerst genau einen Ergebnis-Eintrag, liest ihn zur Bestätigung der
dauerhaften Speicherung zurück und wählt erst danach die neueste freigegebene
Aufgabe oberhalb des abgeschlossenen Eintrags. Es gibt keine zweite Queue, keine
automatische Wiederaufnahme alter Einträge und keine Ausführung von Boardtext.

```sh
# Abschluss dokumentieren, Speicherung bestätigen, nächste Aufgabe übernehmen
kirabridge completion record \
  --workspace /Users/landjunge/.local/share/threaddesk/kirabridge-operator \
  --board 188ce4729a62 --order-entry <task-entry-id> --task-id <logische-id> \
  --status completed --summary "..." --sha <commit> --tests "..." \
  --session-id <bestehende-sitzung>

# Nur lesen und die Auswahl prüfen
kirabridge completion record ... --dry-run
kirabridge completion next --board 188ce4729a62 --newest --dry-run
```

Der Ergebnis-Eintrag enthält Status, Sitzungszuordnung, Commit, Review-Referenz,
Testergebnis und Zusammenfassung; offensichtliche Zugangsdaten und
Steuerzeichen werden abgewiesen. Ein zweiter Lauf mit identischen Angaben liefert
denselben Eintrag. Die Übernahme schreibt einen `claimed`-Eintrag mit
aufgabenbezogenem Schlüssel; parallele Hook-Läufe erzeugen höchstens einen
Gewinner, Verlierer melden `already_claimed`. Nur `completed` führt zur
Übernahme; `failed`/`cancelled` werden dokumentiert, ohne Folgearbeit zu starten.
Ohne explizite `--order-entry` verlangt `next` das bewusste `--newest`, damit
kein historischer Eintrag automatisch übernommen wird.

Auszuführende `ReadyCard`-Einträge müssen `state = READY` tragen; `IDEA`, `HOLD`,
`STALE`, `CANCELLED` und bereits durch `claimed`/`result` referenzierte Aufgaben
werden übersprungen. Metadatenfelder (`task_id`, `handoff_id`, `run_id`) und
Textverweise werden gemeinsam geprüft. Der zurückgegebene Boardtext ist
ausdrücklich unvertrauenswürdig (`untrusted: true`) und wird vom Hook nicht
ausgeführt. Fehlt eine Folgeaufgabe, meldet der Hook `idle` statt zu starten.
Voraussetzung für die Nutzung ist ein Release, das diesen Befehl enthält; die
Codeanwesenheit allein aktiviert keinen Dienst.
