# Direkte Tastatureingabe ohne Profil · 2. November 2026

## Umfang und erhaltene Basis

Gezielte Tastaturkorrektur auf `f58ed2f`, getrennte Arbeitskopie und Branch
`fix/keyboard-direct-20261102`. Die vorherige stundenlange Entwicklung bleibt
unverändert. Keine Installation, kein produktiver Dienstneustart und keine
Eingaben in bestehende Terminal-/Agentensitzungen sind Teil dieses Schritts.

Live bestätigt: RC24/73d4ea0, Core PID38560, geladene 155 Pythondateien,
Quellhash `801ba911c186be211436b30df70643688f09e815ebcd9585babe35d1203884e7`.
ChatGPT meldet wirksam Voll erlaubt. Der frische Katalog enthält **87** Operationen,
einschließlich bereits erlaubter keyboard.key/chord/text/inspect und Profile.
Die frühere Meldung von76 Operationen beschreibt nicht diese frische Beobachtung.
Der ausgeführte native Worker bestätigte AX und Bildschirmfreigabe; diese
Beobachtung ersetzt keine spätere eigene Post-Event-Prüfung.

## Ursachen und kleiner Patch

- Native Grundbefehle bestanden bereits und verlangen kein Profil. Es fehlten
  eine einfache Zielwahl/Wiederholungszahl und eine entsprechende Konsole.
- `keyboard.input` ergänzt optional den exakten Programmnamen/Bundle-Identifier
  (sonst aktuell aktives Programm), Text oder Taste, Modifier, Anzahl1–20 und
  optional ein finales Return nach Text. Bestehende native Pfade, Rechte,
  Desktoptransaktion, Staging und No-Replay bleiben zuständig.
- Genau ein expliziter Fokusversuch mit begrenzter lesender Nachprüfung. Die
  unmittelbare app.focus-Antwort active_observed=false war live reproduzierbar,
  obwohl eine spätere Beobachtung das Programm bereits aktiv sah.
- Der native Transport sanitisiert Fehlermeldungen. Deshalb konnte eine Prüfung
  auf den ursprünglichen Meldungstext nie funktionieren. Nur die exakt bekannte,
  verifizierte und wirkungsfreie Inspect-Verweigerung wird nun typisiert als
  keyboard_not_frontmost weitergegeben; andere Meldungen bleiben sanitisiert.
- Wiederholungen halten App-, Fenster-, Feld- und Workeridentität. Frische
  Snapshots vor weiteren Paaren; unbekannter Ausgang stoppt ohne erneutes Senden.
  Zurückgekehrte Post-Aufrufe werden nicht als Appverarbeitung ausgegeben.
- Das echte leere Notizen-Feld meldete AXTextArea/Note Body Text View, Fokus und
  gültige UTF16-Auswahl, aber AXSubrole/AXEnabled ausdrücklich unsupported. Beide
  Namen fehlen im vollständigen Inventar; AXSelectedText ist schreibbar. Nur
  für diesen bestätigten System-Notes-Prozess erlaubt eine eng gebundene Regel
  diese Kombination. Explizit secure/disabled, fremde Pfade, fehlgeschlagene oder
  übergroße Inventare und Read-only bleiben vor Value-Zugriff verweigert.
  Fehlende Metadaten bleiben null, Herkunft system_notes_writable_body.
- Die private Live-Prüfung zeigte zusätzlich: Notizen meldet im nachgewiesen
  leeren Body AXValue.noValue bei Zeichenanzahl0 und Auswahl0. Ausschließlich
  unter derselben Notes-Klassifikation und erneutem ausdrücklichem noValue/nil
  darf der leere Wert hergeleitet werden; Fehler, unbekannte/nichtleere Werte
  bleiben verweigert. Die Herkunft system_notes_empty_no_value bleibt sichtbar.
  Der gezielte Swift-Harness bestand nach diesem Delta erneut mit26 Noteschecks
  (fünf neu); die ersten privaten Versuche hatten keine Eingabe ausgeführt.
- Konsole: einfache Eingabe und frischer ChatGPT-Katalogstatus; bisheriger
  Profil-Editor geschlossen unter Erweitert erhalten. Verschwundene ausdrückliche
  Ziele verlangen Neuwahl statt stiller Umleitung zum aktiven Programm.

