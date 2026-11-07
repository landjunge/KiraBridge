> Update: RC36 was subsequently installed and its tab-switch failure reproduced.
> The local RC37 repair is installed and natively verified on Intel; see
> [current recovery evidence](TERMINAL-RECOVERY-20261104.md). Historical tasks below remain unchanged.

# Terminal-Kette · Befund und Lieferstand vom 4. November 2026

**RC34 ist tatsächlich installiert; RC36 ist gepusht, veröffentlicht und vorbereitet,
aber noch nicht installiert.** Die Basisanforderung zuverlässiger Fenster-, Tab-
und Eingabezuordnung nach jedem Chat-/Sitzungswechsel ist noch nicht vollständig
abgenommen. Nach dem zunächst rein lesenden Auftrag autorisierte der Nutzer
ausdrücklich Reparatur, Push und Installation.

## Konkrete Tasks und Zustandsübergänge

| Task | Belegter Ablauf | Einordnung |
|---|---|---|
| `windows_installer_prompt_1104` | RC33, 1014 Zeichen: Zielprüfung → Paste → Anzeige `[Pasted Content 1014 chars]` → `exact_widget_mismatch` → `unknown / visible_insert_unknown`; kein Return nachgewiesen | Falsche Echoablehnung bewiesen. Die Zählanzeige beweist weder den vollständigen Inhalt noch Agentenverarbeitung. |
| `kb_merge_team_prompt_20261104` | RC30, 1078 Zeichen: derselbe belegte Rendererübergang → `unknown / visible_insert_unknown` | Gleiche Ursache vor RC33; kein durch das Upgrade neu eingeführter Parserfehler. |
| `windows_installer_enter_1104` | Cursor-, Pane-, Shell-/Agent-PID- und Bildschirmvergleich bestanden → `failed / visible_target_unknown` vor Eingabe | Warnfooter als Bereitschaftshindernis reproduziert; ursprüngliche interne Protokollbeobachtung fehlt. Kein Nachweis eines OS-Identitätsverlusts. |
| `kb_merge_return_newline` | `keyboard.control` gegen Terminal → `unknown / macos_terminal_route_required` | Falscher Steuerungspfad, kein belegter Enter-Effekt. |
| separater `session_busy`-Fall | `session.open(argv=["codex"])` hatte Codex bereits gestartet; anschließender Startversuch verweigert | Dieser Busy-Schutz ist sachlich erforderlich. |

Originale Taskzustände wurden abschließend erneut gelesen und blieben unverändert;
keine historische unbekannte Eingabe wurde wiederholt.

Der Vorher-/Nachher-Text beider Pastefälle stimmt mit den ursprünglichen
Verifikations-SHA256 überein. Nach Paste verschwindet die Shortcutzeile, während
derselbe Warntext an derselben absoluten Spalte bleibt. Die alten Parser
normalisierten Warnbadges nur an der Modellzeile und entfernten nur einen nackten
Shortcut-Hinweis. Exakte Guards:
[`_same_hint_warning_footer`](../src/kirabridge/literal_session_input.py),
[`assess`](../src/kirabridge/visible_readiness.py) und
[Return-Prüfung](../src/kirabridge/session_return.py).
Parserdateien waren in RC30 und RC33 bytegleich. Details und Testgrenzen:
[Footerbericht](CODEX-FOOTER-20261104.md).

## Drei frühere Reparaturansätze

1. `881a53f`: Literalpfad statt Agenten-Auftragshülle bei `/resume`;
   bekannte Transkriptnavigation durfte Bereitschaft nicht dauerhaft vergiften.
   Spätere Proben zeigten zusätzliche Leerzeilen-/Badgeformen.
   [RC20 Terminal Input](RC20-TERMINAL-INPUT-20261030.md).
2. `3eb67c6 → ecb76cb`: cursorgebundener Enter und Frontend-/Deploymentkorrektur.
   Erster Kandidat scheiterte nativ an CWD-Reflow/kompaktem Resume-Footer und wurde
   zurückgerollt; Folgekorrektur bestand begrenzte Abnahmen.
   [RC20 Return](RC20-RETURN-20261031.md).
