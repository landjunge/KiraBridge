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

Der Remote-SHA wird vor Beginn von Schritt 2 unabhängig abgeglichen.
