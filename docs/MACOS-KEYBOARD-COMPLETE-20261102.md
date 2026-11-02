# RC26: macOS-Tastatur — Ergebnis und Abnahme vom 2. November 2026

**RC26 ist veröffentlicht, installiert und über den echten ChatGPT-Apps-Connector
abgenommen.** Der Fehler `keyboard_unsupported` in Apple Notizen und die gemeldeten
Probleme mit Systemkombinationen, Lautstärke und Helligkeit sind in den unten
aufgeführten Prüfungen behoben. Die erforderlichen macOS-Freigaben sind vorhanden.

- Betriebscode und Release-Tag: `34f5e6da7d7232407c20ca98afd168021e7804ce`, `v0.8.0rc26`.
- [Intel-Installationsapp und kompatible Runtimepakete](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc26).
- [Bereinigte maschinenlesbare Abnahme](evidence/rc26-keyboard-final-acceptance-20261102.json).
- Prüfgerät: Intel-iMac17,1, macOS 15.7.4, eingebautes Retina-5K-Display.

## Ursachen und Änderungen

Die Anfrage nannte RC24; auf dem Mac lief nach dem vorherigen Update bereits RC25
mit derselben betroffenen Tastaturimplementierung. Eine eigene Testnotiz
reproduzierte den Fehler über den authentifizierten Apps-Connector. Der unbekannt
beendete Auftrag wurde nicht erneut eingereicht; ein unabhängiger Inhaltslesecheck
bestätigte, dass der Text fehlte.

Apple Notizen liefert für einen beschreibbaren Textbereich teilweise keine
`AXEnabled`- oder `AXSubrole`-Attribute. Leere Bereiche können außerdem keinen
`AXValue` liefern. Der bisherige Vertrag verweigerte solche Ziele. RC26 erkennt
den originalen System-Notizen-Textbereich anhand geprüfter App-/Elementidentität,
Schreibbarkeit, Zeichenzahl und Auswahl. Schutzprüfungen für sichere Felder,
Fokus, Layout und geänderte Prozessgenerationen bleiben wirksam.

Programmgerichtete Tastenereignisse reichen für globale macOS-Funktionen nicht
aus. RC26 verwendet für Systemkombinationen den HID-Ereignisstrom und für
Lautstärke, Helligkeit und weitere Sondertasten systemDefined-Signale. Die
aktuelle Shortcutkonfiguration und die öffentliche Carbon-Registrierung werden
beobachtet; deaktivierte oder unbekannte Belegungen werden nicht erfunden.

Command-Tab benötigte echte Modifier-Loslassereignisse. Die praktischen Tests
fanden zusätzlich eine zeitliche Abhängigkeit: HID-Abfragen zeigen auch unsere
eigenen synthetischen Modifier. RC26 verfolgt diese über die gesamte Folge und
wartet danach höchstens 200 ms rein lesend auf gelöste eigene Zustände. Fremde
Modifier führen weiterhin zum Anhalten. Ein Post-Aufruf gilt nicht als
Verarbeitungsquittung; unbekannte Teilwirkungen werden nicht wiederholt.

Ein Fn-Klassifikationsbit bei Pfeil- und F-Tasten wird beim normalen KeyUp
entfernt. Explizit angefordertes Fn bleibt erhalten. Caps Lock wird öffentlich
über IOHID gesetzt und zurückgelesen, in gewöhnlichen Folgeereignissen erhalten
und getrennt von literalem Unicode behandelt. Der Beleg dafür nennt null
Ereignisposts und die tatsächlichen Zustandsänderungen.

## Praktisch bestätigte Funktionen

Eine eigene signierte Empfangs-App und eindeutig zugeordnete eigene Notizen
verhinderten Änderungen an bestehenden Benutzerdokumenten. Die breite Tastenmatrix
wurde während der Entwicklung geprüft; anschließend wurden die geänderten
Caps-, Modifier- und Fn-Pfade gezielt nachgeprüft. Der letzte Kandidat und die
produktive Installation verwenden exakt den oben genannten Build.

