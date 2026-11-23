<!-- readme-header-v1: Kopf nach ThreadDesk docs/contracts/readme-header-v1.md. Nicht von Hand umgestalten; scripts/readme_header.py apply/check verwenden. -->

<p align="center"><a href="README.md">English</a> &nbsp;|&nbsp; <strong>Deutsch</strong></p>

<p align="center">
  <img src="assets/readme/normalized/KiraBridge-large.svg" alt="KiraBridge" width="256" height="256">
</p>

<p align="center">
  <a href="https://github.com/landjunge/ThreadDesk#readme" title="ThreadDesk"><img src="assets/readme/normalized/ThreadDesk-small.svg" alt="ThreadDesk" width="48" height="48"></a>
  &nbsp;
  <a href="https://github.com/landjunge/4AllPass#readme" title="4AllPass"><img src="assets/readme/normalized/4AllPass-small.svg" alt="4AllPass" width="48" height="48"></a>
  &nbsp;
  <a href="https://github.com/landjunge/TollGate/blob/main/README.de.md" title="TollGate"><img src="assets/readme/normalized/TollGate-small.svg" alt="TollGate" width="48" height="48"></a>
  &nbsp;
  <a href="https://github.com/landjunge/AgentAuthority#readme" title="Agent Authority"><img src="assets/readme/normalized/Agent-Authority-small.svg" alt="Agent Authority" width="48" height="48"></a>
  &nbsp;
  <a href="https://github.com/landjunge/BlockDesign#readme" title="BlockDesign"><img src="assets/readme/normalized/BlockDesign-small.svg" alt="BlockDesign" width="48" height="48"></a>
</p>

<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/design/wordmarks/KiraBridge-dark.svg"><img src="assets/design/wordmarks/KiraBridge-light.svg" alt="KiraBridge" width="312"></picture></p>

<!-- AUTO-DOWNLOADS:START -->
<p align="center">
  <img src="assets/readme/download-macos-apple-silicon.svg" alt="macOS Apple Silicon: In Vorbereitung / Coming soon" width="190" height="52">
  &nbsp;
  <a href="https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc59/KiraBridge-macOS-Intel.dmg" title="KiraBridge-macOS-Intel.dmg herunterladen / download"><img src="assets/readme/download-macos-intel.svg" alt="Download macOS Intel 0.8.0rc59" width="190" height="52"></a>
  &nbsp;
  <img src="assets/readme/download-windows.svg" alt="Windows: In Vorbereitung / Coming soon" width="190" height="52">
  &nbsp;
  <img src="assets/readme/download-linux-desktop.svg" alt="Linux Desktop: In Vorbereitung / Coming soon" width="190" height="52">
  &nbsp;
  <a href="https://github.com/landjunge/KiraBridge/releases/download/linux-v0.8.0rc41/KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz" title="KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz herunterladen / download"><img src="assets/readme/download-debian-server.svg" alt="Download Debian Server 0.8.0rc41" width="190" height="52"></a>
</p>
<!-- AUTO-DOWNLOADS:END -->

<sub>macOS-DMGs: nicht von Apple notarisiert. Beim ersten Start kann eine Freigabe unter Systemeinstellungen → Datenschutz & Sicherheit nötig sein. Das bisherige macOS-Archiv ist keine DMG.</sub>

<p align="center"><strong>Du sprichst mit deiner KI. KiraBridge verbindet Sprache mit der Steuerung deines Computers.</strong></p>

## Eine Werkzeugfamilie, eine gemeinsame Sprachsteuerung

**KiraBridge ist die zentrale Verbindung der NetzwerkPunkt-Werkzeugfamilie.** Sie übersetzt berechtigte Aufträge aus ChatGPT, per Chat oder Sprache, in Aktionen auf dem eigenen Computer und verbindet die weiteren Werkzeuge miteinander. Zur Familie gehören **KiraBridge** für Verbindung und direkte Steuerung, **ThreadDesk** für Projekte, Arbeitsstände und Aufgaben, **4AllPass** für Zugänge und Schlüssel, **TollGate** für Nutzungsgrenzen und Budgets sowie **Agent Authority** für ausschließlich lesende Beobachtung und Nachweise. Jedes Werkzeug erfüllt eine eigene Aufgabe. Die gemeinsame Bedienung der gesamten Familie über natürliche Sprache ist die Vision, an der wir arbeiten. Bestehende Verbindungen, laufende Entwicklung und geplante Funktionen werden dabei ausdrücklich unterschieden.

