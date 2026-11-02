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

## Schritt 8 – Optionales Return innerhalb desselben Auftrags

`submit` bleibt standardmäßig `false`. Die tatsächliche Booleanabsicht wird im
Stagingmanifest und nativen Puffer gespeichert. Core akzeptiert nur einen
Commitbeleg mit genau dieser Returnabsicht. Lange und kurze Texte benutzen
denselben Weg; es gibt weder Clipboardpflicht noch separaten Returntask.

Bei `submit=true` folgt nach dem exakten Text-/Cursorbeleg eine erneute Prüfung
von Appgeneration, Fenster, Feld, Inhalt, Auswahl, Layout und Eingabeberechtigung.
Gehaltene Hardwaretasten/Modifier und Abbruch verhindern den Return. Genau ein
eigenes Return-Down/Up-Paar wird versandt. Jeder Fehler nach begonnener Texteingabe
bleibt Unknown ohne Textreplay oder weiteren Submitversuch. Der Bericht trennt
`text_verified/selection_verified` vor Return und `return_posted` als reine
Versandbestätigung; `submitted/app_processing_confirmed` bleiben ausdrücklich
false. Ein Programm kann Return anders behandeln oder seine Folgeaktion ablehnen.

Sechs gezielte Corefälle bestanden in0,58s (15 nicht ausgeführt): beide
Submitabsichten mit kurzem und großem Unicode-/BOM-Text sowie widersprüchliche
Returnbelege ohne Replay. Unbetroffene Tests wurden nicht wiederholt. Die native
Hardwarekonfliktmeldung enthält jetzt konfliktierende Flagbits und den Held-
Zustand, damit die nächste Liveprobe den bisherigen Stop konkret erklären kann.
Der native Harness bestand genau einen Compile-/Testlauf in16,68s:158
Checkgruppen, davon14 neue Returnchecks plus ein Staging-Submit-Roundtrip.
Enthalten sind wirkungsfreie CGEvent-Returnfactory, Text-vor-Return-Reihenfolge,
Teiltext, Verifikations-/Guardfehler, Abbruch und Teilpost-Unknown ohne Replay.
Gegenseitige Review freigegeben, Ruff/Diffprüfung grün. Noch keine Liveabnahme
des Returnpfads. Die produktive RC24 bleibt während dieser Entwicklung unverändert.

## Schritt 9 – Reale Abnahme und gemessener Optimierungsbedarf

Privater Build aus sauberem, separatem Checkout von
`901f558d9d417bef7a53cb244bf32a09149b7253`, nicht installiert. Derselbe tatsächliche
KeyboardManager mit Desktoptransaktion, Staging und gebundenem nativen Worker
wurde gegen ausschließlich die eigene UUID-Receiver-App ausgeführt. Kein
öffentlicher HTTP-/MCP-Daemon war Teil dieser Vorabprobe.

Zwei reale Aufträge erfolgreich:31 UTF-8-Bytes mit führendem U+FEFF, Umlaut,
Combiningzeichen, Emoji, LF und Tab in0,308s;1.024 ASCIIzeichen mit anschließendem
Return in2,335s. Unabhängiger Receiver bestätigte beide exakten Text-Hashes und
UTF-16-Cursor, im zweiten Fall genau einen Return. Er beobachtete2/2 bzw65/65
Down-/Up-Ereignisse. Clipboard-Generation blieb jeweils gleich. Keine
Eingabewiederholung; eigene Fixture geschlossen und Prozessabwesenheit geprüft.
Der frühere Hardwareguard-Stop trat in diesen Aufträgen nicht auf; das ist
kein Beleg für einen vorherigen Guardfehler oder dessen Reparatur.

Beleg: Backuproot `native-keyboard-implementation-20261101T235356Z`, dort
`step08-live-01/result.private.json` und private Wire-/Receiverbelege. Die
Produktionsprozesse78414/78630/78865 liefen anschließend mit ihren bisherigen
Startzeiten weiter. Die Testfläche deklariert AXEnabled und leeren Subrole
ausdrücklich; universelle TextEdit-/Browserkompatibilität ist nicht abgenommen.

