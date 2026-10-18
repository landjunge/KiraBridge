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

**Stand dieses Commit: Quellkorrektur vorbereitet; aktive Konfiguration noch
unverändert.** Tatsächliche Aktivierung, Probeaufträge, Erhaltung und verbleibende
Grenzen werden nach dem kontrollierten Laden hier ergänzt. Ein positiver Health-
Status allein ist keine Schreib-/Agentenabnahme.

Der bestehende private RC2-Entwurf bleibt auf seinem ursprünglichen Quellpin.
Diese neue Adapteroption ist nicht in dessen bereits gebauten Artefakten;
kein neuer Releasebau oder öffentliche Veröffentlichung durch diesen Auftrag.
Rückweg: nur gesicherte passende Policy und vorherigen Quellpin bei ruhenden
Queues laden; keine Task-/DB-/Zugangsdatenrücksicherung.
