# Braille-Terminal-Installer – Bestandsaufnahme und Prüfplan

Stand: 26.10.2026. Nur Planung; keine Designintegration oder neue produktive Installation.

## Tatsächliche Ausgangspunkte

- Produktiv: RC17 aus `14468ad5e7b28be1c1c4312d2f4517582dbc7701`; eigener Reparaturbranch `fix/queue-withdraw-visible-install-20261026`, PR41. Stabilitätsarbeiten bleiben getrennt.
- Bestehender Designentwurf: PR34, Branch `design/braille-preview-20261025`, Commit `ada6e37df1be607bfdc0dec8428e609c12d46ef8`, Worktree `../braille-preview-20261025`. Offen/Draft, nicht integriert oder installiert.
- Veröffentlicht bleibt `v0.8.0rc14`. RC15/RC16/RC17 sind Entwürfe. Ein installiertes RC17 ist kein veröffentlichtes Release.
- Original „KiraBridge – Ausbauplan und Braille-Terminal-Installer“ vom 25.10.2026: im geprüften Repositorybestand und in zwei verfügbaren Pages-/Bibliothekssuchen nicht eindeutig nachgewiesen. Die Suche ist kein vollständiger Nachweis der Abwesenheit. Vor endgültigem Soll-Abgleich ist der autorisierte Originaltext bzw. eine genaue zugängliche Referenz erforderlich. Kein Original verändert oder exportiert.

## Vorhandene Dateien und Belege

Im Designworktree:

- `scripts/preview_terminal_design.py`: reine stdlib-Funktionen `canvas`, `render`, `plain`, `terminal`, `svg`, `fallback`; vollständiger Brailleschriftzug und perspektivische Brücke.
- `docs/TERMINAL-DESIGN-PREVIEW.md`: vorhandene Bedienung und Grenzen.
- `docs/design-preview/terminal-braille-100.txt`, `.svg`, `.png`: vorhandene Exporte. PNG erneut visuell geprüft; Dateien nicht neu erzeugt oder überschrieben.
- `docs/design-preview/evidence.json`: historische gezielte Render-/Fallbackprüfung, 0,0153 s für einen Render auf diesem Intel-Mac; kein neuer Performance- oder iMac-2015-Benchmark.
- SHA256 Renderer: `abe22463aea3957e8f630d5f95572b0789abc7d9995bdceb0711ab1b2764bf5b`.
- SHA256 PNG: `b9351c9ee22fff4a3d89526f515740da20e51af3665e8a53b51f3e0fd5b5fd12`.

Im bestehenden KiraBridge:

- `src/kirabridge/install_ui.py`: bisheriges ASCII-/Cyan-Setup, menschliche Ausgabe auf stderr.
- `src/kirabridge/installation.py`: geführtes Setup, andere Frontdoor als das versionierte macOS-Paket.
- `scripts/build_release.py`, `installer/release-install.sh`, `installer/install.py`: tatsächliche Paket-Frontdoor und Transaktionen, Sicherung, Versions-/Healthprüfung, Rollback und launchd.
- `docs/INSTALLATION-EXPERIENCE.md`, `docs/DEVELOPMENT_PLAN.md`: vorhandene Installationswünsche und eigenständige modulare Architektur. Historische Pläne vom 18.10. ersetzen nicht das Original vom 25.10.

## Nachgewiesene Lücken

1. Der Entwurf ist statisch: Punktaufbau, Lichtimpuls und Reduced Motion fehlen.
2. Er verwendet `#F23DA0`, nicht das gewünschte `#F06DB0` (RGB 240,109,176).
3. Der echte macOS-Paketinstaller ruft `SetupUI.banner()` nicht auf. Nur dort zu ändern wäre wirkungslos für den gewünschten Installationsbefehl.
4. Das Vorschau-Script wird bisher nicht ins macOS-Paket aufgenommen. Ein Import aus `scripts/` würde im gebauten Paket scheitern.
5. Farbfallbacks, Encoding-/ASCII- und Breitenbehandlung bestehen in der Vorschau; ihre tatsächliche Paketintegration, Animationsabbruch und Sichtbarkeitsabnahme fehlen.

## Vorgesehene modulare Umsetzung – noch nicht begonnen

