# Qwen Code über ACP und KiraBridge-MCP / Qwen Code via ACP and KiraBridge MCP

Stand / checked version: **Qwen Code 0.27.2**, 12.11.2026. Quellintegration;
keine automatische Installation oder Änderung bestehender Anmeldungen.

## Betreiberprofil / Operator profile

Qwen muss bereits installiert und beim ausdrücklich ausgewählten Anbieter angemeldet
sein. Das folgende Profil verwendet den hier tatsächlich geprüften vorhandenen
Zugang. Pfade und Budgets sind Beispiele für einen freigegebenen Arbeitsauftrag.
Andere bereits eingerichtete Qwen-Anbieter können über `qwen_auth_type` gewählt
werden; eine Integration legt weder Konten an noch wechselt sie automatisch.

Qwen must already be installed and authenticated with the explicitly selected
provider. This example uses the existing subscription tested here. Paths and
budgets must match the authorized task. Other supported Qwen authentication types
remain explicit operator choices; there is no provider fallback or login action.

```toml
[agents.qwen]
kind = "qwen_acp"
executable = "/ABSOLUTE/PATH/TO/qwen"
model = "qwen4.0-max-preview"
qwen_auth_type = "qwen-subscription"
qwen_reasoning_effort = "xhigh"
bridge_tools = true
allow_local_tools = false
sandbox_mode = "read-only"
qwen_mcp_tools = ["td_get_thread", "read_query", "task_request", "task_get", "task_events"]
qwen_mcp_operations = ["file.read", "file.list"]
qwen_mcp_read_roots = ["/ABSOLUTE/AUTHORIZED/SOURCE"]
qwen_max_timeout = 1800
qwen_max_session_turns = 256
qwen_max_tool_calls = 512
```

Im **bestehenden** `[principals.<owner>]` muss `qwen` als Agent zugelassen sein.
Erforderlich sind `agent.execute`, `bridge.health`, `task.read` sowie die schon
freigegebenen Fachrechte, etwa `threaddesk.read` oder `file.read`/`file.list`.
Quellpfade müssen zusätzlich innerhalb dessen `roots`/`read_roots` liegen.
Keinen neuen globalen Qwen-Principal und keine pauschalen Rechte daraus ableiten.

The existing task owner must already allow agent `qwen`, execution, health and task
inspection, and the domain capabilities actually needed. Source paths must also
fit that principal's existing roots. This profile grants no new principal rights.

## Aufgaben- und Koordinatoranbindung / Task and coordinator binding

`AgentManager` registriert `qwen_acp`. Der vorhandene Team-Dispatcher versiegelt
`local_tools`, `mcp_grants`, `mcp_operations` und `mcp_read_roots` aus dem
Operatorprofil zusammen mit dem Auftrag. Modellgenerierte Teamantworten können
diese Rechte nicht setzen. Ein Worker kann beispielsweise so konfiguriert werden:

```toml
[team.workers.qwen_worker]
agent = "qwen"
cwd = "/ABSOLUTE/AUTHORIZED/WORKDIR"
timeout = 1800
execution_scope = "separate_managed_session"
mcp_operations = ["file.read", "file.list"]
mcp_read_roots = ["/ABSOLUTE/AUTHORIZED/SOURCE"]

[[team.workers.qwen_worker.mcp_grants]]
tool = "td_get_thread"
calls = 1
[team.workers.qwen_worker.mcp_grants.arguments]
id = "EXACT_AUTHORIZED_THREAD_ID"
max_chars = 100000
offset = 0
```

Für weitere Notizfenster werden weitere exakte Grants mit dem jeweiligen Offset
angegeben. `td_get_thread` ist der bestehende direkte Read und benötigt weder
`version`/`workspace_id` noch die zweite Command-Result-Pagination. Bei
`td_command_query` bleibt `version` dagegen die **JSON-Zahl 1**. Das angebotene
Schema ergänzt lediglich fehlende Scalar-Const-Typmetadaten; Argumente werden
nicht umgeschrieben. Ein String `"1"` bleibt ungültig.

