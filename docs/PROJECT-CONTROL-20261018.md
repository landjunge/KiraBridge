# Projektsteuerung · 18.10.2026

Nutzerauftrag: gezielte Rechte für sechs vorhandene Projekte und tatsächlich
schreibfähiger Codex-Adapter; anschließend ausschließlich Integrationsanalyse.
Keine globale Home-/Filesystemfreigabe, keine neuen Interpreter, Konten, Grok-
Aufträge oder Änderungen bestehender interaktiver Sitzungen. Keine Builds oder
Releases durch diesen Folgeauftrag. Der gesonderte laufende 4AllPass-Release-
Auftrag bleibt davon getrennt autorisiert.

## Festgestellter Ausgangszustand

Geladener Dienst0.5.2, Runtime8e79b3b91a274677996a0fe187b07a7e,
Configc95c79de…cc519. Alle vier Principals besitzen bereits Datei-Schreibrechte,
allerdings nur im Austauschordner~/workspace/KiraBridge. ChatGPT besitzt
zusätzlich Lesewurzeln~/Projects und~/KiraBridge. Die Bridge ist daher nicht
insgesamt read-only; der bestätigte ChatGPT-Writecheck1528 bleibt erhalten.

Der tatsächlich geladene lokale CodexAdapter verwendet wie der geprüfte
GitHub-Stand fest `--sandbox read-only`. Das ist eine eigenständige Grenze.
Eine offene interaktive Codex-Sitzung hat ihren eigenen Berechtigungskontext;
ein verwalteter Adapterlauf ist nicht diese Sitzung.

## Begrenzte Korrektur

`agents.codex.sandbox_mode` erlaubt ausschließlich `read-only` oder
`workspace-write`; sicherer Standard bleibt read-only. Lokaler Betreiber setzt
workspace-write ausdrücklich. Der Arbeitsordner muss weiterhin in einer
Principal-Schreibwurzel liegen; keine automatische Freigabe aller Projekte für
jeden Kindprozess. Codex erhält keine zusätzlichen `--add-dir`-Wurzeln, keine
Sandboxumgehung und keine automatische Netzfreigabe. Projektanweisungen bleiben
aktiv (`--ignore-rules` entfernt). User-Konfiguration und MCP-Server des
Kindprozesses bleiben deaktiviert, um fremde/rekursive Bridge-Konfigurationen
nicht zu übernehmen. Nichtinteraktiv `approval_policy=never` bedeutet keine
Sandboxausweitung. Inventar und Ausführungsbeleg nennen den gewählten Modus;
Turnabschluss bleibt von Projektabnahme getrennt.