Die gemessenen2,335s für1.024 Zeichen machen die vielen synchronen Zielprüfungen
je16 UTF-16-Einheiten zu einem relevanten Langtextrisiko. Keine große Eingabe
wurde blind in den12s-Timeout gefahren. Nächster kleiner Schritt9a ist daher ein
nativer Insert über nachweislich schreibbares AXSelectedText, mit denselben
Vorbedingungen, exaktem Endbeleg und Returnguard. Kein AXValueersatz und kein
Clipboard. Größere Nutzlasten/Geschwindigkeit bleiben bis zu diesen Messungen
offen; Shortcut-Discovery und Profile beginnen erst nach stabiler Tastaturabnahme.

## Schritt 9a – Bedingter nativer Auswahl-Insert

Eine zusätzliche, eng begrenzte Wirkungsfrei-Prüfung zeigte CGEvent-Set/Get-
Roundtrips bis1.024 UTF-16-Einheiten. Das beweist keine OS-Zustellung größerer
Ereignisse; die produktive Eventgrenze wird daraus nicht verändert. Ein eigener
Swifthelper aus dem gepushten Schritt8-Systemcode prüfte anschließend die
kontrollierte Textfläche: `AXUIElementIsAttributeSettable(AXSelectedText)` ergab
success/true. Dieser reine Fähigkeitsbefund löste keine Eingabe aus; Receiver
meldete0 Down/Return und die eigene App wurde geschlossen/abwesend bestätigt.
Entscheidungsbeleg `step09a-decision.json` im bestehenden Backuproot.

Die API ist bedingt: der generische SDK-Attributkommentar bezeichnet SelectedText
als readonly, AppKit bietet einen SelectedText-Setter. Deshalb entscheidet allein
die konkrete native Settableabfrage. Nur success/true verwendet den Setter;
belegt fehlende Unterstützung bleibt beim vorhandenen Ereignisweg, sonstige
Abfragefehler verweigern vor Wirkung. Kein Setterversuch fällt auf Ereignisse
zurück. Die vorhandene16-Unit-Graphemgrenze gilt weiterhin für CGEvents und wird
dem nativen Auswahl-Insert nicht auferlegt.

Textvalidierung, erwarteter Gesamtinhalt und gemeinsame Verifikation/Returnroute
bleiben erhalten. Der Setter erhält eine letzte vollständige Ziel-/Fokus-/
Revisions-/Hardware-/Settableprüfung. Sein tatsächlicher Aufruf ist der einzige
Textwirkungspunkt; Fehlerstatus danach sind Unknown. Die Rückgabe benennt
`insertion_method`, echte AX-Aufrufzahl und tatsächliche Eventzahlen getrennt.
Keine Änderung an öffentlichen Eingaben, Textstaging, Berechtigungen, Clipboard
oder Terminal. Ein betroffener nativer Compile-/Harnesslauf bestand in17,91s:
16 neue AX-Fallgruppen plus die unveränderten158 bisherigen. Geprüft sind
Settablezustände, unklare Abfragefehler, Literal-CFString mit BOM und langem
Graphem, genau ein Setter/keine Textevents, optionales Return sowie Unknown bei
Setterfehlern, fehlendem Beleg, Abbruch oder Returnguardfehler. Kein Replay oder
Eventfallback nach Setterversuch. Native Deltareview freigegeben; Core unverändert,
dessen vorhandene Nachweise werden wiederverwendet. Echte größere Texte und
Geschwindigkeit bleiben bis zur Abnahme des exakten Commitbuilds offen.

## Schritt 9b – Tatsächliche native Eingabe und öffentlicher MCP-Weg

Privater, sauberer Build aus gepushtem Commit
`ce6360a9177ddf6ead0138b5779e478071e87905`: drei reale KeyboardManager-Aufträge
erfolgreich.31 Unicode-/BOM-Bytes in0,254s,100.019 Bytes in0,723s, exakt1 MiB
UTF-8 in2,711s mit anschließend genau einem Return. Jeweils ein nativer
AXSelectedText-Aufruf, keine Textevents,0/0/2 Return-Postcalls. Die unabhängige
Receiver-App bestätigte Inhaltshash, UTF-16-Cursor und Returnzählung; die
Clipboard-Generation blieb gleich. Jede eigene App wurde geschlossen und ihre
Abwesenheit bestätigt. Das sind belegte Werte für diese kontrollierte Textfläche,
keine universelle Leistungszusage für Fremdprogramme. Beleg im Backuproot:
`step09a-live-01/result.private.json`.