Die Entwicklungskonsole hat einen kompakten Produktheader: originale zweifarbige Wortmarke links, fünf mittige Originalicons (32 px innerhalb von 44 px Bedienflächen) und DE/EN rechts. Dekorkonturen bleiben dezent, Bedienelemente und Tastaturfokus kontrastreich. Das gemeinsame Modul ist die unveränderte Kopie **1.2.2**. Ein Icon übergibt nur seine Katalog-ID an den nativen Host; dieser ruft `kirabridge --principal local family switch TARGET --source-pid EIGENER_NATIVE_PID` direkt auf. Erst eine geprüfte JSON-Receipt bestätigt den Fokus; Öffnen bestätigt keine Peer-Verbindung. Reopen erhält die vorhandene Hauptansicht. [Quellnachweise und Grenzen](docs/FIVE-TOOL-DESIGN-20261107.md#family-header-follow-up--12-november-2026): Brokerintegration und installierte Fünf-App-Abnahme bleiben getrennt; KBLive wird durch diese UI-Änderung nicht ausgeliefert.

## Den Computer direkt bedienen

**KiraBridge ist mehr als eine Brücke zu KI-Agenten im Terminal.** Die Computersteuerung gehört zu ihren Kernfunktionen: Programme öffnen oder in den Vordergrund holen, zwischen Fenstern wechseln, Text unmittelbar eingeben, Notizen schreiben und bearbeiten, einzelne Tasten drücken und Tastenkombinationen (Shortcuts) ausführen. Die direkte Tasteneingabe kann ohne Umweg über die Zwischenablage erfolgen. Je nach freigegebenen Rechten und erreichbarer Oberfläche sind auch Maus-, Fenster- und Bildschirmfunktionen nutzbar. Damit kann die KI vorhandene Programme über deren normale Bedienoberfläche steuern, ohne dass für jede einzelne Anwendung erst eine besondere KI-Schnittstelle geschaffen werden muss.

Ein praktisches Beispiel: Du sagst, dass du eine Notiz festhalten möchtest. Die KI kann die entsprechende Anwendung öffnen oder auswählen, das richtige Fenster aktivieren und deinen Text eingeben. Ebenso lassen sich Arbeitsabläufe mit Tastenkombinationen und Fensterwechseln verbinden. Entscheidend ist nicht nur, dass ein Befehl verschickt wird, sondern dass du am Computer eine sichtbare Aktion und ein überprüfbares Ergebnis bekommst. Welche Schritte gelingen, hängt von der aktuellen Anwendung, den Bedienungshilfen des Betriebssystems, den erteilten Berechtigungen und der Stabilität der Verbindung ab.

MCP-Clients können im Entwicklungsquellstand mit `operation_catalog` gezielt die Schemata benötigter Werkzeuge abrufen. `compact=true` liefert dazu nur den ausgewählten Katalog, den nötigen Berechtigungskontext und eine leichte Discovery-Revision; die vollständige Katalogantwort bleibt der Standard. Diese Erweiterung ist im Quellstand und noch nicht als neue installierte Version bestätigt.

## Sprachsteuerung für alle, Barrierefreiheit mitgedacht

**Das Hauptziel von KiraBridge ist, Computer, Anwendungen und KI-Werkzeuge mit natürlicher Sprache bedienen zu können.** Statt komplizierte Bedienfolgen zu lernen, beschreibst du, was geschehen soll: ein Programm öffnen, eine Notiz schreiben, Fenster wechseln oder einen KI-Agenten beauftragen. Diese Form der Steuerung richtet sich grundsätzlich an alle Menschen, ob für alltägliche Aufgaben, produktives Arbeiten, freihändige Bedienung oder komplexe Abläufe.

**Barrierefreiheit denken wir von Anfang an mit, ohne sie zum alleinigen oder vorrangigen Produktzweck zu machen.** Menschen mit Behinderungen, eingeschränkter Mobilität oder Schwierigkeiten mit Maus und Tastatur können besonders davon profitieren, wenn sich Arbeitsschritte per Sprache auslösen und nachvollziehen lassen. Mehr Selbstständigkeit ist ein wichtiger zusätzlicher Nutzen der allgemeinen Sprachsteuerung. Verständliche Rückmeldungen, überprüfbare Ergebnisse und die Möglichkeit zur menschlichen Kontrolle helfen allen Nutzenden.

Die Entwicklung ist nicht abgeschlossen: KiraBridge steuert noch nicht jede Anwendung zuverlässig oder vollständig. Einige Funktionen sind umgesetzt und getestet, andere Abläufe sind noch langsam oder hängen von Berechtigungen und Umgebung ab. Wir optimieren Bedienung, Zuverlässigkeit, Geschwindigkeit und Rückmeldungen fortlaufend. Wichtige Aktionen benötigen gegebenenfalls eine Bestätigung.

## Mit KI-Agenten und Projekten arbeiten

Codex-Inventar und Doctor trennen nun die ausführbare Programmdatei von [passiven Paketlayout-Beobachtungen](docs/providers/CODEX-PACKAGE-DIAGNOSTICS.md). Unterstützte offizielle 0.169-Metadaten können fehlende Companions/Ressourcen sichtbar machen; undurchsichtige Launcher und andere Versionen bleiben unbekannt. Dabei startet weder CLI noch Anmeldung, und keine Ausführung wird gesperrt. Vorhandene Dateien beweisen keine passenden Versionen, Paketintegrität oder funktionierenden Werkzeuge.

Neben der direkten Computersteuerung kann KiraBridge Aufträge an **Codex und Grok** in eingerichteten, sichtbaren Terminalfenstern übergeben und deren Rückmeldungen verfolgen. Laut lokalem Inventar vom 10. November sind außerdem ausführbare Adapter für **Claude Code, OpenCode, Gemini CLI und Copilot** vorhanden. OpenCode kann zusätzlich seine lokale HTTP-API mit Basic-Authentifizierung aus Umgebungsvariablen nutzen; dieser Adapter legt pro Auftrag eine neue Sitzung an und meldet Status und Ergebnis zurück. Ein erkannter Adapter ist noch kein Nachweis für Anmeldung, eine einsatzbereite Sitzung oder einen erfolgreichen Ende-zu-Ende-Auftrag.

Der Entwicklungsstand unterstützt Zwischenfragen an eine ausdrücklich ausgewählte, arbeitende Codex-Sitzung, ohne ihre Arbeit zu stoppen oder einen weiteren Agentenauftrag zu starten. Belegte reine Zwischenfragen-Zustellungen verbrauchen kein Konversations-/Stundenbudget für Modellläufe; beanspruchte verwaltete Versuche zählen auch bei Fehlern oder unklarem Ausgang weiter. Der aktuelle native Weg nutzt das bestehende macOS-Terminal; unklare Zustellungen bleiben ohne automatische Wiederholung erhalten, und Nutzende können Zwischenfragen ausschalten. Die Live-Abnahme auf macOS und die nativen Transportabnahmen auf Windows/Linux/Server werden getrennt belegt und sind noch offen.

Der Entwicklungsquellstand bietet außerdem eine optionale [native Codex-Rootbindung](docs/NATIVE-CODEX-BINDING.md) für neue direkte Nachrichten auf macOS mit Codex 0.169. Sie prüft bei jedem Versuch die zugeordnete logische Root auf dem bestehenden Host und erneuert Prozess- und Socketbeobachtungen automatisch, statt einen alten Terminalhandle zu behalten. Parallele Sitzungen behalten ihre eigene Identität; Annahme, Empfängerquittung und Antwort bleiben getrennt. Quelltests aktivieren diese Route nicht und sind keine Live-Abnahme.

Der Quellstand enthält außerdem [Qwen Code 0.27.2 über ACP und auftragsgebundenes MCP](docs/providers/QWEN.md): vorhandene explizite Anmeldung, native Modell-/Denkstufenauswahl, konfigurierbare Operatorbudgets und berechtigungsgefilterte KiraBridge-Werkzeuge für Lese- oder ausdrücklich erlaubte Codingaufträge. Eine Fortsetzung benötigt die belegte eigene Sitzungsbindung; Turnabschluss und fachliche Abnahme bleiben getrennt. Produktivaktivierung und vollständige Fachabnahme stehen weiter unter den vorhandenen Gates.

Der Entwicklungsquellstand enthält jetzt einen gemeinsamen ACP-Client und den Adapter `opencode_acp` für isolierte reine Textaufträge, mit Sitzungsprüfung, begrenzter Ausgabe und ausdrücklichen Ergebnissen bei Zeitüberschreitung oder Verbindungsabbruch. Der Adapter erzeugt einen eigenen Prozess; die Beobachtung derselben Sitzung in der OpenCode-App und der vollständige macOS-Ablauf müssen noch abgenommen werden. Diese Änderungen sind noch nicht in der veröffentlichten Laufzeit installiert.

Ein getrennter Entwicklungsadapter `opencode_http_v2` zielt auf die `/api`-Oberfläche der installierten gemeinsamen OpenCode-2.2.7-App (Session anlegen/lesen, Prompt mit stabiler Nachrichten-ID, seitenweise Nachrichtenliste). Da V2-Assistant-Nachrichten kein `parentID`/`sessionID` tragen, ordnet er seine eigene zugelassene Anfrage kausal zu und bricht bei fremden oder mehrdeutigen Eingaben geschlossen ab. Der bisherige V1-HTTP-Pfad bleibt unverändert; es gibt keinen Protokoll- oder POST-Fallback nach unklarem Start. Dieser Adapter ist nicht installiert, seine Live-Abnahme bleibt ein eigenes Gate. Ein beobachtetes Idle-Outcome `failed` oder `interrupted` bleibt auch dann unbestätigt, wenn eine Assistentennachricht Text und `finish=stop` enthält.

Teamaufträge merken sich außerdem die belegte Provider-Sitzung des Bearbeiters. Ein späterer Auftrag an denselben Bearbeiter setzt diese Sitzung nur fort, solange sie frei (idle) ist und Agent, Adapter sowie Arbeitsverzeichnis unverändert sind; eine laufende oder unbestätigte (unknown) Sitzung wird nie wiederverwendet. `team_session_get` liest die Bindung, `team_session_clear` setzt einen Tombstone, sodass ein noch laufender Turn eine gelöschte Sitzung nicht wieder anlegen kann. Die Wiederaufnahme deckt derzeit Codex, Grok ACP, versiegelte freie Qwen-ACP-Sitzungen und den getrennten nativen OpenCode-HTTP-Pfad ab; die OpenCode-CLI- und `opencode_acp`-Adapter werden für die Wiederaufnahme abgewiesen, weil ihr isoliertes Profil keinen dauerhaften Sitzungsspeicher besitzt. Die Wiederaufnahme ist auf versiegelte Teamaufträge beschränkt, überlebt einen Bridge-Neustart und wiederholt keinen bereits beanspruchten Core-Auftrag. Der Live-Nachweis mit Codex, Grok und OpenCode/DeepSeek über einen Bridge-Neustart steht in `docs/evidence/team-coordination-live-20261112.json`.

### Quellstand: Teamumfang, Fortsetzung und Fehlerfelder

- Neu im Entwicklungsquellstand: `kirabridge team onboard <team_id> <identity> [--coordinator]`, nur für den Owner. Das Daemon-Werkzeug `team_onboard_register` lässt ausschließlich die Owner-Identität `local` zu, ergänzt `[principals.<id>]` plus `[team.workers.<id>]` und einen erzeugten Token erst, wenn der Kandidat das strenge Konfigmodell besteht, hält zeitgestempelte Sicherungen, stellt bei jedem Fehler beide Dateien wieder her, ist beim Wiederholen idempotent und gibt niemals Tokenwerte aus. Der laufende Daemon hält einen Start-Snapshot der Konfiguration, deshalb orchestriert die CLI den Rest: idle-gesicherter Neuladevorgang (aktive Teamarbeit oder `--no-restart` halten an), ein Rollenaufruf mit Revisions-CAS und genau einem erneuten Versuch, danach verpflichtender Readback von Owner, Koordinator, Revision, Mitgliedschaft und wartender Inbox-Seite. Keine installierte Veröffentlichung.
- `execution_scope = "existing_native_codex_root"` führt einen Teamturn auf dem einen geladenen, elternlosen Codex-Root aus, dessen aufgelöstes cwd dem aufgelösten Worker-cwd entspricht, über `turn/start` des App-Servers. Unter höchstens 16 geladenen Ids ergibt eine andere Anzahl `native_codex_root_not_unique`. Eine fehlende oder längere Id-Liste und ein laufender Turn ergeben `native_codex_target_not_ready`. Der Pfad setzt `terminal_input_attempted = false` und wählt weder Pane, Terminal-PID noch Rollout-Pfad. Die Hostidentität wird geprüft; ein Patch derselben Minor-Linie bleibt gültig. `protocol_version` akzeptiert nur `0.169.<patch>`. Die Route braucht `[visible_handoffs.native_codex]` mit `codex_home`, `host_executable` und `protocol_version`. Agent und Art des Workers müssen `codex` sein. Siehe [Native Codex-Rootbindung](docs/NATIVE-CODEX-BINDING.md).
- `team.coordinator_resume` ist standardmäßig aus. Ist es an, schreibt beendete delegierte Arbeit (`finish`, `fail` oder manuelles `work_complete`) genau eine Abschlussmeldung, Quelle `team`, Ziel `team:<team_id>`, und `TeamManager.resume_coordinators` legt genau einen idempotenten Koordinationsauftrag für einen Auftraggeber mit gesetztem `agent` an. Die Verknüpfung steht in `team_coordinator_resumes`. Ein Auftrag an den eigenen Bearbeiter erzeugt keine Meldung.
- `agents.<name>.model` ist optional. `grok_reasoning_effort` gilt nur bei `kind = "grok_acp"` und muss `^[a-z]{1,16}$` entsprechen. Der Grok-ACP-Adapter übergibt ein gesetztes Modell als `--model` und eine gesetzte Stufe als `--reasoning-effort`.
- Gibt eine Ausführung einen Misserfolg zurück, speichert der Task `error` als `{code, kind, retry_safe}` und bei ganzzahligem Exitcode zusätzlich `exit_code`. Codes dieser Normalisierung sind `command_exit_nonzero`, `command_timeout`, `command_killed`, `agent_exit_nonzero` und `operation_failed`. Ein verschachteltes Peer-`value.error.code` bleibt erhalten, wenn es `^[a-z][a-z0-9_]{0,79}$` entspricht; sonst ist der Code `tool_rejected`. `retry_safe` ist nur in dieser Peer-Form wahr, wenn `evidence.request_sent` falsch ist. Neustart und Abbruch des Dispatchers speichern `error.code` `dispatcher_restart` oder `dispatcher_shutdown` ohne dieses normalisierte Objekt. Die Completion-Nutzlast kopiert `error.kind` nach `error_kind`.
- Ein gekürzter Terminalkatalog ergibt `session_catalog_incomplete` mit `provider_error.reason = "catalog_truncated"`. Ein vollständiger Katalog, der das gewählte Pane nicht mehr trifft, ergibt `session_selection_changed` mit `provider_error.reason` `expected_pid_changed`, `window_changed` oder `pane_missing`.
- Fehler der Gemini- und Copilot-CLI können `provider_error.diagnostic` aus nicht-leerem stderr setzen, bereinigt und höchstens 200 Zeichen. `opencode_http` und `opencode_http_v2` schreiben bei Statusfehlern nur `provider_error.http_status`. Eine unerwartete ACP-Antwort-ID meldet `agent_identity` nur als Form: `response_id`, `message_keys`, `pending_requests`, `adapter`, `reason` und `already_answered`.

ThreadDesk ergänzt diesen Weg um Projekte und Arbeitsstände; weitere Werkzeuge der Familie sollen im gemeinsamen Sprachablauf zusammenwirken. Die Werkzeuge bleiben eigenständig, und ihre tatsächliche Integration wird nicht mit dem Entwicklungsziel verwechselt.

Der ausdrücklich aktivierte ThreadDesk-Werkzeugproxy unterstützt im Entwicklungsstand begrenzte JSON-Schema-2020-12-Verweise innerhalb des gelieferten Schemas, einschließlich eingebetteter Fachschemas. Er lädt keine Schemas aus dem Netzwerk oder von Datenträgern nach; zyklische, mehrdeutige und nicht unterstützte Schemas bleiben ausgeschlossen. Bestehende Werkzeugrechte und Operationsquittungen gelten weiter. Siehe [Proxy-Vertrag](docs/DYNAMIC-THREADDESK-PROXY.md).

Der Entwicklungsstand trennt außerdem die normale MCP-Erreichbarkeitsprüfung von Speicherdiagnosen, schützt laufende ThreadDesk-Aufrufe bei Katalogproblemen und bietet kompakte bestätigte Schreibantworten. Ungewisse Schreibvorgänge benötigen weiterhin den Abgleich ihrer ursprünglichen Operation. Bekannte Lebenszyklusfehler wie `object_in_trash` behalten ihren strukturierten Code, ohne private Peerfehlermeldungen auszugeben. Schreibfeldlimits erscheinen nur bei bestätigten Größenfehlern des passenden Verwaltungsauftrags; Lese- und unbekannte Fehler erhalten keine unpassenden Schreiblimits mehr. Die Änderungen betreffen den gemeinsamen Mac-/Linux-Code; sie belegen keine neue Installation. Siehe [Verhalten und Prüfgrenzen](docs/THREADDESK-OPERATIONS-RELIABILITY.md).

Die Bereitschaftsprüfung unterscheidet jetzt Berechtigung, Plattformunterstützung und ungeprüften Transport. Ausstehende Freigaben und bekannte Blockaden ergeben „nicht bereit“; eine ungeprüfte Session- oder ThreadDesk-Verbindung bleibt unbekannt. Die Statuskorrektur erteilt keine Zugriffsrechte und startet keine Befehle.

Im Entwicklungsstand blockieren gültige macOS-Systembenutzer mit negativer UID, etwa `nobody`, nicht mehr den gesamten Terminalkatalog. Ihre Prozesse gelten weiterhin als fremd; fehlerhafte Prozessdaten und belegte Eingabeziele werden weiterhin abgewiesen.

Die Release-Smoke-Testkonfiguration beschränkt ihre temporäre lokale Identität auf Erreichbarkeits- und `file.read`-Prüfungen mit automatischer Freigabe. Reguläre Installationen benötigen weiterhin standardmäßig eine Freigabe.

## Downloads und Installationsprofile

Die Buttons oben verlinken direkt auf veröffentlichte Installationsdateien und
zeigen deren Versionen. macOS-Desktop und Debian-Remote-Server haben getrennte
Releasewege; ihre Versionsnummern können deshalb unterschiedlich sein.

| Download | Einsatzzweck | Installationsanleitung |
| --- | --- | --- |
| **macOS Intel** | Desktop-App und lokaler KiraBridge-Dienst. Der aktuelle geprüfte Intel-Download ist oben verlinkt. | [Installieren, prüfen und Hilfe finden](docs/INSTALL-DE.md) |
| **macOS Apple Silicon (M-Serie)** | Native Desktop-Installation für Apple-Chips. **Noch kein geprüfter Apple-Silicon-Installer veröffentlicht; der Download-Button erscheint, sobald ein Paket verfügbar ist.** | [Alle Releases](https://github.com/landjunge/KiraBridge/releases) |
| **Windows Desktop** | Lokale Computersteuerung unter Windows. **Im ausgewählten Desktop-Release fehlt derzeit eine herunterladbare Installationsdatei.** | [Windows-Einrichtungsanleitung](docs/WINDOWS-SETUP.md) |
| **Linux Desktop (Ubuntu / Debian Desktop)** | Lokale grafische Computersteuerung. **Derzeit ist kein separat bestätigter Desktop-Installer verlinkt.** Das Serverpaket ist kein Desktop-Installer. | [Alle Releases](https://github.com/landjunge/KiraBridge/releases) |
| **Debian Server (Debian Remote)** | Grafisch unabhängiger Debian-/Linux-x86_64-Server mit Remote-Agenten- und MCP-Funktionen; **keine Linux-Desktop-App**. Der separate Serverdownload ist oben verlinkt. | [Debian-Server installieren](docs/INSTALL-LINUX-SERVER.de.md) |

[Alle Versionen, Prüfsummen und Release-Hinweise](https://github.com/landjunge/KiraBridge/releases)
sind öffentlich; für den Download ist kein GitHub-Konto nötig. Releases können
Vorabversionen sein. Status, Voraussetzungen und Grenzen stehen beim jeweiligen
Release. KI-Anmeldung und mögliche Anbieterkosten bleiben getrennt.

Die Download-Buttons werden bei Veröffentlichung, Bearbeitung oder Löschung
eines Releases, bei Änderungen am Aktualisierungsskript und zusätzlich alle
sechs Stunden für nachträglich hochgeladene Dateien aktualisiert. Angeboten
werden nur vollständige, geprüfte Downloads. Desktop-Buttons verwenden das
neueste veröffentlichte Desktop-Release; fehlende Plattformen werden nicht aus
älteren Desktop-Releases ergänzt. Debian Remote wird unabhängig aus dem neuesten
veröffentlichten `linux-*`-Serverrelease gewählt. Buttons für Apple Silicon und
Windows-Desktop erscheinen, sobald dieses Desktop-Release entsprechende Pakete enthält.

Der Quellcode kann neuere Änderungen als die veröffentlichten Pakete enthalten.
Die tatsächlich auf deinem Rechner laufende Version siehst du in der App oder
mit `kirabridge status`. Quellcommit, erfolgreicher Build und installierte
Version sind unterschiedliche Nachweise.

Im macOS-Entwicklungsstand zeigt das Infofenster den Commit der App als
**App-Build** neben der Paketversion an.

**Frühere Windows-Entwicklungsvorschauen:** Der [RC33-Paketbericht](docs/RC33-DELIVERY-20261104.md)
und der [Windows-Einrichtungsbericht](docs/WINDOWS-SETUP-20261104.md) beschreiben
deren begrenzte Tastatur-, Shortcut- und abgesicherte Fenstersteuerung. Sie belegen
keinen aktuellen Windows-Funktionsgleichstand und keinen aktuellen allgemeinen
Windows-Installer. [Windows-Einrichtungsanleitung](docs/WINDOWS-SETUP.md).

[Historische Release- und Installationsbelege](docs/evidence/readme-current-20261107.json)
bleiben als datierte Nachweise erhalten, nicht als aktueller Installationsstand.

## Wobei KiraBridge dir hilft

- **An lokalen Projekten arbeiten:** Lass deine verbundene KI Projektdateien und
  Protokolle lesen, Dateien bearbeiten oder Befehle ausführen — im erlaubten Rahmen.
- **Mit Terminalagenten arbeiten:** Schicke Aufträge an Grok Build und Codex
  in ihren eingerichteten Terminalsitzungen auf deinem Computer.
- **Die Arbeit verfolgen:** Sieh Anfragen, Nachrichten und Ergebnisse im lokalen Steuerfenster.
- **Den Zugriff bestimmen:** Lege fest, welche Ordner und Aktionen erlaubt sind
  und wann ein Auftrag deine Freigabe braucht.
- **Keine späten Überraschungen:** Höchstens drei Aufträge warten gleichzeitig; ein vierter
  storniert den ältesten wartenden. Was länger als eine Stunde wartet, wird gestoppt und
  gemeldet, nie später ausgeführt. Große Ausgaben bleiben in der Datenbank kurz, das Protokoll vollständig.
- **Neuester Boardtext (Entwicklungsstand):** `order="newest"` liest die neueste Whiteboard-Seite, `whiteboard_search` findet Text in einem Board. Keine neue Installation.
- **Technische Boardeinträge:** `progress`, `claimed`, `task` und `problem` bleiben in KiraBridge, nur als letzter Stand im laufenden Prozess, ohne Audit und ohne Datenbank. Abschalten: `[threaddesk]` `route_technical_entries = false`.

ThreadDesk und andere Integrationen sind optional. Der Kern von KiraBridge funktioniert eigenständig.
Ist ThreadDesk eingerichtet, bringt das Paket die gepinnte ThreadDesk-Bibliothek mit. Der
Installer stellt `[threaddesk]` `source_root` und `command` auf sie und auf das Python der
Release um; der Rollback setzt beide Werte zurück. Andere Einstellungen bleiben unverändert.

## Loslegen

1. **Installieren oder aktualisieren.** Wenn dein Download ein DMG ist, öffne es,
   ziehe `KiraBridge.app` nach `Programme` und starte die App. Andernfalls lade
   `KiraBridge-macos.tar.gz` herunter, entpacke es vollständig und führe im
   entpackten Ordner `KiraBridge` `sh ./install.sh --desktop
   --require-visible-terminal` in einem separaten Terminalfenster aus. Folge der
   Bestätigung. Laufende Agentensitzungen erhalten.
2. **App öffnen.** Der Installer aktualisiert Dienst und Desktop-App gemeinsam.
   Öffne `KiraBridge.app` in `~/Applications`. Vorhandene Einstellungen und Zugänge
   bleiben erhalten; der Installer erstellt eine Rückfallsicherung.
3. **Chat verbinden.** Folge der [ChatGPT-Verbindungsanleitung](docs/CHATGPT.md).
   Bitte ihn zum Einstieg, eine kleine Datei aus einem erlaubten Ordner zu lesen.
   Gib die Anfrage bei Bedarf frei und prüfe das Ergebnis in deinem Chat.

**Voraussetzungen:** Intel-Mac, geprüft mit macOS 15.7.4; Python 3.11 und uv 0.11.6
bereits im Terminal verfügbar; Internet zum Laden von Abhängigkeiten.
Installiere mit deinem normalen Benutzerkonto. KI-Konten und mögliche Anbieterkosten
bleiben getrennt; die Chatverbindung braucht die passenden Kontoberechtigungen.
Für Terminalaufträge müssen Grok Build oder Codex installiert und angemeldet sein.
Richte ihre Terminalsitzung in KiraBridge als Ziel ein.

Diese Vorabversion hat bekannte Einschränkungen bei der Terminalbedienung; die App
ist nicht von Apple notarisiert. Beachte die Hinweise beim ausgewählten Download
und [Installation, Prüfung und Hilfe](docs/INSTALL-DE.md). Der
[RC36-Nachweis](docs/TERMINAL-MINIMIZED-RC36-20261104.md) bleibt ein historischer Bericht.


## Linux-/Debian-Server

Die [in Main integrierte Serverimplementierung aus PR72](https://github.com/landjunge/KiraBridge/pull/72)
bietet einen privaten HTTP-MCP-Dienst auf Loopback mit Bearer-Authentifizierung
und Healthprüfung sowie Installation, Update und Rollback über `systemd --user`.
Zielplattformen sind Debian 13 und Ubuntu 24.04 x86_64. Der Onlineinstaller benötigt
einen laufenden Benutzermanager; die Laufzeit über Logout/Neustart folgt der Sitzungspolitik
des Hosts. Linger, Administratorrechte, Firewall und öffentliches HTTPS werden nicht eingerichtet.

Der Server läuft ohne macOS-GUI, Terminal.app oder native Tastatursteuerung.
Zwischenablage ist optional (`wl-clipboard`/`xclip`). ChatGPT-/Kontoverknüpfung und
Fernzugriff benötigen eigene Konfiguration.

Der Entwicklungsquellstand unterscheidet die Terminalwege je Betriebssystem: eine bestätigte sichtbare Shell auf macOS, eigene native PTYs auf Linux und `windows.console.handoff` auf Windows. Unter Linux führen `terminal_control` / `terminal.visible` und ChatGPTs normales `terminal.execute` exakte argv in einer neuen temporären PTY aus. Das Ergebnis enthält PID/TTY, Ausgabe, beobachteten Exitstatus und Cleanupbelege. Bestehende Nutzersitzungen bleiben erhalten; `create_if_needed` betrifft nur macOS-Fenster. Explizite Pane-Ziele und privilegierte Direktausführung sind unter Linux nicht unterstützt. Getrennte interaktive eigene Sitzungen nutzen `session.open`; die Erkennung listet sie auch ohne tmux, Eingabe und Schließen prüfen weiterhin genaue Kennung und PID. Bestehende Rechte-, Programm- und Arbeitsverzeichnisgrenzen gelten weiter. Diese Quelländerung aktualisiert keine veröffentlichten Downloads und belegt noch keine Live-Sprachabnahme der neuen Route.

Die Linux-Erkennung nennt ihren Provider `linux.existing_native`. Sie trennt gebundene Datei-, Prozess- und eigene PTY-Adapter von ungeprüfter Transportverfügbarkeit: Eine Bindung meldet `state=unknown`, `runtime_availability=not_probed` und behauptet kein `available=true`. Desktop-Transporte bleiben nicht unterstützt. Diese passiven Metadaten ändern weder Operationsbeschreibungen und Berechtigungsprüfungen noch den Terminalweg; macOS und Windows behalten ihre bestehenden Wege. Installationsstand und native Plattformabnahme brauchen eigene Belege.

Das 0.8.0rc41-Archiv ist nativ auf Debian 13.6 x86_64 abgenommen und
[im getrennten Serverrelease veröffentlicht](https://github.com/landjunge/KiraBridge/releases/tag/linux-v0.8.0rc41). Der echte Download
stimmt mit GitHubs Digest und den Releaseprüfsummen überein. Ubuntu 24.04 ist ein
unterstütztes Ziel; eine neue native Ubuntu-Abnahme wird hier nicht behauptet.
[Linux-x86_64-Archiv](https://github.com/landjunge/KiraBridge/releases/download/linux-v0.8.0rc41/KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz) ·
[Prüfsummen](https://github.com/landjunge/KiraBridge/releases/download/linux-v0.8.0rc41/SHA256SUMS).
[Installation, Update und Rollback](docs/INSTALL-LINUX-SERVER.de.md) ·
[Quell-, Abnahme- und Downloadbelege](docs/evidence/readme-current-20261107.json).

[Finale native Releasebelege](docs/evidence/debian-dirktest-release-20261107.json).
[Archiv-SHA-256](https://github.com/landjunge/KiraBridge/releases/download/linux-v0.8.0rc41/KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz.sha256).

```sh
gh release download linux-v0.8.0rc41 -R landjunge/KiraBridge -p 'KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz*'
sha256sum -c KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz.sha256
tar -xzf KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz
cd KiraBridge-0.8.0rc41-Linux-x86_64
sh install.sh --yes
```

Für ein Update das neue Release in ein frisches Verzeichnis laden, prüfen und dort
`sh install.sh --yes` mit denselben Zielpfaden ausführen. Die bisherige Laufzeit für
Rollback behalten; [explizite Pfade und Rollbackbefehle](docs/INSTALL-LINUX-SERVER.de.md)
decken auch Hosts mit gemeinsam beschreibbaren übergeordneten Verzeichnissen ab.

## Tastenfolgen und weniger Cloudaufrufe

`keyboard_sequence` führt bis zu 32 echte Key-down/Key-up-Paare ohne Zwischenablage
seriell in einem idempotenten Task aus. Wenn die nächste Taste von der Rückmeldung
der vorigen abhängt, bleiben einzelne Aufrufe erforderlich. Blocktext ist ein
eigener Vorgang und ersetzt keine verlangten einzelnen Tastenereignisse.

Bekannte Lesewerkzeuge teilen eine Übergabe über
`read_query(query={"operation":"tool.batch","calls":[...],"result_format":"structured"})`.
Das optionale strukturierte Format entfernt ausschließlich bewiesene äquivalente
JSON-Textkopien; alle strukturierten Werte, Fehler und Metadaten bleiben.
Der Default ist `full`. Rechte werden frisch geprüft. Bei ungewissem Ausgang
denselben Task lesen, statt die Eingabe erneut auszuführen.

[RC28-Tastenfolgen](docs/RC28-E2E-LATENCY-20261103.md) ·
[RC29-Aufrufreduktion](docs/RC29-CLOUD-CALL-REDUCTION-20261103.md) ·
[RC30-Messungen, Installation und Grenzen](docs/RC30-HOTPATHS-20261103.md).
Dieselben acht großen Leseergebnisse benötigten im gemessenen RC30-Vergleich einen
statt zwei Apps-Aufrufe; Median 22,72 → 13,02 Sekunden bei je drei Gruppen.
Cloudlatenz bleibt; das ist kein neuer physischer Tasten- oder Voicevergleich.

RC31 ergänzt direkte native JSON-Reads über `read_query` mit `operation="native.read"`
und begrenzte Accessibility-Unterbäume mit `max_depth>0`. Dadurch sinken wiederholte
UI-Leseaufrufe und persistente Taskdaten. Ereignisabrufe laden große Ausgaben nicht
mehr mit. Siehe [RC31-Umsetzung, Messungen und Auslieferungsstand](docs/RC31-NATIVE-READS-20261103.md).

RC32 bündelt zusätzlich Attribute innerhalb optionaler UI-Unterbäume. Dieselben
zwölf eigenen AppKit-Buttons benötigten im kontrollierten nativen Test 8,14 statt
16,86 ms Median bei zwanzig abwechselnden Runden. Siehe [RC32-Messungen und Grenzen](docs/RC32-NATIVE-ATTRIBUTE-BATCHING-20261103.md).

## Lizenz

Private, nicht geschäftliche Nutzung ist unter der
[Netzwerkpunkt Personal Use License 1.0](LICENSE) kostenlos. Geschäftliche Nutzung
benötigt eine gesonderte schriftliche Erlaubnis. Der deutsche Lizenztext ist maßgeblich.

[Entwicklerdokumentation](docs/DEVELOPERS.de.md): Python ab 3.11, gelockte
uv-Umgebung, CLI-Einstieg, Quellverzeichnisse und gezielte Prüfungen. Ausgangspunkt
ist ein Repositorycheckout; veröffentlichter Installer und Entwicklungsumgebung sind getrennt.

Lokaler CLI-Modulkandidat: [Terminal-/Codex-/Grok-Grenzen und Prüfgrenzen](docs/plans/TERMINAL-CLI-MODULES-20261104.md).
Dieses Entwicklungspaket ist vom veröffentlichten RC49-Download getrennt; die
echte Browserchat-Abnahme steht noch aus.

Lokaler Big-Plan-Koordinatoradapter: [freigegebener Aufgaben-Loop, Codex/Grok-Prüfung und Agentenberichte](docs/COORDINATOR-LOOP.md). Eigenes Opt-in-Profil; bestehende sichtbare Sitzungen und veröffentlichte Pakete behalten ihren bisherigen Stand.

Quelländerung: Der Koordinator meldet fachliche Zustandswechsel und sendet unveränderte Stände nicht mehr minütlich erneut. Lokale Beobachtungen bleiben aktuell; Meldeversuche behalten ihre Kennung über Neustarts, auch bei unklarem Ausgang. Laufende Dienste benötigen ein separat geprüftes Update.

Der neue Quellbefehl `bigplan-loop --profile <Fixtureprofil> preview --fixture <Fixturedaten.json>` prüft ausschließlich private Offline-Fixtures und zeigt eine mögliche Auswahl oder Zurückhaltung samt geprüftem Routing. Die Vorschau ist weder Freigabe noch Claim und startet keine Aufgabe; sie liest kein Live-Board und keinen Core.

Bei verlorener Team-Submitantwort bleibt der ursprüngliche Coreauftrag erhalten. Neue markierte Submit-Unklarheiten können genau einen belegten erfolgreichen Originalversuch ohne neuen Modellturn übernehmen. Historische UNKNOWNs bleiben gehalten. Für ein geprüftes Ergebnis ohne Aktionen verwendet der Owner bei gestopptem Supervisor `bigplan-loop --profile <Profil> reconcile --request <TeamWorkReprocess.json> --expected-profile-sha256 <SHA256>`: Der Befehl hält den vorhandenen Singletonlock, prüft Profilidentität, Reportingscope und ursprüngliche Arbeitszuordnung und nutzt die bestehende Owneroperation. Der Antrag bindet Work-/Core-ID, Requesthash, Receipt, Attempt und nativen Ergebnishash. Er startet weder Bridge, Dispatcher, Provider noch Folgeauftrag; der reguläre Supervisor verarbeitet nach Neustart das vorhandene Ergebnis. Alle nativen Originalturns müssen innerhalb der ursprünglichen Ausführungslease abgeschlossen sein. Dieser reine Ergebnispfad führt die vorhandenen gepinnten Abnahmechecks zu Ende, publiziert den Originalreceipt über die vorhandene Outbox und verarbeitet dessen Completion-ACK. Er verlängert keine Lease und startet keinen weiteren Turn. Andere Stopgründe bleiben gehalten. Vorher den aktuellen Zustand sichern; Status, Grantdateien, Outbox, fremde UNKNOWNs und Leases erhalten.

Vertrauenswürdige Einträge unter `continuation.task_routing` binden eine Codex-`WorkerRouting`-Regel an eine zugeordnete Task-ID. Vorschau und Ausführung lösen dieselbe Regel auf; Aufgaben ohne eigene Regel behalten das globale Worker-Routing. Alte Profile mit `continuation.assignments` erfordern eine ausdrückliche Migration und werden niemals still umgeschrieben.

Der [Integrationscheckpoint vom 6. November](docs/BIGPLAN-INTEGRATION-STATUS-20261106.md) bündelt angenommene Pakete, gemeinsame Remote-/Absturztests und die damals offenen Gates. Für geprüfte Quelle und installierten Pin gilt der [Abgleich vom 7. November](docs/evidence/readme-current-20261107.json); datierte Checkpoints behalten ihre historischen Ergebnisse.

Der konfigurierte Koordinator und der frisch bestätigte unveränderliche Owner seines konfigurierten Teams dürfen denselben begrenzten `coordinator_status` mit aufgezeichneten Zeiten lesen. Die Team-Ownerschaft gewährt nur diese Statusansicht; Steuerung, Completion-ACKs und private Core-Daten behalten ihre bisherigen Rechte.

Der Entwicklungsstand trennt außerdem den gespeicherten `ledger_state` vom Workflowstatus einer Aufgabe. Eine gebundene terminale Ablehnung, ein Fehler oder Stopp ersetzt ein veraltetes angezeigtes `waiting` nur bei passenden Aufgaben-/Quellmetadaten und bekannten terminalen Work-/Core-Zuständen; aktive oder unbekannte Bindungen bleiben unverändert. Die Zähler folgen dem angezeigten Workflowstatus. Diese reine Leseprojektion stoppt keine Nativeffekte, gibt keine Leases frei und bestätigt keinen Projektabschluss; Installation und Liveabnahme bleiben getrennt.

Sein Status zeigt gespeicherte Warte-, Ausführungs- und Abnahmezeiten aus dem gebundenen Core und Receipt. Fehlende oder ungültige Zeitwerte bleiben unbekannt; das Lesen startet keine Arbeit.

Das optionale [native Worker-Routing](docs/COORDINATOR-NATIVE-ROUTING-20261106.md) verwendet die geprüfte CLI-Matrix für versiegelte Managed-Aufträge; sichtbare Sitzungen und das eigene strukturierte Grok-Reviewprotokoll bleiben erhalten. Angeforderte Modell-/Effortwerte und beobachtete Metadaten bleiben getrennt; lokale Fixturetests sind keine Provider- oder Deploymentabnahme.

[CLI-Rückgabe und reine Postfachzustellung](docs/NATIVE-COMPLETION-RETURNS-20261106.md): Der integrierte Quellstand belässt Antworten/Ergebnisse im Postfach des anfragenden Clients. `--inbox-only` vermeidet Terminalzustellung; Completionquittungen benötigen keinen weiteren Agententurn.

[Frühere Windows-Vorschau dev2](docs/WINDOWS-DEVELOPMENT-20261103.md):
Native Tastatur und lokales MCP haben die Abnahme in einer eigenen Windows 11-VM bestanden.
[Ergebnisse und Grenzen](docs/WINDOWS-DEVELOPMENT-20261103.md); macOS bleibt getrennt.

[Frühere Windows-Desktop-Vorschau dev3](docs/WINDOWS-DESKTOP-20261104.md): Alle sechs nativen
Gastprüfungen bestanden, einschließlich Ctrl-/Alt-/Shift-Kombinationen und
abgesicherter Fenstersteuerung. Die dokumentierte Windows 11-Installation ist
geprüft. [Belege und Grenzen](docs/WINDOWS-DESKTOP-20261104.md);
der frühere dev2-Nachweis bleibt für Rückfallhinweise erhalten.

Im Entwicklungsstand bleibt der CLI-Start vom optionalen Linux-PTY-Modul unabhängig: POSIX-Terminalabhängigkeiten werden erst bei dessen Ausführung geladen. Der erzeugte Windows-CMD-Starter erhält Kindprozess-Exitcodes, auch wenn ein Rollback die aufrufende Datei neu schreibt. Ein begrenzter öffentlicher Windows-CI-Job prüft Import, CLI-Hilfe und diesen Startervertrag; das ist keine Desktop- oder Installerabnahme. Aktuelles Paket und Windows-Installation ohne erhöhte Rechte benötigen weiterhin eigene native Belege.

### Designquellstand · 7. November 2026

Der gemeinsame Header mit fünf Originalicons ist implementiert und lokal geprüft.
Der [Designnachweis](docs/FIVE-TOOL-DESIGN-20261107.md) beschreibt Status-/Versionsgrenzen
und die bestandene Browserprüfung; die installierte native App bleibt ungeprüft.
Diese Quelllieferung belegt keinen neuen Download oder installierten Laufzeitstand.

### Nativer Familienfensterwechsel (Quellstand)

Die vorhandenen fünf Icon-Hosts können `kirabridge --principal local family switch
TARGET --source-pid EIGENER_NATIVE_PID` aufrufen. Der macOS-Broker verwendet den
installierten nativen Systemhelper und die bestehende Policy ohne Taskdatenbank.
Vor Launch/Reopen gelten weiter die freigegebenen `roots` und State-Ausschlüsse;
Registrierung und automatische Capabilities erweitern keinen Pfadzugriff.
Er prüft registrierte Installation/PID/Start/UID und die tatsächliche Aufruferkette,
überträgt äußere Fenstermaße, bestätigt den Zielfokus und verbirgt erst danach die
anderen registrierten Familienfenster. Prozesse und UI-Zustände bleiben erhalten;
die 4AllPass-Sperrregeln gelten weiter. UNKNOWN blockiert blinde Wiederholung;
fehlende oder mehrdeutige Ziele bleiben Fehler. [Registrierung, JSON-ABI und
Abnahme](docs/FAMILY-WINDOW-BROKER.md) sind von Installation und bestehenden
Downloads getrennt.