For additional note windows, grant the exact additional offsets. The existing
direct `td_get_thread` read avoids command-result pagination. Native command
queries retain their typed envelopes, including numeric `version: 1`.

Große native Command-Resultate dürfen nur anhand eines tatsächlich beobachteten,
erfolgreichen Readresultats fortgesetzt werden: gleiche Basisargumente, Workspace,
Command und Katalogrevision, beobachteter Digest und exakt nächster Resultatoffset.
Diese Fortsetzung verbraucht das Aufrufbudget und prüft erneut die aktive
Core-Aufgabe. Dasselbe gilt für den tatsächlich zurückgegebenen `next_offset`
direkter `td_get_thread`-Notizfenster. Der vorhandene Core-Read `whiteboard_read`
liest Beitragsindizes und einzelne Beiträge; leere Notes beweisen kein leeres
Whiteboard. Nach einem genehmigten Indexread sind nur die dort tatsächlich
beobachteten Entry-IDs desselben Boards jeweils einmal lesbar. Eine erneute
Indexfreigabe bleibt ein eigener gezählter Aufruf. Fremde Digests, übersprungene Seiten und Schreiboperationen bekommen
dadurch keine Freigabe.

Large native read results may continue only at the observed next page, bound to
the same exact base request and returned digest. Every page consumes call budget
and revalidates the active Core task. This mechanism cannot grant writes.

`read_query` verwendet den vorhandenen direkten Datei-Leseweg innerhalb der
Auftragsroots; `task_request` darf nur konfigurierte Operationen mit dem aktuellen
Coreauftrag als `parent_id` anfordern. Nur dessen eigene Child-Ergebnisse sind
über `task_get`/`task_events` zugänglich. Jeder MCP-Effekt läuft durch die bestehende
Daemon-Berechtigungsprüfung und die zusätzliche Auftragsrestriktion.

Native coordinator routing recognizes `qwen_acp`. A sealed Qwen routing decision
passes the selected model and reasoning effort directly to the adapter; it does
not invent an effort CLI flag. The verified managed routing path currently
requires the existing `qwen-subscription` selection. Direct adapter profiles can
select the other supported Qwen authentication types without a routing fallback.

## Werkzeugrechte und Grenzen / Tool permissions and limits

Der Adapter startet `--acp --bare --safe-mode` und schließt die in Bare registrierten
nativen Shell-/Datei-/Goal-/Exec-Tools explizit aus. In 0.27.2 bleiben ausdrücklich
über `session/new` bzw. `session/load` übergebene MCP-Server trotz Safe Mode verfügbar.
Der Adapter wartet auf native MCP-Bereitschaft und den tatsächlichen Werkzeugkatalog,
bevor er den Prompt sendet. Implizite Projekt-MCPs, Hooks und Skills werden nicht
als Auftragsrechte übernommen. MCP-Turns verwenden `default`/Ask, reine Textturns
`plan`. Die ACP-Permissionantwort ist sitzungsgebundenes `allow_once` für ein
konfiguriertes MCP-Werkzeug; die genaue Argumentfreigabe erfolgt **einmal im Proxy
vor dem Effekt**, zusätzlich zur normalen Serverprüfung.

The scoped MCP server uses the existing `kirabridge connect` transport. Its
owner-only temporary policy contains no token. Existing credentials stay on the
standard connect path, outside prompts and process arguments. No parallel server
protocol, queue or permission store is introduced.

Für ausdrücklich freigegebene Coding-/Schreibaufträge müssen Operatorprofil und
AgentInput `local_tools` erlauben, das Profil `allow_local_tools = true` und einen
passenden `sandbox_mode` besitzen; zusätzlich ist die vorhandene Principal-
Berechtigung `agent.local_tools` erforderlich. **Auch dann bleiben Qwens native
Datei-/Shelltools ausgeschaltet**: Änderungen erfolgen über die konkret erlaubten
KiraBridge-MCP-Operationen. `danger-full-access` erfordert zusätzlich bestehende
explizite volle Principalrechte. Eine Integration ist keine Vollmachterteilung.

