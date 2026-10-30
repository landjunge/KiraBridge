# Issue 51: leere macOS-Shells und ChatGPT-Eingabe · 30.10.2026

Auftrag `channel-fa23a557d4a44e8da2e2be149c9d2564`, Konversation
`shell-control-issue51-oct30`, Nachricht `0416af39-7e3a-4ae5-8849-46be8c9dcf7f`.
Empfang gelesen, Receipt `184202e8-c676-459e-adb0-699743d6d3a9` bestätigt.

Der Shell-Fehler ist im Entwicklungszweig behoben und lokal geprüft.
[Draft-PR54](https://github.com/landjunge/KiraBridge/pull/54), Branch
`fix/issue51-shell-prompt-20261030`, Codecommit
`f869aa53ed84edfa00bb8e7b26538b0d58aa5be4`, Basis main
`307004e5b2e4285c19e8d7544bedf45b28297a0b` nach PR53.
[Issue51](https://github.com/landjunge/KiraBridge/issues/51) bleibt offen.
Keine produktive Installation, kein Neustart, Merge oder Release dieses Auftrags.

## Belegte Ursache

1. Ein vorhandener freier Shell-Tab wurde ausschließlich gelesen. Seine letzte
   nichtleere Bildschirmzeile war `➜  ~ ` mit unverändertem abschließendem Leerzeichen
   und anschließend leeren Terminalzeilen. `.zshrc:11` setzt `ZSH_THEME="robbyrussell"`;
   die vorhandene Theme-Datei definiert Pfeil, zwei Leerzeichen, Verzeichnis und
   Leerzeichen sowie optionale Git-Dekoration. Diese Dateien wurden nicht geändert.
2. Der tatsächliche Pfad ist `session.input` → `SessionManager.send` →
   `direct_terminal_required` für Principal `chatgpt` oder `client_type=chatgpt` →
   `TerminalAppTransport.send_confirmed` → `empty_shell_prompt`.
   Der Parser in `platform_adapters/shell_prompt.py` akzeptierte `%`, `$`, `#`
   und den kontrollierten KiraBridge-Prompt, nicht den beobachteten Theme-Prompt.
   Deshalb `visible_input_not_empty`, bevor die native Eingabe beginnt.
3. `send_confirmed` enthielt zusätzlich eine eigene JavaScript-Promptprüfung mit
   derselben Lücke. Eine alleinige Python-Korrektur hätte diese zweite Ablehnung
   nicht beseitigt. Der Agent-Promptparser `visible_readiness.py` steuert diesen
   Shell-Zweig nicht. Die Ursache ist keine belegte Arbeitsverzeichnisstörung.
4. Frühere erfolgreiche Shelltests als Principal Codex verwendeten den anderen
   `send`-Zweig und waren kein Nachweis für funktionierende direkte ChatGPT-Eingabe.
   Die neuen Tests prüfen ausdrücklich den ChatGPT-Zweig.

Quellen: [Promptparser](../src/kirabridge/platform_adapters/shell_prompt.py),
[SessionManager](../src/kirabridge/session_manager.py),
[Cliententscheidung](../src/kirabridge/permissions.py),
[nativer Transport](../src/kirabridge/platform_adapters/terminal_app.py).

## Änderung und Sicherheitsgrenzen

- Zusätzliche strikte Erkennung `➜  <ein Verzeichnistoken> `: exakt zwei Leerzeichen
  nach dem Pfeil, genau ein abschließendes Leerzeichen, maximal 240 Tokenzeichen.
  Vorhandene Eingabe, zusätzliche Leerzeichen, Steuerzeichen, Fortsetzungsprompts,
  Git-Dekoration und Verzeichnistoken mit Leerzeichen bleiben abgelehnt.
- Die doppelte native Promptheuristik entfällt. Stattdessen prüft der native Schritt
  die letzten 8192 Unicode-Codepoints des akzeptierten Bildschirminhalts vor und
  nach dem Fokussieren auf Gleichheit. Auch ein Wechsel zu einem anderen gültigen
  leeren Prompt führt jetzt zum Abbruch. Busy wird unmittelbar vor `doScript`
  erneut geprüft; UID/TTY/PID/Startzeitprüfung und Unsicherheitsbehandlung bleiben.
- Kein Löschen vorhandener Eingabe, kein Probe-Return, keine automatische Wiederholung,
  kein Wechsel in einen anderen Tab und kein versteckter Transport als Ersatz.

Textbasierte Promptbeobachtung ist weiterhin begrenzt: beliebige Themes, Git-Dekoration,
  mehrzeilige Prompts und Shells mit Verzeichnisleerzeichen sind nicht allgemein
  abgenommen. Die Bildschirmvergleiche sind kein atomarer Betriebssystem-Lock gegen
  gleichzeitige manuelle Eingabe. Der Fehlercode für einen unbekannten Prompt bleibt
  aus Kompatibilitätsgründen `visible_input_not_empty`.

## Tests und unabhängige Prüfung

Intel iMac17,1, macOS 15.7.4 / Build24G517, x86_64, Python3.11.15, uv0.11.6,
isolierte Worktree-venv, `uv sync --locked --dev --python /usr/local/bin/python3.11`.

Gezielter Lauf:

```sh
uv run pytest -q tests/test_shell_prompt.py tests/test_plain_shell_paste.py tests/test_discovery_visible.py tests/test_session_dispatch_evidence.py tests/test_sessions.py tests/test_terminal_tabs.py
```

Erster Lauf: **124 bestanden, 1 fehlgeschlagen**. Ausschließlich der neue Test
verwendete den nicht vorhandenen Enum-Namen `State.SUCCEEDED`; nach Korrektur auf
`State.COMPLETED` bestand der einzelne betroffene Test. Der zusätzliche Test für
den gemeinsamen Paste-only-Promptpfad bestand ebenfalls. Damit sind **126 verschiedene
relevante Tests bestanden**, kein wiederholter lokaler Gesamtsuitenlauf.

Die sieben Tests mit tatsächlich erzeugtem nativen JavaScript prüfen Erfolg,
Inputänderung vor Dispatch, Wechsel zu anderem leeren Prompt, Inputänderung beim
Fokuswechsel, Busy beim Fokuswechsel, Busy vor Dispatch und geänderte Prozessidentität.
JavaScript läuft gegen einen Fake-Application-Host ohne Zugang zu Terminal.app.
Nach Ergänzung des Subprozess-Aufräumens im Harness wurden genau diese sieben Fälle
erneut erfolgreich geprüft. Fehlerfälle belegen null `doScript`-Aufrufe.
Weitere Tests prüfen den echten Task-/ChatGPT-Zweig, Callback-Abbruch und verhindern
den ungeschützten Raw-send-Fallback. Ruff, Formatprüfung und `git diff --check` bestanden.
Native Read-only-Subagentprüfung des Source-/Test-Diffs: kein blockierender Befund.

## Echter isolierter Intel-Test

Nur ein neu angelegtes eigenes Fenster `terminal:3912:ttys003`, Shell-PID43881.
Die übrigen Tabs wurden weder beschrieben noch geschlossen. Isolierte Bridge-Instanz
mit explizitem Principal `chatgpt`, eigenen temporären Zustandsdateien und ausschließlich
Entwicklungscode; keine Verbindung zu einer zweiten Daemoninstanz und keine Änderung
der produktiven Konfiguration.

Der echte frische Prompt `➜  owned-shell ` wurde vom Baseline-Parser abgelehnt und
vom Fix akzeptiert. Zwei `SessionManager.send("chatgpt", ...)`-Aufrufe über den
nativen bestätigten Pfad schrieben jeweils einen unterschiedlichen harmlosen Marker
in eine private Receipt-Datei. Beide Marker sind exakt einmal vorhanden, zusammen
zwei Zeilen; Receipt-SHA256:
`338c2c7480c8208f1094273d58589e9bbba6b82ca41370264af029d9768e4bf9`.
Dies belegt diese zwei Shellkommandos; es ist keine vollständige Agent-Handoff-Abnahme.

Das eigene Fenster wurde nach Idle-/PID-Prüfung geschlossen. Eine neue unabhängige
Inventur bestätigt denselben ursprünglichen Satz aus fünf nativen Tab-IDs
3033/3206/3541/3546/3903; alle acht ursprünglichen Prozessidentitäten unverändert.
[Strukturierter Beleg](evidence/issue51-shell-prompt-20261030.json).

## Sicherungen, Produktion und verbleibende Gates

Private lokale Sicherung:
`~/.local/share/kirabridge/backups/issue51-shell-prompt-20261030/`.
Vor Änderungen `main-before.tar` und vollständiges `before.bundle`, beide SHA256
gegen `backup-manifest.json` nachgelesen; `git bundle verify` erfolgreich.
Nach dem Abschnitt Kopien aller vier geänderten Code-/Testdateien mit unabhängig
nachgelesenen SHA256 in `verified-change-manifest.json`. Privater `live_probe.py`,
`live-probe-result.json` und Receipt erhalten. Keine Geheimnisse in Git aufgenommen.

Produktionsbeobachtung vor/nach Test identisch: RC18, PID18197,
Instanz `82cd506b1d854b50b4cc58c5016fc856`,
Quellhash `bea0158935efd09a2304be2eb024ce79d5a100cf754742dcbe52aaddce1dc9ee`,
Konfigurationshash `52747b8353bef4cc162997c34c30d8e759ca0691725d902f313ce4653cf903c2`.
RC17-Rückweg und veröffentlichte Releases bleiben unverändert; siehe vorhandenen
[Installationsbericht](RC18-PUBLISH-INSTALL-20261029.md).

Automatische GitHub-Läufe zum Codecommit: Verify push40987909261,
Verify PR40987936366, macOS-Paket40987936257. Paketjobs haben null gestartete Schritte;
Annotation von Job123843220658 nennt fehlgeschlagene Kontozahlung/Ausgabenlimit.
Kein manueller Dispatch oder Retry, keine Billingänderung. Linux war beim ersten
Dokumentationsstand noch in Arbeit; maßgeblich ist der aktuelle PR-Checkstatus.
ARM und bezahlte macOS-Ausführung bleiben zurückgestellt, kein behaupteter Erfolg.
Der GitHub-Connector lehnt den direkten Job-GET als nicht zugelassenen Endpunkt ab;
deshalb wurde ausschließlich diese fehlende Read-only-Ansicht über `gh api` gelesen.

Historische unknown/blocked-/Library-Aufträge wurden weder wiederholt, freigegeben
noch bereinigt. Die aktuelle Übergabe wurde tatsächlich empfangen, hat aber einen
separaten `delivery_timeout`/unknown-Status nahe Return; sie wurde nicht erneut gesendet.
Dieser Zeitablauf ist kein Beleg für eine Ursache im Shell-Promptparser.

Nächster sicherer Schritt: Draft-PR54 und Pflichtchecks prüfen; getrennte Freigabe
für Integration und spätere produktive Installation abwarten. Danach echte
ChatGPT-API-Shellabnahme einschließlich Ausgabe/Exitstatus und vollständige
Codex-Paste/Return/ACK/ChatGPT-Empfangsabnahme durchführen. Issue51 erst nach dessen
eigenen vollständigen, wiederholbaren Abnahmekriterien schließen.
