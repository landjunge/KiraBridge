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

## Noch getrennt abzunehmen

Private Native-App aus dem überprüften Commit bauen; ausschließlich private
HTTP/MCP-Instanz und eigene leere Testnotiz verwenden. Text, exakt zwei Return,
unabhängigen Feld-/Auswahlnachweis, weitere einfache Tasten/Chord und Idempotenz
prüfen. Katalog nach privatem Neustart prüfen. Produktive Installation und
Neustart bleiben ausgeschlossen; bestehende Freigaben werden nicht geändert.

Die erste private Beobachtungsfixture scheiterte vor jeder Eingabe. Ihr
Diagnose-Streamwrapper unterstützte beim Cleanup zunächst read() nicht; der
private Wrapper wurde korrigiert. Der ursprüngliche Fehler und Logs bleiben
erhalten. Ein vermuteter Double-Roundtripfehler wurde rein lesend nicht
reproduziert; an der Startidentitätsprüfung wurde nichts gelockert.

Private Baseline, Quellarchiv und Testbelege:
`~/.local/share/kirabridge/backups/keyboard-direct-repair-20261102/`.
Das ursprüngliche Archiv hat SHA256
`efd04d422db42359659f1580c342bfcacc1699d427b7c2d1077a4d06e5e09fbb`.
Die Live-Abnahme wird erst nach tatsächlicher Durchführung ergänzt.