| Funktion | Beobachteter Beleg |
| --- | --- |
| 54 benannte Tasten, F1–F20 und Ziffernblock | 54/54 am eigenen Empfänger, je genau erwartetes Down/Up, keine verlorenen Protokolleinträge. |
| Unicode, Umlaute, Japanisch, Emoji, Tab und Zeilenwechsel | Exakter Inhalt beziehungsweise SHA256 des tatsächlich empfangenen eigenen Textes. |
| Command+A und Shift+A | Tatsächliche Auswahl und Großbuchstabe im Empfänger. |
| Fn+Backspace | Vorwärtslöschen aus `abcd` zu `abd`. |
| Wiederholungen | 20 Down- und 20 Up-Ereignisse bei 20 Wiederholungen. |
| Alle fünf Modifier | Command/Control/Option/Shift/Fn mit F20 zweimal: vier Ereignisse mit exakt passendem Modifierbitfeld. |
| Caps Lock | Ein-/Ausschalten zurückgelesen; Folgezeichen groß; Literaltext unverändert. Caps+Shift entspricht der unabhängig abgefragten aktiven macOS-Belegung. |
| App-Wechsel vorwärts/rückwärts | Tatsächlich anderer Vordergrundprozess, Umschalter danach geschlossen; drei beziehungsweise vier Posts einschließlich Modifierfreigaben. |
| Wechsel zwischen Fenstern | Fokus zwischen zwei unabhängigen eigenen Fenstern gewechselt; keine gemeinsame Tabgruppe. |
| Control+Pfeil rechts/links | Unterschiedliche Desktopansichten und Rückkehr visuell geprüft. Produktiver Connector zusätzlich auf automatisches Routing und Versand geprüft. |
| Mission Control und Programmfensterübersicht | Sichtbar geöffnet und geschlossen. |
| Spotlight und Escape | Suche sichtbar geöffnet und per systemweitem Escape geschlossen. |
| Schreibtisch zeigen/F11 | Im finalen Paket sichtbar geöffnet und geschlossen, jeweils vollständige Quittung mit zwei Posts und gelösten Fn-Flags. |
| Lautstärke, normal und Option+Shift | Spätere CoreAudio-Lesewerte: 0.2543667 → 0.3097164 beziehungsweise 0.2632136 → Ausgangswert. |
| Bildschirmhelligkeit, normal und Option+Shift | Internes Display: 0.3750057 → 0.4375067 beziehungsweise 0.3906310 → Ausgangswert. |
| Stummschaltung | Tatsächliches Mute false → true → false. |

Die Desktopbilder wurden unabhängig von einem zweiten Team-Agenten beurteilt.
Sie bleiben wegen sichtbarer Benutzerinhalte privat. Der öffentliche
Space-Notificationzähler blieb hier bei null und dient ausdrücklich nicht als
Wechselbeleg. Eine aktive Space-ID wurde nicht über private APIs beschafft.

## Produktive Abnahme über ChatGPT

Nach der sichtbaren Installation wurden **13 eindeutige produktive Apps-Aufgaben**
mit `principal=chatgpt` erfolgreich abgeschlossen: sieben Tastatursteuerungen,
zwei Inspektionen, drei Systeminventare und eine Freigabenabfrage. Alle Belege
nennen den nativen Build `34f5e6d`.

- Unicode wurde in einer bestehenden eigenen Testnotiz und einer zuvor leeren
  eigenen Notiz jeweils genau einmal eingefügt und unabhängig nachgelesen.
- Zweimal Return erzeugte vier Posts; die nachfolgende Inspektion bestätigte die
  Cursorverschiebung von UTF-16-Position 22 auf 24 und insgesamt 25 UTF-16-Einheiten.
- Control+Pfeil rechts/links ohne expliziten Systemmodus wurde korrekt zu
  `space_right`/`space_left` aufgelöst und mit je drei Posts gesendet. Diese
  produktiven Versandquittungen sind keine zusätzliche Bestätigung eines
  Spacewechsels; dafür gilt die separate visuelle Desktopabnahme.
- Spätere separate Inventare bestätigten die tatsächliche Lautstärkeänderung
  beider Kanäle und die exakte Rückkehr zu 0.2543666958808899. Unmittelbare
  `observed_after`-Daten des Schreibaufrufs waren noch veraltet und wurden dafür
  nicht verwendet.

Text in Notizen verwendete den geprüften AX-SelectedText-Weg. Deshalb nennt der
Textbeleg korrekt null CG-Posts sowie bestätigten Text und bestätigte Auswahl.
Ein separater manueller Web-, Mobil- oder Voice-UI-Durchlauf fand nicht statt.

## Freigaben und Bedienoberfläche

Die Prüfung bindet Freigaben an PID und Generation des tatsächlich ausführenden
Tastaturprozesses. Bei der produktiven Abnahme waren Bedienungshilfen und
Tastatureingaben-Senden erlaubt. Eingabeüberwachung und Bildschirmaufnahme waren
hier ebenfalls erlaubt, sind aber keine Voraussetzung für gewöhnliches natives
Tastensenden. AppleEvents-Automation ist für diesen Eingabeweg nicht erforderlich.

Der Tastaturbereich zeigt bei fehlenden oder unbekannten Freigaben verständliche
Hinweise, manuelle Schritte und passende Systemeinstellungen-Links. Die native
Oberfläche öffnet nur die fest erlaubten Einstellungsziele nach Benutzeraktion.
Normale Statusaktualisierungen entfernen bereits angezeigte Hinweise nicht.
Weder macOS-Freigaben noch Benutzer-Shortcuts wurden still geändert.

## Paket, Installation und Datenerhalt

Alle Tests und Builds liefen lokal auf diesem Intel-Mac. Gezielte Python-,
native Vertrags- und Browserprüfungen sowie Ruff/Formatierung bestanden.
Neue reine native Matrizen decken unter anderem 270 Caps- und 1.539
Fn-KeyUp-Kombinationen ab; sie erzeugen keine OS-Eingaben. GitHub Actions und
Cloud-Builds wurden nicht verwendet.

