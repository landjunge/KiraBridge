# N1: CLI-Rückgaben ohne zusätzlichen Agententurn

Teilauftrag `BP-NATIVE-COMPLETION-20261106-N1`, Claim
`188ce4729a62/e69fdb03e21d`, ein Schreiber01a1a7d1. Eigener Worktree
`native-completion-chain-20261106` ab C2
`843db415ad2fa7b619ae00d7fae2f973bdaaf7ee`. C2, Windows und dessen offenes
Prozessgate bleiben unverändert. Keine neue Queue, kein Endpoint oder Providerstart.

## Ursache und enge Änderung

`message_send` behandelt `answer/result` bei nicht gesetztem `dispatch` bereits
als passive Rückgaben. Der CLI-Caller setzte dagegen ohne `--inbox-only` immer
`dispatch=true` und erzeugte dadurch auch für diese Typen einen neuen Receiverjob.
Der Fix gibt nur für diese beiden Typen den vorhandenen Serverdefault weiter.
`question/work/note` und explizites `--inbox-only` behalten ihren bisherigen Pfad.
Historische Dispatchentscheidungen bleiben beim vorhandenen MessageManager
gepinnt; ein früheres UNKNOWN wird weder umgedeutet noch erneut ausgeführt.

Automatische Rückgabe beziehungsweise Parentabschluss ist bereits das Ergebnis.
Ein Transport-ACK ist keine neue Nachricht und benötigt keinen Modellturn.
Explizite neue Arbeit bleibt ein eigener autorisierter Auftrag mit stabiler ID.
TeamWork, MessageReceiver, Outbox und CompletionClient bleiben die vorhandenen
Ausführungs-/Rückgabekomponenten.

## Sofort nutzbarer Weg auf der bestehenden Runtime

Wenn tatsächlich noch ein externes Ergebnis aussteht, kann die vorhandene CLI es
bereits passiv senden; Platzhalter nur durch die passende eigene Bindung ersetzen:

```text
kirabridge --config <CONFIG> --principal <ABSENDER> message send <EMPFÄNGER> <ERGEBNIS> --conversation <CONVERSATION> --key <STABILE_ID> --kind result --reply-to <ORIGINAL_MESSAGE_ID> --inbox-only
```

Dasselbe gilt für `--kind answer`. Kein zusätzliches ACK-Ergebnis senden, wenn
der ursprüngliche Parent/Receiver es bereits automatisch geliefert hat.
Für passive Hinweise bleibt `--kind note --inbox-only --no-reply` ausdrücklich
erforderlich; der bisherige Note-Default wird hier nicht umgestellt.

Vorhandener Server-MCP-Weg: `message_send` mit `message.kind=answer|result`,
`dispatch=false`, `request_reply=false` und passenden Original-/Gesprächskennungen.
Für autorisierte neue Arbeit kann dessen bereits vorhandenes `completion_target`
den bestehenden `completion_receive/ack`-Kanal wählen. `kirabridge watch --target
<TARGET> --once` liest und quittiert eine solche Completion. Dies fügt keinen
Folgeprompt hinzu und weckt keine schlafende TUI.

Die installierte RC39-CLI-Datei ist bytegleich zum ungeänderten843db41-Caller
(SHA256 `74c7e305d8045e0440ff637610fcbd64eee980c3fa9fb72e4b7682cf5384288d`).
Der vorhandene Schalter wurde vor dem Fix über denselben Parser und echten
lokalen MCP positiv geprüft. Keine produktive Nachricht oder Installation dafür.

## Sitzungsgrenze und Nachweise

Ein fehlendes `send_message_to_thread` wird nicht durch Behauptung verfügbar.
`codex queue` ist kein passiver Completiontransport; neue Status-/Freeze-/ACK-
Prompts verursachen zusätzliche Turns. Auch die
[offizielle OpenAI-Dokumentation](https://developers.openai.com/blog/mastering-codex-remote-for-engineering)
unterscheidet Queue als Folgeturn von Steer. Dieser Fix verändert weder Codex
noch dessen Toolkatalog. Frühe Arbeitsmeldungen bleiben im Board; für dieses
Paket liest Root den Threadabschluss, ohne zusätzliche Queue-Callbacks.

`tests/test_cli_message_returns.py` benutzt den tatsächlichen CLI-Parser und
authentifizierten lokalen HTTP-MCP-Client. Nur das Laden der isolierten Testpolicy
wird injiziert; Agenten sind deterministische lokale Python-CLIs. Keine echten
Provider-/TUI-/Windows-/Remoteabnahmen daraus ableiten.

- Altcode:2 relevante Fehler (answer/result erzeugen Jobs),3 Kontrollfälle grün,
  5,87s. Darin funktionieren bereits `--inbox-only` und zwei einmalige Workstarts.
- Nach Korrektur:8 gezielte Fälle grün,8,46s; passive Rückgaben, Original-UNKNOWN,
  automatische Parentrückgabe, CLI-watch/ACK und expliziter Folgestart.
- Betroffener Lauf:24 Tests grün,14,51s, einschließlich vorhandener Message-,
  Completion- und sichtbarer historischer Idempotenzregressionen. Nicht addieren.

Das versionierte `skills/cli-model-router/SKILL.md` wird vom vorhandenen Installer
übernommen und wurde deshalb auf ausdrückliche Rootanweisung bytegleich zur
kanonischen Fassung synchronisiert. Keine globalen Skillwrites durch diesen
Bearbeiter. Quelle/Testlogs/Manifest liegen privat unter
`~/.local/share/kirabridge/backups/bigplan-native-completion-chain-20261106-n1/`.
Quellkandidat bleibt uninstalliert/unaktiviert/unpushed; kein CI-/Releaseeingriff.
