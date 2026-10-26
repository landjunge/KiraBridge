# Gemeinsamer Braille-Renderer / Shared Braille renderer

Dieser Präsentationsbaustein übernimmt die Schrift und räumliche Brücke unverändert
aus PR34, Commit `ada6e37`. Die unverfärbte Zellgeometrie hat weiterhin exakt den
SHA-256 des bisherigen vollständigen 100-Spalten-Entwurfs. Die Primärpalette ist
jetzt **#F06DB0** (240,109,176), mit hellem Pink und weißen Lichtkanten. Historische
Exporte und der alte Entwurf bleiben in dessen Branch erhalten; neue Exporte tragen
eigene Dateinamen.

```sh
python3 scripts/preview_terminal_design.py --width 100 --color auto
```

Die Vorschau lädt dieselbe reine stdlib-Datei, die der Installer verwenden kann:
`src/kirabridge/terminal_design.py`. Sie importiert keine Bridge, startet keinen
Dienst und ändert weder Fenster, Terminaleinstellungen, Zwischenablage noch Queues.
Dies ist noch kein Nachweis einer sichtbaren Installation oder eines neuen Releases.

## Schnittstelle und Bewegung

`API_VERSION=1` bietet `options_for(stream, width=None, env=None, color="auto",
motion="reduced")`, `static_banner(options)` und `AnimationController(options)`.
Die zurückgegebenen Optionen enthalten `width`, `unicode`, `color` und das boolesche
`motion`. Der Controller besitzt **keinen Writer** und keine Hintergrundarbeit:
`poll(now=..., urgent=False)` liefert höchstens einen Frame oder `None` und überspringt
veraltete Frames. Keine Sleeps, Locks, Threads, wartenden Joins oder Countdown-Schleifen.
`finish()` liefert einmal das vollständige statische Endbild, danach `""`.
`cancel()` und `poll(urgent=True)` beenden Dekoration ohne weitere Ausgabe.

Voreinstellung ist reduzierte Bewegung: ein einziges statisches Bild. Explizites
`motion="full"` ermöglicht geordneten Punktaufbau und einen kurzen Lichtimpuls;
`motion="auto"` benötigt dazu `KIRABRIDGE_MOTION=full`. Ein ausdrücklich gesetztes
`KIRABRIDGE_MOTION=reduced` erzwingt immer statische Darstellung. Der Installer kann
an echten eigenen Phasengrenzen pollen; er muss nicht auf die Dekoration warten.
Frames enthalten nur Braillezeichen, SGR-Farben und Zeilenumbrüche, keine Cursor-,
Bildschirm- oder Alternate-Screen-Befehle. Die Folge hängt neue Frames an; sie verändert
keine bereits ausgegebenen Nutzerinhalte. Kein animierter Prozentwert behauptet
Installationsfortschritt.

Maximal acht Frames, höchstens zwei Sekunden logischer Animationszeit, 128 KiB pro
Frame und insgesamt 256 KiB mit reserviertem vollständigem Endbild. Es gibt keine
Warteschlange alter Frames; ein langsamer Konsument springt direkt zum passenden
aktuellen beziehungsweise statischen Endbild. Vor Eingabe, Fehler und langsamer oder
gebrochener Ausgabe muss der **Caller** `cancel()` verwenden. `finish()` ist kein
Fehlercleanup, weil es Grafik ausgibt. Unterbrochene farbige Writes benötigen beim
Caller ein bestmögliches SGR-Reset mit Zeilenabschluss; die Vorschau behandelt
KeyboardInterrupt und BrokenPipe entsprechend. Ein defekter Stream kann keinen
bestätigten Reset garantieren. Die reine Renderinglogik kann keinen fremden Writer
blockieren oder steuern.

## Fallbacks und Exporte

Farben nur an einem geeigneten TTY: RGB bei Truecolor, sonst deklarierte 256-Farben-
Unterstützung oder monochrom. `NO_COLOR`, `TERM=dumb` und umgeleitete Ausgabe erhalten
keine Escape-Sequenzen und keine Bewegung, auch nicht mit `--color always`.
Diese sichere Logausgabe ist gegenüber dem historischen expliziten Pipe-Farb-Override
bewusst strenger. Nicht kompatibles Encoding oder Breiten unter 30 Spalten verwenden
ASCII; `--ascii` erzwingt diesen Fallback. Die Breite ist auf 1–160 begrenzt.

```sh
python3 scripts/preview_terminal_design.py --width 100 --color never \
  --text docs/design-preview/terminal-braille-f06db0-100.txt \
  --svg docs/design-preview/terminal-braille-f06db0-100.svg
```

`--frames` zeigt am geeigneten farbigen TTY die endliche Sequenz ohne dekorative
Wartezeiten. Das ist eine Frame-Vorschau, kein autonomer Animationsthread. Text-/SVG-
Exporte sind ausdrücklich optional und auf das Repository begrenzt. SVG verwendet
dieselben Braillezellen und RGB-Werte; tatsächliche Punktform hängt von der lokalen
Monospace-Schrift ab. Keine externen Assets, GPU oder zusätzlichen Bibliotheken.

[Neuer Text](design-preview/terminal-braille-f06db0-100.txt),
[neues SVG](design-preview/terminal-braille-f06db0-100.svg),
[gezielter Prüf-/Quell-/Hashnachweis](design-preview/renderer-f06db0-evidence.json).

32 gezielte Fälle bestanden: alte vollständige Geometrie, Palette/SVG-Zellgleichheit,
Fallbackmatrix, Breiten, Punktreihenfolge, Lichtimpuls, Frame-/Bytebudget, veraltete
Frames, Prompt-/Cancel-Priorität, isolierter Import ohne Bridge sowie vier
unterbrochene Preview-Write-/Flush-Fälle. Ein einzelner lokaler Intel-Mac-Messwert: statisches
100-Spalten-Bild etwa 0,011 s; Controlleraufbau plus erster 160-Spalten-Frame etwa
0,028 s. Kein separater iMac-2015- oder ARM-Benchmark, keine ganze Testsuite.
Paket-, Sichtbarkeits-, Installations-, Update- und Rollbackabnahme bleiben getrennt.

**English:** The shared dependency-free presentation reuses PR34's entire Braille
wordmark and perspective bridge, with exact primary pink #F06DB0. API1 returns
strings only; caller-polled optional build/pulse motion has no threads, sleeps,
locks or I/O. Reduced motion is static. Unsupported/non-TTY/NO_COLOR/dumb output
has no escapes or animation; narrow/incompatible output falls back to ASCII.
The caller owns prompt priority, cancellation and best-effort reset of interrupted
writes. Thirty-two targeted renderer/preview checks passed; actual packaged installer,
visible macOS installation, service and release acceptance are separate work.