3. `acc1c85`: Softwrap-Echoprüfung und mehrzeiliger Return nach einem konkreten
   886-Zeichen-Fall. Komplexere Unicode-/Whitespaceformen blieben begrenzt.
   [Wrapped Prompt Repair](WRAPPED-PROMPT-REPAIR-20261031.md).

Die Ansätze deckten spätere Rendererzustände nicht vollständig ab. Historisch gab
es zusätzlich echte Bindungsfortschreibungs-/TTY-Wiederverwendungsfehler und eine
falsche globale Busy-Sperre durch fremde UNKNOWN-Reservierung
([RC20](RELEASE-0.8.0rc20.md), [Issue 51](ISSUE51-SHELL-PROMPT-20261030.md)).
Die vier aktuellen Tasks beweisen diese historischen Ursachen nicht.

## Nachgewiesene Engpässe und Korrekturen

| Befund / Nachweisgrad | Änderung und Grenze |
|---|---|
| Footerablehnung: bewiesen durch Original-SHA und Replay | RC34 akzeptiert ausschließlich den exakten bekannten Warnfooterübergang bei unverändertem restlichem Inhalt. Aktive Turns, unbekannte Dialoge und Identitätswechsel bleiben gesperrt. |
| Tastensequenz: 17 Einzelrequests, 57,598 s gesamt, davon 50,512 s zwischen Tasks (87,697 %) | RC34 empfiehlt den vorhandenen `keyboard.sequence`-Pfad, auch über `action_request` bei altem Apps-Katalog. Ein App-Inventar statt N, weiterhin frische Prüfung je Taste, maximal 32 echte Tastenpaare. Netzwerk-/Modell-/Transportanteile sind nicht einzeln gemessen. |
| Fünf historische Fensterablehnungen am alten Geometrievergleich; ursprüngliche Geometriepaare fehlen | RC34 ersetzt starre alte Hostgeometrie durch positive AX-/Tabpartition-/CG-Identität; andere Flächen bleiben exakt gebunden. Historische Einzelursachen dadurch nicht rückwirkend bewiesen. |
| Erfolgreicher RC34-Befehl: 15,342 s intern, 11,710 s vor Running; Code zählt sechs vollständige Kataloge | RC35 reduziert auf vier gesamt / drei vor Eingabe. Zwei Screens bleiben frisch; abschließende Lock-/PID-/TTY-/Fokusprüfungen bleiben. Produktiver RC35/36-Zeitvergleich fehlt. |
| CG=0, drei frisch positiv minimierte AX-Fenster: persistent reproduziert | RC36 behandelt minimierte Anker getrennt von sichtbaren CG-Flächen und erhält sie unverändert. Keine automatische Wiederherstellung fremder Fenster. |
| Aktuelle eigene logische Fenster-ID vorhanden, eigene Nonce fehlt in sichtbarer CG-/AX-Ansicht | Physische Zuordnung tatsächlich unbestätigt; derzeit keine begründete Guardlockerung. Ursache zwischen Tabcontainer, Space und Fokus noch offen. |

Quellstände: RC34 `1a57394`, RC35 `2b432a9`, RC36 `d4aebdd`.
RC34: 317 verschiedene fokussierte Fälle. RC35: sechs gezielte Fälle sowie
21 Fälle der betroffenen Datei inkrementell; Gruppen überschneiden sich.
RC36: fünf neue plus 29 betroffene Fälle. Unabhängige Code-/Paketreviews,
lokale Intel-Pakete und veröffentlichte Downloadfingerabdrücke geprüft.
Keine Cloud-CI, Windows-Builds oder fremden Worktree-Änderungen.

## Aktuelles Installationshindernis

Ein verifiziertes RC36-Bootstrap ohne Produktionslistener erzeugte genau eine eigene
Ressource `terminal:3695:ttys005`, Shell-PID 43218. Der Task
`rc36_owned_bootstrap` stoppte als UNKNOWN bei der Fokusprüfung **vor argv**.
Die bestehende Ressource wurde nicht nochmals erzeugt.

Die logische Terminal-Ansicht kennt ID/TTY/Nonce. Eine unabhängige frische
CG-Abfrage sieht die eigene ID jedoch nur außerhalb der Onscreen-Menge.
Ein neuer Helperprozess bestätigt denselben Widerspruch; ein bloßer
Inventarcache ist damit nicht belegt. Die einzige damalige sichtbare Fläche
war fremd und wurde nicht für Eingaben verwendet.

