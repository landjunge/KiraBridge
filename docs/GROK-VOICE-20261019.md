# Grok Voice und Handy – laufende Reparatur

Status: Die Hauptfunktion ist noch nicht durchgehend abgenommen.
Die bestehende ChatGPT-Anbindung wird funktional unverändert belassen.

## Unterstützte Schnittstellen

xAI dokumentiert eigene MCP-Connectoren für Grok und Connectoren auf Web,
iOS und Android:

- https://docs.x.ai/grok/connectors
- https://x.ai/news/grok-connectors

Für eigene Sprachclients ist der vollständige Werkzeugrückweg über die
Speech-to-Speech API dokumentiert: Funktionsaufruf, tatsächliches Ergebnis als
`function_call_output`, anschließend `response.create` und Audioausgabe.
Das ist eine eigene API-Sitzung und kein Nachweis für einen bestehenden
nativen Grok-App-Sprachchat:

- https://docs.x.ai/developers/model-capabilities/audio/speech-to-speech
- https://docs.x.ai/developers/rest-api-reference/inference/voice

## Reale Befunde

Vor dieser Reparatur gab es in der lokalen OAuth-Datenbank nur widerrufene
technische Testclients. Ein aktiver echter Grok-Client fehlte. Der frühere
öffentliche MCP-Test bewies daher keine Verbindung des Grok-Kontos.

Die Anmeldung wurde nun im tatsächlich angemeldeten Grok-Webkonto durchgeführt.
Grok registrierte sich selbst, durchlief den OAuth-Rücksprung und erhielt Tokens.
Grok zeigt KiraBridge als verbunden und alle Werkzeuge als aktiviert an.
Ein echter Auftrag im Grok-Webgespräch rief Bridge-Health und Terminalkatalog ab;
die Version und die drei tatsächlichen Terminalziele kamen zurück. Die separate
OAuth-Auditkette bestätigt Zugriffe des echten Clients.

Eine weitere vom Nutzer genannte Verbindungskennung war bereits freigegeben,
hatte aber vor Ablauf noch keinen Tokenaustausch abgeschlossen. Eine Freigabe
wird deshalb nicht mit einer aktiven Verbindung gleichgesetzt.

Der gekoppelte iPhone-Zugang ist über die verfügbaren Entwicklerwerkzeuge nicht
fernsteuerbar: CoreDevice meldet ausgeschalteten Entwicklermodus. Das ist eine
Grenze der Teststeuerung, kein Beweis für eine Grok-Produktgrenze. Entwicklermodus,
Geräteneustart oder Ersatz-Chat werden nicht als Voraussetzung erfunden.

## Gezielte Änderungen

Nur der konfigurierte Grok-App-Principal erhält den gekoppelten Auftragsrückweg.
Seine bestehenden `task_request`, `task_submit`, `action_request`, `action_submit`
und `task_get` liefern nach bis zu 18 Sekunden das tatsächliche Ergebnis im
aktuellen Werkzeugaufruf zurück. Längere Aufträge behalten dieselbe ID; die
Rückgabe weist auf das Weiterwarten über `task_get` hin. Ein Transportabbruch
startet den Auftrag nicht erneut. Erforderliche Freigaben bleiben wirksam.

`conversation_return.text` enthält die tatsächliche Antwort oder den tatsächlichen
Fehler. Eine Eingabequittung für ein bestehendes Terminal wird ausdrücklich
nicht als fertige Agentenantwort ausgegeben. Eine vorbereitete Werkzeugrückgabe
ist kein Beleg für abgespielten Ton.

Das Codefenster nach OAuth-Freigabe war nur zwei Minuten lang. Mobile Browser
können die Abfrageseite beim App-Wechsel pausieren. Das Fenster wird auf die
verbleibende ursprüngliche zehnminütige Anmeldefrist angepasst. Bereits abgelaufene
oder verbrauchte Codes werden nicht wiederbelebt; PKCE, Rücksprungbindung und
einmalige Verwendung bleiben erhalten.

## Prüfungen und verbleibende Abnahme

Die Rückgabe wurde mit realem MCP-HTTP-Transport und echten isolierten
Kindprozessen getestet: direkte Antwort, längere Antwort, Wiederanbindung nach
Transportabbruch, Schutz vor Doppelstart, Empfängertrennung, Freigabe sowie die
Unterscheidung von Terminaleingabe und ausgeführtem Auftrag. Der bisherige
ChatGPT-/andere-Principal-Vertrag wird separat auf Unverändertheit geprüft.
Die OAuth-Prüfung deckt App-Wechsel über zwei Minuten und tatsächlichen Ablauf ab.

Für den Abschluss fehlen weiterhin korrelierte Tests im nativen Grok-Sprachmodus,
insbesondere auf dem Handy: gesprochener Auftrag, tatsächlicher Agenten- und
Terminalaufruf und hörbare Ergebnisrückgabe im selben laufenden Sprachgespräch.
Die Browser- oder API-Prüfung wird nicht als Handy-Abnahme ausgegeben.

## Befund im echten Eve → Grok Build → Codex-Handoff

Die Nachrichten Seq 87 und 88 waren verarbeitet; beide waren Notizen ohne
angeforderte Antwort. Die Frage Seq 89 erzeugte die tatsächliche Codex-Antwort
Seq 90 mit fünf Herzchen. Diese Antwort war jedoch automatisch an einen weiteren
verwalteten Grok-Empfänger disponiert und von diesem quittiert worden. Die
Quittierung belegt deshalb nicht den Empfang durch die sichtbare Build-Sitzung.

Das ist eine konkrete Konkurrenz im Rückweg. Automatische Empfängerantworten
bleiben nun im Postfach des ursprünglichen anfragenden Clients. Antworten und
Ergebnisse starten standardmäßig keinen weiteren Empfänger; ein ausdrücklich
angeforderter Dispatch bleibt möglich. Alte Idempotenzentscheidungen werden bei
Wiederverbindung erhalten. Bereits abgeschlossene Aufträge werden nicht wiederholt.
Für Eve kann außerdem der bestehende Nachrichtenaufruf auf die korrelierte
Agentenantwort warten und sie im selben Werkzeugergebnis zurückgeben.

Nach `session.input` wird Eve explizit zum Lesen genau dieses Terminalziels
weitergeführt. Die Quittung wird nicht als fertige Antwort ausgegeben.