1. Den vorhandenen deterministischen Renderer weiterverwenden und als eine gemeinsame, reine stdlib-Präsentationskomponente verpacken. CLI-Vorschau und echter Paketinstaller verwenden dieselbe Implementierung. Keine zweite Schrift-/Brückengenerierung, kein ThreadDesk-, Hersteller-, Netzwerk-, GPU- oder Laufzeitdienst-Zwang. Assets samt SHA-/Buildnachweis deterministisch mitführen; vorhandene Exporte bewahren.
2. Exakte Palette `#F06DB0`, helleres Pink und weiße Lichtakzente festlegen. Nur Grafikzellen im Bereich U+2800–U+28FF, normale lesbare Beschriftungen für Schritte. Kein Ändern der Terminaleinstellungen oder des Nutzerhintergrunds.
3. Optionalen Animationscontroller getrennt vom Installerzustand vorsehen: geordneter Punktaufbau und kurzer Lichtimpuls, feste Frame-/Ausgabebudgets, kleine begrenzte Puffer, veraltete Frames verwerfen. Keine dekorativen Sleeps, wartenden Locks oder unbeschränkten Joins im Installationspfad. Fehler, Eingabe und echte Statusmeldungen haben Vorrang; bei langsamer Ausgabe oder fehlender Unterstützung sofort statische Darstellung. Reduzierte Bewegung vollständig statisch, kein verdeckter dauernder Effekt. Der Installer wartet nie auf Animationsabschluss.
4. Bestehende Fähigkeiten übernehmen: TTY und Encoding prüfen, `NO_COLOR`, `TERM=dumb`, RGB/256/monochrom, ASCII bei unpassender Unicode-Unterstützung oder kleiner Breite, keine Escape-Sequenzen in umgeleiteten Protokollen. Explizite Bewegungsoption und dokumentierte sichere Standardwahl. Kein Banner in MCP-stdout, Status-JSON, Daemon oder Agentenausgaben.
5. Vorhandene reale Installationsereignisse darstellen: Voraussetzungen, Paket-/SHA-Prüfung, Vorbereitung, Leerlaufprüfung, Backup, Umschaltung, Health/Version und gegebenenfalls Rollback. Keine erfundenen Prozentwerte oder Erfolgsanzeigen. Abschluss trennt lokale Dienstprüfung von einem tatsächlich ausgeführten ChatGPT-Zielaufruf.

## Spätere sichtbare Installation – jetzt nur vorbereitet

Erst nach ausdrücklicher Freigabe des konkreten Pakets und der produktiven Installation:

1. Authentifizierten privaten Download und SHA-Abgleich im sichtbaren Ablauf dokumentieren. Keine erfundene URL und kein `curl | sh`.
2. Ein separates eigenes sichtbares macOS-Terminalfenster eröffnen. Keine Eingabe in bestehende Codex-/Grok-Fenster. Fenster-ID, Tab, TTY, Shell-PID und Prozessstart frisch eindeutig abgleichen; `isatty`, erreichbares `/dev/tty` und tatsächlich sichtbare Fensterzuordnung nachweisen. Eine bloße PTY oder ein gespeicherter alter Handle reicht nicht.
3. Sichtbarkeit unmittelbar vor Aktivierung erneut prüfen. Bei fehlender oder geänderter Zuordnung kontrolliert vor Umschaltung abbrechen; kein unsichtbarer Ersatz. Fensterverlust während der Transaktion muss über den vorhandenen Abbruch-/Wiederherstellungsweg sicher behandelt werden, nicht durch Signale an fremde Sitzungen.
4. Schriftzug, Animation, alle Schritte, Fehler und den abschließenden echten Version-/Diensttest in diesem Fenster zeigen. Keine Zugangsdaten ausgeben. Fenster und Ergebnisprotokoll zur Ansicht offen lassen.
5. Nach erfolgreichem Abschluss bleibt der launchd-Dienst unabhängig vom Fenster aktiv. Das Schließen von Terminal oder Browser darf ihn nicht beenden.

## Update und Rollback

Die vorhandene versionierte Installation und Transaktionssicherung weiterverwenden: Kandidat vollständig vor Dienstwechsel prüfen; bestehende Konfiguration, Rechte, Credentials, Whiteboards und Nutzerdaten erhalten; fremde Dienste und laufende Arbeit nicht überschreiben. Vor Aktivierung auf gesicherten Rückweg, gespeicherte alte Quelle/Plist und Datenverträglichkeit prüfen. Bei Fehlern bekannten gesunden Dienst über vorhandenen Rollback wiederherstellen und tatsächliche Version/Health zurücklesen. Kein Datenbank-Backup blind zurückspielen, keine Historie oder Queue-Holds löschen. Design bleibt bis zur Abnahme eigener überprüfbarer Patch.