Explicit coding profiles can use their existing granted MCP operations and exact
mutation grants. Native Qwen filesystem and shell tools remain disabled. Task
scope is a permission boundary at the MCP interface, **not an OS sandbox or
protection from other processes running as the same user**.

Aufruf-/Einmalgrantzähler gelten pro Proxyverbindung, nicht global für ein ganzes
Subagententeam. Mehrere Verbindungen erhalten kein erfundenes gemeinsames Budget.
Mutationen brauchen stabile native Idempotenzschlüssel und aktuelle Revisionen;
teamweite Zusagen müssen die vorhandenen Core-/Teamverträge nutzen.

Timeout kommt aus dem validierten AgentInput; oberhalb des konfigurierten
`qwen_max_timeout` wird vor dem Start abgelehnt. Obergrenzen sind 3600 Sekunden,
2048 Sessionturns und 4096 Toolcalls. Defaults sind 300 Sekunden, 48 Turns und
32 Calls; umfangreiche Fachaufträge benötigen ein entsprechend konfiguriertes
Operatorprofil. Die engen Markerlimits sind kein Produktivlimit. Diese Grenzen
sind keine Preisgarantie oder automatische Änderung eines Anbietertarifs.
Ein Task kann bis zu 256 exakte Grants enthalten; die private serialisierte
Policy bleibt auf 65536 Zeichen begrenzt und wird vor Prozessstart geprüft.
Beobachtete Read-Fortsetzungen und deklarierte Dateioperationen vermeiden große
Listen einzeln vorab erratener Requests. Große native Toolausgaben können vom SDK
elidiert werden; nötigenfalls kleinere sichtbare Fenster lesen und Sichtlücken
benennen. Qwen-Felder werden bei anderen Agentarten nicht serialisiert, damit
bestehende Core-/AutoNext-Konfigurationsfingerprints erhalten bleiben.

## Sitzungen und Ergebnisbelege / Sessions and evidence

ACP `initialize`, Sitzungsidentität, CWD, Owner und Task bleiben gebunden.
`session/new` bietet die Modelloptionen an; eine angeforderte Denkstufe wird über
`session/set_config_option` gesetzt und nativ zurückgelesen. Hier bot das gewählte
Modell `none`, `low`, `medium`, `xhigh`; `xhigh` wurde bestätigt. Fehlende Optionen
werden abgewiesen. Angefordertes Modell und zurückgelesene Sessionmetadaten sind
keine unabhängige Backendmodell-Attestierung.

Received, started, `end_turn` and project acceptance are separate states. Results
record native stop reason and task/session/CWD binding, with
`project_completion_verified = false`. Thought content is never part of the
returned answer. Timeout, disconnect or missing final stop preserves the bounded
non-thought text as an explicitly unconfirmed observation, never a completed
result. Cleanup failure preserves the already observed native result
or original exception while retaining an unconfirmed outcome.

Normale **IDLE-Folgearbeit** derselben Team-/Workerbindung setzt die Qwen-Sitzung
über den bestehenden Core-/Team-Sitzungsspeicher fort. Vor dem Load werden der
versiegelte neue Request, Owner, Agent, CWD, exklusives Work-Lease, Clear-Generation
und das gespeicherte Modell-/Auth-/Effortprofil erneut geprüft. Der Adapter prüft
diesen Beleg vor Spawn, Load und Prompt; jeder neue Turn erhält eine frische
MCP-Policy mit seiner eigenen Task-ID und seinem Argumenthash. Der Proxy prüft bei
normalem Resume zusätzlich vor jedem Toolcall das aktuelle Team-Lease. Ein Clear,
eine fremde Work-ID oder veraltete Generation entzieht damit den weiteren Zugriff.
Aktive und UNKNOWN-Slots werden nicht automatisch wiederverwendet; ein beliebiger
`resume_session`-String ohne versiegelten Teambeleg bleibt gesperrt. Modellstart,
Sitzungszulassung und Abschluss sind getrennt: Ein echtes `session/load`-ACK stoppt
nur die bestehende Admission-Wache, es markiert weder Modellstart noch Abschluss.

