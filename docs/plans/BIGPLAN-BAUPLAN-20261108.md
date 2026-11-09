> **Nicht maßgeblich. Maßgeblich ist ThreadDesk-Thread `6b5b73b9de36` (Master mit Etappen E01–E09; Status im Board `188ce4729a62`; Nutzerbeschluss 09.11.2026). Diese Datei ist Archiv bzw. technischer Spiegel.**

# Big Plan · Bauplan v2

Stand: 08.11.2026, 13:00 Uhr (Berlin). Überarbeitung des gesamten Big Plans.
Die Grundrichtung bleibt unverändert. Neu sind der Abgleich mit dem tatsächlichen
Stand, die Liste der Widersprüche, die ergänzten Module und eine neue Reihenfolge.

**Ablage: nur privat** (KiraBridge `docs/plans/`, neben `BIGPLAN-GESAMTPLAN-20261105.md`).
Der Plan enthält Serveradressen und offene Sicherheitsbefunde. Er gehört nicht in die
öffentlichen Repos `threaddesk`, `4AllPass` oder `tollgate`.

Dieser Plan ist ein Planregister. Er ist keine Aufgabenqueue, keine READY-Freigabe
und kein Arbeitsauftrag für den Koordinator. Pakete werden erst durch eine
ausdrückliche Nutzerfreigabe zu Aufträgen.

---

## 0. Grundlage dieses Abgleichs

**Abgeglichene Planquellen**

| Quelle | Ort | Einordnung |
|---|---|---|
| Big-Plan-Skill 1.4.0, WORKFLOWS 1.1.0, REFERENCES 1.1.0 | `~/.agents/skills/big-plan/` | Regeln und Zielbild. Bleiben gültig. Abschnitte zu AutoNext und Prioritäten werden durch diesen Plan präzisiert. |
| Koordinationsboard `482f593429ad` (Notes, 108 Einträge) | ThreadDesk, Operator-Workspace | Nutzerbeschlüsse 28.10. bis 07.11. Bleiben als Herkunft erhalten. |
| Entwicklungsboard `188ce4729a62` (578 Einträge) | ThreadDesk, Operator-Workspace | Arbeitsgedächtnis. Enthält `BIGPLAN-ABGLEICH-20261107`. |
| Produktboards `c2d4c7bc985a`, `911bb6f922e2`, `138fb6baeff2`, `dc200bb01137`, `a6fe31f58501`, `c9a396be4081`, `a17c937b7553`, `455dad75c60f`, `597fd5fcb040`, `30e962aaed81` | ThreadDesk | Produktbezogene Pläne und Beschlüsse. |
| `BIGPLAN-GESAMTPLAN-20261105.md` | KiraBridge `docs/plans/` | Bisher strukturiertester Gesamtplan (Pakete BP-…). Wird hier fortgeschrieben, nicht ersetzt. |
| `THREADDESK-KIRABRIDGE-PLAN-20261026.md`, `THREADDESK-GRAPH-PAPIERKORB-BEDIENUNG-20261026.md`, `PROJECT-*-20261106.md` | ThreadDesk `docs/plans/` | ThreadDesk-Fachpakete P01–P15 und B01 ff. |
| `docs/TEAMPLAN.md` (14.08.), `PLAN.md` | ThreadDesk | Historisch. |

**Am 08.11.2026 selbst geprüft (lesend)**

- GitHub: Default-Branches, letzte Commits, offene PRs, Releases und READMEs von
  `threaddesk`, `KiraBridge`, `4AllPass`, `tollgate`, `agent-authority-lab` und `threaddesk-server`.
- Debian-VServer `netcup` (Debian 13.6, x86_64): laufende Dienste, offene Ports,
  Docker-Container und Caddy-Routen. Es wurde nichts verändert.
- Intel-Mac: installierte Apps, launchd-Dienste, `bigplan-loop status`, lokale Worktrees.

**Nicht zugänglich:** das ChatGPT-Projekt „big plan“ und die dort liegenden Dateien
`Big_Plan_Ergaenzung_KiraBridge_2026-11-07.md` und `KiraBridge_Wiedereinstieg_2026-11-07.md`.
Ihr Inhalt ist nur über die Zusammenfassungen in den Boards eingeflossen.

---

## 1. Grundrichtung (unverändert)

1. **Fünf eigenständige Produkte**, einzeln nutzbar und über dokumentierte Schnittstellen verbunden:
   KiraBridge (Ausführung, Kommunikation, CLI-Steuerung), ThreadDesk (Gedächtnis, Projekte,
   Whiteboards, Graph, Server & Sync), 4AllPass (Identitäten und Geheimnisse), TollGate
   (API-Kosten, Budgets, Stopps), Agent Authority (ausschließlich lesende Beobachtung und Evidenz).
2. **MCP ist die gemeinsame Schnittstelle.** Bestehende Server und Adapter werden erweitert, nicht neu gebaut.
3. **Zielbild Remote:** Handy/ChatGPT → ThreadDesk Server & Sync → KiraBridge Server → Heimrechner
   → CLI-Agent → Ergebnis und Belege zurück in ThreadDesk. Eine Queue, ein Dispatcher, ein Kern.
4. **Acht CLI-Module** auf einem gemeinsamen Adapterkern, getrennt von OS-Adaptern für macOS, Windows und Linux.
5. **Windows für Dirk** hat hohe Priorität und wartet nicht auf alle acht CLI-Module.
6. **Belegpflicht:** Quelle, Test, Build, Installation, Veröffentlichung und echte Abnahme sind getrennte Zustände.
7. **OpenAI-Zulassung** ist der letzte Meilenstein (Beschluss 08.11.2026).

---

## 2. Ist-Stand je Produkt (08.11.2026)