## Nur notwendige spätere Tests und Abnahmekriterien

- Gezielte Rendereränderungen: vollständiger Name, Braille-Zeichenbereich, exakte Palette, Breite, deterministische Ausgabe, Fallbackmatrix und gleiche Zellbasis für Exporte.
- Fakeclock-/Streamfälle: Punktreihenfolge, Lichtimpuls, statischer Reduced-Motion-Modus, begrenzte Frames/Puffer, langsame/gebrochene Ausgabe, Prompt-Priorität sowie Reset/Zeilenabschluss bei Fehler und Abbruch. Kein Warten des Installers auf dekorative Ausgabe; tatsächliche Laufzeitwirkung auf diesem Intel-Mac messen.
- Paketvertrag: Renderer im gebauten Paket, Manifest/SHA korrekt, fehlende/manipulierte Pflichtassets vor Aktivierung ablehnen; Status-JSON und MCP unverändert maschinenlesbar.
- Danach gezielt das geänderte gebaute Paket in einer isolierten eigenen sichtbaren Terminal-/launchd-Umgebung prüfen: Neuinstallation/Update, echte Schritte und Fehler, Start/Neustart, Datenerhalt und Rollback. Sichtbarkeitsverlust vor Aktivierung als Negativfall, keine fremde Sitzung berühren. Keine Wiederholung unveränderter Gesamtsuiten ohne konkreten Grund.
- Ein lokaler Intel-Pass ist kein ARM-Pass und kein bestandener GitHub-Actions-Lauf. Sicherheits-/Merge-/Release-Gates bleiben bestehen.

## Tatsächliche Teamarbeit

- `terminal_repair`: Renderer und tatsächliche Paket-Frontdoor, sichere sichtbare Bindung; lesend.
- `whiteboard_repair`: vorhandene Assets/Hashes, Update-/Rollback- und UI-Verträge; lesend.
- `receiver_contract_audit`: Quellenabgleich, exakte Farbabweichung, Modularitäts-/Sicherheitsprüfung; lesend.
- Root: Ergebnisse gegengeprüft, vorhandene PNG angesehen, aktuellen Git-/Releasezustand und zugängliche Bibliothekssuche geprüft, dieser Plan und gemeinsames Whiteboard. Kein Unteragent hat für das Design Tests, Codeänderungen oder eine Installation ausgeführt.

Nächster sicherer Schritt: Originalplan abgleichen und diesen Wiederverwendungsplan abstimmen. Danach gegebenenfalls ausschließlich eine getrennte Vorschauänderung umsetzen und prüfen. Keine produktive Designinstallation, kein Merge, keine Veröffentlichung durch diesen Plan.

## Fortgeführte Stabilitätsprüfung – getrennt vom Design

Am 26.10. auf Intel-macOS15.7.4/Python3.11.15: 1522 Tests bestanden, 1 optionaler AA-Quelltest übersprungen; CI-Warnungsmodus aktiv. Gepinnte ThreadDesk-/TollGate-Adapterquellen vorhanden. Der vollständige Paketlauf RC14→144 bestand Upgrade, Datenerhalt, idempotente Wiederholung, Neustart und KeepAlive, scheiterte aber beim RC14-Rollback an der Bereitschaftsfrist von30Sekunden. Der alte Versionszeiger wurde wiederhergestellt; ein gesunder alter Dienst ist nicht belegt. Frische Installation wurde danach nicht erreicht. Testdienst-Cleanup unabhängig bestätigt. Keine Produktionsänderung; keine ganze Testsuite wiederholt. Ein lesender Ursachenabgleich bleibt offen; keine Ursache aus leeren Dienstlogs erfunden. Quelle144 bleibt unverändert.

[Strukturierte lokale Testergebnisse](evidence/local-macos-acceptance-14468ad-20261026.json). Für dieses Planungs-/Belegupdate sind keine neuen lokalen Tests erforderlich; normale Pflichtchecks bleiben bestehen.