Die separate explizite `QwenRecoveryBinding` bleibt für nachgewiesen eigene
historische Sitzungen verfügbar: Receipt und Transcript-Hash vor dem Load, genaue
Session/UID/CWD/Owner/Modell/Auth/Effort-/Handoffbindung und neuer gebundener
Coreauftrag. Native 0644-Transcripts benötigen eine intakte eigene Parentkette und
einen privaten Vorfahren; kein chmod. Nach dem geprüften Load darf die native
History wachsen. Historische UNKNOWN-Aufträge werden nicht als completed
umgeschrieben. Ein ausdrücklich belegter abgeschlossener eigener Turn kann bei
verlorenem privatem Store ebenfalls als historischer Continuation-Beleg dienen;
das ersetzt nicht den normalen exklusiven IDLE-Pfad.

Normal idle follow-ups use the existing exclusive sealed Team/Core session lease,
with renewed task scopes and generation checks. Explicit historical recovery is
separate. Neither path adopts arbitrary user session IDs or retries UNKNOWN
work. Native Qwen subagent/workflow execution is not enabled by this restricted
profile; a configured Core team alone is not proof of actual collaboration.

## Bisherige Prüfung / Evidence boundary

Fixtures prüfen ACP-Framing/Stop/Fehler, Sitzungsbindung, Toolverweigerung,
Budget-/Grant-/Pfadgrenzen, echte private HTTP+stdio-MCP-Verbindungen und erlaubte
Coding-Childaufträge mit unabhängiger Datei-Rückleseprüfung. Das sind keine
vorgegebenen Liveanbieter-Ergebnisse.

Die erste reale Markerprobe endete nativ, lieferte aber weder den Marker noch einen
MCP-Aufruf: **kein Marker-PASS**. Der erste Familienauftrag verlor das Ergebnis
beim Cleanup und bleibt historisch UNKNOWN; sein eigener finaler Entwurf wurde
aus nicht als Thought markierten Assistanttexten gerettet und ausdrücklich nicht
abgenommen. Die danach explizit fortgesetzte gleiche Qwen-Sitzung bestätigte
`xhigh`, führte zwei echte MCP-Fachzugriffe aus und endete sauber. Das war ein
technischer Teilerfolg, keine abgeschlossene Familienanalyse. Der folgende
Fortsetzungsturn hat den direkten Plan-Read mit `success: true`, Revision 29,
Offset 0 und `next_offset = 100000` belegt; daraus folgt noch keine vollständige
Lektüre aller 872980 Zeichen oder fachliche Abnahme. Anschließend haben drei echte
Qwen-Worker eigene Teillieferungen mit end_turn und bestätigtem Cleanup geliefert;
die ursprüngliche Hauptsitzung hat sie als expliziten Zwischenstand synthetisiert.
Die fachlichen Lücken bleiben erhalten. Ein Protokollfixture prüft zwei normale
versiegelte Teamturns einschließlich session/load, verworfenem History-Replay und
echten MCP-Aufrufen mit erneuerten Task-Scopes; es ist kein behaupteter
Liveanbieter-Codingpass. Reale Berichtswrites waren beim Quellencheckpoint noch
nicht abgenommen; ein Schreibprofil zeigte die nun gezielt korrigierte
session/load-Admission-Lücke, ohne empfangenen Append-Aufruf. Liveaktivierung und
endgültige Abnahme koordiniert der Parent nach den bestehenden Gates.

## Gepinnte Primärquellen / Pinned primary sources

- [Release 0.27.2](https://github.com/QwenLM/qwen-code/releases/tag/v0.27.2)
- [Source tag v0.27.2](https://github.com/QwenLM/qwen-code/tree/v0.27.2)
- [Pinned CLI config](https://github.com/QwenLM/qwen-code/blob/v0.27.2/packages/cli/src/config/config.ts)
- [Pinned ACP implementation](https://github.com/QwenLM/qwen-code/tree/v0.27.2/packages/cli/src/acp)
- [Current settings documentation](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/)
  is newer documentation, not proof of a capability in the pinned release.
