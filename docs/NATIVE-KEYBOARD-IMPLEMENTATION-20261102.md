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
noch kein nativer Text-/Return-UI-Nachweis. Schritt3-Commit/Remote: `de90c2285f9c2d8e9bc9f6e58f36fdd559c94f55`, unabhängig abgeglichen.


## Schritt 4 – Native einzelne Taste

`keyboard.key` führt über den eigenen KeyboardManager, `keyboard.execute`, die
bestehende Desktop-/Sessiontransaktion und denselben nativen Transport. Die
Autorisierung wird unmittelbar vor Sendung erneut geprüft. Die Operation geht
nicht am Manager vorbei durch den generischen SYSTEM_LEAVES-Dispatch.

Der Swift-Worker unterstützt 27 benannte Tasten mittels Carbon-Keycodes und
prozessgerichtetem CGEvent-Down/Up. Logische Zeichen/physische Positionen bleiben
bis Schritt5 ausdrücklich unsupported. Vor Down werden Tokenbesitzer/-ablauf,
Worker/Appgeneration, frischer Fokus-/Feld-/Layoutzustand, native Postrechte sowie
konfliktfreie physische Modifier/Tasten geprüft. Nach Postbeginn bleibt jeder
Fehler Unknown; nur ein eigener Key-up wird bestmöglich an dieselbe noch gültige
Appgeneration geschickt. Kein globaler Versand, kein Modifierreset und kein Replay.
Der Ergebnisbereich `native_post_calls` bestätigt zurückgekehrte Post-Aufrufe,
keine Appverarbeitung (`app_processing_confirmed=false`).

Nachweise: fünf gezielte Corefälle bestanden (exaktes Ziel/Owner/Lock,
Reautorisierung, Unknown ohne zweiten Aufruf, Serialisierung und Key/Submittrennung).
Ein gemeinsamer Swiftcompile/Harnesslauf bestand in8,46s mit22 neuen Key-/Binding-/
Fehlergrenzenchecks plus15 bestehenden Snapshotchecks. Alle27 Namen stimmen
mit dem Pythonvertrag überein. Gegenseitiger enger Autor-/Rootreview grün;
keine zweite Reviewrunde oder Gesamtsuite.

Noch keine echte OS-Eingabe oder Appkompatibilitätsabnahme. Die verbleibende
Racegrenze nach letzter Fokus-/Generationsprüfung und Crash zwischen Down/Up
wird nicht als absolut gelöst ausgegeben. Clipboard-/Terminalwege unverändert.


Schritt4-Commit/Remote: `5b20d0ee1220f1f45d51c19b518bb95caa5d4299`, unabhängig abgeglichen.

## Schritt 5 – Kombinationen und Layoutauflösung

`keyboard.chord` nutzt unverändert denselben Manager, Write-Capability,
Transaktionslock, Autorisierungscheck und nativen Pairpfad. Benannte, freigegebene
physische und logische Tasten werden nativ aufgelöst. Physische Modifier-/Caps-/
Fn-/Medien-/Systempositionen bleiben gesperrt. Command/Control/Option/Shift werden
explizit als Flags übertragen, ohne Hardwaremodifier global zu drücken/lösen.

Logische Buchstaben sind Basis-Tastenbezeichnungen: Großschreibung fügt niemals
Shift hinzu. Cmd+Z bleibt damit von Cmd+Shift+Z getrennt. Für Symbolglyphen wird
nur minimal fehlendes Shift/Option ergänzt; mehrdeutige Positionen oder Modifier
werden vor Eingabe verweigert. Deadkeyfolgen werden nicht als eine Taste geraten.
Die Übersetzung verwendet aktuelle TIS-/UCKeyTranslate-Daten und Tastaturtyp;
Layout-ID und Datenhash werden gegen den frischen Zielsnapshot geprüft.

Nachweise: zwei neue gezielte Core-Chordfälle grün (fünf bestehende deselected).
Ein gemeinsamer Swift-Harness prüfte zunächst47 neue Layoutfälle, einschließlich
rein lesender echter installierter DE-/US-Daten für z/Z/y/Y unter Cmd und CmdShift
sowie US-Option-E-Deadkey-Verweigerung. Ein enger Abschlusscheck verwarf die lokal
nicht bestätigte CGEventSource-Set/Get-Annahme. Die tatsächlichen Down/Up-Events
setzen und verifizieren stattdessen explizit ihr keyboardEventKeyboardType-Feld.
Der direkt betroffene Harness bestand danach mit53 Layout-/Factorychecks sowie
wiederverwendeten15 Snapshot-/22 Pairchecks in11,47s; keine weitere Suite.
Unabhängige Reviews beider Implementierungsteile freigegeben, Ruff grün.

Keine Layoutumschaltung, keine OS-Posts, kein Clipboardzugriff. Ergebnis weiterhin
Versandbeleg mit unverändert requested und ausdrücklich resolved, kein Beleg
für Appverarbeitung. Schritt5-Commit/Remote: `acc096e9ab97f0d5e3b26c122364bbe845758be3`, unabhängig abgeglichen.


## Schritt 6 – Kurzer nativer Literaltext

`keyboard.text` ist über denselben Manager/Lock/Transport angebunden. Kein
Clipboardaufruf, kein AXSetValue und kein Return. Vorläufig werden Submit und
Payloads oberhalb eines vollständigen nativen Frames vor Running/Versand
verweigert; der folgende Stagingschritt erweitert dies ohne Clipboardalternative.

