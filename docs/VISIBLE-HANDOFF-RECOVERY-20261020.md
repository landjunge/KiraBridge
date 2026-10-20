# Sichtbare Kira-Übergabe: Ursache und dauerhafte Korrektur

Am 20. Oktober wurde die konkrete Codex-Blockade nachgestellt. Der Dispatcher
rc9 antwortete, Wartung war aus, Dateiaufträge wurden ausgeführt. Zwei neue
Kira-Nachrichten scheiterten dagegen mit visible_target_busy. Ursache war die
alte Reservierung kira-codex-unlocked-20261020-0616: Einfügeversuch mit
session_transport_unavailable, Zustand unknown, keine Bestätigung. Diese
Reservierung schützte vor einer möglicherweise wiederholten Eingabe, blieb aber
ohne tatsächlichen Empfangsabgleich dauerhaft vor allen neuen Codex-Übergaben.

Codex hat den alten Auftrag jetzt als tatsächlicher Empfänger über seine
authentifizierte Verbindung in der ursprünglichen sichtbaren Sitzung gelesen,
mit Empfangsbeleg quittiert und eine begrenzte Abschlussantwort geschickt.
Die zentrale Abgleichsfunktion setzt die Reservierung damit auf completed.
Sie behauptet keinen nachträglichen Erfolg des ursprünglichen UI-Transports.
Kein neuer Prompt, Return, Signal, Ersatzfenster oder Agentenstart war nötig.
Privater Beleg: codex-old-reservation-reconciled-20261020.json.

## Korrektur im rc10-Kandidaten

Vor dem Claim einer neuen Nachricht prüft der Receiver die zentrale sichtbare
Route. Ein beschäftigtes Eingabefeld, eine noch offene Übergabe oder gesperrte
Mac-Sitzung lässt sie ungeclaimt in queued, mit dauerhaftem verständlichem
Wartegrund. Die Beobachtung erzeugt keine falsche Abschlussmeldung und zählt
nicht als Agententurn. Pro Ziel bleibt die Reihenfolge erhalten; ein beschäftigter
Codex verdeckt keine bereitstehende Grok-Nachricht. Neuprüfung ist zeitlich
begrenzt und erzeugt nur bei verändertem Wartegrund einen weiteren Beleg.

Die Ausführungsgrenze prüft Fenster/TTY/Wurzel-PID/Agenten-PID und Eingabefeld
nochmals. Wechselt Bereitschaft zwischen Vorprüfung und Ausführung, darf der
Auftrag ausschließlich dann zurück in queued, wenn kein Handoff-Datensatz und
keine gestartete/acknowledged Verarbeitung existieren. Unklare Einfüge- oder
Return-Ausgänge werden niemals automatisch wiederholt. Vorhandene unbekannte
Reservierungen können nur durch den echten Empfangs-/Antwortabgleich enden,
nicht durch Zeitablauf oder pauschales Löschen.

Ein interner expliziter Reparaturhelfer resume_unsent kann eine frühere
busy/not-ready-Ablehnung nur unter denselben Nachweisen erneut einreihen.
Alte Fehlerbelege und Abschlussmeldungen bleiben erhalten. Der Helfer ist
kein neues öffentliches MCP-Werkzeug und kein pauschaler Retry von Altaufträgen.
Gleiche Aufträge dürfen nicht über zwei wiederholte Kira-Nachrichten doppelt
gestartet werden.

Alle Absender Kira, Eve, Codex und Grok verwenden weiter die gebundenen sichtbaren
Fenster. Neues Fenster/CLI/managed_receiver ist kein Ersatz. Einfügen, separates
Return und authentifizierter Empfang bleiben getrennt. Normale Freigaben bleiben
erhalten; kein Sondertoken wird hinzugefügt. Der bekannte defekte externe
Grok-Tunnel wird in diesem Paket nicht verändert.

## Prüfstand