## Gezielte Prüfung vor privatem Nativebuild

- 64 direkte neue/bestehende Vertrags-/Dispatcherfälle bestanden.
- 7 unabhängige Grenzfälle bestanden.
- Nach konkretem Fokusfehler 94 betroffene Transport-/Direktfälle bestanden;
  unabhängiger enger Nachlauf5 Fälle bestanden. Die Auswahlen überlappen.
- Console-Auswahl14 bestanden, anschließend4 direkt betroffene Fälle nach
  Ergänzung der Verfügbarkeit. Synthetische Browserfälle prüfen Einmalversand,
  Antwortverlust, fehlende Belege, Rechte, Katalogwechsel und Altprofile; ein
  zusätzlicher negativer Fall belegt erhaltenes Ziel bei verschwundener App.
- Ein echter Swiftcompile/Harness bestand in20,39s:21 neue Notes-Grenzchecks
  plus bestehende Snapshot-/Key-/Text-/Stage-/Returnprüfungen. Das ist kein
  tatsächlicher Notizen-Tasteneffekt. Unabhängiger Source-Review freigegeben.
- Ruff, Format, JavaScript-Syntax und Diffprüfungen bestanden im jeweiligen Delta.

## Tatsächliche private Abnahme: bestanden

Produktcode-Commit **c036dfa361054f01269267dcc7bb70cae348f07d**; eigener
nativer App-Build, ausschließlich private HTTP/MCP-Instanz mit Principal
`chatgpt`. Dem Principal waren keine Profilverwaltungsrechte eingeräumt.
Die tatsächlich ausführende private Native-App bestätigte Accessibility und
Post-Event-Rechte. Keine Berechtigung wurde angefordert oder geändert.
Die normale externe ChatGPT-Verbindung wurde nicht auf diesen Kandidaten umgestellt.

Eine eigene neue leere Notiz wurde über die vorhandene Notizen-Menüaktion
erzeugt. Erst nach Nachweis des fokussierten, schreibbaren Body-Felds und seiner
leeren Auswahl wurde geschrieben. Die Testnotiz bleibt als Beleg erhalten.

| Aktion | Tatsächlicher Beleg | Ausführungszeit, ein Messwert |
| --- | --- | --- |
| Text | text_verified=true, ein Versuch, 36 UTF-16-Einheiten | 0,510 s |
| Return, Anzahl 2 | requested/completed=2/2, vier Down-/Up-Postcalls; anschließender Feldbeleg: 38 UTF-16-Einheiten, Cursor 38/0 | 0,481 s |
| Gleiche Return-Auftrags-ID erneut abfragen | ursprünglicher abgeschlossener Auftrag; Feld unverändert, keine zusätzliche Eingabe | kein neuer Auftrag |
| Pfeil links / rechts | Cursor 37, anschließend 38 | 0,201 / 0,203 s |
| ⌘A | Auswahl 0/38 | 0,210 s |
| Auswahl mit rechts kollabieren | Cursor wieder 38/0 | 0,211 s |

SHA256 des Felds nach Return:
`fa3b3e61edc6ff84f538fb13f6bfdc0ebc4f042fcd9df02e01fd9105ca80db6e`.
Der unabhängige Reviewer berechnete ihn erneut aus dem ursprünglichen privaten
Testtext **plus genau zwei LF**. Postcalls allein werden weiterhin nicht als
Appverarbeitungsbeweis ausgegeben: app_processing_confirmed bleibt false;
der zusätzliche AX-Feldbeleg weist den tatsächlichen Effekt nach.
Sämtliche erfolgreichen Eingabeaufträge hatten genau einen Versuch und
keinen automatischen Retry. Einzelmesswerte erlauben keine p95-Zusage.

Zwei private Core-Laufzeiten mit unterschiedlichen Instanz-IDs und
Katalogrevisionen lieferten nach Neustart dasselbe autorisierte, technisch
verfügbare keyboard.input-Schema einschließlich Anzahl1–20 und ohne Profilpflicht.
Kein produktiver Dienst wurde dafür neu gestartet. Der unabhängige Reviewer
prüfte die gespeicherten Originalbelege, ohne Eingaben zu wiederholen.
Die bereinigten Metadaten stehen in
[evidence/keyboard-direct-repair-20261102.json](evidence/keyboard-direct-repair-20261102.json).
Keine Feldinhalte oder nativen Zieltoken werden dort gespeichert.