[Offizielle OpenAI-Dokumentation: Sandbox](https://learn.chatgpt.com/docs/sandboxing)
beschreibt workspace-write, getrennte Approval-Policies und zusätzliche
Schreibwurzeln. Lokale CLI0.163.0 bestätigt die verwendeten Optionen.

Die private Policy ergänzt nur vorhandene Projektverzeichnisse und tatsächlich
registrierte, vorhandene Git-Worktrees: KiraBridge, ThreadDesk,4AllPass,TollGate,
Gnom-Hub-v1 und Agent-Authority-lab. Der alte separate gnom-hub-Repo wird nicht mit
dem aktuellen Produkt gnom-hub-v1 verwechselt. Existierende Freigaben bleiben;
Capabilities, Programmlisten, Tokens, Queue und Runtime-Daten werden nicht ersetzt.
Terminal-CWD, Dateiwerkzeuge und strukturierter Adapter bleiben getrennte Prüfungen.
Eine Terminal-Programmliste ist keine OS-Sandbox; vorhandenes zsh wird nicht als
solche ausgegeben. cat/System-Python werden nicht zusätzlich freigegeben.

## Prüfung und Aktivierung

Vorbereitung:9 gezielte Codex-/Rechtegrenzenfälle bestanden, inklusive sicherem
Default, Ablehnung von danger-full-access, erhaltener Task-/Ownergrenze und
getrenntem Turn-/Projektabschluss. Ruff Format/Check bestanden. Kein Paketbau.
Konfiguration wurde vor jeder Änderung mit erhaltenem0600-Modus privat gesichert;
265 Taskzeilen und vorhandene Nachrichten sind gehasht, keine aktive/wartende
Task-/Empfängerqueue. Historische unknown-Zustände werden nicht neu gestartet.

Aktiviert am18.10.2026 bei ruhender Task-/Empfängerqueue mit SQLite-
Schreibbarriere. Laufende Quelle bleibt0.5.2 mit gezieltem Backport55046b0;
keine Umstellung auf den kompletten privaten0.6-Releasekandidaten. Runtime
193c91766e444f06827de90256a7a328 lädt Config4507332a…140b5 und
Python-Quellfingerabdruck0ca2386d…e5065. Originalpolicy liegt lokal geschützt
unter `~/.local/share/kirabridge/project-control-20261018/config.before.toml`.
Config0600 erhalten. Nur bestehende Wurzeln/registrierte Worktrees ergänzt,
Capabilities und Programmlisten unverändert.

Je sechs echte Datei-Schreib-/Leseproben und Git-Prozesse im jeweiligen Projekt
bestehen über authentifiziertes MCP mit bestehendem chatgpt-Principal. Eine echte
strukturierte Codex-Probe in KiraBridge schreibt die vereinbarte Datei; Inhalt
unabhängig zurückgelesen. Alle eigenen synthetischen Prüfdateien anschließend
entfernt. Vier Gegenfälle bleiben gesperrt: Home-Schreibpfad, Home-Terminal-CWD,
cat und System-Python. Die fünf anderen Projekte erhalten keine zusätzlichen
Modellläufe: deren Datei-/Prozessrechte und gemeinsamer Adaptermodus sind belegt,
keine sechs vollständigen Entwicklungsabnahmen behauptet.

Alle265 alten Taskzeilen und fünf Nachrichten byteinhaltlich per Zeilenhash
erhalten; beide unbekannten Empfängerjobs bleiben unbekannt, nicht wiederholt.
Zugangsdatei, Runtime-Key und LaunchAgent unverändert; Auditkette gültig.
Die globale Codex-Konfigurationsdatei hat während des Beobachtungsintervalls
allerdings einen anderen Hash/mtime17:56:09. Ursache nicht belegt; dieser Auftrag
hat sie nicht geschrieben und setzt fremde Änderungen nicht zurück. Der explizite
Adapterparameter workspace-write gilt unabhängig davon. Kein behaupteter
vollständiger Erhalt ihres Inhalts. Dateimodus bleibt0600.

[Konkrete Taskkennungen und Erhaltungsbelege](evidence/project-control-20261018.json).
Der Client läuft lokal über den echten Dienst, nicht als neue externe ChatGPT-
Unterhaltung. Die bereits bestandene externe ChatGPT-Dateiabnahme1311 und der
Writecheck1528 bleiben erhalten und werden nicht neu ausgeführt.

Bedienung: `bridge_readiness` mit benötigten read_paths, operations und
executables aufrufen; anschließend `task_request` mit stabiler task_id und
idempotency_key, Operation agent.execute, agent=codex und cwd im konkreten
Projekt. Annahme ist kein Laufabschluss: task_get/task_events abfragen. Bei
Verbindungsabbruch zuerst dieselbe Taskkennung lesen, Schreibauftrag nicht mit
neuer Kennung doppelt starten. Neue Worktrees außerhalb freigegebener Eltern
benötigen weiterhin gezielte lokale Ergänzung. Kindprozess-Netz-/Git-Metadaten-
Grenzen können weitere konkrete Schritte begrenzen; keine globale Freigabe.
Ein positiver Health-Status allein ist keine Schreib-/Agentenabnahme.

Der bestehende private RC2-Entwurf bleibt auf seinem ursprünglichen Quellpin.
Diese neue Adapteroption ist nicht in dessen bereits gebauten Artefakten;
kein neuer Releasebau oder öffentliche Veröffentlichung durch diesen Auftrag.
Rückweg: nur gesicherte passende Policy und vorherigen Quellpin bei ruhenden
Queues laden; keine Task-/DB-/Zugangsdatenrücksicherung.