Zusätzlich bestand eine reale Folge mit frischem Ziel vor jeder Aktion:
Text einfügen, benannte Linkstaste, Command+A, markierte Auswahl nativ ersetzen.
Inhalt und Auswahl wurden nach jeder Aktion unabhängig geprüft, ohne Return
oder Clipboardänderung. Ein erster Fixturelauf besaß kein Editmenü und bestätigte
deshalb keine SelectAll-Wirkung; daraus wurde kein Produktfehler abgeleitet.
Die Test-App besitzt jetzt ein reguläres Cocoa-Menü Edit→Select All mit Command+A.
Native Implementierung blieb unverändert; der zweite Lauf bestand alle vier
Aufträge. Keine Wiederholung derselben Task-ID. Fixture-Menüdifferenz unabhängig
geprüft, expliziter Edit-Titel für spätere AX-Menüpfade ergänzt. Beleg:
`step09b-keys-live-02/result.private.json`.

Auch der vollständige öffentliche HTTP-/MCP-/Task-Workerweg ist jetzt belegt.
Das Abnahmeskript `scripts/accept_native_keyboard_macos.py` verwendet das vorhandene
MCP-Testmuster, privaten Datenordner, minimale Testberechtigungen, frischen
Zufallstoken und zufälligen Loopback-Port. Die gepinnte Native-App wird nur im
privaten Testprozess verdrahtet. Der erfolgreiche Lauf
`step09b-mcp-live-04/evidence.json` bestätigt einen lesenden Inspecttask und genau
einen `task_submit` für langen Unicode-/BOM-Text mit Return, vollständiges Staging,
Text-/Caretbeleg und unabhängigen Receiverhash mit Returnzählung1. Test-App,
Nativeworker und Loopback-Endpunkt wurden geschlossen und unabhängig abwesend
geprüft. Vorläufe01–03 enthielten keinen schreibenden Tastaturauftrag: korrigiert
wurden Fixture-Belegdateien (0600 vor atomarer Veröffentlichung), der Aufrufweg
für Inspect (Readonlytask statt begrenztem `read_query`) und die Behandlung des
normalen Taskfeldes `error:null`. Keine Produkt-/Rechteänderung für diese
Korrekturen und keine Eingabewiederholung. Die großen nativen Texte und die
Tastenfolge wurden nicht nochmals getestet. Die Fixture- und Skriptdifferenzen
sind unabhängig geprüft; Ruff/Syntax/Diffprüfung grün.

Vor Shortcut-Discovery bleibt die bereits dokumentierte Workerepochen-Grenze von
256 Textcommits zu behandeln: derzeit sichere Verweigerung statt automatischer
Erneuerung. Produktive RC24 und vorhandene Sitzungen bleiben währenddessen
unverändert. Keine allgemeine Fremdprogrammkompatibilität oder Installation dieses
Entwicklungsstands behauptet.

## Schritt 9c – Begrenzte Workerepochen ohne manuelles Neustarten

Der Transport zählt versandte Textcommits pro eigenem Hilfsprozess direkt nach
abschließender Autorisierung, vor dem Write. Bei256 Versuchen erneuert erst die
nächste frische `keyboard.inspect`-Abfrage diesen eigenen Hilfsprozess unter
bestehender Transportsperre und Gesamtfrist. Die native Replayhistorie bleibt
innerhalb jeder Epoche vollständig; keine Mutation wird wiederholt oder auf ein
anderes Ziel umgebogen. Andere Operationen lösen keinen Wechsel aus.

Neue Inspektion liefert neue Worker-/AX-Handles. Alte Referenzen werden danach
wie bei jedem Epochenwechsel verweigert; Clients müssen das frisch beobachtete
Ziel verwenden. App, Core-Daemon, Terminal und Clipboard werden nicht neu gestartet.
Genau drei zusätzliche simulierte Transportfälle bestanden in0,33s (67 nicht
ausgeführt):255→256→neue Inspektion, andere Operationen ohne Rotation sowie
Autorisierungsverweigerung ohne Zählerverbrauch. Native Swiftdateien unverändert;
die174 bisherigen Nativechecks und tatsächlichen Eingaben wurden wiederverwendet.
Unabhängige Deltareview und Ruff/Diffprüfung grün.
