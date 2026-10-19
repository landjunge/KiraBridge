# OpenCode über KiraBridge

Stand: 19.10.2026. Implementiert ist der native V1-CLI-Vertrag von OpenCode
**1.4.4**. Die neuere V2-Dokumentation verwendet andere Konfigurationsfelder;
daraus wird keine Kompatibilität dieser Implementierung abgeleitet.

## Einrichten und aufrufen

Der Betreiber konfiguriert einen eigenen Agentenzugang mit `kind = "opencode"`,
absolutem `executable`, explizitem `model = "provider/model"` und bei Bedarf
`api_key_env`. Beispiel für einen bereits beim Betreiber eingerichteten Anbieter:

```toml
[agents.opencode]
kind = "opencode"
executable = "/usr/local/bin/opencode"
model = "openrouter/ANBIETER/MODELL"
api_key_env = "OPENROUTER_API_KEY"
allow_local_tools = false
```

Der Modellname ist ein Platzhalter und muss durch eine tatsächlich verfügbare
Modell-ID ersetzt werden. Das Kennwort gehört in die ausdrücklich ausgewählte
Umgebungsvariable des Bridge-Dienstes. Der Adapter übernimmt weder die vollständige
Dienstumgebung noch OpenCodes vorhandene `auth.json`. Der authentifizierte
Bridge-Zugang benötigt zusätzlich die Berechtigung für diesen Agenten; seine
Aufträge bleiben den bestehenden Einzelauftrags- bzw. automatischen Freigaben
unterworfen.

Ein bereits lokal laufender Ollama-Dienst mit vorhandenem Modell kann ohne
Cloudkonto verwendet werden:

```toml
[agents.opencode]
kind = "opencode"
executable = "/usr/local/bin/opencode"
model = "ollama/kirabridge-text:latest"
base_url = "http://127.0.0.1:11434/v1"
api_key_env = "OPENCODE_API_KEY"
allow_local_tools = false
```

`base_url` wird ausschließlich vom Betreiber konfiguriert und auf lokales
Loopback-HTTP beschränkt. Der Adapter verwendet OpenCodes bereits enthaltenes
`@ai-sdk/openai-compatible`, definiert genau das ausgewählte Modell mit einem
deklarierten Kontext von 4096 und einem Ausgabelimit von 128 Tokens und deaktiviert
Modell-Toolaufrufe. Er lädt keine Modelle oder SDK-Pakete nach. Das lokale
Profil reicht keine Provider-API-Schlüssel an den lokalen Dienst weiter. Das
Modell muss bereits verfügbar sein; der Adapter behauptet keine geeignete
Leistung für umfangreiche Entwicklungsaufträge. Lokale Inferenz verursacht
keine Cloud-API-Gebühren, benötigt aber die Rechenressourcen des Macs.

Die deklarierte Kontextgröße ist OpenCode-Metadatum: Sie setzt Ollamas
tatsächliches `num_ctx` nicht. Der lokale Abnahmeweg verwendet deshalb den
eigens aus dem bereits vorhandenen `llama3.2:1b` erstellten Alias
`kirabridge-text:latest` mit `PARAMETER num_ctx 4096`,
`PARAMETER num_predict 128` und `PARAMETER temperature 0`. Dafür werden die
vorhandenen Modellgewichte wiederverwendet; das Originalmodell und andere
Sitzungen werden nicht geändert. Die offizielle OpenAI-kompatible
Ollama-Schnittstelle verlangt für eine feste Kontextgröße diesen Weg über
Modelfile/Modellalias. Ein anderer lokaler Provider muss seine tatsächlichen
Ressourcenlimits selbst verbindlich umsetzen.

Das Profil erlaubt höchstens zwei native Agentenschritte. In V1 injiziert
`steps = 1` schon vor dem ersten Modellaufruf eine künstliche
„Maximale Schritte erreicht“-Assistentennachricht. `steps = 2` vermeidet diese
erste Vorbelegung; lokale Tools bleiben unabhängig davon verweigert. Ein
finaler Stop ohne beobachtbaren Antworttext gilt als unbestätigt.

