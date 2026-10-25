# Discovery and visible terminal / Werkzeugerkennung und sichtbares Terminal

RC17 source; raw production configuration and permissions remain unchanged.

## Deutsch

`bridge_health`, `operation_catalog` und `agent_inventory` liefern einen principal-
bezogenen Versions-/Instanz-/Rechte-/Beobachtungs-Fingerabdruck. Bei erlaubtem
automatischem Lesezugriff beobachten `operation_catalog`, `agent_inventory` und
`bridge_health(observe_terminals=true)` die Terminalzuordnung frisch. Normales
`bridge_health` ist leichtgewichtig: keine Terminalabfrage und keine belegten
Terminal-Leseplätze durch sekündliche Proxy-Monitore. `terminal_observation.freshness`
kennzeichnet `cached`/`not_probed`, mit ursprünglichem `observed_at`; nach
Rechteänderungen werden alte Beobachtungen verworfen. Health ist niemals
Eingabebereitschaft. Frische Fensterwechsel-Revisionen entstehen durch ausdrückliche
Beobachtung, nicht durch passive Health-Polls. Verweigerung wird weiterhin als
`approval_required`/`not_authorized` gemeldet, kein erfundener Ausführungsbeleg.
Installierter Agent, ausführbare Datei, Adapter, beobachtete Sitzung und tatsächliche
Eingabebereitschaft sind getrennte Zustände. Eine erfolgreiche Ausführung ist erst
durch den konkreten Taskbeleg nachgewiesen.

MCP-Initialisierung meldet KiraBridge-Version statt SDK-Version. `tools/list` ist
nebenwirkungsfrei. Der stdio-Daemonproxy prüft den aktuellen Katalog vor Weiterleitung,
beobachtet Health/Katalog und sendet `notifications/tools/list_changed` bei Änderungen.
Clients müssen bei Neuverbindung neu initialisieren/listen. Der zustandslose HTTP-
Endpunkt verspricht keine unaufgeforderten Push-Nachrichten; Health/Katalog ausdrücklich
neu abfragen. Provider-Toollisten werden paginiert und begrenzt aktualisiert. Ein
abgebrochener MCP-Schreibaufruf wird nie automatisch wiederholt.

Direkte ChatGPT-Steuerung (`terminal.execute`, `terminal_control`, ggf. autorisiertes
`admin.execute`) läuft im bestätigten sichtbaren nativen Shellfenster. Bestehendes
geeignetes freies Fenster zuerst verwenden; sonst separates Fenster erzeugen.
Vor Eingabe Fenster/Tab, TTY, aktueller Benutzerprozess, PID-Startzeit, Shell und
leerer Prompt erneut prüfen. Root-eigener `login` ist kein Benutzer-Shell-PID; ein
alter Handle wird nur bei frisch nachgewiesener tatsächlicher Abstammung akzeptiert.
Geänderte, beschäftigte, mit Eingabe gefüllte oder fremde Fenster bleiben unberührt.
Bei unklarem Ergebnis nicht erneut senden. Timeout beendet keinen fremden Prozess.

Bekannter Principal `chatgpt` oder ausdrücklich konfiguriertes `client_type="chatgpt"`
aktiviert die Regel; die Rolle ist keine vom Toolaufruf frei wählbare Behauptung.
Neue Konfigurationsfelder benötigen einen kompatiblen Parser beim Downgrade.
Interne Codex-/Grok-Ausführung ist davon getrennt; ThreadDesk bleibt eigener Zugang.
`session.open` benötigt weiterhin Öffnungs-/Ausführungsrechte. Bereits akzeptierte
exakte Tasks ersetzen keinen noch offenen manuellen Genehmigungsschritt, benötigen
aber kein unmögliches zweites UI-Token. Explizite alte Fenster-Tokens bleiben einmalig
und zeitlich gebunden. Stale Targets und abgelaufene Grants werden weiter abgelehnt.

Terminal.app-Automation/Accessibility und angemeldete GUI-Sitzung sind echte Laufzeit-
voraussetzungen, keine aus Policy-Grants ableitbaren Betriebssystemrechte. Fehlende
OS-Rechte werden gemeldet und hier nicht automatisch verändert. Ein privilegierter
Befehl darf nur in derselben bestätigten sichtbaren TTY sudo verwenden; keine
Passwortaufnahme/Weitergabe. launchd läuft weiterhin unabhängig von Fenstern.

## English

Discovery separates configured grants, current observations and actual execution.
Read tools refresh permitted native observations; tools/list remains side-effect free.
The stdio proxy refreshes catalogs and emits list-changed notifications; stateless
HTTP clients explicitly refresh health/catalog after reconnection or session changes.
Only confirmed task evidence proves execution; unavailable OS permissions are not
silently granted. Lost writes are reconciled rather than replayed.

ChatGPT direct commands reuse a freshly verified idle visible native shell or create
a separate visible window. Window/TTY/current-user PID/start identity and empty prompt
are checked before typing; busy or changed targets are preserved. This does not govern
Codex/Grok internal execution. ThreadDesk remains independent. Exact accepted tasks
and automatic permissions agree without bypassing manual approval/replay checks.
Real Intel tests and remaining gates: [acceptance](ACCEPTANCE-MACOS-RC16.md).


## RC17 polling correction / Korrektur der Statusabfragen

**English:** Routine `bridge_health` is passive for terminal discovery; current
runtime/version/grants remain live. Set `observe_terminals=true`, or call
`operation_catalog`/`agent_inventory`, for a fresh bounded terminal observation.
Cached observations retain their original timestamp, are never input proof, and
are discarded when permissions change. This prevents each one-second stdio
health monitor from saturating the shared foreground read slots. Automatic health
polling alone no longer discovers window changes. Explicit `session_catalog` and
`session_read` remain fresh, and every input independently rechecks its target.

**ChatGPT cache / ChatGPT-Cache:** Some Apps schemas still require the obsolete
`completion_subscription`. Actual RC17 submission requires no Events subscription;
existing cached tools work with the historical field set to the empty string.
Use stable task/idempotency IDs and `task_get`, never replay uncertain writes.
Refresh the host connector metadata when available; KiraBridge cannot overwrite
already injected tool declarations. / Manche Apps-Schemas verlangen noch das alte
Feld. Leere Zeichenkette ist abwärtskompatibel; keinen neuen Events-Kanal erfinden,
keine zusätzlichen Rechte vergeben und unsichere Aufträge nicht wiederholen.
