# Claude Code

Adapter `claude_code`, Schnittstellenversion `1`. Geprüfte lokale CLI:
Claude Code **2.1.236**. KiraBridge startet einen eigenen kurzlebigen Prozess;
vorhandene interaktive Claude-, Codex- oder Grok-Sitzungen werden nicht übernommen.

```toml
[agents.claude]
kind = "claude_code"
executable = "/usr/local/bin/claude"
api_key_env = "ANTHROPIC_API_KEY"
allow_local_tools = false
```

Die Identität muss zusätzlich in `principals.<zugang>.agents` freigegeben sein.
Ein Auftrag verwendet `agent.execute` mit `agent = "claude"`, `prompt`, einem
erlaubten `cwd` und einem Zeitlimit. `local_tools = true` wird vor Prozessstart
abgelehnt; dieser Adapter ist ausschließlich für Textantworten vorgesehen.

Der native `--safe-mode` erhält die native Anmeldung, lädt aber keine persönlichen
oder projektbezogenen Anpassungen. Zusätzlich setzt der Adapter leere
Einstellungsquellen, `disableAllHooks`, eine leere Werkzeugliste, `dontAsk`, eine
explizit leere strikte MCP-Konfiguration und deaktiviert Skills, Chrome sowie
Sitzungspersistenz. Er benutzt weder Berechtigungsumgehung noch `resume`.
Organisationsrichtlinien werden nicht umgangen. Die Umgebung enthält nur den
minimalen Terminalkontext, HOME und die ausdrücklich konfigurierte Schlüsselvariable.
Vorhandene Benutzereinstellungen werden nicht geändert. Prompttext wird als
rekonstruierbare JSON-Zeichenfolge über stdin übertragen; ein festes Präfix und
Unicode-Escapes für `@` verhindern Slash-/Dateiverweis-Vorverarbeitung.
Der angeforderte Arbeitsordner wird zuerst gegen die erlaubten Wurzeln geprüft;
der eigentliche Textturn läuft in einem eigenen leeren temporären Arbeitsordner.
Damit werden auch vor der Werkzeugprüfung keine Kontextdateien aus dem
angeforderten Repository eingelesen. Das ist keine behauptete Betriebssystem-Sandbox.

Ein Prozessstart oder `system/init` belegt keine Modellarbeit. Erst eine native
Assistentenantwort beziehungsweise das native erfolgreiche Resultat belegt Arbeit.
Erfolg erfordert `result/subtype=success`, `is_error=false`, eine konsistente
Sitzungs-ID und Exitcode 0. Fehlendes Resultat, Timeout, Beendigung, Sitzungswechsel oder
unerwartet aktivierte Werkzeuge führen zu unbekanntem Ausgang; kein blinder Retry.
Native Fehlertexte werden nicht in Fortschritts- oder Ergebnisnachweise kopiert.
Ausgabetext bleibt auf 64 KiB begrenzt. Ein erfolgreicher Modellturn bestätigt
keinen vollständigen Projektabschluss.

Am 19.10.2026 meldete der lesende lokale `claude auth status --json` ausdrücklich
**nicht angemeldet**. `ANTHROPIC_API_KEY` war nicht gesetzt. Das ist kein
funktionsfähiger Anbieterzugang und kein erfolgreicher echter Modelltest.
Login, Tarif oder Abrechnung müssen separat vorhanden sein; der Adapter bucht nichts.

Quellen, abgerufen am 19.10.2026:

- [Native Automatisierung und JSONL-Protokoll](https://code.claude.com/docs/en/headless)
- [CLI-Flags einschließlich Safe Mode, Werkzeugliste und MCP](https://code.claude.com/docs/en/cli-reference)
- [Einstellungsquellen und Richtlinien](https://code.claude.com/docs/en/settings)
- Lokale `claude --help`, `claude auth status --help` und strukturierter Authstatus.

Die aktuelle Online-Dokumentation enthält auch neuere Flags als die installierte
Version. Der Adapter verwendet ausschließlich lokal vorhandene Flags; insbesondere
kein neueres `--permission-prompts` und kein OAuth-deaktivierendes `--bare`.
