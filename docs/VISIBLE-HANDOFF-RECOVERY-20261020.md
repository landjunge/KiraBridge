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
