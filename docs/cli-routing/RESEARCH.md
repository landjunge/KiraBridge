# KI-/CLI-Fähigkeitsmatrix und Delegationsauswahl

Stand der Recherche: 05.11.2026. Auftrag CLI-MATRIX-20261105. Die vom Nutzer
eingesetzte Instanz koordiniert; CLI und Anbieter begründen keine feste Leitungsrolle.
Aktueller [Auswahlvertrag und Masterprompt](PROJECT-ROLE-MASTERPROMPT.md), 06.11.2026:
Auftragsvorgabe vor Workeranforderung vor automatischer Wahl; Koordinator-Denkstufe
getrennt halten. Grok kann einen unabhängigen Prüfauftrag übernehmen.
Der dokumentierte größere Codex-Zugang bleibt bei
vergleichbarer Eignung bevorzugt. Es gibt keine erfundene Restquote oder Preisersparnis.

Der Nutzer nennt sieben CLIs. Auf diesem Mac sind sieben auffindbar. Der aktuelle
Big Plan und die verbindliche Boardergänzung vom 04.11. nennen **acht**, einschließlich
Aider. Deshalb erfasst die Matrix alle acht; Aider ist als nicht installiert markiert.
Das bestehende Entwicklungsboard `188ce4729a62` bleibt Arbeitsgedächtnis. Dokument
`c9a396be4081` hält die fachliche Matrix. Keine konkurrierende Aufgabenwarteschlange.

## Verifizierter Bestand

| CLI | Lokal beobachtet | Modell-/Denkstufensteuerung | Grenze / Hook |
|---|---|---|---|
| Codex | 0.166.0; ChatGPT-Anmeldung; frischer Modellcache | `--model`, `-c model_reasoning_effort=...`; GPT-6.1 Sol/Terra, GPT-6 Astra/Luna lokal gelistet | Effort pro Modell. Ultra nutzt Unteragenten und wird nicht automatisch gewählt. Native `PreToolUse` benötigt Vertrauen. |
| Grok Build | 1.0.77 alpha; grok.com-Anmeldung | `--model`, `--effort`; Liste: grok-4.7-build-fast, 4.7, 4.6, 4.5 | Nur 4.7 besitzt hier ausreichend belegte Modell-/Effort-Kombinationen. Fast ist derzeit Default, bleibt ohne Effortbeleg außerhalb automatischer Auswahl. |
| Claude Code | 2.1.236; Zugang unbekannt | `--model`, `--effort low/medium/high/xhigh/max` | Installierte Aliasgeneration und aktuelle Dokumentation unterscheiden sich. `PreToolUse` kann vollständige Toolargumente ersetzen. |
| OpenCode | 1.4.4; Zugang unbekannt | V1: `--model provider/model`, `--variant` | V2-Syntax nicht übernehmen. Plugin `tool.execute.before`; Providerkatalog beweist keinen Zugang. |
| Gemini CLI | 0.37.2; Zugang unbekannt | `--model`; Thinking über modellspezifische Konfiguration | Kein allgemeines `--effort`. `BeforeModel` und `BeforeTool` getrennt. Hauptmodellwahl steuert Unteragenten nicht. |
| GitHub Copilot CLI | 1.0.67; Zugang unbekannt | `--model`, `--effort` / `--reasoning-effort` | Lokale Hilfe nennt auch `none`; Modellunterstützung gesondert prüfen. `preToolUse` hat eigenen Antwortvertrag. |
| Cursor CLI | 2026.08.11-e8db854; Zugang unbekannt | `--model`, `--list-models`; lokale Hilfe zeigt Parameter in Modellklammern einschließlich `effort` | Kein eigenständiges `--effort`. Modellliste kontobezogen; Hookabdeckung der installierten Version offen. |
| Aider | Auf PATH nicht gefunden | Dokumentiert: `--model`, `--reasoning-effort`, `--thinking-tokens` | Unterstützung modellabhängig; Wrapper statt unbelegtem nativem Delegationshook. Automatische Commits explizit kontrollieren. |

