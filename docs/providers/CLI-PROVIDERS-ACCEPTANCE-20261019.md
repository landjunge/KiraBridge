# CLI-Anbieter: tatsächliche Abnahme am 19.10.2026

Vier native Adapter sind implementiert und im bestehenden lokalen KiraBridge-
Dienst aktiviert. **OpenCode ist mit einer echten Textantwort nachgewiesen.**
Gemini, Claude Code und Copilot sind keine behaupteten erfolgreichen Modellzugänge:
Für sie bestehen die unten genannten externen Hindernisse.

## Ergebnis je Anbieter

| Zugang | Tatsächlicher Nachweis | Verbleibende Grenze |
|---|---|---|
| `opencode` | Authentifizierter Streamable-HTTP-MCP-Auftrag, nativer Sitzungsausweis, Antwort exakt `KIRABRIDGE_MCP_OPENCODE_OK`, `step_finish=stop`, Exit 0, Aufgabe `completed` | Isolierter Textmodus mit kleinem lokalem Modell; keine Projektwerkzeuge oder bestehende Sitzungsfortsetzung |
| `gemini` | Genau ein OAuth-Bridgeauftrag ohne bestätigten Abschluss; anschließende native Null-Turn-Diagnose belegt `IneligibleTierError` vor der Sitzung | Google bedient diesen persönlichen Gemini-CLI-Login nicht mehr; kein kostenpflichtiger API-Ersatz aktiviert |
| `claude` | Native lesende Anmeldungskontrolle: `loggedIn=false`; Adapter- und Abbruchtests bestanden | Anmeldung bzw. ein ausdrücklich ausgewählter vorhandener Anbieterzugang fehlt |
| `copilot` | Native Anmeldungskontrolle: `isAuthenticated=false`; eigene native Offline-Sitzung mit effektiver Werkzeugliste `[]` angelegt und geordnet geschlossen, null Prompts | Für dieses isolierte Profil fehlt ein ausdrücklich ausgewählter geeigneter Token |

