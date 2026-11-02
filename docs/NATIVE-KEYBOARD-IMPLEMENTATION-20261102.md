# Native Tastatur – schrittweise Umsetzung · 2. November 2026

Verbindlich ist der [korrigierte freigegebene Plan](NATIVE-KEYBOARD-PLAN-20261102.md).
Native lange Texte benötigen keine Zwischenablage; optionales Return gehört zur
selben Eingabetransaktion und setzt einen vollständigen Einfügebeleg voraus.
Die bestehende Clipboard-Funktion und ihre Aufrufer bleiben erhalten.

Arbeitsbranch: `feature/native-keyboard-20261102`. Produktiv bleibt der zuletzt
abgenommene RC24-Stand; Entwicklungsschritte werden erst nach gezielten Tests,
Review, Dokumentation, Commit und unabhängig geprüftem Push fortgesetzt.

## Schritt 0 – Korrektur übernommen

Commit/Remote: `8c66fb9ed1d9126b7776cb265f879af6e063ffcb`.
Freigegebene Reihenfolge und Clipboard-Unabhängigkeit sind dokumentiert.
Keine Produktcode- oder Laufzeitänderung.

## Schritt 1 – Intentmodelle und verlustfreier Transferplan

`keyboard_models.py` ergänzt strikte Text-, Tasten- und Chordverträge mit
vollständiger Zielreferenz. Text erlaubt bis 1 MiB UTF-8 und optionales `submit`;
Tasten und Chords erlauben kein zusätzliches Submit. Gemischte Schlüssel,
ungültige Surrogate, doppelte Modifier und unvollständige Ziele werden verweigert.
Der Text wird weder getrimmt noch normalisiert oder als Kommando interpretiert.

`keyboard_text.py` erzeugt UTF-16LE-Stagingpakete ohne BOM, trennt keine
Surrogatpaare und bindet Task, Principal, Ziel, Textdigest und Submit-Absicht.
Die Größenprüfung umfasst den vollständigen JSON-Frame einschließlich Encoding-
und Envelope-Overhead. Transportstücke sind keine zugesagten CGEvent-Grenzen.

Nachweise: 31 unterschiedliche gezielte Vertragsfälle erfolgreich, einschließlich
exaktem Roundtrip bis 1 MiB, Emoji/ZWJ/Combining, CRLF/Leerraum, Surrogatgrenze und
maximal 64-KiB-Frames. Beim ersten Lauf fehlte das Pflichtfeld `arguments` am
wiederverwendeten Taskvalidator; nach Korrektur wurden ausschließlich die sieben
betroffenen Fälle erneut geprüft (7 passed, 19 deselected). Die übrigen 19 Fälle
waren zuvor grün. Ruff für die drei geänderten Pythondateien ist grün.

Grenze: Noch keine neue Operation öffentlich registriert, kein Worker gestartet,
kein Textfeld beschrieben und kein Stagingempfänger oder Eventeffekt abgenommen.
Die Clipboard-/Terminalimplementierungen wurden nicht geändert. Verlorene oder
vertauschte Frames muss der spätere native Empfänger prüfen; dieser reine
Transferplan behauptet dafür keinen bestehenden Laufzeitnachweis.

Der unabhängige Review fand zwei zusätzliche Vertragslücken: veränderbare
Wire-Dicts und nachträglich ungeprüft veränderte Modelle. Fünf direkte Regressionen
reproduzierten beide Befunde. Nach tiefer Neuvalidierung und unveränderlicher
JSON-Ablage mit defensiven Wire-Dicts sind nur die zwölf betroffenen Fälle erneut
grün (12 passed, 19 deselected). Der enge unabhängige Abschlussreview ist freigegeben.

Schritt1-Commit/Remote: `6a926cf6e1ca4ca43c18372c2bc14b3c6ea55073`, unabhängig abgeglichen.


## Schritt 2 – Native Ziel- und Feldbeobachtung

`keyboard.inspect` ist als rein lesende Operation an den vorhandenen Dispatcher
und Swift-Worker angebunden. Der Snapshot prüft Appgeneration, aktives Fenster,
fokussiertes Element und Besitzer sowie UTF-16-Auswahl, Wertdigest und Layout.
Der native AX-Tokenstore wird weiterverwendet. Es werden keine Rohtextwerte
zurückgegeben, keine Tasten gesendet und keine Berechtigungen angefordert.
Sichere oder unzureichend klassifizierbare Felder werden vor dem Value-Read
verweigert. Die 4-MiB-Wertgrenze wird vor einer zusätzlichen UTF-16-Kopie geprüft.

Der passive Protokollmarker `KiraBridgeKeyboardProtocol=1` kennzeichnet neue
Worker. Ohne diesen exakten Integer meldet der Katalog nur Keyboard unverfügbar;
andere Fähigkeiten alter Worker bleiben erhalten. Neue Swiftquellen sind in
Build-/Quellhashlisten und bestehenden expliziten Harness-Compilelisten enthalten.

Nachweise: 9 direkt betroffene Pythonfälle bestanden,159 übrige deselected.
Ein echter gemeinsamer Swiftcompile mit 15 Metadaten-/Revisionschecks und ein
Builder-Mockfall bestanden als2 pytest-Fälle in8,77s. Native Autor-/Rootreview
und unabhängiger Check der Pythonverdrahtung sind grün. Keine erneute Vollsuite.

Grenzen: Der Native-Harness injiziert AX-Metadaten und ruft keine UI-/TCC-APIs
auf. Fehlende Subrole/Zeichenanzahl werden strikt verweigert; echte TextEdit-/
NSTextView-Kompatibilität und Eingabeeffekte sind noch nicht abgenommen.
Clipboard-/Terminalimplementierungen und laufende Benutzersitzungen unverändert.
Schritt2-Commit/Remote: `fb532628e4fde3445224a9a772df2b72b7adb63a`, unabhängig abgeglichen.


## Schritt 3 – Gemeinsame Eingabetransaktion

`DesktopInput` verwendet exakt die bestehende `SessionManager.lock`. Damit
nehmen native App-/Fensterfokus-, AX-Schreib- und App-Lebenszyklusaktionen an
derselben Serialisierung wie bestehende Terminaleingaben teil. Ein zusätzlicher
verschachtelter Sessionlock entfällt. Die zugrunde liegenden Clipboard-/
Terminalimplementierungen sind unverändert. Read-only und Stop-/Signalpfade
werden nicht an die neue Desktoptransaktion gebunden.

Die gemeinsame Gesamtfrist beginnt vor dem Warten auf die Sperre. Ein Ablauf
vor dem nativen Versuch meldet `desktop_input_busy` ohne Running/Dispatch;
nach Beginn des nativen Aufrufs konservativ `desktop_input_unknown`, ohne Replay.
Der Marker beweist keine OS-Verarbeitung. Innere Beobachtungstimeouts behalten
ihren Ursprung; Cancellation gibt nur selbst erworbene Locks frei.

Nachweise: sechs direkt notwendige Konkurrenz-/Deadline-/Cancellation-/
Dispatcherfälle bestanden (76 unbetroffene deselected), dazu der bestehende
konkrete app.focus-Dispatcherfall separat bestanden. Unabhängiger enger Review
freigegeben; Ruff grün. Der Trace einer simulierten Text+Return-Transaktion
schließt konkurrierende vorhandene Sessioneingabe zwischen beiden aus; dies ist
noch kein nativer Text-/Return-UI-Nachweis. Schritt4 erst nach Remote-SHA-Abgleich.