Gezielte Prüfungen decken alle vier Absender, Reihenfolge/Fairness, Neustart,
authentifizierten Abgleich einer früheren Reservierung, konkurrierenden
Bereitschaftswechsel sowie negative Wiederholungsprüfungen ab. Ein echter
MCP-HTTP-Test mit isoliertem Terminaladapter prüft Warten und anschließend
genau ein mehrzeiliges Einfügen, separates Return und Agentenantwort.
Die unabhängige Grok-Prüfung und tatsächliche Aktivierung stehen vor Auslieferung
noch aus. Der aktive beschäftigte Original-Codex wird nicht für einen Test
unterbrochen.

## Unabhängige Prüfungen vor Aktivierung

Der eingefrorene Kandidat6f8f220, Quelle
ec9a15064d1f08d8ba44d3aa366e5f8679060c6a692023af6ce0d3c61ff392de,
besteht 844 Gesamttests in182,36Sekunden, Ruff sowie Wheel-/Lockprüfung.
Grok prüfte genau diesen Commit im vorhandenen Fenster selbst mit
144 Tests in41,16Sekunden und empfiehlt die begrenzte Abnahme.
Antwort76d06004-8f87-430c-a801-9b4150eec1e3,
Übergabechannel-f8c61682f7b44a1e898a4cc851b74635.
Er benennt die Grenze ehrlich: Ein Neustart setzt schon laufende Jobs auch
ohne gespeicherten Inputbeleg auf unknown; diese werden nicht automatisch
wiederholt. Gequeued wartende ungeclaimte Aufträge überstehen Neustarts.

Zwei getrennte Codex-Teamprüfungen untersuchten unabhängig Readiness und Client.
Die aktuelle Terminalaufnahme zeigt tatsächliche Arbeit und eine nichtleere
Eingabe q; beides berechtigt zu keiner automatischen Eingabe. Terminal.app
liefert aktuell sichtbaren Inhalt, nicht den gesamten Scrollback.
Alte sichtbare Working-Texte können synthetisch die konservative Prüfung
blockieren; das ist für die konkreten Versuche nicht als Ursache belegt.
Busy nur hinter dem letzten Prompt zu suchen würde tatsächlich arbeitenden
Codex fälschlich freigeben. Deshalb wird diese Schranke nicht pauschal entfernt.
Ein unbekannter Dialog ist keine Zusage von Bereitschaft. Gesicherter aktueller
Diagnoseausschnitt mit Zeit, Bindung und konkreten Regelmatches:
visible-codex-readiness-diagnosis-20261020.json.

Kiras tatsächlich verwendeter alter Werkzeugcache kann nachweislich lesen.
task_request verwendet completion_subscription als leeren String auf oberster
Ebene, keine erfundene Subscription-ID. Erfolgreiche echte chatgpt-Aufträge:
kira-client-read-audit-1792486422962 (Katalog) und
kira-client-original-codex-read-1792486459206 (OriginalCodex,1020Zeichen).
Neue read_query/session_read-Tools sind in der lokalen Codex-Bindung vorhanden;
das belegt keine automatische Cache-Erneuerung im externen Kira-Work-Chat.

Beispiel für den bereits real geprüften alten Kira-Weg:

    {
      "completion_subscription": "",
      "completion_target": "EINDEUTIGE_DIAGNOSE_ID",
      "request": {
        "task_id": "EINDEUTIGE_DIAGNOSE_ID",
        "idempotency_key": "EINDEUTIGE_DIAGNOSE_ID",
        "operation": "session.read",
        "arguments": {
          "pane_id": "terminal:22104:ttys000",
          "expected_pid": 94023,
          "max_bytes": 4096
        }
      }
    }

Danach completion_receive/task_get verwenden, gelesene Abschlussmeldung erst
danach quittieren. Die bestehende Regression in test_event_push.py prüft die
normale Einreichung ohne Push-Subscription.

Der echte Kira->Codex->Kira-Nachweis ist bis zur tatsächlich beobachteten
sichtbaren Eingabe, einmaligem Return, authentisiertem Empfang und zurück
empfangenem KIRA-TEST-OK offen. Kein Grok-Test oder isolierter Adapter ersetzt
ihn. Der große ThreadDesk-/4AllPass-Auftrag bleibt bis dahin zurückgestellt
und wird nicht mehrfach gestartet.
