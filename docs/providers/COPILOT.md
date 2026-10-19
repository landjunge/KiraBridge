# GitHub Copilot CLI

Adapter `copilot_cli`, Schnittstellenversion `1`. Geprüfte lokale CLI:
**1.0.67**. Der Adapter verwendet das eigenständige `copilot`, nicht die ältere
`gh copilot`-Erweiterung und keine laufende fremde Sitzung.

```toml
[agents.copilot]
kind = "copilot_cli"
executable = "/usr/local/bin/copilot"
api_key_env = "COPILOT_GITHUB_TOKEN"
allow_local_tools = false
```

Zusätzlich muss `copilot` in `principals.<zugang>.agents` stehen. `agent.execute`
erhält `agent = "copilot"`, `prompt`, einen erlaubten `cwd` und ein Zeitlimit.
`local_tools = true` wird vor dem Prozessstart abgelehnt.

Der angeforderte Arbeitsordner wird gegen KiraBridges Wurzelgrenzen geprüft.
Die tatsächliche textbasierte CLI-Sitzung arbeitet anschließend in einem eigenen
leeren temporären Ordner mit temporärem `COPILOT_HOME`. Persönliche und bestehende
projektbezogene Konfiguration, Plugins, Sitzungen und MCP-Server werden nicht
übernommen. Das ist erforderlich, weil `--no-custom-instructions` alleine in
1.0.67 keine Repository-Hooks deaktiviert. Die frische Konfiguration deaktiviert
Hooks, Gedächtnis und IDE-Verbindung. Eine native Werkzeug-Allowlist mit der
absichtlich nicht existierenden exakten ID `kirabridge_text_only_no_tools`,
`--deny-tool=*`, deaktivierte integrierte MCP-Server, deaktivierter Remoteexport
und Auto-Update verhindern zusätzliche lokale Ausführung. Kein `--allow-all`,
`--allow-all-tools`, `--yolo`, `resume`, `continue` oder autonomer Dauerbetrieb.
Ein leeres `--available-tools=` wird ausdrücklich nicht verwendet: CLI 1.0.67
normalisiert es zu einer fehlenden Einschränkung statt zu einer leeren Liste.

Minimierter nativer Offline-Prüfnachweis vom 19.10.2026, CLI **1.0.67**:
Der stdio-Server startete mit `--available-tools=kirabridge_text_only_no_tools`,
`--deny-tool=*`, `--disable-builtin-mcps`, `--no-custom-instructions`,
`--no-ask-user`, `--no-auto-update`, `--no-remote-export`, `--no-experimental`
und `--no-bash-env`. Ausschließlich für die Metadatenprobe wurden
`COPILOT_OFFLINE=true` und ein nicht benutzter Loopback-Provider gesetzt.
In eigenem temporärem `COPILOT_HOME` und leerem Arbeitsordner
erhielt eine neue lokale SDK-Sitzung dieselbe native `availableTools`-Allowlist;
Konfigurationsentdeckung und Sitzungstelemetrie waren abgeschaltet. Ergebnis:

```json
{
  "auth.getStatus": {"isAuthenticated": false},
  "session.create": "success",
  "session.tools.initializeAndValidate": "success",
  "session.tools.getCurrentMetadata": {"tools": []},
  "session.destroy": "success",
  "prompt_calls": 0
}
```

Das belegt die effektive leere Werkzeugliste der initialisierten nativen
SDK-Sitzung mit dem korrigierten Filter, keinen globalen Werkzeugkatalog und
keinen erfolgreichen Modellturn. Eine erste Offline-Startprobe ohne den von der
CLI verlangten lokalen Provider endete vor einer RPC-Antwort und gilt nicht als
Prüferfolg. Bestehende Anmeldungen, Konfigurationen und Sitzungen wurden nicht
übernommen oder geändert; die eigene Probesitzung wurde geordnet geschlossen.

Prompttext wird mit festem Präfix als rekonstruierbare JSON-Zeichenfolge kodiert;
`@` wird als Unicode-Escape übertragen, damit native Dateiverweise nicht vor der
Werkzeugprüfung eingelesen werden. CLI 1.0.67 verlangt `--prompt <text>`: Der
kodierte Text ist daher für lokale Prozessbetrachter sichtbar. Schlüssel stehen
ausschließlich in der ausdrücklich gewählten Umgebungsvariable, niemals in argv.
Auditnachweise enthalten weder rohe Fehlertexte noch Schlüssel.

`session.start` oder Spawn allein bedeuten keine tatsächliche Modellarbeit. Eine
native Assistentenantwort belegt Arbeit. Erfolg erfordert eine Assistentenantwort,
`assistant.turn_end`, das native JSONL-`result` mit derselben `sessionId` und
`exitCode=0` sowie Prozess-Exitcode 0. Timeout, fehlender Endbeleg, fremde Sitzung
oder unerwartete Werkzeug-/Hook-/Subagentenausführung ergeben einen unbekannten
Ausgang. Auch eine Beendigung über die Bridge hebt einen zuvor eingelesenen
Erfolgsbeleg auf. Nachrichten werden auf 64 KiB begrenzt; temporäre CLI-Daten werden nach
dem begrenzten Aufruf entfernt. Ein erfolgreicher Modellturn ist kein belegter
Projektabschluss.

Für einen belastbaren automatischen Zugang ist eine ausdrücklich ausgewählte
native Tokenvariable sinnvoll. Das Kopieren persönlicher Anmeldungs-, Plugin-
oder Konfigurationsdateien in die Isolation findet nicht statt. Am 19.10.2026 waren
`COPILOT_GITHUB_TOKEN`, `GH_TOKEN` und `GITHUB_TOKEN` in der Arbeitsumgebung nicht
gesetzt. Eine zusätzliche echte isolierte stdio-Serverprobe beantwortete das native
`auth.getStatus` erfolgreich mit **`isAuthenticated=false`**. Dabei wurden weder
Sitzungen noch Prompts angelegt und keine Modelle aufgerufen; nur der eigene
Probeprozess wurde danach beendet. Ein existierender Keychain-Eintrag oder ein
Copilot-Tarif ist damit nicht nachgewiesen. Die CLI-Installation alleine ist kein
echter erfolgreicher Modelltest.
Der Adapter erzeugt keine Abonnements und verspricht keine kostenfreien Modellaufrufe.

Quellen, abgerufen am 19.10.2026:

- [GitHub Copilot CLI](https://docs.github.com/en/copilot/concepts/copilot-surfaces/copilot-cli)
- [Offizielles SDK und native Ereignisschemata](https://github.com/github/copilot-sdk/blob/main/nodejs/src/generated/session-events.ts)
- Lokale `copilot --help`, `copilot help permissions`, `copilot help config`,
  `copilot help environment` und `copilot login --help`.
- Bereits installiertes öffentliches CLI-Paket `1.0.67/app.js`: native JSONL-
  Ausgabe schreibt `{type:"result", sessionId, exitCode}`; Repository-Hooks werden
  unabhängig von der Einstellung zum Laden eigener Anweisungen entdeckt.
