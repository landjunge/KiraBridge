# Reparatur des tatsächlich fehlgeschlagenen kurzen Prompts

31.10.2026, Fortsetzung mit Kira-Skill und Whiteboard `0ab8b95a7369`.
Die bisher offengelassene Grenze war für den normalen Nutzungsfall unzureichend.
Dieser Bericht ergänzt die früheren erfolgreichen Longprompt-/Postfachtests.

## Konkreter Fehler und Korrektur

`readme_kirabridge_codex_1031` versuchte 886 Zeichen in einer logischen Zeile
an neue Sitzung `terminal:7875:ttys002`, Shell 30586, Codex 30638. Das Einfügen
war sichtbar; `TerminalAppTransport.native_paste_observation` suchte jedoch
die gesamte logische Zeile innerhalb eines ungebrochenen Displayabschnitts.
Codex zeigte acht umbrochene Zeilen. Ergebnis: `visible_paste_unconfirmed`,
Attempt 1, Return nicht versucht. Separater `readme_enter_only_1031` wurde
mit `visible_target_unknown` vor Eingabe abgewiesen, weil seine Returnprüfung
nur die erste Entwurfszeile maskierte. Der README-Codex arbeitete beim aktuellen
Readback bereits; beide historischen Tasks unverändert, kein Replay/Interrupt.

Der native Codex-Echo-Check ist nun ein begrenzter Frischebeleg am letzten
aktuellen Composer. Shell/Grok behalten ihre bisherigen Checks. Erst der
vollständige aktuelle Widgetvergleich autorisiert danach Return.
Ein einfacher einzeiliger Prompt wird exakt vorwärts gerendert: einzelne
ASCII-Leerzeichen, einspaltige Zeichen, keine echten Zeilenumbrüche/Tabs oder
komplexen Grapheme; tatsächliche Terminalspalten werden mit Prozessidentitäten
und exaktem Screen gebunden. Bekannte Codex-Margen sind zwei Prefixspalten,
eine rechte Randspalte und optional eine weitere Indikatorspalte. Keine
allgemeine Whitespace-Normalisierung oder alternative Eingabeimplementierung.

Quelle für FirstFit/Leerzeichenprojektion und Margin:
[Codex-TextArea](https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/tui/src/bottom_pane/textarea/wrapping.rs),
[Composerlayout](https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/tui/src/bottom_pane/chat_composer/composer_layout.rs).
Sichtbares Rendering bleibt ein zusammengesetzter Beleg mit leerem Vorzustand,
Clipboard-Lease und exaktem Ziel, kein unabhängiger Rohtextzugriff auf Codex.

Zusätzlicher Livebefund: Terminal.history stellt eine leere Payloadzeile als
eine Paddingzelle dar. Nur im angeforderten Text tatsächlich leere Zeilen
erhalten diese weitere erwartete Darstellung; Zeilenanzahl, nichtleere Zeilen
und vom Nutzer eingegebene Leerzeichen bleiben exakt.

Expliziter cursorgebundener Return erkennt eingerückte Fortsetzungen und
bekannte leere Displayzeilen vor dem klar getrennten Modellfooter. Jede
ausgeblendete Zeile wird einzeln auf Approvalüberschriften, Fortschritt und
Queue-Hinweise geprüft. Ein unbekannter Dialog, aktiver Turn oder geänderter
Cursor/Prozess/Screen erlaubt keinen Return. Slash und Codex-Menü bleiben
eigene Module; es wurde kein zweiter Ausführungsweg eingeführt.

## Prüfung und echte Abnahme

Neun betroffene Suiten: 277 bestanden nach erstem Echo-/Widgetfix. Nach den
zusätzlichen nativen Randfällen wurden nur betroffene Tests wiederholt:
40 Wrap-/Clipboardfälle, danach 152 Literal-/Return-/Clipboardfälle. Die letzte
Returnhärtung wurde gezielt geprüft. Überlappende Zahlen nicht addieren.
Ruff/Format/diffcheck und unabhängiges Review; gefundene Placeholder-Suffix-,
Leerzeilen-, versteckte Approval- und Queuehintfälle jeweils gezielt korrigiert.

Keine neue Terminalöffnung: vorhandene bestätigte leere Shell
`terminal:7864:ttys000` / PID 29930 verwendet. Private authentifizierte HTTP-MCP-
Bridge und eigener sichtbarer Codex. Kurzer nicht kollabierter Prompt einmal
eingefügt, Return=true, Completion empfangen/ACK, sichtbare Antwort und exakt
ein User-/Antwortitem im eigenen Rollout. Alter Verifier false, korrigierter
mit frisch beobachteten 130 Spalten true. Der reale historische 886-Zeichen-
Frame ergibt ebenfalls alt false / neu true bei 129 Spalten; seine externe
Voraufnahme ist kein zeitgleiches internes Taskframe.

Die gemeinsamen Läufe blieben bei zwei weiteren Befunden ehrlich stehen:
Test-Launcher nutzte zunächst `codex -C` ohne OS-cd aus der wiederverwendeten
Homeshell; der CWD-gebundene Slashverifier lehnte ab. Launcher korrigiert.
Danach machte der echte Leerzeilentest die Paddingzelle sichtbar. Im selben
Fenster nach genauer Prüfung fortgesetzt: bestehender eigener 121-Zeichen-
Draft mit frischem Cursor einmal per Return bestätigt, ohne erneutes Paste;
exakt ein User-/Antwortitem. Anschließend normaler `/resume`-Paste+Return und
eine Menübestätigung ohne Paste jeweils completed/Attempt 1. Eigener Test-Codex
beendet, vorhandene Shell/Fenster und andere Prozessidentitäten erhalten.
Keine fehlgeschlagenen Gesamtläufe nachträglich als erfolgreich umbenannt.

Private Rohbelege:
`~/.local/share/kirabridge/backups/wrapped-singleline-repair-20261031/`,
insbesondere `actual-failure.private.json`, `native-acceptance/`, `native-final/`
und `native-final/final-continuation-summary.json`. Der vorhandene Harness
`scripts/accept_macos_adapter_intel.py` unterstützt nun explizites Wiederverwenden
eines leeren exakten Pane/PID und den kurzen einzeiligen Regressionstest.

Der bisherige produktive Core ist während dieser Quellprüfung `c573709`.
Commit/Paket/Installation und produktive Abnahme folgen separat. Andere komplexe
Unicode-/Whitespace-/Softwrapformen bleiben ohne positiven Beleg gesperrt.