## Fehlgeschlagene Vorversuche und Grenzen

Die erste private Beobachtungsfixture scheiterte vor jeder Eingabe. Ihr
Diagnose-Streamwrapper unterstützte beim Cleanup zunächst read() nicht; der
private Wrapper wurde korrigiert. Ein vermuteter Double-Roundtripfehler wurde
lesend nicht reproduziert; die Startidentitätsprüfung blieb unverändert.
Der zweite Versuch verweigerte das leere Notes-Feld korrekt vor jeder Eingabe,
bis die beschriebene eng begrenzte noValue-Regel ergänzt und geprüft war.

Versuch03 scheiterte an einer falschen Assertion im privaten Testharness:
Ein zulässiges error=null wurde als Fehler behandelt. Sein akzeptierter
Textauftrag bleibt explizit unknown; private Datenbank und Workerzustand wurden
lesend abgeglichen: kein Ausführungsbeginn, side_effect_possible=false,
dispatcher_shutdown, Worker beendet, Testfeld zweimal weiterhin leer.
Kein Replay dieses Auftrags. Der korrigierte Harness wurde erst danach mit
neuer Auftragsidentität ausgeführt. Originaldatenbank und Logs bleiben erhalten.

Die Scope-Beschriftung des erfolgreichen Harness war zunächst aus der alten
Fixture übernommen. Sie wurde transparent korrigiert; ursprüngliche Beschriftung
und Korrektur sind im privaten Beleg enthalten. Native Pfad-/Commitbelege
verwiesen durchgehend auf den eigenen Kandidaten, nie auf einen installierten Patch.

Bestanden sind die gezielten Vertrags-, Sicherheits-, Native-, UI- und privaten
Notizenprüfungen. Keine pauschale Aussage über sämtliche Programme, fremde
Eingabefelder oder eine vollständige Release-Regression. Ein öffentliches
Release-Paket wurde nicht veröffentlicht. Installation und Abnahme über die
produktive ChatGPT-Verbindung bleiben ein gesonderter autorisierter Schritt.

## Artefakte und unveränderte produktive Installation

- Produktänderungen: f5d2e84; gezieltes Empty-Notes-Delta: c036dfa.
- Privater Build: `~/.local/share/kirabridge/backups/keyboard-direct-repair-20261102/native-candidate-empty/KiraBridge.app`.
- Native Binärdatei SHA256: `19ffc3b59c8d6a9c7f4d8bf5470035089143b949ad635171ebbca40299535dbb`.
  Der App-Build ist auf Produktcommit c036dfa gepinnt; spätere reine Berichtscommits
  ändern diesen gebauten Produktstand nicht.
- Quellbackup vor Änderungen: `source-before.tar.gz`, SHA256
  `efd04d422db42359659f1580c342bfcacc1699d427b7c2d1077a4d06e5e09fbb`.
  Private vollständige Logs und Testbelege liegen neben diesem Archiv; sie bleiben lokal.
- Installiert bleibt **0.8.0rc24 / 73d4ea0**, produktiver Core PID38560 mit
  identischer Instanz und Startzeit. Katalog weiterhin87 Operationen;
  der neue keyboard.input-Befehl ist dort erwartungsgemäß noch nicht enthalten.
  Konfiguration, Installationsmanifest und globaler Native-Binärhash blieben gleich.
- Ursprüngliche Entwicklungsarbeitskopie sauber und unverändert. Codex PID3552
  und seine Shell PID3524 blieben erhalten. Die frühere GUI-Companion-PID27279
  war bei Abschluss nicht mehr vorhanden; Ursache unbekannt, keine gezielte
  Stop-/Quit-Aktion durch diese Reparatur. Deshalb keine Behauptung, alle
  GUI-Prozesse seien unverändert geblieben.

Für eine spätere Installation: überprüften Produktstand über den vorhandenen
Upgradeweg übernehmen, Rechte der tatsächlich ausgeführten Native-App prüfen,
Core-/Katalogidentität abgleichen und dieselbe eigene Testnotiz über die reale
ChatGPT-Verbindung abnehmen. Aktuell ist keine weitere manuelle Profileinrichtung
oder pauschale erneute Freigabe als Voraussetzung belegt.