Geminis historischer Auftrag bleibt `unknown`: Nachträgliche Diagnose schreibt
keine früheren Ausführungszustände um. Neue belegte Authablehnungen vor einer
Sitzung erhalten jetzt `agent_auth_unsupported_client`. Ein Upgrade der lokal
installierten Version 0.37.2 auf die inzwischen verfügbare Version 0.64.0 würde
die Kontosperre nicht aufheben. [Offizielle Google-Mitteilung](https://github.com/google-gemini/gemini-cli/discussions/28017).

## Echter lokaler MCP-Nachweis

Der Auftrag `cli-opencode-mcp-20261019-01` wurde über den authentifizierten
Zugang **`chatgpt`** vom lokalen MCP-Client eingereicht. Das ist ein Nachweis
dieses Zugangs, kein neuer Nachweis eines Aufrufs aus der ChatGPT-Oberfläche.
Er benötigte keinen Browserklick: `approval_mode=automatic`,
`approval_required=false`. Nach rund 10,48 Sekunden lag die exakte Antwort mit
konsistenter nativer Session-ID und Abschlussbeleg vor.

Mehrfaches Einreichen desselben Inhalts und Idempotenzschlüssels lieferte
dieselbe Aufgabe; die Datenbank bestätigt **genau einen Ausführungsversuch**.
Ein Ergebnisabruf durch den anderen authentifizierten Zugang `local` erhielt
`not_found`. Agentenberechtigungen gelten auch zwischen lokalen Zugängen.

Verwendet wurde ausschließlich der bereits lokale Ollama-Dienst. Ein eigener
neuer Alias `kirabridge-text:latest` erbt das vorhandene `llama3.2:1b` und setzt
`num_ctx=4096`, `num_predict=128`, `temperature=0`. Keine Modellgewichte wurden
heruntergeladen und kein bestehender Modellname ersetzt. `ollama ps` bestätigte
4.096 Kontexttokens und CPU-Ausführung. Die Abnahme löste keine Cloudmodell-
API-Aufrufe aus. Strom- und lokale Rechenressourcen bleiben erforderlich.

Der erste lokale Versuch hatte nur einen nativen Endbeleg ohne Text. Das
Ein-Schritt-Profil setzte bereits vor der Antwort eine native Max-Steps-
Assistentennachricht. Das Profil wurde auf zwei Schritte korrigiert; leere
Antworten gelten jetzt ausdrücklich als unbestätigt. Die erfolgreiche zweite
isolierte Probe und der spätere Produktions-MCP-Auftrag sind getrennte Aufgaben.
Unbekannte Aufgaben wurden nicht blind wiederholt.

## Aktivierung und Bestandsschutz

Die vorhandene Laufzeit liegt unter `/Users/EXAMPLE_USER/KiraBridge`, ihre tatsächlich
geladene private Konfiguration unter `~/.config/kirabridge/config.toml`.
Der Quellcode wurde in einem separaten Git-Arbeitsstand entwickelt und additiv
in die bestehende Installation übernommen. Bestehende Codex-/Grok-Klassen
blieben im Laufzeitcode unverändert; die vorhandenen zusätzlichen
Providerfehlerdiagnosen gingen nicht verloren.

Nur die bestehenden Agentenlisten von `local` und `chatgpt` wurden um die vier
neuen Namen ergänzt. Deren automatische Freigabe und alle anderen Policyfelder
bleiben erhalten. `codex` und `grok` behalten ihre bisherigen zwei Agentennamen
und erhalten keine zusätzliche Ausführungsberechtigung.

Vor dem Dienstneustart gab es keine wartenden oder laufenden Bridge-Aufträge.
Bridge und Freigabeoberfläche wurden per SIGTERM geordnet neu geladen;
der Dispatcher antwortet wieder. Der separate Chat-Events-Dienst und bestehende
interaktive Agentensitzungen wurden nicht beendet. **625 vorherige Auftragszeilen
und 103 bereits veränderte bzw. neue fremde Dateien blieben bytegleich**;
gesichert durch private SHA-256-Vergleiche. Konfigurations- und Codebackups liegen
privat unter `~/.local/share/kirabridge/cli-providers-20261019/activation-backup`.
Die Konfiguration behält Modus 0600.

Vor dem Push wurde festgestellt, dass das Repository öffentlich war. Es wurde
entsprechend der ausdrücklichen ursprünglichen Vorgabe auf **privat** gestellt;
GitHub bestätigte die Sichtbarkeit. Es wurde kein öffentlicher Dienst aktiviert.

## Prüfungen und Bedienung

- Lokale Gesamtsuite vor den letzten Authdiagnosekorrekturen: **365 bestanden,
  43 umgebungsabhängig übersprungen**.
- Abschließende Tests des tatsächlich installierten Codes, einschließlich
  bisheriger Codex-/Grok-Tests und aller neuen Provider-/Scope-/Idempotenztests:
  **132 bestanden**.
- Ruff, Formatprüfung und Offline-Paketbau bestanden.
- Native Offlineprüfungen bestätigten die jeweiligen Werkzeug-, MCP-, Hook-
  und Konfigurationssperren; diese Prüfungen sind keine Modellturns.

Der [reduzierte maschinenlesbare Nachweis](../evidence/cli-providers-20261019.json)
enthält Aufgaben-ID, tatsächliches Ergebnis, Grenzen und Dateihashes, keine Tokens
oder rohen Authfehlermeldungen. [Bedienung und Konfigurationsbeispiel](README.md).

```sh
kirabridge ask opencode "Antworte kurz auf Deutsch: KiraBridge bereit."
```

Alle vier neuen Adapter sind derzeit Textadapter. Native Projektbearbeitung,
Shellwerkzeuge und bestehende Sitzungsfortsetzung sind für sie noch nicht
implementiert. Die vorhandenen Codex-/Grok-Funktionen bleiben separat verfügbar.
Es wurden keine neuen kostenpflichtigen Konten oder Abonnements eingerichtet.
