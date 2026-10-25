# Terminal design preview / Terminal-Designvorschau

Eigenständiger Entwurf auf Basis `6739343`, ohne Änderungen am Installer, Dienst,
Bedienfenster oder produktiven KiraBridge. Keine Animation, GPU, Downloads oder
zusätzlichen Abhängigkeiten; Python 3.8 oder neuer genügt. Das vollständige Wort **KiraBridge**
und die räumliche Brücke bestehen aus Unicode-Braillezellen. Pink geht in helles
Pink über; weiße Lichtkanten setzen Akzente. Ein dunkler Terminalhintergrund wird
vorausgesetzt und nicht verändert.

```sh
python3 scripts/preview_terminal_design.py --width 100 --color always
```

`--color auto` (Standard) nutzt Farbe nur am Terminal, respektiert `NO_COLOR` und
`TERM=dumb`: `COLORTERM=truecolor`/`24bit` aktiviert RGB, `TERM` mit `256color`
verwendet die 256-Farben-Palette; sonst bleibt die Ausgabe monochrom.
`--color always` erzwingt RGB und überschreibt diese automatischen Schutzwerte
ausdrücklich. `--color never` behält die Braillegrafik ohne ANSI-Sequenzen.
`--ascii`, eine nicht unterstützte Ausgabe-Encoding oder Breiten unter 30 Zeichen
verwenden einfachen ASCII-Text; sehr schmale Ausgaben umbrechen den Namen. Zulässig
sind 1–160 Spalten. Die Schrift skaliert in vier festen Stufen, statt Buchstaben
abzuschneiden. Die Vorschau sendet ausschließlich Text und gegebenenfalls
SGR-Farbsequenzen; keine Bildschirm-, Clipboard- oder Fenstersteuerung.

Review-Artefakte aus demselben deterministischen Renderer:

- [Brailletext ohne Farbe](design-preview/terminal-braille-100.txt)
- [SVG auf dunklem Hintergrund](design-preview/terminal-braille-100.svg)

```sh
python3 scripts/preview_terminal_design.py --width 100 --color never \
  --text docs/design-preview/terminal-braille-100.txt \
  --svg docs/design-preview/terminal-braille-100.svg
```

Exporte sind optional und auf dieses Repository begrenzt. SVG verwendet exakt
dieselben Braillezeichen und RGB-Werte als Monospace-Text, ohne externe Assets;
die tatsächliche Punktform hängt von der verfügbaren Schrift ab. Der Entwurf
ist keine nachgewiesene Änderung der installierten Benutzeroberfläche.

**English:** This standalone static preview renders the entire KiraBridge wordmark
and a perspective bridge using Unicode Braille dots, with a pink/light-pink gradient
and white highlights. It never launches or changes KiraBridge. Use `--color never`
for plain Braille, or `--ascii` for the bounded plain-text fallback. Automatic color
respects `NO_COLOR`, redirected output and `TERM=dumb`, and selects RGB only with
explicit truecolor support, otherwise a declared 256-color palette or monochrome.
`--color always` explicitly overrides those automatic settings. Incompatible encodings and
narrow terminals fall back safely. Text and SVG share one renderer. No animation,
external assets or third-party packages are required. Installation remains separate.

## Prüfung und bewusstes Ende dieses Schritts

Agent `receiver_contract_audit` hat nur den notwendigen gebündelten Render-/Fallbackcheck
ausgeführt: alle Grafikzeichen Braille, deterministischer Renderer, identischer SVG-Text,
RGB/256/monochrom, NO_COLOR/TERM=dumb/Umleitung, expliziter Farb-Override, ASCII,
Encoding und schmale bzw. ungültige Breiten. Ruff und Diffprüfung bestanden.
Gemessener einzelner100-Spalten-Render:0,0153 Sekunden auf dem vorhandenen Intel-Mac
mit Python3.8; kein gesonderter Hardwarebenchmark auf einem weiteren iMac2015.
Der erste Export stieß auf Python3.8s fehlendes Path.is_relative_to; nur diese
Kompatibilität korrigiert, anschließend den betroffenen Export erfolgreich geprüft.
Root hat die vollständige [PNG-Vorschau](design-preview/terminal-braille-100.png)
aus dem SVG mittels macOS sips erzeugt und visuell geprüft. Ein zunächst
abgeschnittenes QuickLook-Thumbnail war kein abgeschnittener Terminaltext; für die
Vorschau wurde der vollständige SVG-Export verwendet. Numerische Hintergrundmaße
vermeiden einen zusätzlichen Prozentmaß-Rendererunterschied.

Keine Änderung an install_ui.py, MCP-stdout, Dienst, Berechtigungen oder Produktion.
Aktuell läuft produktiv weiter RC17/012b592; Quelle dieser Vorschau ist getrennt.
Nach Vorführung wird wie beauftragt angehalten; keine Installation oder Integration
des Designs ohne folgenden Nutzerauftrag. Pflicht-CI bleibt durch Abrechnung blockiert;
RC17 bleibt Entwurf. Bibliotheksarbeit aus PR33 wurde hier nicht dupliziert.