| Produkt | GitHub `main` | Veröffentlicht | Installiert (Mac) | Server (netcup) | README sagt |
|---|---|---|---|---|---|
| **KiraBridge** (privat) | `50fb483` (08.11., PR #86) | macOS Intel RC36 · Linux RC41 (07.11.) · Windows nur rc37.dev1 / RC33 | `~/Applications/KiraBridge.app` 0.8.0 (RC40, 06.11.) | `kirabridge.service` (User) RC41 `350d368`, nur `127.0.0.1:8765`, kein öffentlicher Weg | macOS-Download RC36, Mac installiert RC40, Debian RC41, Windows-Vorschau rc37.dev1 |
| **ThreadDesk** (öffentlich) | `21fef21` (07.11., README/CI) | 0.1.1rc1 (Pre-release) · 0.1.1rc2 nur Entwurf | `/Applications/ThreadDesk.app` **0.2.0** und zusätzlich `~/Applications/ThreadDesk.app` 0.1.1-rc.2 sowie eine RC1-Test-App | `threaddesk-server.service` mit ungeversioniertem `serve_handoff.py`, öffentlich über Caddy `goodsrv.de:8443`; TLS-Proxy 8446 deaktiviert | „Aktuelle Desktop-Ausgabe 0.1.1rc1“; Handoff „für Gnom-Hub-V1“ |
| **ThreadDesk Server** (privat, `threaddesk-server`) | `1f993b1` (07.11.) | – | – | siehe oben | „bindet nur `127.0.0.1:8766`“ |
| **4AllPass** (öffentlich) | `99b92b1` (07.11.) | 0.1.2-rc.2 (18.10.), enthält laut README noch den alten Weg, der echte Geheimnisse als `access_token` ausgibt | `/Applications/4AllPass.app` 0.1.0 (28.09.) | Docker-Stack `4allpass-*` (Caddy, Web, Backend, Postgres, Redis); **Backend-Image vom 19.08.2026**; öffentlich unter `pass.netzwerkpunkt.de` | „Das Produkt ist die Desktop-App“ |
| **TollGate** (öffentlich) | `bc9739e` (07.11.), Version 1.0.12 | nur Ankündigungs-Release ohne Pakete | keine App | nur statische Webseite `tollgate.netzwerkpunkt.de`, kein Gateway | „Kein veröffentlichter Installer“ – stimmt |
| **Agent Authority** (privat, `agent-authority-lab`, Branch `master`) | `1e5a73d` (07.11.) | keine Releases | keine App installiert | `agent-authority-browser.service`, „private synthetic“, über Socket hinter Caddy | „Observer“; verlinkt auf KI-Zentrale D-012 |

**Koordination auf dem Mac:** `de.threaddesk.bigplan-coordinator` läuft, aber
`autonext.enabled = false` (`state: disabled`, `reason: not_started`). Vier frühere
Live-Karten stehen auf `held: outside_mandate`. `de.threaddesk.bigplan-reports` läuft.

**Server netcup, weitere Dienste:** zwei GitHub-Actions-Runner für KiraBridge,
`ki-hilfezentrum` und `kh-runtime-coordinator` (eigenes Projekt außerhalb der fünf),
`fail2ban`. Plattenbelegung 6 %. Im Home-Verzeichnis liegen 14 Testordner
`kb-debian-dirktest-*` und zwei weitere Smoke-/Verify-Ordner, einige mit
fehlerhaften Namen (`…%dirk`, `…%$dirk`).

---

## 3. Gefundene Widersprüche und ihre Auflösung

Schwere: **A** = Risiko für Sicherheit oder Daten · **B** = blockiert den Plan · **C** = Doku/Ordnung.

| Nr. | Schwere | Widerspruch | Auflösung |
|---|---|---|---|
| W01 | A | **4AllPass: veralteter Server und Desktop-Download mit bekannter Lücke.** (a) Server: Backend- und Web-Image vom 19.08.2026. In `main` liegen seitdem 33 Backend-Commits, darunter Härtungen für Auth und WebAuthn (#230–#237). Nachprüfung am 08.11.: Der Server ist nur das Zero-Knowledge-Sync-Backend (Konten, Geräte, Tresor-Snapshots). Der alte Weg für Geheimnisse an Maschinen fehlt dort im Backend und im ausgelieferten PWA-Bundle. (b) Der Desktop-Download RC2 enthält laut eigener README noch die frühere Ausgabe echter Tresorgeheimnisse als `access_token`. | **BP-SEC-01**: (b) zuerst mit Warnhinweis oder RC3, (a) als geplanter Neu-Rollout mit Sicherung. Kein Notfall-Abschalten nötig. |
| W02 | A | **Laufender Servercode liegt in keinem Repository.** `serve_handoff.py` auf dem Server patcht `handoffs.scoped_call` zur Laufzeit. Weder `threaddesk` noch `threaddesk-server` enthalten diesen Stand. | **BP-OPS-02**: Code in `threaddesk-server` übernehmen, prüfen, Dienst aus dem Repo-Pin starten. |
| W03 | B | **Mac-Sync-Relay zeigt ins Leere.** `~/.config/threaddesk-sync/http-relay.py` (launchd `com.landjunge.threaddesk-sync-relay`) spricht per SSH `https://127.0.0.1:8446` an. Der TLS-Proxy dort ist seit 08.11., 01:30 Uhr deaktiviert, Port 8446 lauscht nicht. Das Relay ist außerdem ein loses Skript außerhalb jedes Repos. | In **BP-OPS-02** entscheiden: Relay auf den öffentlichen Endpunkt 8443 umstellen oder entfernen. Danach als Teil des Desktop-Sync-Clients versionieren. |
| W04 | B | **Serverstand im Board ist überholt.** Board `c2d4c7bc985a` (07.11., 12:59) und README `threaddesk-server` sagen „nur Loopback, TLS 8446 aktiv“. Tatsächlich: Bindung `172.18.0.1:8766`, öffentlich über Caddy `:8443`, TLS-Proxy aus. | Mit **BP-TRUTH-01** (Ist-Stand-Register) beheben; README und Board korrigieren. |
| W05 | B | **Drei verschiedene „Priorität 1“.** 28.10.: KiraBridge stabilisieren. 05.11.: Remote-Kette Handy→Debian→Mac. 07.11. (Board 482f): (1) macOS-Terminal/MCP, (2) Debian-Tunnel, (3) Modularität. 07.11. (Board 188c): „Windowsinstaller zuerst, Debian-vor-Windows überholt“. | Neue Reihenfolge in Abschnitt 5. Windows ist im Quellstand fertig und braucht nur noch Veröffentlichung und Übergabe. Danach laufen macOS-Stabilität und Debian-Tunnel parallel. Beide führen in die Remote-Kette. |
| W06 | B | **„WINDOWS-FERTIG“ ohne Auslieferung.** PR #74 ist gemergt (07.11.), das native RC41-Paket liegt lokal. Auf GitHub gibt es keinen Windows-RC41-Release. Die README verweist weiter auf rc37.dev1 und RC33. Dirks Windows-Version und Architektur sind nicht geprüft. Das Repo ist privat, Downloads brauchen Zugang. | **BP-WINDOWS-02** abschließen: Release, Zugang für Dirk, Prüfliste, README. |
| W07 | B | **AutoNext gilt im Skill als aktiv, ist aber aus.** Der Skill beschreibt eine eigenständige Fortsetzung. `bigplan-loop status` meldet `autonext disabled / not_started`. | **BP-AUTO-01**: AutoNext mit einem kleinen, freigegebenen Katalog einschalten und den Skill an den tatsächlichen Zustand anpassen. |
| W08 | B | **KiraBridge-Server ist nicht vom Mac unabhängig erreichbar.** Ziel vom 07.11.: Debian-Tunnel mit ausgeschaltetem Mac abnehmen. PR #85 (Tunnel-Doku) ist offen, beide CI-Läufe scheitern, der Test mit ausgeschaltetem Mac fehlt. | **BP-DEBIAN-02**. |
| W09 | B | **Ort des ThreadDesk-Servers.** Der Gesamtplan sagt „ThreadDesk Server bleibt im ThreadDesk-Repository“. Seit 07.11. gibt es das private Repo `threaddesk-server`, die öffentliche Quelle enthält den Servercode aber weiterhin. Zwei Quellen driften auseinander. | Entscheidung **E2**. Vorschlag: `threaddesk-server` wird der einzige Ort für Serverbetrieb und Packaging; der gemeinsame Sync-Kern bleibt im öffentlichen Repo und wird per Pin eingebunden. |
| W10 | C | **ThreadDesk-Versionen.** README: 0.1.1rc1. GitHub: 0.1.1rc2 nur Entwurf. Installiert: 0.2.0 (PR #95, 30.10., unveröffentlicht) plus zwei ältere Apps parallel. | **BP-TD-REL-01**: 0.2 veröffentlichen, README korrigieren, Altinstallationen sichern und entfernen. |
| W11 | C | **ThreadDesk-Arbeitsregeln widersprechen dem Big Plan.** `AGENTS.md` (26.10.) erlaubt nur ThreadDesk-Arbeit, keine KiraBridge-Pakete. `docs/TEAMPLAN.md` (14.08.) beschreibt noch das MVP. Die README nennt Gnom-Hub-V1 als Handoff-Ziel. | **BP-PLAN-01**: `AGENTS.md` auf den Fünf-Produkte-Auftrag verweisen lassen, `TEAMPLAN.md` als historisch markieren, README auf KiraBridge als Übergabeweg umstellen. |
| W12 | C | **Rollen der Agenten sind uneinheitlich.** Boardbeschreibung: „KiraBridge (Codex), ThreadDesk (Grok)“. 04.11.: Codex Hauptarbeit, Grok sparsam für Reviews. 07.11.: „Claude entwickelt, Kira prüft“. Continuation-Profil: „Codex koordiniert, Grok implementiert mit high“. | Rollen gehören zu **Lanes**, nicht zu Produkten (Abschnitt 6). Die Auswahl je Paket trifft die Koordination nach WORKFLOWS W5. |
| W13 | C | **CLI-Reihenfolge.** Skill: acht Module fest. 04.11.: zuerst Claude Code und OpenCode. 05.11.: Phase 1 sind Codex, Grok, Claude Code, Gemini und Cursor. KiraBridge-README nennt nur Codex und Grok. | Gilt der jüngste Beschluss vom 05.11. Drei Wellen, siehe **BP-CLI-01** bis **-03**. Die README nennt nur, was abgenommen ist. |
| W14 | C | **Agent Authority: Produkt oder Labor?** Big Plan: eines der fünf Produkte. Repo heißt `agent-authority-lab`, Beschreibung „Experimental security lab … Prototype v0.2“, Branch `master`. Die README verlinkt die KI-Zentrale, die laut REFERENCES nicht herangezogen werden soll. Schreibweise wechselt zwischen „AgentAuthority“ und „Agent Authority“. | Entscheidung **E3** (Produktname und Repo-Beschreibung). Den Link auf die KI-Zentrale durch eine eigene Entscheidungsnotiz im Repo ersetzen. |
| W15 | C | **Design.** 07.11.: KiraBridge-Design zurückgestellt (PR #73 Entwurf). 08.11.: verbindliche Designleitlinie für alle fünf Tools. | Kein Widerspruch in der Sache, nur im Zeitpunkt. **BP-DESIGN-01** kommt nach der Stabilisierung. Die Icon-Sammlung ist schon vorbereitet. |
| W16 | C | **OpenAI-Zulassung.** 07.11.: „ausdrücklich NICHT Big Plan“. 08.11.: „letzter Meilenstein im Big Plan“. | Der Beschluss vom 08.11. gilt (**BP-OPENAI-01**). |
| W17 | C | **README-Kopf und offene README-PRs.** Die README-PRs vom 01.11. (TD #98, 4AP #250, AA #53, KB #55) sind offen. Am 07.11. wurden READMEs aber direkt auf `main` geändert. 4AllPass und Agent Authority haben kein `README.de.md`. Die Lizenz-PRs (#96, #47, #249, #38, #52) liegen seit dem 27.10. als Entwurf. | **BP-DOC-01**: alte PRs schließen oder neu aufsetzen, Lizenztexte in einem Durchgang vereinheitlichen. |
| W18 | C | **KiraBridge-Quellpin uneinheitlich.** README: installiertes RC40 aus `d12838a`. Board: RC40 aus `a5d381a`. `main` ist inzwischen weiter (PR #83 Latenz, #84, #86). | Mit **BP-TRUTH-01** auflösen; Mac-Runtime über **BP-KB-REL-42** auf den aktuellen Stand bringen. |
| W19 | C | **Arbeitsstände sind unübersichtlich.** KiraBridge: 163 Worktrees und 182 lokale Branches. ThreadDesk: 38 Worktrees. Die Haupt-Worktrees stehen auf alten Branches (4AllPass 115 Commits hinter `main`, Agent Authority 295, ThreadDesk mit 22 offenen Änderungen). | **BP-HYG-01** nach den AGENTS-Regeln: sichern, dann in den Papierkorb, nichts erzwingen. |

---

## 4. Modulkarte (bestehend und ergänzt)

### 4.1 Produktmodule

| Produkt | Vorhanden (belegt) | Offen im bisherigen Plan | **Neu ergänzt** |
|---|---|---|---|
| KiraBridge | MCP-Bridge, TaskManager/Policies, TeamDispatcher, MessageReceiver, AutoNext-Kern, Coordinator-Loop, Codex- und Grok-Adapter, Win32-Grundlagen, Debian-Server-Profil, Remote-Task-Vertrag v1, Peer/Relay (lokal geprüft) | CLI-Module 3–8, Windows-Parität, Remote-Abnahme, Ocean-Adapter | **Geräte-Pairing und Widerruf** als eigenes Modul (bisher nur Teil von BP-DEBIAN-01) · **Update-Kanal** für Mac, Windows und Linux · **Code-Signierung/Notarisierung** (nirgends belegt) |
| ThreadDesk | Threads, Snapshots, Wissen, Bibliothek, Graph mit Aktivität, Papierkorb, Backup v3 (0.2), dynamischer MCP-Katalog (PR #97), Projektgedächtnis/Planrevision (PR #99), Server & Sync | ChatGPT-Bedienbarkeit jeder Fachaktion (P15), Handoff-HTTP produktiv, Offline-Option für Desktop-Nutzer | **Ist-Stand-Register** (Abschnitt 4.2) · **Sync-Client** als versioniertes Desktop-Modul statt loser Relay-Skripte · **Mehrnutzer** auf dem Server |
| 4AllPass | Tresor, PWA, Browser-Erweiterung, geschützter Executor-Vertrag (synthetisch), Broker-Ereignisse G5 | Geschützte Nutzung durch Agenten (BP-4AP-01) | **Patch- und Deploymentkette für die Produktion** · Rückruf/Warnhinweis für Releases mit Sicherheitslücke |
| TollGate | Gateway, MCP, n8n, WorkflowControl (Reserve/Dispatch/Settlement), persistente Stopps | Bindung an einen echten Providerweg (BP-TG-01) | **Betriebsprofil**: lokal neben KiraBridge oder auf dem Server – bisher nirgends festgelegt (Entscheidung E4) |
| Agent Authority | Observer-CLI, HTML-Bericht, native macOS-App, Warnregeln, Browserzweig auf dem Server | Live-Beobachtung der Remote-Kette (BP-AA-01) | **Ereignis-Einspeisung** aus KiraBridge und ThreadDesk über das vorhandene Authority Event Envelope v1 (`threaddesk/docs/authority/`) |

### 4.2 Querschnittsmodule (neu)

| Modul | Zweck | Begründung aus dem Abgleich |
|---|---|---|
| **X1 Ist-Stand-Register** | Eine maschinenlesbare Datei je Produkt (`STATUS.json`) mit Quellpin, Build, installierter Version (Mac/Windows/Server), veröffentlichtem Release und letzter echter Abnahme. Boards, READMEs und Koordinator lesen daraus, statt Prosa abzuschreiben. | W04, W10, W18: Board, README und Wirklichkeit weichen bei fast jedem Produkt voneinander ab. |
| **X2 Server-Betrieb** | Inventar als Datei im Repo, gemeinsamer Ingress, Deploy nur aus Repo-Pins, Backups, Health-Checks, Aufräumen von Testresten. | W01–W04: Code ohne Repo, deaktivierter Dienst, veraltetes Image. Alle öffentlichen Routen hängen am Caddy im 4AllPass-Compose-Stack. |
| **X3 Sicherheitsbasis** | Patchstand je Dienst, Dependabot und Advisories (offen: glib RUSTSEC-2024-0429 in TD/Tauri), Abhängigkeits-PRs, Trennung von CI-Runnern und Produktionsdaten. | W01. Zwei Runner für das private KiraBridge-Repo laufen auf demselben Host wie die 4AllPass-Datenbank. |
| **X4 Auslieferung und Distribution** | Releases, Zugang für externe Tester (Dirk), Signierung, Prüfsummen, Webseiten (netzwerkpunkt.de), Downloadlinks in READMEs. | W06, W10. Das private KiraBridge-Repo blockiert die Weitergabe. `KiraBridge-public` steht seit 21.10. bei RC12. |
| **X5 Plan-Governance** | Ein kanonischer Plan (diese Datei), datierte Nachträge, Kurzfassung im Board. Der Skill verweist hierher. | Der Plan ist heute auf ChatGPT-Bibliothek, Skill, zwei Boards und Dokumente in zwei Repos verteilt (W05, W11, W16). |
| **X6 Arbeitsstand-Hygiene** | Regelmäßiges Aufräumen von Worktrees und Branches nach den AGENTS-Regeln. | W19. |

---

## 5. Priorisierter Bauplan

Die Reihenfolge folgt vier Regeln:

1. Sicherheit und Wahrheit vor neuen Funktionen.
2. Fast fertige Lieferungen vor neuen Baustellen.
3. Die Remote-Kette ist das strategische Kernziel; alles davor bereitet sie vor.
4. Breite (weitere CLIs, Produktanschlüsse, Design) erst auf einem stabilen Kern.

Aufwand: **S** bis 1 Tag · **M** 2–4 Tage · **L** mehr als 1 Woche (Agentenarbeit, grob geschätzt).
Bestehende Paket-IDs aus dem Gesamtplan werden weiterverwendet.

### Stufe 0 – Sicherheit und Wahrheit (sofort)

| ID | Ziel | Abnahme | Aufwand | Abhängig |
|---|---|---|---|---|
| **BP-SEC-01** 4AllPass | Erledigt am 08.11.: Prüfung, ob der alte Geheimnisweg auf dem Server erreichbar ist. Er ist es nicht. Offen: (1) RC2-Release und README mit Warnhinweis versehen oder RC3 aus `main` veröffentlichen. (2) Server aus einem geprüften `main`-Pin neu ausrollen, vorher Postgres sichern und das Rückspielen prüfen. | Desktop-Download ohne alten Weg. Server-Images entsprechen einem benannten Pin. Login und Sync danach mit Testkonto geprüft. | M | E1 |
| **BP-OPS-01** Server-Inventar | Dienste, Ports, Routen, Pfade und Verantwortliche des VServers als `ops/netcup.json` in einem privaten Repo. Testordner `kb-debian-dirktest-*` sichern und entfernen. | Inventar stimmt mit `systemctl`, `ss` und Caddy überein. Ein Prüfskript meldet Abweichungen. | S | – |
| **BP-OPS-02** ThreadDesk-Server in Ordnung bringen | `serve_handoff.py` als richtige Funktion in `threaddesk-server` übernehmen (kein Monkey-Patch), testen, Dienst aus dem Repo-Pin starten. TLS-Proxy endgültig entfernen oder wieder einschalten. Mac-Relay umstellen oder entfernen. README und Board korrigieren. | Dienst läuft aus Pin X. `/health` antwortet. Sync vom Mac funktioniert wieder (Readback eines Testobjekts). Kein Code außerhalb eines Repos. | M | E2 |
| **BP-TRUTH-01** Ist-Stand-Register | `STATUS.json` je Produkt einführen und einmal befüllen. Kleines Prüfskript vergleicht mit GitHub, Mac und Server. | Alle fünf Produkte plus Server haben eine aktuelle Datei. Abweichungen W04, W10 und W18 sind aufgelöst. | M | BP-OPS-01 |
| **BP-PLAN-01** Plan-Governance | Diesen Plan als kanonisch festlegen. Skill 1.5.0 verweist hierher und gibt den AutoNext-Zustand korrekt an. ThreadDesk-`AGENTS.md` und `TEAMPLAN.md` anpassen. Kurzfassung als Eintrag in Board `482f593429ad`. | Ein Agent findet von jedem Einstieg (Skill, Board, Repo) in höchstens einem Schritt diesen Plan. | S | – |

### Stufe 1 – Fast fertige Lieferungen abschließen

| ID | Ziel | Abnahme | Aufwand | Abhängig |
|---|---|---|---|---|
| **BP-WINDOWS-02** Dirk-Paket | Das nativ geprüfte Windows-RC41-Paket (Quelle `818fbac`, Main `a81cd10`) als Release veröffentlichen. Zugang für Dirk klären. Dirks Windows-Version und Architektur abfragen. Prüfliste DE/EN, README aktualisieren. | Release mit Prüfsumme. Download erneut geladen und Hash geprüft. Dirk hat Zugang und Prüfliste. Rückmeldekanal steht. | S | E5 (Zugang) |
| **BP-DEBIAN-02** Server-Tunnel | PR #85 reparieren (CI rot) und mergen. Tunnel einrichten. `bridge_health` und eine `td_*`-Abfrage aus ChatGPT mit **ausgeschaltetem Mac**. | Mitschnitt des Aufrufs mit Zeitstempel bei ausgeschaltetem Mac. Gleiche Abfrage nach Neustart des Dienstes. | M | BP-OPS-02 |
| **BP-KB-REL-42** macOS-Stabilität | Aktuellen `main` (u. a. Katalog-Latenz PR #83, PR #84, #86) als RC42 bauen und installieren. Terminal-, MCP- und Tastaturabläufe mit Zeiten messen. Offene Abnahme aus RC39 nachholen: Return, Antwort, `/status`, `/model`, Fokus- und Tabwechsel direkt aus dem Chat. | Installierte Runtime entspricht `main`. Messwerte vorher/nachher. Chat-Abnahme ohne manuelles Return. | M | – |
| **BP-TD-REL-01** ThreadDesk 0.2 | 0.2 (Papierkorb, Aktivitätsgraph, Backup v3, dynamischer MCP) als Release veröffentlichen. README-Version korrigieren. Doppelte Installationen sichern und entfernen. Handoff-Text in der README von Gnom-Hub auf KiraBridge umstellen. | Ein ThreadDesk.app auf dem Mac mit Daten unverändert. README und Release stimmen überein. | S | – |

### Stufe 2 – Die Remote-Kette (Kernziel)

| ID | Ziel | Abnahme | Aufwand | Abhängig |
|---|---|---|---|---|
| **BP-PAIR-01** Geräte-Pairing | Heimgerät meldet sich beim KiraBridge-Server mit eigenem, widerrufbarem Geräteschlüssel. Auftrag bindet Gerät und Scope (Vertrag `remote-task-v1`). | Pairing, Widerruf, falsches Gerät und abgelaufene Freigabe als Tests. Nach Widerruf keine Ausführung. | M | BP-DEBIAN-02 |
| **BP-AUTO-01** AutoNext einschalten | Kleinen, ausdrücklich freigegebenen Katalog anlegen und AutoNext einschalten. Leerer Katalog startet nichts. Unklare Wirkung wird nicht wiederholt. | Zwei freigegebene Testkarten laufen je genau einmal. Eine nicht freigegebene wird nicht angefasst. Neustart ohne Replay. | S | BP-KB-REL-42 |
| **BP-REMOTE-03** echte mobile Abnahme | Vom Handy über ThreadDesk Server (8443) und KiraBridge Server einen harmlosen Auftrag an den Heim-Mac geben. Ergebnis mobil im selben Thread lesen. Danach mit ausgeschaltetem Mac: Auftrag bleibt sichtbar „nicht übernommen“. | Ein Auftrag, ein Claim, ein Ausführungsversuch, Readback am Handy. Offline-Fall korrekt angezeigt. | M | BP-PAIR-01, BP-AUTO-01, BP-OPS-02 |
| **TD-P15** ChatGPT-Bedienbarkeit | Jede ThreadDesk-Fachaktion (Graph, Suche, Dateien, Papierkorb, Snapshots, Projekte) über KiraBridge aus ChatGPT ausführen und zurücklesen. | Liste je Aktion: Erfolg, Konflikt, Wiederholung, Readback. Fehlende Weiterleitungen als KB-Pakete erfasst. | M | BP-KB-REL-42 |

### Stufe 3 – CLI-Breite und Plattformen

| ID | Ziel | Abnahme | Aufwand | Abhängig |
|---|---|---|---|---|
| **BP-CLI-01** Welle 1: Claude Code | Drittes Modul neben Codex und Grok auf dem gemeinsamen Adapterkern: Login und Version ohne Modellkosten feststellen, kleinste echte Route. | Auftrag, Return, Antwort, Abbruch und Rückkehr je Route belegt. | M | BP-KB-REL-42 |
| **BP-CLI-02** Welle 2: Gemini, Cursor | Gleiches Verfahren. Zugang vorher klären, keine neuen API-Kosten. | wie oben | M | BP-CLI-01 |
| **BP-WINDOWS-03** Parität | Nach Dirks Rückmeldung fehlende Terminal- und Sitzungsfunktionen im Windows-Adapter ergänzen. Codex und Grok unter Windows nativ prüfen. | Prüfliste in der VM und bei Dirk getrennt ausgewiesen. | L | BP-WINDOWS-02 |
| **BP-LINUX-01** Linux-Fähigkeiten | Desktop- und Headless-Fähigkeiten getrennt ausweisen. | Eigene Linux-Ergebnisse, kein Mac-Ergebnis als Linux-Beleg. | M | BP-DEBIAN-02 |

### Stufe 4 – Produktanschlüsse

| ID | Ziel | Abnahme | Aufwand | Abhängig |
|---|---|---|---|---|
| **BP-AA-01** Beobachtung der Remote-Kette | KiraBridge und ThreadDesk senden Ereignisse im Authority Event Envelope v1. Agent Authority zeigt die Kette Handy → Server → Mac → Agent → Rückgabe. Nur lesend. | Bericht zu einem echten BP-REMOTE-03-Lauf mit Lücken als „unbekannt“ markiert. | M | BP-REMOTE-03, E3 |
| **BP-TG-01** erste Budgetbindung | Einen quotierbaren API-Weg (kein Abo) über TollGate führen: Reserve, Dispatch, Settlement, Stopp. Betriebsort festlegen. | Harter Stopp bei Budgetende im echten Lauf. Unklare Abrechnung wird als unklar ausgewiesen. | M | E4 |
| **BP-4AP-01** geschützte Nutzung | Agent erhält einen einzeln erlaubten Zugang über den geschützten Executor, nie das Rohgeheimnis. | Negativtests: kein Geheimnis in Log, Board oder Prompt. Widerruf wirkt sofort. | L | BP-SEC-01 |

### Stufe 5 – Auftritt und Ordnung

| ID | Ziel | Abnahme | Aufwand | Abhängig |
|---|---|---|---|---|
| **BP-DESIGN-01** gemeinsames Designsystem | ThreadDesk-Dunkelthema als Vorlage, Konturen in der jeweiligen Markenfarbe, gleiche Icons in Kopfzeile, App, Dock und Installer. Icons aus Board `a17c937b7553`. | Screenshots je Produkt und Plattform, 48-px-Lesbarkeit geprüft. | M | Stufe 1 |
| **BP-DOC-01** READMEs und Lizenzen | Offene README- und Lizenz-PRs schließen oder neu aufsetzen. Kopf nach WORKFLOWS W3 in allen fünf. Angaben aus `STATUS.json`. | Alle Downloadlinks geprüft. Keine Versionsangabe ohne Release. | S | BP-TRUTH-01 |
| **BP-PUBLIC-01** öffentliches Schaufenster KiraBridge | Öffentliches Repo mit Beschreibung, Demo, Roadmap und Feedbackkanal. Privates Entwicklungsrepo bleibt privat (Beschluss 07.11.). | Seite öffentlich, keine internen Daten, Aussagen gegen `STATUS.json` geprüft. | S | BP-DOC-01 |
| **BP-HYG-01** Arbeitsstände | Worktrees und Branches nach den AGENTS-Regeln sichern und aufräumen. Haupt-Worktrees auf `main` zurückführen, nachdem fremde Änderungen gesichert sind. | Höchstens eine Handvoll aktiver Worktrees je Repo, Sicherungsliste dokumentiert. | M | – |

### Stufe 6 – Erweiterung und Abschluss

| ID | Ziel | Aufwand | Abhängig |
|---|---|---|---|
| **BP-CLI-03** Welle 3: OpenCode, Copilot CLI, Aider | L | BP-CLI-02 |
| **BP-MULTI-01** Mehrnutzer auf ThreadDesk Server und KiraBridge Server | L | BP-REMOTE-03 |
| **OCEAN-01** Ocean-Adapter, sobald Testzugang und Speicherverträge geklärt sind | L | Zugang über Dirk |
| **BP-OPENAI-01** OpenAI-Zulassung: Bestandsaufnahme, Sicherheitsabnahme, Minimalrechte, MCP-Abnahme, Unterlagen, Einreichungsweg | L | alles davor |

### Kritischer Pfad

```
BP-OPS-01 ─► BP-OPS-02 ─► BP-DEBIAN-02 ─► BP-PAIR-01 ─┐
                                                       ├─► BP-REMOTE-03 ─► BP-AA-01
BP-KB-REL-42 ─► BP-AUTO-01 ────────────────────────────┘
```

Neben dem kritischen Pfad laufen BP-SEC-01, BP-WINDOWS-02 und BP-TD-REL-01. Sie
berühren andere Dateien und Dienste.

---

## 6. Lanes statt fester Agentenrollen

Je Lane gibt es einen Schreiber. Die Koordination wählt Agent, Modell und
Denkstufe je Paket nach WORKFLOWS W5. Reviews macht immer ein anderer Agent als der Autor.

| Lane | Pakete | Gemeinsame Ressource, die abgestimmt werden muss |
|---|---|---|
| L1 Server & Sicherheit | BP-SEC-01, BP-OPS-01/02, BP-DEBIAN-02, BP-PAIR-01 | VServer, Caddy, 4AllPass-Datenbank |
| L2 KiraBridge macOS | BP-KB-REL-42, BP-AUTO-01, BP-CLI-01/02 | installierte Mac-Runtime, sichtbare Terminals |
| L3 Windows | BP-WINDOWS-02/03 | Windows-VM |
| L4 ThreadDesk | BP-TD-REL-01, TD-P15, BP-TRUTH-01 | installierte ThreadDesk-App und Nutzerdaten |
| L5 Produktanschlüsse | BP-AA-01, BP-TG-01, BP-4AP-01 | ab Stufe 4 |
| L6 Doku & Auftritt | BP-PLAN-01, BP-DOC-01, BP-DESIGN-01, BP-PUBLIC-01 | READMEs aller Repos |

In Stufe 0 und 1 können L1, L2, L3 und L4 gleichzeitig arbeiten.

---

## 7. Entscheidungen, die beim Nutzer liegen

| Nr. | Frage | Vorschlag |
|---|---|---|
| E1 | 4AllPass: RC2 zurückziehen oder RC3 veröffentlichen, und wann wird der Server neu ausgerollt? | RC2 sofort mit Warnhinweis versehen, RC3 aus `main` bauen. Server danach in einem angekündigten Wartungsfenster mit Sicherung neu ausrollen. |
| E2 | Wo lebt der ThreadDesk-Server? | `threaddesk-server` für Betrieb und Packaging, Sync-Kern weiter im öffentlichen Repo per Pin. |
| E3 | Agent Authority: Produktname, Repo-Beschreibung, Default-Branch. | Produktname „Agent Authority“, Repo-Beschreibung auf Beobachtungsprodukt ändern, Labor-Historie im README behalten. |
| E4 | TollGate-Betriebsort | Zunächst lokal neben KiraBridge, Server später. |
| E5 | Wie bekommt Dirk das Windows-Paket? | Einzelner Collaborator-Zugang oder Release im öffentlichen Schaufenster-Repo. |

---

## 8. Pflege dieses Plans

- Neue Nutzerbeschlüsse werden als datierter Nachtrag unten angefügt. Ältere Abschnitte werden nicht still umgeschrieben.
- Status je Paket steht im Board `188ce4729a62` mit Paket-ID. Der Plan selbst enthält keine Fortschrittsprosa.
- Versionen und Installationsstände stehen nur im Ist-Stand-Register (X1), nicht in Plan oder README-Text.
- Historische Pläne bleiben unverändert und verweisen hierher: `BIGPLAN-GESAMTPLAN-20261105.md`, `TEAMPLAN.md`, `PLAN.md`.

## Nachträge

### N1 · 08.11.2026 – Plan-Governance, Entscheidungsnamen, Agentenlage

**Kanonischer Einstieg.** Dieser Bauplan ist der kanonische Plan (BP-PLAN-01).
`BIGPLAN-GESAMTPLAN-20261105.md` Abschnitt 9 (verknüpfte ThreadDesk-Threads,
Pakete BP-CLI-02, BP-COORD-02, BP-SANDBOX-01, BP-LAUNCHER-01, BP-TD-*, BP-AA-02,
BP-OPENAI-99) gilt als Teil dieses Plans. Beide Dateien werden nur durch datierte
Nachträge fortgeschrieben.

**Kollision der Entscheidungskennungen.** Abschnitt 7 hier und Gesamtplan 9.9
verwenden beide „E1 …“, meinen aber verschiedene Fragen. Ab jetzt gilt:

| Kennung | Bedeutung | Stand 08.11. |
|---|---|---|
| **E1–E5** (dieser Plan, Abschnitt 7) | 4AllPass-RC2/RC3 und Server-Rollout · Ort des ThreadDesk-Servers · Agent-Authority-Name · TollGate-Betriebsort · Dirks Zugang | **offen**, Vorschläge in Abschnitt 7 |
| **G9.9-E1 … G9.9-E6** (Gesamtplan 9.9) | Übernahmen gelten · acht CLIs · Automatik nur im freigegebenen Rahmen · AA strikt lesend · Graph liest erst vorhandene Links · Reihenfolge | **entschieden** |
| **W6** (Gesamtplan 9.7) | VServer-Zuständigkeit | **offen**; bis dahin keine produktiven Serveränderungen (G5) |

**Agentenlage ab 08.11.2026 (Nutzervorgabe).** Es steht nur Claude zur Verfügung.
Codex und Grok fallen als Autoren und Reviewer aus. Das ändert Abschnitt 6 so:

- Jede Lane wird von einem eigenen Claude-Teilagenten in einem eigenen Worktree
  bearbeitet. Weiterhin gilt: ein Schreiber je Worktree.
- „Review durch einen anderen Agenten als den Autor“ wird durch die
  Claude-Organisatorsitzung erfüllt, die nicht selbst geschrieben hat.
  Das ist eine schwächere Unabhängigkeit als ein Review durch einen anderen Anbieter
  und wird im jeweiligen PR so benannt.
- Parallele Arbeit ist ausdrücklich erwünscht.

**Gestartete Lanes (Organisator Claude, 08.11.2026 abends).** Reihenfolge nach G9.9-E6:

| Lane | Paket | Umfang dieses Laufs |
|---|---|---|
| L1/L2 | BP-DEBIAN-02 (Teil) | PR #85 CI reparieren; Blocker `com.kirabridge.chat-events` diagnostizieren und versionieren. Kein Servereingriff. |
| L2 | BP-KB-REL-42 | RC42 aus `main` bauen, isoliert abnehmen. Mac-Installation nur, wenn alle Gates grün sind. |
| L2 | BP-CLI-02 Phase 1 | Bestandsabgleich der acht CLIs, nur lesend, ohne Modellkosten. |
| L1 | BP-OPS-01 | Server-Inventar `ops/netcup.json` plus Prüfskript, nur lesend. |
| L1 | BP-SEC-01 (b) | 4AllPass: Hinweis zu RC2 in der README, Release-Text als Datei. Die Release-Bearbeitung entscheidet der Nutzer. |
| L4 | BP-TD-KONSOL-01 | Lesende Bestandsaufnahme der Threads, Vorarbeit für BP-TD-GRAPH-01. |
| L4/L6 | BP-TD-REL-01 (Vorbereitung), BP-PLAN-01 (ThreadDesk) | README-Version und Handoff-Text, AGENTS-Verweis, historische Pläne markieren, 0.2-Notizen. |

Nicht gestartet, weil Freigabe oder Zuständigkeit fehlt: BP-OPS-02 (W6), BP-SEC-01 (a)
Server-Rollout (E1), BP-WINDOWS-02 Versand an Dirk (E5), BP-AUTO-01 (wartet auf RC42),
alle Releases mit Außenwirkung.

### N2 · 08.11.2026 – W6 entschieden: VServer-Zuständigkeit

**Entscheidung des Nutzers (08.11.2026):** „W6 übernimmst du auch.“ Damit ist die
Claude-Organisatorsitzung ab sofort **alleinige Ownerin und einzige Schreiberin** des
VServers `netcup` (Root-Zugang `netcup`, Nutzer `daniel` über `netcup-daniel`).
Sie folgt auf die beiden Codex-Sitzungen „Luna“ (Installationsschreiber RC41) und
Serverowner 11907. Deren beidseitige Übergabe kam nicht mehr zustande; beide
Sitzungen stehen nicht mehr zur Verfügung (Nutzervorgabe N1: nur Claude).

Grundlage der Übernahme:

- Übergabemappe `~/.local/state/vserver-production-handoff-20261107/handoff-readonly.md`,
  SHA256 `ebcfaa71edf73cbeda83e475489eb4977f73fc9543b24a585ce6325b50c27b33`, frisch gelesen.
- Lesende Prüfung am 08.11., 18:05 MEZ: auf dem Server läuft kein Codex-, Grok- oder
  Luna-Prozess. Es gibt also keinen zweiten aktiven Schreiber.
- Die Bedingung „erst nach Windows-Abschluss“ aus `VSERVER-PRODUCTION-GATE-WINDOWS-PENDING-20261107`
  ist erfüllt: PR #74 ist gemergt (`a81cd10`), das Gate WINDOWS-FERTIG ist im Board belegt.

Regeln für den Betrieb ab jetzt:

1. G5 gilt weiter. Entwicklungs-Teilagenten arbeiten nicht auf dem Produktivhost. Sie
   dürfen dort nur lesen. Produktive Änderungen macht allein die Ownerin, nur aus
   Repo-Pins, mit Sicherung vorher, Rückweg und Readback danach.
2. Vor der ersten produktiven Änderung liegt das Inventar aus BP-OPS-01 vor.
3. Offene Owneraufgaben aus der Mappe: Zugangspfad `credentials.json` gegen `secrets.env`
   abgleichen; Qualität der Sicherung `20261107-151533-486c1abc` prüfen; Testordner
   `kb-debian-dirktest-*` sichern und erst dann entfernen.

Damit freigegeben: BP-OPS-02, BP-DEBIAN-02 (Tunnel), BP-PAIR-01 und das Konzept für
BP-SANDBOX-01. Weiter getrennt freizugeben ist der Neu-Rollout des 4AllPass-Servers (E1),
weil er Nutzerkonten betrifft.

**Korrektur zu Abschnitt 2:** Die installierte Mac-CLI läuft aus
`0.8.0rc41-c81430b88738`, nicht aus RC40. Gilt bis zum Ist-Stand-Register (BP-TRUTH-01).

### N3 · 09.11.2026 – Kurzabgleich und Reihenfolge

Organisator Claude, Nutzerauftrag „Big Plan kurz überarbeiten, dann abarbeiten“.
Paketstatus mit Belegen steht im Board `188ce4729a62`. Hier nur, was die Reihenfolge ändert.

**Abgeschlossen seit N1:** BP-OPS-01 (KB #98), BP-CLI-02 Phase 1 (KB #99),
PR #85 Debian-Fernzugang gemergt, BP-SEC-01 (b) Hinweis und RC3-Entwurf (4AllPass #258),
ThreadDesk-Doku für BP-TD-REL-01/BP-PLAN-01 (TD #105), Berichts-Dedupe (TD #106),
TD-Peer-Recovery (KB #104). RC42 wird nicht installiert. Er ist durch RC43 (`eb2038d`) ersetzt.

**Jetzt in Arbeit:**

| Lane | Paket | Umfang |
|---|---|---|
| L2 | BP-KB-REL-42 | RC43 headless abnehmen und installieren. Die Chat-Abnahme mit sichtbaren Terminals bleibt ein eigener Schritt. |
| L4 | BP-TRUTH-01 | `STATUS.json` je Produkt, Schema `status-v1`, Prüfskript in ThreadDesk |

**Wartet auf Nutzerfreigabe:** BP-OPS-02 Phase B, also das Umschalten des
ThreadDesk-Servers auf Release `7a456e2` (Phase A ist abgeschlossen). Außerdem
BP-AUTO-01 (Testkarten), BP-TD-REL-01 (Veröffentlichung 0.2) sowie E1 und E5.

**Danach auf dem kritischen Pfad:** BP-DEBIAN-02 Tunnelabnahme mit ausgeschaltetem Mac
(nach OPS-02 B), dann BP-AUTO-01 (nach RC43), BP-PAIR-01 und BP-REMOTE-03.

**Arbeitsregel ab 09.11.:** Keine Fensterflut. Teilagenten und Prüfungen arbeiten headless,
ohne neue Terminal-, App- oder Browserfenster. Abnahmen mit sichtbaren Fenstern werden
gebündelt und einzeln angekündigt.

### N4 · 09.11.2026 – Dauerregel: sparsam arbeiten

Nutzervorgabe (09.11.2026): Im Big Plan wird **immer sparsam** gearbeitet. Das gilt für
Token, Modellkosten und Nutzungslimits.

- Die Koordination liest gezielt: Board, kanonischen Plan und die betroffenen Dateien.
  Sie liest keine ganzen Historien und keine Rohtranskripte.
- Nur so viele Teilagenten wie nötig. Leichte Arbeit (Doku, Inventar) läuft auf einem
  kleineren Modell, Sicherheit, Installation und Review auf dem stärkeren.
- Berichte sind kurz: Ergebnis, Pins, Belege, Offenes. Keine Wiederholung bekannter Stände.
- Wird ein Limit knapp, startet keine neue Lane. Laufende Lanes werden nur abgeschlossen.

### N5 · 09.11.2026 – Governance: ThreadDesk ist die einzige maßgebliche Quelle

**Nutzerbeschluss (09.11.2026, verbindlich):** „ThreadDesk ist ab sofort die einzige maßgebliche Quelle für den Big Plan und das zentrale Projektgedächtnis. GitHub dient ausschließlich der technischen Entwicklung und Umsetzung. Die ChatGPT-Bibliothek bleibt als Backup erhalten.“ Dazu die Korrektur des Nutzers: „Der Big Plan war immer in ThreadDesk.“

**Maßgeblicher Ort:** ThreadDesk-Thread `188ce4729a62` (Notizabschnitte „BIG PLAN …“ und Whiteboard) samt verknüpften Plan-Threads. Es gibt keinen zweiten Plan-Thread. Der Inhalt dieser Datei und von Gesamtplan Abschnitt 9 wurde dort am 09.11.2026 unverändert als Abschnitt „BIG PLAN – RÜCKFÜHRUNG AUS GITHUB, 09.11.2026“ ergänzt, zusammen mit der Abweichungs- und Doppelungsliste und dem Paketstatus.

**Herkunft dieser Datei:** Bauplan v2, die Nachträge N1–N4 und Gesamtplan Abschnitt 9 stammen von Claude und haben die Doppelung zu ThreadDesk erzeugt. Sie sind ab jetzt Archiv bzw. technischer Spiegel. Aussagen in dieser Datei, die sie als „kanonisch“ bezeichnen (X5, BP-PLAN-01, N1 „Kanonischer Einstieg“) und Gesamtplan 9.12 („GitHub Masterfassung“) sind damit überholt.

**Governance:**

1. Planänderungen entstehen nur in ThreadDesk, mit Datum, Quelle, Status und Verantwortlichkeit.
2. GitHub-Plandateien werden nicht als führende Kopie bearbeitet. Neue Plan-Dateien tragen den Hinweis „Nicht maßgeblich. Maßgeblich ist ThreadDesk-Thread `6b5b73b9de36` (Master mit Etappen E01–E09; Status im Board `188ce4729a62`; Nutzerbeschluss 09.11.2026). Diese Datei ist Archiv bzw. technischer Spiegel.“
3. Die ChatGPT-Bibliothek bleibt als Backup unverändert.
4. Bei Widerspruch gilt der neueste belegte Nutzerbeschluss; Unklares wird als „offen – Nutzer“ geführt, nicht selbst entschieden.
5. Nichts wird eigenmächtig gelöscht.
6. Das Skript `scripts/plan_notice_check.py` im ThreadDesk-Repo meldet Plan-Dateien ohne den Hinweis.

**Ergänzung zu N5 (09.11.2026, nach vollständiger Lektüre des Masters):** Maßgeblich ist der ThreadDesk-Master `6b5b73b9de36` („Gesamtplan ThreadDesk & 4AllPass“, Etappen E01–E09, Stabilitätsabnahme ST-01–ST-05). Planhierarchie: Master → Board `188ce4729a62` (Status, Belege, Entscheidungen, Rückführung aus GitHub) → Produktthreads. Die Zuordnung der Etappen E01–E09 und ST-01–ST-05 zu den BP-IDs dieser Datei steht im Board-Abschnitt „BIG PLAN – KORREKTUR ZUR RÜCKFÜHRUNG“. Es wurde nichts umbenannt. Die Hinweise in den GitHub-Plandateien verweisen auf den Master; der Status liegt im Board. Diese Datei stammt von Claude und ist nur Archiv bzw. technischer Spiegel.
