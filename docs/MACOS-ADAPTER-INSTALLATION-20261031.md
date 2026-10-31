# macOS-Adapter: produktive Installation und Wiederherstellung

Stand 31.10.2026. Der Nutzer hat mit „weiter install“ die Installation und
danach die Fortsetzung bis zum Planabschluss beauftragt. Kira-Skill und
vorhandener Installer verwendet. Whiteboard `0ab8b95a7369`: Installation in
Revision 8, zusätzliche Connector-/Nachrichtenbelege in Revision 9 jeweils
gespeichert und unabhängig zurückgelesen.

[Strukturierte Laufzeit-, Abnahme- und Sicherungsbelege](evidence/macos-adapter-installation-20261031.json).

## Installierter und tatsächlich getesteter Stand

Lokales Bundle aus Codecommit `7dff6f21d4bfe61da50b82092446b2e12eb50f59`,
Paket-SHA256 `ac2f1d4575044516528373ba5bf2073660840a46e6097eb0162d98b9b2f55e7f`.
Dokumentationscommit vor Installation `3ff7398`. Unterstützter Installer
sichtbar im eigenen bestätigten Tab `terminal:7799:ttys000`, Shell PID 25674;
13:05:34Z bis 13:05:46Z, Exitcode 0.

Core PID **25826**, Start `2026-10-31T13:05:44.721811+00:00`, Instanz
`39058371a48e4a3aa63f7eaa5994b548`; Quellhash
`e790665737fa910d99730f6f2a0a7ca5dec9511beebb3e1832d5a7e6e19077db`,
132 Pythondateien. Unabhängig geprüft: launchd-PID/Pfad, authentifizierter
Status und 143 Wheel-Paketdateien bytegleich. RC20-Versionslabel allein
genügt nicht. macOS 15.7.4/24G517, Intel iMac17,1; andere Systeme ungetestet.

Task `macos-installed-prompt-20261031`: 1528 Zeichen einmal eingefügt,
`completed`, Attempt 1, `return_sent=true`; Completion empfangen/ACK.
Sichtbare korrekte Antwort und genau ein User-Item plus ein finales
Antwort-Item im gebundenen echten Codex-Rollout unabhängig geprüft.
Thread `01a19213-97f8-72b1-9e2c-9eff39704c00`, Turn
`01a19215-0f61-7160-9898-b89ebe286532`, Codex 0.166.0.

`require_idle=true` verweigerte ein eigenes beschäftigtes Shellziel mit
`session_busy` vor Eingabe; falsche PID ebenfalls verweigert. Ein interner
Rawmodusaufruf ohne `require_idle` wurde nicht als Busy-Verweigerung gezählt.
Das ist von `visible_target_working` bei Nachrichtenübergabe getrennt.
Eigener Test-Codex PID 26034, Shell und Tab 7799 danach geschlossen;
Absenz und Erhalt anderer Fenster und Parent-Codex 57091 geprüft.
Slash-/Menü-/Return-/Approval-Quellabnahme im
[Implementierungsbericht](MACOS-ADAPTER-IMPLEMENTATION-20261031.md).

## Separater externer Ausfall

Der Core war erreichbar; der Tunnel war ausgefallen. Sein
`mcp.commands[0].command` zeigte auf die alte venv im Worktree
`managed-message-route-20261028`. Der stdio-Kindprozess endete mit Exit 1;
der Tunnel fuhr danach geordnet mit Exit 0 herunter. Neustart allein half nicht.

Nach privater Sicherung ausschließlich dieses YAML-Feld auf den stabilen
installierten Launcher `~/.local/bin/kirabridge --config
~/.config/kirabridge/config.toml --principal chatgpt connect` korrigiert.
Tunnel PID **25909**, healthz/readyz 200 und frischer erfolgreicher
Controlplane-Poll. Echter ChatGPT-App-`bridge_health`-Aufruf erreichte danach
den produktiven Core; der [Postfach-Livetest](WORKING-SESSION-MESSAGING-20261031.md)
belegt zusätzlich echtes Senden über den externen Connector. Keine manuelle
Voice-/Browser-UI-Abnahme behauptet. Core-Konfiguration, Credentials und
Tunnel-Plist erhalten.

## Sicherung, Erhalt und Grenzen

Privater Backupbaum:
`~/.local/share/kirabridge/backups/macos-implementation-20261031T121031Z/`.
`productive-install-20261031T130351Z/preinstall` enthält die vollständige alte
Releaseinstallation, Konfiguration/Credentials und konsistenten SQLite-Snapshot;
Hashes und Integrität geprüft. Installer-Rollbackpunkt:
`~/.local/share/kirabridge/install/backups/20261031-140537-c7f850fc`.
Unterstützten Rollback verwenden, keine alte Datenbank über neue Arbeit kopieren.
Kein Rollback nötig gewesen. Tunnel-Sicherung in `tunnel-repair-20261031T130658Z`.

Unabhängig bestätigt: Konfigurations-/Credentialhashes und Modi,
Berechtigungsrevision, 27 Queue-Holds und beide ursprünglichen Unknown-Tasks
unverändert; `integrity_check=ok`. Console 15308 und Parent 57091 erhalten.

Kurze nicht kollabierte visuell umgebrochene Mehrzeilentexte können weiter
vor Return mit `visible_paste_unconfirmed` stoppen. Terminalprojektionen
unterscheiden nicht zuverlässig jedes Leerzeichen von echten Zeilenumbrüchen;
kein unsicherer Whitespacevergleich und kein Replay eingeführt. Nicht alle
Eingabeformen sind daher als behoben bezeichnet.

Die spätere Nachrichten-Statuskorrektur wird gesondert versioniert. Dieser
produktive Prompt-/Installationsnachweis bezieht sich präzise auf `7dff6f2`.
Kein Merge und kein öffentlicher GitHub-Release.