Unabhängig geprüft wurden 487 Manifestmitglieder, 479 Paketquellen gegen den Git-Buildtag,
171 Wheeldateien/Assets und 159 installierte Pythondateien. Die offizielle
Paketprüfung und die vollständige isolierte macOS-Abnahme bestanden: Upgrade von
RC25, Datenbewahrung, Idempotenz, Dienstneustart, Crash/KeepAlive, Rollback und
Neuinstallation. Der optionale Test eines offenen Completion-Reads lief nicht.

Die echte Intel-Installationsapp enthält den vollständigen geprüften Runtimepayload.
ZIP, 553 App-Einträge und 488 Runtime-Dateien wurden einschließlich Modi und
Signaturen unabhängig verglichen. Der veröffentlichte ZIP-Download wurde erneut
geladen und seine Prüfsumme stimmt mit dem lokal installierten Paket überein:

```text
Build/Tag: 34f5e6da7d7232407c20ca98afd168021e7804ce
Installer-ZIP SHA256: 51b066d2fa3abe38ce47f49aaed32e079b8646995bd06e46f2dc0b2637d37885
Native SHA256: 5ef3c6a1fcba528af1f0d0a28c371f7e347e9c2d8eadcf9e553cb5a53db4ace4
Python-Quellbaum SHA256: 301c80d46734797f2b9e21503f6919855482275a4ba12ee1700f8d4e0712087a
```

Die produktive Prüfung bestätigte die laufende GUI, den nativen Worker, alle drei
LaunchAgents und vier bytegleiche HTTP-Oberflächenassets. Der vorhandene
ChatGPT-Wiederanlauf aus RC25 bleibt mit KeepAlive und 30 Sekunden Drosselung
enthalten. Nach der Arbeitspause antwortete der Connector weiterhin mit derselben
RC26-Kerninstanz; daraus wird kein gesonderter Netzunterbrechungs- oder
Rechnerneustarttest abgeleitet.

Sechs privat gehashte Einstellungs-, Zugangs- und Profil-Dateien einschließlich
der Profil-Sperrdatei sowie die
ursprünglichen Codex-Prozessidentitäten blieben erhalten. Zwei eigene Testnotizen
wurden gelöscht. Das eigene beendete Installationsfenster wurde geschlossen und
zweimal unabhängig als abwesend bestätigt; andere Benutzerfenster und laufende
Sitzungen blieben erhalten. Alle fünf privaten Testkerne sind beendet.

Lokale Lieferung: `~/Downloads/KiraBridge-RC26-Intel-34f5e6d/`.
Der gesicherte Rückweg liegt unter
`~/.local/share/kirabridge/install/backups/20261102-200938-46bda9e9/`.
Spätere reine Dokumentationscommits ändern weder den Release-Tag noch das
installierte Paket.

## Grenzen der Abnahme

- Play/Pause, Titelwechsel und Suchlauf sind als Sondertastensignale konstruktiv
  geprüft. Eine Medienwirkung wurde wegen nachgewiesener laufender Brave-
  Audioausgabe nicht erzwungen; der vorbereitete eigene Medienempfänger wurde
  nicht aktiviert.
- Tastaturbeleuchtung, Auswurf, Spiegelung, Kontrast und nicht benannte registrierte
  Systemkombinationen hängen von Hardware beziehungsweise Konfiguration ab.
  Deren tatsächliche Wirkung wird nicht als abgenommen ausgewiesen.
- Touch ID, Power, Secure Attention und die physische Identität einer allein
  gedrückten Globe/Fn-Taste werden nicht virtuell nachgebildet.
- Sichere Felder, unklarer Fokus und gehaltene Benutzertasten bleiben geschützt.
  Eine unbekannte Teilwirkung wird nicht automatisch wiederholt.
- Ad-hoc-Signaturen, keine Apple-Notarisierung; kein zusätzlicher vollständiger
  Mac-Neustart während dieser Abnahme.

## Primärquellen

- [Apple CGEvent](https://developer.apple.com/documentation/coregraphics/cgevent)
  und [HID-Ereigniseinspeisung](https://developer.apple.com/documentation/coregraphics/cgeventtaplocation/cghideventtap).
- [Apple-Tastaturkurzbefehle einschließlich Fn](https://support.apple.com/en-us/102650).
- [UCKeyTranslate](https://developer.apple.com/documentation/coreservices/1390584-uckeytranslate)
  und die tatsächliche aktuelle macOS-Tastaturbelegung.
- Apple SDK: `ev_keymap.h`/`IOLLEvent.h` für Sondertastensignale,
  `IOHIDLib.h`/`IOHIDParameter.h` für Modifierzustände und `CarbonEvents.h`
  für `CopySymbolicHotKeys` ohne öffentliche semantische Aktionsnamen.