Native Unicodeeinheiten sind graphem- und surrogatsicher begrenzt. Jede tatsächliche
Down/Up-Unicodepayload wird über CGEvent Set/Get exakt zurückgelesen. Erwarteter
Gesamtfeldwert und UTF-16-Auswahl werden vor dem ersten Ereignis berechnet und
begrenzt. Nachfolgende Einheiten prüfen frische Zielroute/Sicherheit/Layout/
Hardwaremodifier. Der abschließende Beleg vergleicht UTF-8, UTF-16 und Caret exakt;
kanonisch ähnliche, aber unterschiedliche Zeichenfolgen gelten nicht als gleich.
Fehlender Beleg oder Teilfehler nach einem Post bleiben Unknown ohne Replay.
LF/CR/Tab werden in einzeiligen Text-/Suchfeldern vorab verweigert.

Nachweise: drei neue gezielte Corefälle grün (sieben unbetroffene deselected).
Der betroffene Swift-Harness bestand nach einem konkreten ArraySlice-Compilefix
mit27 neuen Textchecks plus den wiederverwendeten90 bisherigen Checks in12,73s.
Enthalten: echte ungepostete Unicodeevent-Set/Get-Roundtrips, Whitespace/CRLF/Tab/
Case/Emoji/Combining, ExpectedField/Selection, Grenzen sowie Teilfehler/noReturn.
Keine weitere Suite. Unabhängige Reviewteile freigegeben, Ruff grün.

Noch keine echte App-/Performanceabnahme: TextArea-Klassifikation allein beweist
keine universelle Submit-freie Semantik von Fremdprogrammen. Das Ergebnis meldet
`text_verified/selection_verified`, aber keine bestätigte Programmaktion.
Lange Texte und optionales Return sind weiterhin die nächsten getrennten Schritte.

## Schritt 7 – Verlustfreies, begrenztes Textstaging

Alle öffentlichen `keyboard.text`-Aufträge verwenden jetzt dieselbe interne
Begin/Chunk/Commit-Übertragung. Darwin Foundation verlor im nachgewiesenen
JSON-String-Fall ein führendes U+FEFF. Deshalb gibt es keinen direkten nativen
JSON-Textpfad mehr: UTF-16LE ohne BOM mit Base64 erhält auch dieses Zeichen.
Authentifizierte Principal-Namen mit führendem U+FEFF werden vor Workerstart
verweigert, damit die Parserabweichung keine Besitzeridentitäten zusammenführt.

Das Manifest bindet Task, Besitzer, exaktes Ziel samt Worker, Submitabsicht,
UTF-8-Hash, beide Längen und Chunkzahl. Der originale kanonische Binding-String
vermeidet Unterschiede der Python-/Foundation-Floatserialisierung. ACKs müssen
Transfer-ID, Zustand, explizit `input_attempted=false` und exakte Integerzähler
bestätigen. Core behält während der Übertragung dieselbe Desktoptransaktion
und prüft die Berechtigung vor jedem Versand erneut. Abbruch vor Commit räumt
nur den eigenen Speicherpuffer auf, auch bei entzogener Eingabeberechtigung.
Commit entfernt den Puffer und verbraucht die ID vor Validierung und Eingabe;
ein verlorener oder widersprüchlicher Commitbeleg wird niemals wiederholt.
Die internen Stagingoperationen sind keine öffentlichen Tools.

Grenzen: ein Speicherpuffer, 1 MiB UTF-8, höchstens 65 Chunks à 16.384 UTF-16-
Einheiten, monotone Ablaufzeit 60 Sekunden. 256 verbrauchte IDs je Workerepoche
werden ohne Eviction gespeichert; danach erfolgt eine sichere Verweigerung.
Automatische Epochenrotation ist noch nicht implementiert. Keine Nutzdaten auf
Disk, kein Clipboardzugriff, keine neuen Services. Return bleibt bis Schritt8
gesperrt. Die vorhandene 12-Sekunden-Desktopfrist wurde nicht erhöht.

Gezielte Nachweise: Python24 Fälle grün,60 nicht ausgeführt; darunter große
Unicode-/BOM-Texte über Framegröße, fehlerhafte ACKs/Zähler, Berechtigungsentzug,
Pufferabort und unbekannter Commit ohne Replay. Der bereits verifizierte native
Harness wurde wiederverwendet:26 neue Stagingchecks plus117 bisherige in14,69s.
Er belegt tatsächliche Codec-/Manifestprüfung und injizierten Writer; keine
GUI-Ereignisse. Ruff und Diffprüfung grün. Reale lange Texte und Geschwindigkeit
sind damit noch nicht abgenommen. Die eigene kontrollierte GUI-Testfläche ist
im Repository enthalten. Vorabproben mit privatem Schritt6-Build verweigerten
zunächst wegen Vordergrund/Feldzustand. Mit ausdrücklich aktiviertem AX-Testfeld
bestätigte Inspect anschließend AX- und Postingberechtigung; der Eingabeversuch
stoppte vor jedem Post wegen gleichzeitig gehaltener Hardwaretasten/Modifier.
Der unabhängige Receiver meldete null Down-/Returnereignisse. Alle eigenen
Fixtureinstanzen wurden geschlossen und ihre Abwesenheit bestätigt.
Die installierte RC24 und vorhandene Terminal-/Clipboardwege bleiben unverändert.

Die unabhängige Coreprüfung fand einen zu frühen Commitmarker: Ein Widerruf
unmittelbar vor dem tatsächlichen Versand ließ den Puffer unnötig bis zur
Ablaufzeit bestehen. Der Marker wird jetzt nach erfolgreicher abschließender
Autorisierung direkt vor dem Transportwrite gesetzt. Der neue Widerruffall und
die beiden betroffenen Unknown-/Receiptfälle bestanden zusammen (3/3,15 nicht
ausgeführt); übrige bereits grüne Nachweise wurden nicht wiederholt.
