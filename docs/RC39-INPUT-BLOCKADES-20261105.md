# RC39 Eingabeblockaden – Quellreparatur, 05.11.2026

Auftrag: Diagnose und minimale Reparatur, keine Installation, kein Big Plan,
keine Auditlöschung. Native Terminals und alte UNKNOWN-Aufträge wurden nicht bedient.

## Gesicherter Ausgangsstand

Ausgangsworktree `/Users/landjunge/KiraBridge`, Branch
`fix/visible-busy-idle-20261021`, HEAD `dfbae48`: vier geänderte versionierte
Dateien und neue Dateien. Unverändert belassen. Private Sicherung unter
`/Users/landjunge/KiraBridge-backup-rc39-20261105-041937` enthält HEAD, Status,
binären HEAD-/Index-Diff und Archiv aller nicht ignorierten untracked Dateien.

Eigener Worktree `/Users/landjunge/KiraBridge-rc39-input-fix`, Branch
`fix/rc39-input-blockades-20261105`. Basis `147e6f8` enthält RC39 `d9b0c0a`
und die bereits vorhandene, uninstallierte Copy-Footer-Korrektur. Die spätere
Big-Plan-Continuation `2a8d2fe` ist kein Bestandteil dieses Branches.
Installationsmetadaten zeigen weiterhin RC39/d9b0c0a; keine neue Laufzeitabnahme.
Produktive SQLite-Daten wurden ausschließlich über mode=ro gelesen.

## Diagnose und Änderung

- Codex: gespeicherte Capture `3613c4d1d685450f81c8aba8349fe9c2` zeigt
  `New activity · enter/esc latest · ? shortcuts` mit optionalem Warnungsbadge.
  Die genaue zusätzliche Shortcuts-Zeichenfolge fehlte in der bekannten
  Transcript-Footer-Grammatik. Eng ergänzt. Working/unknown-Protokoll, Drafts,
  unbekannte Dialoge und Copy-Return-Semantik bleiben gesperrt. Copy-Toolbar
  mit New-activity-Präfix ist bereits durch Basis `147e6f8` korrigiert.
- Shell: Capture `0dac40347a2947978e60c6a4ac479a76` zeigt den leeren
  robbyrussell-Prompt mit `git:(fix/visible-busy-idle-20261021) ✗ `.
  Der Parser unterstützte keine Git-Dekoration. Exakte bekannte Branch-/Dirty-
  Grammatik ergänzt; keine Whitespace-Normalisierung, eingegebener Text bleibt
  geschützt. Echte LF-Zeichen in den Captures, kein Serialisierungsfehler.
- Grok: Handoff `channel-38547d04c51f4984964deae5b4c869fd` hat `inserting`
  und danach UNKNOWN/`visible_paste_unconfirmed`, ohne bestätigtes Return.
  Diese ungeklärte Reservierung verursacht `visible_target_busy` trotz später
  leerem Composer. Sie wird ausdrücklich nicht automatisch entsperrt.
  Native Echo-Erkennung suchte die letzte vollständige logische Textzeile,
  die bei Box-Umbruch nicht zusammenhängend sichtbar ist; die nachfolgende
  Payloadprüfung unterstützte außerdem den tatsächlichen beschrifteten unteren
  Boxrand nicht. Neu: exakter Einzeilen-ASCII-Nachweis über vollständiges
  Widget einschließlich unverändertem Rand/Footer, in Python und generiertem JS.
  Neue übergebene Aufträge mit sicher erkannter dekorierter Box und unprüfbarer
  Payload werden vor Paste als `visible_input_geometry_ambiguous` abgewiesen.
- Audit: tatsächlich 20000 optionale `diagnostic.*`-Einträge, davon 19902
  Verbindungseinträge, 72 Runtime-, 23 Rejection- und 3 Workflow-Einträge.
  Das ist die konfigurierte Gesamtgrenze, kein Nachweis eines Input-Fehlers.
  Export schafft keinen neuen Platz. Weder Limit erhöht noch Logs gelöscht oder
  Diagnosepflicht deaktiviert. Kern-Audit bleibt unabhängig beschreibbar;
  Workflow-Readiness ohne erforderlichen Diagnoseeintrag bleibt negativ.

## Prüfungen

Alle Prüfungen lokal aus `src` mittels vorhandener Python-3.11-Umgebung,
keine Abhängigkeiten installiert:

- 111 bestanden: neue Shortcuts-Regressionsfälle, Copy-Footer und Readiness.
- 21 bestanden: neue UNKNOWN-Paste-/Auditgrenzen, Reservierungsumfang, Diagnostik.
- 280 bestanden: Literal-Input, Handoff, Session-Return, Adaptervertrag,
  Preinput-Races.
- Shell/Grok-Unterauftrag: erster gezielter Lauf 117 bestanden, ergänzter
  Shell-Suitability-Fall 1 bestanden, erweiterte Grok-Suite 22 bestanden.
  Diese Läufe überlappen; keine künstliche Gesamtsumme. Generiertes Echo-JS
  wurde tatsächlich in Node ausgeführt.
- Ruff lint/format aller zehn betroffenen Pythondateien und git diff --check
  bestanden. Unabhängiges lesendes Review ohne gefundenen Guard-Bypass.

## Grenzen und Übergabe

Keine native positive Bedienabnahme, kein Paket/Release, kein Merge, keine
Installation, keine Dienst-/Konfigurations-/Budgetänderung. README DE/EN,
Webseite, Abbildungen und Installationsweg benötigen für diese uninstallierte
Quellkorrektur keine Produktänderung; bei späterer Auslieferung Releasehinweise
und native Abnahme aktualisieren.

Grok-Mehrzeilen, Umbruch, Nicht-ASCII und Rand-Leerzeichen sind in dekorierten
Boxen weiterhin nicht exakt bestätigt. Die neue Vorprüfung gilt für submitted
Literal-Input und Handoff-Dispatch. Paste-only (`submit=false`) verwendet weiterhin
den bisherigen Weg und kann unbestätigt enden. Separates Grok-Return bleibt
`unsupported_return_frame`; kein Return ohne Payload-/Semantiknachweis ergänzt.
Bestehende UNKNOWN-Pastes brauchen individuellen belegten Abgleich, keine
Wiederholung. Für vollständige Grok-Unterstützung fehlt ein exakt geometriegebundener
Umbruch-/Mehrzeilenrenderer samt realer isolierter Abnahme. Auditkapazität erfordert
gegebenenfalls eine ausdrücklich gewählte Aufbewahrungs-/Budgetentscheidung;
Export allein setzt das vorhandene Limit nicht zurück.
