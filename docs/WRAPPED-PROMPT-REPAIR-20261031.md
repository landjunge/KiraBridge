# Reparatur des tatsächlich fehlgeschlagenen kurzen Prompts

31.10.2026, Fortsetzung mit Kira-Skill und Whiteboard `0ab8b95a7369`.
Produktiv repariert und über den echten ChatGPT-Connector abgenommen:
Codecommit `acc1c850ba3d2ff384e02da78e489b48ebbbf27a`.
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

Während der obigen Quellprüfung lief produktiv noch `c573709`.
Andere komplexe Unicode-/Whitespace-/Softwrapformen bleiben ohne positiven
Beleg gesperrt; keine allgemeine Rohtext-/Exactly-once-Garantie behauptet.

## Tatsächliche Installation und produktiver End-to-End-Test

`acc1c850ba3d2ff384e02da78e489b48ebbbf27a` auf dem bestehenden Entwicklungsbranch
gepusht und remote bestätigt. Offline gebautes Bundle SHA256
`551fd4118c700795e960838507684321db26a4c3048db7c00fd0fb7adf36f502`;
420 Manifestdateien und alle 132 Pythondateien im Quellbaum/Wheel/Payload
bytegleich geprüft. Ein erster isolierter Testdienststart brach vor Readiness
ab; die damalige Ausgabeunterdrückung ließ keine Ursache erkennen. Eine
diagnostische Wiederholung mit stderr-Log bestand ohne Code-/Paketänderung.
Erster Fehlbeleg bleibt erhalten, Ursache dieses einzelnen Abbruchs ungeklärt.

Unterstützter Installer in derselben bestehenden Shell, 14:30:18–14:30:30Z,
Exit 0. Aktiver Core PID **35746**, Start `2026-10-31T14:30:28.259044+00:00`,
Instanz `a7da137f455f408bb26b95b875b99006`, Paketquellhash
`aef9319b72cce81a4b5d8702a7eccb69984bba43077c21bca881cd879a87c848`.
Unabhängig launchd/current/authentifizierter Status und alle 143 installierten
Wheel-Dateien geprüft. Versionslabel weiterhin RC20, Commit/Quellhash maßgeblich.

Über den tatsächlichen externen ChatGPT-App-Connector zum neuen produktiven Core:

| Task | Inhalt | Ergebnis |
|---|---|---|
| `wrapped-installed-singleline-20261031` | 886 Zeichen, eine logische Zeile mit sichtbarem Umbruch | completed, Attempt 1, Return=true |
| `wrapped-installed-blankline-20261031` | 125 Zeichen, echte innere Leerzeile | completed, Attempt 1, Return=true |

Beide Completions empfangen und ACK. Kein manueller Nach-Return in diesen beiden
produktiven Tests. Sichtbare Kennungsantworten und jeweils genau ein User- und
Finalantwortitem unabhängig im eigenen Rollout nachgewiesen, Thread
`01a1925f-f626-7f82-b7dd-0eeebcfbadfb`. Eigener Test-Codex 35856 nach Abschluss
mit frischer Identitäts-/Leer-/Screenprüfung beendet. Vorhandene Shell 29930,
Fenster 7864, alle ursprünglichen Fenster-IDs und andere Codexidentitäten erhalten.
Kein neues Terminal geöffnet. Die ursprüngliche README-Sitzung blieb erhalten.

Konfiguration/Credentials/Modi/Berechtigungsrevision/launchd-Optionen, 28 Holds
und historische Datensätze einschließlich beider konkreten README-Fehler
unverändert. Unabhängige Belege in `productive/independent-running-verification.json`;
produktive Abnahme in `productive/acceptance/actual-productive-e2e-proof.json`.
[Versionierte Belegübersicht](evidence/wrapped-prompt-repair-20261031.json).
Whiteboard-Meilensteine Revisionen 14–16 jeweils gespeichert und zurückgelesen.

Vollständiges privates Preinstallbackup unter `productive/preinstall`.
Unterstützter Installer-Rollbackpunkt
`~/.local/share/kirabridge/install/backups/20261031-153021-014baa7c`;
kein Rollback nötig. Keine Veröffentlichung und kein Merge.
