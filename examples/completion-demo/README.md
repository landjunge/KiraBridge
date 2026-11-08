# Abschlusskanal-Abnahme

[Originale Task-, Callback- und Quittierungsbelege](run-20261019-01/evidence.json)
zeigen den tatsächlichen lokalen Rückkanal einschließlich eines echten Codex-Turns.
Grok-/Providerfehler werden ausschließlich in isolierten Tests simuliert.

```sh
.venv/bin/python scripts/accept_completion_channel.py /private/tmp/kirabridge-completion-NEU \
  --real-codex "$(command -v codex)" --probe-installed
```

Ohne `--real-codex` werden nur lokale Terminalaufträge ausgeführt. Der Zielordner
muss neu sein. `--probe-installed` prüft ausschließlich den vorhandenen
`chatgpt`-MCP-Handshake und die Werkzeugliste, ohne Auftrag oder Dienstneustart.
Der eigentliche Lauf nutzt eigene Principals, flüchtige Tokens, Loopback-Port,
Testdateien und SQLite. Secrets werden nicht exportiert. Der Listener gibt die
wirklich empfangenen Meldungen im Terminal aus; keine simulierten Fortschrittslogs.

[Implementierung, Fehlerklassen, Empfangsgrenzen und Nutzung](../../docs/COMPLETION-CHANNEL-20261019.md).
Eine Callback-Quittung ist keine Behauptung, dass ein inaktiver ChatGPT-Chat
aufgeweckt wurde. Der neue Stand ist nach kontrolliertem Reload ohne laufende Aufträge auch im
Betreiberdienst aktiv: [Aktivierung](run-20261019-01/activation.json),
[App-Terminalauftrag](run-20261019-01/installed-submission.json) und
[wirklicher Callback/Ack](run-20261019-01/installed-delivery.json) sind belegt.
184 Tests und alle Ruff-Prüfungen bestanden.