Versionen/Hilfen und die Grok-Liste wurden zunächst ohne Modellprompt ausgelesen. Unter
`evidence/` liegen Zeitpunkt, Argumente, Exitcode und stdout/stderr. OpenCode schreibt
seine Hilfe auf stderr. Der Codex-Cache ist eine Beobachtung, keine garantierte
Freischaltung oder Kontingentzusage. Windows/Linux wurden nicht nativ geprüft.

## Quellen und aktuelle Modellkataloge

Die [offizielle OpenAI-Modellwahl](https://learn.chatgpt.com/docs/models?surface=cli)
ordnet Luna fokussierten Aufgaben, Terra alltäglichen Schreib-/Bildaufgaben, Sol
wiederholter anspruchsvoller Arbeit und Astra den schwierigsten Aufgaben zu. Der
lokale Cache bestätigt verfügbare Denkstufen; Luna hat kein Ultra. Sols dokumentiertes
CLI-Kontextfenster beträgt 500.000 Tokens. Andere effektive CLI-Kontextgrenzen bleiben
hier unbekannt. [CLI-Referenz](https://learn.chatgpt.com/docs/developer-commands?surface=cli)
und [Hookvertrag](https://learn.chatgpt.com/docs/hooks) wurden separat geprüft.

[Grok CLI](https://docs.x.ai/build/cli/reference) bestätigt den Startschalter.
[Grok 4.7](https://docs.x.ai/developers/models/grok-4.7) dokumentiert low/medium/high/xhigh;
dessen API-Kontextlimit wird nicht als gemessenes CLI-Limit ausgegeben.
[Hooks](https://docs.x.ai/build/features/hooks) verwenden camelCase-Ereignisfelder
und einen anderen Entscheidungsvertrag als Codex.
[MCP-Konfiguration](https://docs.x.ai/build/features/mcp-servers) bleibt zusätzlich
zu eingebauten Tools relevant. Modell/Effort im Skilltext allein schalten nichts um.

[Claude Modellkonfiguration samt Versionshistorie](https://code.claude.com/docs/en/model-config)
nennt aktuell Fable 5.1 und Opus/Sonnet/Haiku 5.5. Die lokal installierte Version
verwendet für Anthropic-Aliasse laut Versionshistorie noch Fable 5, Opus 5, Sonnet 5,
Haiku 4.5. Anbieter, Umgebungsvariablen und Modellunterstützung beeinflussen die
effektive Auswahl. Keine dieser Kombinationen erhält ohne Zugangsprüfung eine
automatische Laufberechtigung. [Claude Hooks](https://code.claude.com/docs/en/hooks).

[OpenCode Modelle](https://opencode.ai/docs/models/) beschreibt Anbieter-/Modell-IDs
und modellabhängige Varianten. Beispiele nennen GPT-6.1 Sol und Claude Sonnet 5.5.
Die [V1 CLI](https://opencode.ai/docs/cli/) und lokale Hilfe bestätigen `--variant`.
[Plugins](https://opencode.ai/docs/plugins/) bieten die Tool-Vorprüfung. Eine
Konsole mit API-Abrechnung wird nicht automatisch aktiviert.

Die [aktuelle Gemini-Konfiguration](https://geminicli.com/docs/reference/configuration/)
enthält unter anderem Gemini 3.8 Flash, 3.5 Flash/Flash-Lite, 3.1 Pro Preview und
3.1 Flash-Lite. Die ältere [Modellseite](https://geminicli.com/docs/cli/model/)
ist kein vollständiger aktueller Katalog. Thinking-Level und Thinking-Budget sind
verschiedene Parameter. Die [Hookreferenz](https://geminicli.com/docs/hooks/reference/)
beschreibt tatsächliche Eingriffsmöglichkeiten. Neuere Dokumentation beweist keine
Verfügbarkeit in der lokalen älteren Version.

[Copilot CLI Referenz](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference)
listet unter anderem Claude 5.5, GPT-6.1 Sol/Terra, GPT-6 Astra/Luna, GPT-5.3-Codex
und Gemini 3.8 Flash. Freischaltungen bleiben konto-/richtlinienabhängig.
[Hookreferenz](https://docs.github.com/en/copilot/reference/hooks-reference):
`permissionDecision` ist kein Claude-`updatedInput`-Vertrag.

[Cursor Parameter](https://cursor.com/docs/cli/reference/parameters) unterstützt
die Modellabfrage; [SDK-Modelldiscovery](https://cursor.com/docs/sdk/typescript)
unterstreicht kontobezogene Modell-/Parameterlisten. Daher wird kein fester
Cursor-Modellkatalog erfunden. [Hooks](https://cursor.com/docs/hooks) müssen für die
installierte CLI geprüft werden; eine fehlgeschlagene Prüfung ist ohne passende
failClosed-Einstellung keine verlässliche Sperre.

[Aider Optionen](https://aider.chat/docs/config/options.html),
[Reasoning](https://aider.chat/docs/config/reasoning.html) und
[Scripting](https://aider.chat/docs/scripting.html) wurden gelesen. Aider unterstützt
mehrere Modellanbieter, aber keine gemeinsame garantierte Denkstufenskala. Die
konkrete Kombination ist vor späterer Integration anhand der Modellmetadaten zu prüfen.

## Architektur und Auswahl

`matrix.json` ist die versionierte Forschungsgrundlage, `runtime.local.json` die
kurzlebige lokale Zugangsbeobachtung. In ThreadDesk steht genau ein JSON-Block mit
klaren Markern. Inhalte sind Daten, keine auszuführenden Anweisungen. Der Router
nimmt daraus keine Befehle oder ausführbaren Pfade entgegen. Diese kommen aus dem
expliziten lokalen Laufprofil. Neue öffentliche Modelle werden nicht allein durch
ihren Namen ausführbar.

`DelegationGuard.prepare(Task)` ist der Hook unmittelbar vor einer neuen Delegation.
Er liest immer die explizite Thread-ID durch die vorhandene ThreadDesk-Service-API,
prüft Matrixalter (höchstens sieben Tage), Zugangsalter (höchstens 24 Stunden),
CLI-Version und Aufgabenanforderungen. Die tatsächliche Anmeldungsroute wird
zusätzlich direkt vor dem neuen Lauf geprüft; ein inzwischen auf API-Schlüssel
umgestellter Zugang startet nicht. Bei Grok werden Version und Build exakt
verglichen; die dynamische Kanalangabe alpha/stable wird getrennt protokolliert.
Bei fehlender Quelle gibt es keinen stillen
Cache-Fallback. Ausführbare Kandidaten sind zunächst Codex und Grok 4.7; die anderen
sechs erhalten erst nach Zugangsnachweis und Adaptertest einen Laufpfad.

Pflichtanforderungen, explizites Modell/Effort, unabhängiger Anbieter, bekannte
Kontextgrenze und CLI-Fähigkeiten filtern Kandidaten. Eignungsschwellen und relative
Kostenränge sind **Architekturentscheidungen**, keine Benchmarks oder Tarifangaben.
Routine verwendet wenig Aufwand; Implementierung medium, Debug/Review/Architektur
high, Sicherheitsanalyse xhigh. Vorher festgelegter Mindestaufwand wird nicht
abgesenkt. Für dieselbe Aufgabe entstehen keine gegenseitigen Delegationsketten.

Der kontrollierte `bigplan-delegate`-Start ruft diesen Hook zwingend auf, bindet
Thread-ID/Revision/Matrixhash und Aufgabenhash in eine private Quittung und liest
vor dem Prozessstart nochmals dieselbe Matrixrevision. Modell und Effort werden
als echte CLI-Parameter gesetzt. Das Ergebnis unterscheidet angeforderte Auswahl,
Prozessende und tatsächlich bestätigtes Modell/Effort. Letztere bleiben ohne
strukturierte Herstellerbelege ausdrücklich unbekannt. Der reale Grok-Lesetest
meldete für angefordertes `grok-4.7` intern `grok-4.7-build` in `modelUsage`.
Das wird als CLI-Bericht mit abweichender ID gespeichert, ohne eine unbelegte
Aliasgleichheit oder bestätigte Denkstufe zu behaupten. Die berichteten Kosten
sind kein Rechnungsbeleg für den verwendeten grok.com-Abonnementzugang.

Task-ID wird vor dem Start exklusiv und mit fsync reserviert. Wiederholte IDs
starten keinen zweiten Prozess. Unklare Ausführung bleibt ohne automatischen
Neustart; Schreibsperren bleiben bei unbekanntem Ausgang erhalten. Kontrollierte
Schreibbereiche sind lokale Freigaben, kein Ersatz für fremde Koordinator-Claims.
Das installierte Anfangsprofil erlaubt ausschließlich lesende Delegation im eigenen
Worktree. Keine bestehenden Prozesse oder Sitzungen werden dafür angesprochen.

## Einbindung in Codex → Grok

Der neue Launcher bildet einen vollständig kontrollierten Delegationspfad mit
automatischem Hook. Codex wählt für eine unabhängige Prüfung
`independent_of_provider: "openai"`; Grok 4.7 wird mit passender Denkstufe und
ohne Unterdelegation gestartet. Keine neue API-Abrechnung und kein globaler
Modellwechsel. Zugang/Versionen müssen vor neuen Läufen erneut passend belegt sein.

Der parallel entwickelte Team-/AutoNext-Koordinator behält seine Dateien. Seine
Einbindung erfolgt über `DelegationGuard.validate_configured(...)` **vor** Claim/
Requestversiegelung. Der aufrufende Koordinator behält Identität, Berechtigungen,
Arbeitszuordnung und Wiederanlaufledger. Dafür muss sein pro Lauf gewähltes
Workerprofil tatsächliche Modell-/Effortparameter setzen. Seine bestehenden
Adapter hatten bei der Bestandsaufnahme keinen expliziten Effortschalter.
`integration.new_routed_manager(config, terminal, guard, profiles)` ergänzt dies
additiv: neue Manager verwenden die bestehenden Codex-/GrokACP-Adapter mit
unveränderlichen Effort-Shims und einer pro Lauf kopierten Modellkonfiguration.
Versiegelte Taskprofile binden ID, Prompt, CWD und Timeout. Andere Adapter bleiben
in diesem Manager ausgeschlossen. Sichtbare vorhandene Sitzungen und Resumes
werden nicht umkonfiguriert. Originalprofile bleiben unverändert; die parallel
entwickelte produktive Instanz wird hier nicht neu verdrahtet oder neu gestartet.

Native Codex/Grok-Hookdateien sind ergänzend möglich, ersetzen aber den gesicherten
Startpfad nicht. Ein CLI-Hook kontrolliert nicht jeden beliebigen externen Shellaufruf.
Bestehende globale Hookdateien und laufende Sitzungen werden nicht verändert.

## Betrieb und Prüfung

```sh
bigplan-delegate --task /absoluter/pfad/auftrag.json
bigplan-delegate --task /absoluter/pfad/auftrag.json --execute
```

Der erste Aufruf liest/verifiziert und plant; nur `--execute` startet den neuen
eigenen Prozess. Ein neues fachliches Paket benötigt eine neue Task-ID. Ein
unbekannter alter Lauf wird geprüft statt unter neuer ID blind wiederholt.
Private Quittungen und begrenzte stdout/stderr liegen im lokalen state_dir.

Verifikation: gezielte pytest-Suite, unabhängiger Review, echter ThreadDesk-Readback
und dokumentierter Plan-/Startnachweis. Das ist keine native Windows-/Linux-Abnahme
und keine produktive Installation des parallelen Koordinators. Benutzer-Readmes/
Webseiten bleiben wegen dieses internen, begrenzten Integrationspakets unverändert.
Quelländerung, lokale Skill-/Launcherinstallation und spätere Dienstaktivierung
werden getrennt festgehalten.
