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

## Tatsächlich aktivierter Stand

Der vor Installation gepushte Merge eff7df0 enthält den von Grok geprüften
Quellstand. Das bytegeprüfte Wheel wurde ohne Dependency-Wechsel installiert.
Aktivierung activation-c9a310d9fb49446483216d910c25e6ed ist completed:
Version 0.8.0rc10, Core-PID 29302,
Quell-SHA ec9a15064d1f08d8ba44d3aa366e5f8679060c6a692023af6ce0d3c61ff392de.
Die tatsächliche Konfiguration blieb bytegleich:
cd80c04c54e27e57bc4249261a3a2ce9f9ba9300e83fcf301b6d4eff253245c3,
effektiv ba72132a31dd21f44891b75a631d2f8b2495c6c82b4fba2a544f32212b21703d.
Kiras echtes policy_inspect bestätigt Quelle und Konfiguration als matches_loaded.
Alle16 beobachteten bestehenden Fenster-/Agenten-/App-/Tunnelprozesse erhalten.
Nur Core und Steuerdienst wurden geladen. Der erste lokale Aktivierungsversuch
wurde noch vor Reservierung/Neustart durch den Dateihashvergleich angehalten;
der neue Helfer erhält die bestehende Konfigurationsdatei bytegenau statt einen
bereits vorhandenen Abschnitt erneut zu formatieren. Kein Dienst wurde dabei
blind erneut gestartet. Beleg activation-visible-wait-rc10.json.

Nur der ursprüngliche kurze Test d5f54c18-7068-4abb-9d2f-339fb9a8a526 wurde
explizit wieder eingereiht: vorher failed/visible_target_not_ready, started=null,
kein ACK, kein Handoff und keine Eingabe. Nachricht/Absender/Body/Konversation
bleiben identisch. Beide alten Fehlerbelege bleiben erhalten; kein neuer
Kira-Test und kein Großplan wurden gestartet. Der Receiver meldet jetzt queued,
terminal_input_attempted=false und einen verständlichen Wartegrund, während
der Original-Codex diesen Reparaturturn noch ausführt. Beleg
codex-kira-short-test-resumed.json.

Die zuletzt frisch gelesene Originalanzeige zeigte ein leeres Eingabewidget,
aber eine aktuelle Working/esc-to-interrupt-Zeile; die frühere Eingabe q war
in dieser späteren Aufnahme nicht mehr vorhanden. Das ist weiterhin echte
laufende Arbeit, keine bewiesene Fehlbereitschaft. Der aktuelle Reparaturturn
muss beendet werden, bevor die sichtbare Übergabe zulässig ist.

Ein getrenntes Codex-Teammitglied wartet ausschließlich auf die Antwort dieser
originalen Kira-Konversation über die tatsächliche Kira-Werkzeugbindung. Kein
Versand, Ersatzfenster, weiteres Return oder Nachrichten-Duplikat durch den
Beobachter. Der echte End-to-End-Nachweis bleibt offen bis eingefügt/abgesendet,
authentisiertem Codex-ACK und Kira-Empfang von KIRA-TEST-OK. Ein späterer Beleg
kira-codex-real-e2e-20261020.json darf erst nach diesem tatsächlichen Ablauf
Erfolg melden; bis dahin ist der Gesamtweg nicht als abgenommen auszugeben.
