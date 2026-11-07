# KiraBridge 0.7.0rc1 — Teams / private release candidate

## Deutsch

Ein gemeinsames Team verbindet die eingerichteten KI-Zugänge mit getrennten
Identitäten. Der Besitzer wählt einen Koordinator, beispielsweise ChatGPT,
Codex oder Grok. Koordinator, Bearbeiter und Prüfer können Aufgaben an andere
aktive Teammitglieder vergeben, adressierte Nachrichten senden und die bewusst
im Team geteilten Ergebnisse einsehen. Beobachter lesen nur. Koordinatorwechsel
sind atomar und revisionsgebunden; der Besitzer behält seine Steuergewalt.

Neue MCP-Werkzeuge `team_*`, die CLI `kirabridge team` und der lokale Team-Bereich
der Freigabeoberfläche verwenden dieselbe dauerhafte SQLite-Domäne. Ein begrenzter
Dispatcher führt freigegebene Aufträge über echte authentifizierte Agentenzugänge
und die bestehende Aufgabenverwaltung aus. Strukturierte Agentenantworten können
kontrolliert Nachrichten oder Unteraufträge erzeugen, ohne Nachrichtentext als
Shellcode auszuführen. Delegationstiefe, Unterauftragszahl, Warteschlangen,
Aktionen pro Antwort und Ausführungen pro Stunde sind begrenzt. Unbekannte
Ausgänge werden nicht automatisch neu ausgeführt.

Die Standard-Antwortauswertung bleibt `strict_json`: Nur ein vollständiges
Team-JSON-Objekt kann Aktionen auslösen. Ein ausdrücklich eingerichtetes
Empfängerprofil `response_framing="work_reply_header"` berücksichtigt zusätzlich
den festen Vorspann `Here is the work reply:` mit Zeilenumbruch und anschließend
genau einem JSON-Objekt. Eingebettetes JSON in beliebiger Prosa oder Codeblöcken
wird nicht als Auftrag ausgeführt.

Besitzer und aktueller Koordinator können über `team_work_reprocess` bzw.
`kirabridge team reprocess` die Auswertung eines vorhandenen, nachweislich
abgeschlossenen Core-Ergebnisses bewusst erneut anstoßen. Core-ID und SHA-256
des unveränderten nativen UTF-8-Ergebnistexts binden die Aktion an den geprüften
Beleg; `team_work_get` liefert dafür `evidence.core_result_sha256`. Das geteilte
Team-Ergebnis muss bereits abgeschlossen sein und null vorherige Aktionen
belegen; je Teamauftrag ist höchstens eine Nachverarbeitung möglich. Es erfolgt
kein erneuter ursprünglicher Modellaufruf. Zulässige Aktionen können weiterhin
neue begrenzte Unteraufträge erzeugen. Alte Belege ohne geteiltes Hashfeld
benötigen zuerst eine autorisierte lokale Prüfung.

Enthalten sind außerdem native CLI-Textadapter für OpenCode, Gemini CLI, Claude
Code und GitHub Copilot CLI. Anmeldung und tatsächliche Modellverfügbarkeit
bleiben getrennt vom Vorhandensein eines Programms. OpenCode wurde lokal mit
Ollama geprüft. Der vorhandene persönliche Gemini-CLI-OAuthzugang wird vom
Anbieter abgewiesen; Claude und Copilot benötigen einen passenden eigenen
Zugang. Es werden keine kostenpflichtigen Konten oder Modellpakete automatisch
eingerichtet.

ChatGPT ist ein externer Teilnehmer: Es kann koordinieren, Aufgaben lesen,
annehmen und Ergebnisse zurückmelden, wenn der Chat tatsächlich aktiv ist.
Eine Rolle weckt keinen inaktiven Chat. Automatische CLI-Aufträge benutzen
separate verwaltete Arbeitssitzungen; bestehende Sitzungen bleiben erhalten.
Die vier neuen CLI-Adapter unterstützen Textaufträge, keine nativen Projekttools
oder Sitzungsfortsetzung. Private Einzelaufträge bleiben außerhalb des Teams.
Teamrollen erweitern keine Datei-, Terminal- oder Systemberechtigungen.

Dieses private Vorabrelease ersetzt keine eingefrorenen älteren RC-Artefakte.
Windows-Nativbetrieb, fremde Konten, ein frischer externer Mac und echte Linux-
Desktopsitzungen sind gesonderte Abnahmen. Die bestehende Lizenz gilt unverändert.
Siehe [Team-Bedienung](TEAM-ORCHESTRATION.md) und [Anbieter](providers/README.md).

## English

Persistent teams connect configured AI identities through addressed messages,
delegated assignments and deliberately shared results. The owner chooses the
coordinator; coordinator changes use revision checks and preserve owner control.
Workers and reviewers can delegate; observers can only read. Private tasks and
mailboxes remain private. Roles never expand filesystem or execution permissions.

The `team_*` MCP tools, `kirabridge team` CLI and local Team panel share one
SQLite domain. A bounded dispatcher submits real authenticated agent tasks to
the existing task pipeline. Versioned response actions support messages and
bounded child assignments; text is never treated as shell code. Recovery reads
known task evidence and never blindly replays unknown execution.

Default `strict_json` parsing accepts actions only from a complete team JSON
response. A worker-specific opt-in, `response_framing="work_reply_header"`,
accepts the exact `Here is the work reply:` header, a newline and one JSON object.
Embedded JSON in arbitrary prose or code fences remains inert.

Only the owner/current coordinator may explicitly reprocess a proven completed
core result using `team_work_reprocess` or `kirabridge team reprocess`, pinned to
its original core task ID and native UTF-8 response SHA-256. The shared evidence
field is `core_result_sha256`. The shared work must already be completed with
zero prior actions; at most one reprocessing is allowed per work item.
This never retries the original model turn;
valid actions may still create bounded child assignments. Historical records
without a shared hash need authorized local evidence review first.

OpenCode, Gemini CLI, Claude Code and Copilot CLI text adapters are included.
Provider authentication and availability are separate from executable presence.
OpenCode has been exercised with local Ollama. The locally configured personal
Gemini CLI OAuth account was rejected by the provider; Claude and Copilot
require suitable credentials.
No paid subscription or cloud-model workaround is installed automatically.

ChatGPT remains an external participant: it can coordinate and report results
while its chat is active; assigning a role does not wake an inactive chat.
CLI work uses separate managed sessions. The four new adapters provide text
turns, without native project tools or existing-session resume. This private
candidate does not replace previously frozen RC artifacts. Existing license
terms remain unchanged; external-host and Windows acceptance remain separate.