Eine unabhängig geprüfte einmalige Auswahl des exakt eigenen Window-Menüeintrags
stoppte mit macOS `-1728` („Objekt kann nicht gefunden werden“). Der genaue
Objektzugriff und ein möglicher Menüeffekt sind nicht nachgewiesen; kein Replay.
Ein breiter Fehler→Detach-Fallback wurde in der Prüfung verworfen und vor
Ausführung vollständig entfernt. Keine Installer-Start-/Ergebnismarker, keine
bestätigte physische Bindung, kein neuer Installationstask vorhanden.
Das eigene Fenster bleibt zur gezielten Fortsetzung erhalten; keine weitere
Fenstererzeugung. Parallel neu auftauchende fremde Sitzungen wurden nicht benutzt.

Abschlussbeobachtung: Core 37967 / Instanz
`93839d0cff304feead3d04f93b8159ff` weiterhin RC34.
Alle elf ursprünglichen geschützten Prozessidentitäten und vier
Konfigurations-/Credentialhashes unverändert.
RC36-Paketquelle bleibt `d4aebdd89a206045731f2692a3f363fddaa15ee0`;
spätere Dokumentationscommits ändern diese Paketidentität nicht.
[Lieferstatus](evidence/rc36-delivery-status-20261104.json).

Zusätzliche Beobachtungslücke: `diagnostics_storage` meldet
`budget_exhausted` bei 20.000/20.000 Einträgen. Der
[AuditObserver](../src/kirabridge/diagnostics.py) verwirft dann neue
Diagnosemetadaten, ohne Aufgaben zu blockieren. Kein Nachweis eines
Laufzeitengpasses; keine Löschung oder Budgetänderung vorgenommen.

## Minimaler weiterer Testplan und fehlende Belege

1. **Zuerst Sichtbarkeit herstellen/beobachten:** die eine vorhandene eigene
   Ressource auf dem aktiven macOS-Desktop eindeutig nachweisen; in einer
   begrenzten Beobachtung PID/Geburt, logische ID/TTY, Nonce, native CG-/AX-Fläche,
   Worker und Fokus zusammen erfassen. Ohne Kohärenz keine Eingabe oder Installation.
2. **Dann einmal regulär installieren:** gleiche eigene Ressource, Backup/Idle/
   Sichtbarkeits-/Integritätsgates; anschließend tatsächlich laufende Quelle,
   Python-/Nativebytes und geschützte Prozesse/Dateien prüfen.
3. **Ein harmloser Befehl und Zeitvergleich:** genau ein eigener `printf`,
   Start-/Running-/Endezeiten und Kataloganzahl erfassen; kein allgemeiner
   Geschwindigkeitsfaktor aus einer Probe.
4. **Kleine Zustandsmatrix:** Wiederverbindung/neuer Chat mit gleichem Principal,
   Core-Neustart und neue Agent-PID; minimierte/gemischte Fenster.
   Unveränderte, frisch bestätigte Identität darf genau einmal schreiben;
   geänderte PID-Geburt, UNKNOWN-Reservierung derselben oder nicht sicher
   unabhängigen Zielressource, Dialog oder fehlende Fläche müssen vor Eingabe
   stoppen. Eine positiv unabhängige eigene Ressource darf allein wegen einer
   fremden UNKNOWN-Reservierung nicht blockieren. Nur eigene Testressourcen.
5. **Begrenzt offene Fälle:** ursprüngliche Enter-Protokollbeobachtung,
   fünf historische Geometriepaare, generischer nativer `keyboard_unsupported`-
   Grund und vollständige native Chat-/Threadwechselmatrix fehlen.
   Zwei simulierte Bridge-Reopen-Fälle und ein tatsächlicher RC34-Shellbefehl
   ersetzen diese Matrix nicht. Bereits bestandene Parserproben nicht wiederholen.

Private Originalbelege liegen in den drei Verzeichnissen
`~/KiraBridge-footer-audit-20261104`,
`~/KiraBridge-terminal-latency-audit-20261104` und
`~/KiraBridge-terminal-minimized-audit-20261104`; keine Rohbilder,
Fenstertitel oder Gesprächsinhalte in Release-Assets.