Ein Auftrag verwendet die vorhandene Operation `agent.execute`:

```json
{
  "agent": "opencode",
  "prompt": "Antworte kurz: KiraBridge ist erreichbar. Keine Werkzeuge verwenden.",
  "cwd": "/ABSOLUTER/BEREITS/FREIGEGEBENER/ARBEITSORDNER",
  "timeout": 60.0,
  "local_tools": false
}
```

## Tatsächliche Funktion und Grenzen

Der Adapter startet für jeden Auftrag eine **separate neue Textsitzung** und
verwendet `opencode run --pure --format json --agent kirabridge`. Der Prompt wird
als UTF-8 über stdin übermittelt. Es werden keine bestehenden interaktiven
Sitzungen, Server oder offenen Aufträge fortgesetzt und keine `--continue`,
`--session`, `--attach`, `--command` oder Dateianhang-Optionen verwendet.

Das angeforderte Arbeitsverzeichnis wird gegen die Zugriffsrechte geprüft und
während der Ausführung als Verzeichnis geöffnet gehalten. Der eigentliche
OpenCode-Prozess arbeitet in einem leeren privaten temporären Verzeichnis. Er
erhält **keinen Projektdateizugriff**. Dies steht auch in der Ergebnis-Evidenz:
`execution_workspace = "private_temporary_directory"`,
`requested_workspace_access = false`. Das ist ein Textadapter, kein behaupteter
Projektbearbeiter und keine OS-Sandbox. Bei ausdrücklich angeforderten lokalen
Werkzeugen mit entsprechender Agentenkonfiguration wird vor dem Start
`agent_capability` zurückgegeben.

Der isolierte V1-Konfigurationssatz verweigert alle nativen Tools auch für den
ausdrücklich ausgewählten Agenten. Projektkonfiguration, externe Plugins,
MCP-Server, externe Skills, Claude-Code-Konfigurationsübernahme, LSP, Formatter,
Snapshots, automatische Updates und Sitzungsfreigaben sind deaktiviert. Separate
temporäre XDG-Konfigurations-, Daten-, Cache- und Statusverzeichnisse verhindern
die Übernahme fremder OpenCode-Einstellungen, Sitzungen und Remote-Konfiguration
aus gespeicherten Zugangsdaten. Das leere globale Konfigurationsverzeichnis ist
nicht schreibbar, damit OpenCodes eigene Schreibbarkeitsprüfung die sonst
automatisch gestartete Plugin-Paketinstallation überspringt. Betriebssystemweit
verwaltete OpenCode-Einstellungen führen zu einem klaren Konfigurationskonflikt;
sie werden nicht überschrieben.

Im geprüften V1-Quellcode reicht der normale `run`-Pfad stdin als Textteil an den
Provider weiter. Die gesonderte Auflösung von `@Datei`-Verweisen gehört zum
`--command`-Pfad. Da keine Command- oder Dateianhang-Option übergeben wird, werden
solche Prompttexte vom Adapter nicht als Dateizugriffsauftrag ausgewertet.

Prozessstart, Sitzung und belegter Arbeitsstart bleiben getrennt. Erst ein
nativer `step_start` oder ein beobachteter Modelltext bestätigt Arbeit. Ein
`step_finish` mit `part.reason = "stop"` **und** Exitcode 0 ist der erfolgreiche
Abschluss eines Agententurns. Fehlender Endevent, Verbindungsabbruch, Zeitlimit
oder Sitzungswechsel bleiben `unknown`; ausdrückliche Provider- oder
Längenfehler sind kein Erfolg. Ein erfolgreicher Turn beweist keinen vollständigen
Projektabschluss. Der Adapter führt keine automatische Wiederholung aus.

