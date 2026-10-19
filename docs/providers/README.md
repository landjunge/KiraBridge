# Weitere CLI-Anbieter in KiraBridge

Stand: 19. Oktober 2026. Vier getrennte native Adapter ergänzen Codex und Grok.
Sie verwenden die vorhandene persistente Auftragsverwaltung, Berechtigungen,
Prozesskontrolle und MCP-Operation `agent.execute`; keine zusätzliche Python-
Laufzeitabhängigkeit und kein dauerhaft laufender Anbieter-Dispatcher sind nötig.

| CLI | Konfigurationsart | Lokal geprüfte Version | Zugang und Kosten | Anleitung |
|---|---|---|---|---|
| OpenCode | `opencode` | 1.4.4 | Ein explizites `provider/model`; lokal mit vorhandenem Ollama-Modell ohne Cloudgebühr, Cloudtarife separat | [OpenCode](OPENCODE.md) |
| Gemini CLI | `gemini_cli` | 0.37.2 | Unterstützte Enterprise-Anmeldung oder ausdrücklich gewählter API-Key; der vorhandene persönliche OAuthzugang wird vom Anbieter abgewiesen | [Gemini](GEMINI.md) |
| Claude Code | `claude_code` | 2.1.236 | Vorhandener nativer Login oder ausdrücklich gewählter Anthropic-Key; kein kostenloser Zugang angenommen | [Claude](CLAUDE.md) |
| GitHub Copilot CLI | `copilot_cli` | 1.0.67 | Ausdrücklich ausgewählter Copilot-Token; Installation beweist weder Anmeldung noch verfügbaren Tarif | [Copilot](COPILOT.md) |

Die Tabelle beschreibt die lokal geprüften Versionen. Sie behauptet keine
Kompatibilität mit jeder künftigen CLI-Version. Die verlinkten Anbieterberichte
enthalten offizielle Quellen und die jeweils tatsächlich überprüften Grenzen.

## Bedienung

Der Betreiber ergänzt die gewünschten `[agents.<name>]`-Abschnitte und trägt
genau diese Namen in `principals.<zugang>.agents` ein. Der Zugang benötigt
`agent.execute` und einen erlaubten Arbeitsordner. [Konfigurationsbeispiel](../../examples/cli-providers.toml).
Bestehende automatische Freigaben oder Einzelauftragsfreigaben bleiben erhalten.
Neue Adapter schalten keine anderen Funktionen und keine fremden Identitäten frei.

```sh
kirabridge ask opencode "Antworte kurz: KiraBridge bereit."
kirabridge ask gemini "Antworte kurz: KiraBridge bereit."
kirabridge ask claude "Antworte kurz: KiraBridge bereit."
kirabridge ask copilot "Antworte kurz: KiraBridge bereit."
```

Für MCP bleibt das vorhandene Werkzeug `task_request` zuständig:

```json
{
  "request": {
    "api_version": "1",
    "task_id": "provider-text-001",
    "idempotency_key": "provider-text-001",
    "operation": "agent.execute",
    "arguments": {
      "agent": "opencode",
      "prompt": "Antworte kurz: KiraBridge bereit.",
      "cwd": "/ABSOLUTER/FREIGEGEBENER/ORDNER",
      "timeout": 120,
      "local_tools": false
    }
  }
}
```

`task_get` und `task_events` liefern den dauerhaften Zustand und native
Ergebnisbelege. Die identische Aufgaben-ID und der identische Idempotenzschlüssel
lesen bei Wiederholung denselben Auftrag. Ein unbekannter Ausgang wird nicht
automatisch erneut ausgeführt. Fehlende Authentifizierung wird durch einen
Adaptereintrag oder eine vorhandene ausführbare Datei nicht behoben.

## Tatsächlicher Funktionsumfang

Alle vier neuen Adapter führen **isolierte Textaufträge** in eigenen begrenzten
Sitzungen aus. Ihre nativen Werkzeuge, MCP-Erweiterungen, Plugins und Projekthooks
sind deaktiviert. Das angeforderte Arbeitsverzeichnis wird geprüft; die CLI läuft
in einem eigenen leeren temporären Ordner. Zulässigen Projektkontext muss der
Aufrufer ausdrücklich im Prompt übergeben. Dies ist keine Betriebssystem-Sandbox.

Eine vorhandene interaktive Sitzung wird weder übernommen noch beendet. Lokale
Dateibearbeitung, Shellwerkzeuge und die Fortsetzung bestehender Sitzungen sind
für diese vier Adapter noch nicht implementiert. `local_tools=true` wird vor
Ausführung abgelehnt. Die bisherigen Codex-/Grok-Funktionen bleiben eigenständig.
Ein erfolgreich beendeter Modellturn beweist keinen vollständigen Projektabschluss.

Die native Isolation ist pro Anbieter nötig: Beispielsweise bedeutet bei der
geprüften Copilot-Version eine leere Werkzeug-Allowlist tatsächlich keine
Einschränkung. Gemini behandelt eine leere MCP-Allowlist ebenfalls als uneingeschränkt.
Die Adapter und nativen Offlineprüfungen berücksichtigen diese Unterschiede.

## Weitere untersuchte Kandidaten

[Aider](https://aider.chat/docs/usage.html) bietet Terminalsteuerung für
Codeänderungen mit unterschiedlichen Modellen. Es wäre ein weiterer eigener
Adapter, benötigt aber zuerst einen nachgewiesenen Maschinenvertrag für
Änderungsbelege und Zugriffsbeschränkungen. Es wird hier nicht unter einer anderen
Anbieteridentität gestartet. Diese Auslieferung konzentriert sich auf die vier
bereits vorhandenen CLIs; eine bloße Installation gilt nicht als Integration.

## Abnahme

Die synthetischen Adapter- und Integrationstests prüfen native Endereignisse,
Sitzungswechsel, Ausgabegrenzen, Timeout/Abbruch, Werkzeugverweigerung,
Umgebungsisolation, Agentenzulassung, Idempotenz und fremden Auftragszugriff.
Die Anbieterberichte trennen diese Tests von tatsächlichen Modellaufrufen.
Der [Integrationsbericht](CLI-PROVIDERS-ACCEPTANCE-20261019.md) hält den konkreten
Livezustand und verbleibende Anmeldeschritte fest.