Das bedeutet keine Garantie eines einzigen HTTP-Versuchs: OpenCode V1.4.4
wiederholt bestimmte Providerfehler intern. Das konfigurierte Schrittlimit
begrenzt diese Transportwiederholungen nicht; der Bridge-Timeout begrenzt die
gesamte Lebensdauer des eigenen Prozesses. Cloudprofile besitzen dadurch keinen
festen Kostenrahmen. Der hier aktivierte dedizierte lokale Ollama-Alias verwendet
kein Cloudmodell. [Native V1-Retry-Implementierung](https://github.com/anomalyco/opencode/blob/v1.4.4/packages/opencode/src/session/retry.ts).

Ausgabetext und gespeicherte Terminalausgabe sind jeweils auf 64 KiB begrenzt;
die Terminalverwaltung begrenzt zusätzlich einzelne Protokollzeilen und beendet
den eigenen Prozess bei Zeitlimit oder Abbruch. Providerfehler und rohe
stderr-Ausgabe werden nicht als Ergebnisnachweise gespeichert.

## Kosten, Anmeldung und Nachweis

Die installierte CLI allein ist kein Beleg für ein nutzbares Modellkonto oder
kostenlose Modellaufrufe. OpenCode kann verschiedene Cloudanbieter und lokale
Modelle verwenden; ein Cloudkonto, API-Key oder Abonnement kann Kosten
verursachen. Für diesen Adapter muss ein gewähltes Modell mit dem gezielt
übergebenen Zugang nutzbar sein. Native Browseranmeldung und gespeicherte
OpenCode-Zugänge werden in diesem isolierten Profil absichtlich nicht kopiert.
Es wird kein neues Abonnement gebucht und kein kostenpflichtiger Provider als
kostenlos bezeichnet. Eine mögliche kostenlose Modell-ID muss beim Zeitpunkt
der konkreten Abnahme erneut geprüft werden.

Gezielte synthetische Tests prüfen Endeventpflicht, Providerfehler ohne
Fehlertextweitergabe, Exitcodes, Sessionwechsel, Ausgabebegrenzung, minimale
Umgebung, Toolverweigerung, managed-Konflikt, Prozessbereinigung bei Timeout
und Löschung des nur für diesen Aufruf angelegten temporären Zustands. Eine
solche Prüfung ist kein echter Cloudmodell-Aufruf. Den tatsächlich erfolgten
Live-Nachweis führt der Integrationsbericht getrennt auf.

Am 19.10.2026 bestanden 25 gezielte Adaptertests. Zusätzlich bestätigten die
installierte CLI 1.4.4 und ihre nativen Befehle `debug config` bzw.
`debug agent kirabridge` mit Exitcode 0 den isolierten Agenten und seine
Konfiguration. Der lokale Profilcheck bestätigte den enthaltenen
OpenAI-kompatiblen Provider, Loopback-Endpunkt, die Tokenlimits, deaktivierte
Modelltools, `permission = {"*":"deny"}` und null externe Plugins. Dabei wurde
kein Modellaufruf ausgelöst; dies ist ausdrücklich ein Konfigurationsnachweis.

## Offizielle Quellen

- [CLI und JSON-Ausgabe](https://opencode.ai/docs/cli/)
- [V1-Berechtigungen](https://opencode.ai/docs/permissions/)
- [Konfigurationsquellen und Prioritäten](https://opencode.ai/docs/config/)
- [Anbieter und native Zugangsdaten](https://opencode.ai/docs/providers/)
- [Ollama OpenAI-Kompatibilität und feste Kontextgröße](https://docs.ollama.com/api/openai-compatibility)
- [V1.4.4 run.ts: tatsächlicher stdin-/JSONL-Vertrag](https://github.com/anomalyco/opencode/blob/v1.4.4/packages/opencode/src/cli/cmd/run.ts)
- [V1.4.4 Konfigurationsinitialisierung](https://github.com/anomalyco/opencode/blob/v1.4.4/packages/opencode/src/config/config.ts)
- [V1.4.4 globale XDG-Pfade](https://github.com/anomalyco/opencode/blob/v1.4.4/packages/opencode/src/global/index.ts)
- [V1.4.4 Plugininitialisierung](https://github.com/anomalyco/opencode/blob/v1.4.4/packages/opencode/src/plugin/index.ts)
