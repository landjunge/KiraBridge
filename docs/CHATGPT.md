# ChatGPT anbinden und einen Auftrag bestätigen / Connect and confirm one task

## Deutsch: den tatsächlichen Anschluss prüfen

Diese Anleitung beschreibt den lokalen Assistenten im Quellstand
`7af39cd97b58054d6e7333cd3430d00f4b46c3f4` (`0.6.0rc2`), keinen neu
veröffentlichten Download. Der dokumentierte Betreiber-Mac
mit `0.5.2`-Backports und das eingefrorene private RC2-Paket `57bee99` sind andere
Stände. Das alte Paket enthält die späteren Agenten-/Workflowfunktionen nicht und
akzeptiert nicht jede aktuelle Konfiguration. [Installation DE](INSTALL-DE.md),
[installation EN](INSTALL-EN.md) und [Releaseabnahme](RELEASE-ABNAHME-20261018.md)
unterscheiden die Pakete und den Updateweg. Bestehende gesunde Einrichtung nicht
für einen Nachweis erneut durchlaufen oder zurücksetzen.

Der normale Installer führt lokale Einrichtung und `kirabridge chatgpt setup`
zusammen. Bei einer bereits eingerichteten lokalen Bridge zeigen zunächst diese
Befehle den vorhandenen Zustand; sie legen keine neuen Aufträge an:

```sh
kirabridge status
kirabridge chatgpt status
```

Nur wenn die ChatGPT-Anbindung noch fehlt, den lokalen geführten Assistenten
verwenden. Sprache und globale Optionen sind echte CLI-Argumente:

```sh
kirabridge chatgpt setup --language de
# Andere bestehende Konfiguration: globale Optionen vor dem Unterbefehl
kirabridge --config /absolute/private/config.toml chatgpt status
```

Der Assistent führt zu den offiziellen Kontoseiten. Die nötige Konto-/Workspace-
Berechtigung und mögliche Kosten müssen im eigenen Zielkonto geklärt werden;
keine Verfügbarkeit für jede ChatGPT-Oberfläche oder iPhone-Sprachsitzung wird
behauptet. Er benötigt einen eingeschränkten **Tunnel-Runtime-Schlüssel**. Codex-
Login und gewöhnlicher API-Schlüssel ersetzen diesen nicht. Verdeckte Eingabe nur
im lokalen Terminal; keine Schlüssel in Chat, argv, Logs oder Screenshots.
Der Schlüssel liegt getrennt mit Modus0600, die Tunnelverwaltung erhält eine
`file:`-Referenz. Vorhandene Schlüssel/Policy bleiben erhalten; unvollständige
Einrichtung wird mit nächstem Prüfschritt gemeldet statt überschrieben.

Der Assistent übernimmt die bestehende lokale Policy für einen getrennten
`chatgpt`-Zugang; er erzeugt keine allgemeinen Zusatzrechte. Neue lokale Einrichtung
bleibt standardmäßig manuell. Ein bewusst automatisch freigegebenes Betreiberprofil
ist eine andere Vertrauensentscheidung. Laufende/wartende Aufträge und Empfängerjobs
werden vor einer erforderlichen Umstellung berücksichtigt. `kirabridge connect`
ist der MCP-Stdio-Proxy zum lokalen Dienst: keine Banner, interaktiven Eingaben oder
Diagnoselogs in dessen stdout einbauen. Der interaktive Assistent gehört ins lokale
Terminal, nicht in den MCP-Datenstrom.

### Ein erster harmloser Dateiabruf

Eine bereits vorhandene, ausdrücklich erlaubte kleine Projektdatei auswählen.
Die Beispielpfade müssen durch genau diesen Pfad ersetzt werden; nicht erst neue
Dateien/Konten anlegen oder Rechte pauschal erweitern. Vorprüfung des eingerichteten
ChatGPT-Principals, sofern dieser lokal tatsächlich so heißt:

```sh
kirabridge --principal chatgpt readiness --operation file.read --read-path /absolute/allowed/project/README.md
```

Anschließend **aus dem vorgesehenen Chat**, über dessen verbundene KiraBridge-App:

1. `bridge_health` aufrufen. Geladene Version und Freigabemodus beachten;
   der authentifizierte Principal steht in der verfügbaren Readiness-Antwort.
2. `bridge_readiness` mit diesen Parametern aufrufen. Readiness liest keinen
   Dateiinhalt und beweist noch keine Ausführung:

   ```json
   {
     "operations": ["file.read"],
     "read_paths": ["/absolute/allowed/project/README.md"]
   }
   ```

3. Nach erfolgreicher Vorprüfung einmal `task_request` aufrufen. Eine freie stabile
   Taskkennung wählen und für genau diese Anfrage beibehalten:

   ```json
   {
     "request": {
       "api_version": "1",
       "task_id": "first-project-read-1",
       "operation": "file.read",
       "arguments": {
         "path": "/absolute/allowed/project/README.md",
         "max_bytes": 4096
       },
       "idempotency_key": "first-project-read-1"
     }
   }
   ```

4. Nur bei `approval_required=true` die zurückgegebene `local_approval_url` lokal
   öffnen (`kirabridge approvals`) und genau diese Anfrage prüfen/freigeben.
   Bei false Ergebnis direkt abfragen; keine unnötige Freigabe verlangen.
5. `task_get` mit `{"task_id":"first-project-read-1"}` abfragen und tatsächlich
   erhaltenen Dateiinhalt/Status prüfen. Empfang, Freigabe und queued sind kein
   Abschlussnachweis. Fehler mit `task_diagnose` derselben Kennung untersuchen.

Bei Abbruch/409/Timeout dieselbe Kennung zuerst abfragen. Unklaren Schreib-/Agenten-
auftrag niemals durch einen neuen Task oder neue Idempotenzkennung wiederholen.
Eine Wiederverbindung ist keine Wiederholungsfreigabe. Der echte ChatGPT-Dateibeleg
`chatgpt-file-verification-20261018-1311` ist bereits bestanden (9117Bytes); ihn
nicht erneut ausführen. Er belegt seinen damaligen Pfad/Principal, keine beliebigen
Schreib-/Terminal-/Agentenrechte. [Bestehender Reparaturbeleg](REPAIR-PROJECT-ACCESS-20261018.md).

Ein älterer App-Katalog kann `bridge_readiness` und `task_diagnose` noch nicht
anbieten, obwohl der Dienst sie enthält. Dann die gezeigte lokale Readiness des
konkreten Principals verwenden. `task_get` enthält bei Fehlern bereits die
vorhandene Diagnose samt tatsächlichem Task-Preflight. Fehlende Toolnamen nicht
als Taskoperationen erfinden; keine Aufträge zur Katalogaktualisierung wiederholen.
Eine Aktualisierung des App-Katalogs ist vom laufenden Dienst getrennt.

### Für den nächsten Ablauf nur dessen Fähigkeiten freigeben

| Vorhaben | Tatsächliche Grenze und Anleitung |
| --- | --- |
| Codex entwickelt im Projekt | Betreiber setzt `agents.codex.sandbox_mode="workspace-write"` ausdrücklich; Standard `read-only`. Kein zusätzliches `ask`-Flag. Principal/CWD bleiben begrenzt, Kind-MCP bleibt aus. [Sicherheit](SECURITY.md). |
| Grok verwendet lokale Werkzeuge | ACP braucht Betreiberoption `allow_local_tools`, Principalrecht `agent.local_tools` und Task-Opt-in `local_tools=true` zusammen. API-Textturns sind getrennt, keine universelle Kosten-/Stoppkontrolle. |
| PNG-Entwurf ansehen | Eigene `file.image`-Capability, begrenzter Bildsnapshot über eigenen Task. Datei-Leserecht allein genügt nicht. [Bildweg](IMAGE-READ-20261018.md). |
| ThreadDesk-Kontext oder Wissen | Fester Betreiberpeer, eigene `threaddesk.read`/`threaddesk.manage`/`threaddesk.knowledge`-Rechte je Operation und Revision. [Adapter](THREADDESK-ADAPTER-20261018.md), [Wissen](THREADDESK-KNOWLEDGE-20261018.md). |
| Vorhandene Workflowbelege ansehen | `observations.read` plus `task.read`, nur ausgewählte eigene Tasks, begrenzte Metadaten. Kein Autoritäts-/Budgetnachweis. [Beobachtungsexport](WORKFLOW-OBSERVATION-EXPORT.md). |
| Eigenen gebundenen Workflow stoppen | Optionales, standardmäßig deaktiviertes `stop_only`-Wiring; Kosten unbekannt, kein harter Dollarcap. Anfrage, dauerhafte Sperre, Prozessende und externe Restwirkung getrennt. [Betreiberanleitung](WORKFLOW-CONTROL-CONFIGURATION.md). |

Nativer Codex-MCP-Zugang, ChatGPT-App-Principal, verwalteter Agentenkindprozess und
bestehende interaktive Sitzung sind verschiedene Kontexte. Ein engerer nativer
Codex-Principal schränkt die ausdrücklich breiteren App-Rechte nicht nachträglich
ein; diese sind ebenso wenig Voreinstellung für neue Nutzer. Kein Adapter übernimmt
fremde interaktive Sitzungen. Änderungen benötigen die lokale Betreiberentscheidung;
der Chat erteilt sich keine Rechte und aktiviert keine optionale Assembly.

## English: connect, then confirm the actual task

Use the [English installation guide](INSTALL-EN.md) to identify the package first.
Current source `7af39cd` (`0.6.0rc2`), the recorded Mac `0.5.2` backport and frozen
private RC2 `57bee99` are different states. Do not reset a healthy configuration or
try the old package against newer settings. Inspect `kirabridge status` and
`kirabridge chatgpt status`; only missing setup needs the interactive local command:

```sh
kirabridge chatgpt setup --language en
```

The installer includes this same guided connection step. Follow the official
account pages yourself. A restricted tunnel runtime key is required, not a Codex
login or ordinary API key. Enter it hidden locally, never in chat, process arguments
or logs. Existing keys, data and permissions are retained; incomplete setup is
reported instead of overwritten. The separate ChatGPT principal receives the
existing local policy. New local setup defaults to manual approval; the operator
Mac's broader automatic profile is not a general default. Account access, charges
and availability in the actual chat surface remain account-specific, not guaranteed
by a healthy tunnel. Keep `kirabridge connect` stdout exclusively for MCP.

For one confirmed task, select a small existing authorized project file. Substitute
its exact path in the CLI readiness and JSON examples above. Global CLI options
`--config` and `--principal` precede the subcommand. From the **intended ChatGPT
chat**, call `bridge_health`, then `bridge_readiness` for `file.read` and that path.
Readiness checks prerequisites without reading contents. Submit the shown
`task_request` once with a fresh stable task ID/key. When `approval_required=true`,
review that exact request through its returned local approval URL (`kirabridge
approvals` locally); otherwise poll directly. Use `task_get` with the same ID and
check the actual returned contents and final status. A queue receipt is not execution.
Use `task_diagnose` with that ID for failure evidence. After a disconnect or 409,
inspect the existing task first; never replay an uncertain write/agent task under a
new ID. The already confirmed ChatGPT read `chatgpt-file-verification-20261018-1311`
(9117Bytes) is retained evidence, not a test to repeat.

Older App catalogs may omit `bridge_readiness` and `task_diagnose` despite server
support. Use the shown local readiness for the actual principal; failed-task
`task_get` already includes its existing diagnosis and execution preflight.
Do not invent task operations for missing tool names or replay work to refresh a
catalog. App-catalog updates and service reloads are separate.

Codex defaults to read-only; only the operator's explicit
`agents.codex.sandbox_mode="workspace-write"` enables the managed adapter's write
mode. Principal/CWD restrictions remain and child MCP stays disabled. Native Codex,
ChatGPT App, managed children and existing interactive sessions are separate
contexts. Grok ACP local tools require configuration, principal and task opt-ins
together; its API text adapter does not gain local tools or universal cost control.
PNG images, ThreadDesk knowledge and observation export each require their specific
rights, as linked in the table. None enables another or proves imported context
trusted. Optional [owned workflow control](WORKFLOW-CONTROL-CONFIGURATION.md) is
disabled by default and stop_only: cost unknown, no hard dollar cap. Stop intent,
confirmed durable barrier, owned process exit and unknown external effects differ.
Local status alone does not establish a successful call from a target ChatGPT account.

## Historische Anschlussbelege / Historical connection evidence

Die folgende unveränderte frühere Notiz enthält damalige Versionsangaben und damals
noch offene Punkte. Diese sind **kein aktueller Auftrag zur Wiederholung** und keine
Aussage, dass inzwischen dokumentierte Datei-/Bild-/Wissens-/Beobachtungsnachweise
noch fehlen. Spätere Belege: [Projektsteuerung](PROJECT-CONTROL-20261018.md),
[Bildabruf](IMAGE-READ-20261018.md), [Wissen](THREADDESK-KNOWLEDGE-20261018.md),
[Beobachtungen](WORKFLOW-OBSERVATION-EXPORT.md). Die dort benannten Belegumfänge
bleiben begrenzt; Quellstand ist kein Nachweis einer laufenden Aktivierung. Externe
Dokumentationslinks im Archiv sind damalige Quellen, hier nicht neu abgefragt.

The unchanged note below preserves historical version/status statements, including
then-outstanding checks. These do not reopen completed checks. Follow the dated
source/task evidence linked above; a source checkout is not proof of live activation.
External documentation links are preserved historical references, not newly verified.

<details>
<summary>Archiv: Anschlussnotiz vom 17.–18.10.2026 / archived connection note</summary>

# ChatGPT-Anbindung: Tunnel aktiv, Statusabfrage zurückgemeldet

**Fortschreibung18.10.2026:** Die lokale Bridge läuft auf0.5.1. Direkte
Projektlesung wurde über die verbundene KiraBridge-App dieser Codex-Sitzung
tatsächlich bis zum vollständigen Ergebnis geprüft, einschließlich erneutem
Abruf nach Tunnel-Wiederverbindung ohne Doppelauftrag. Eine weitere, nicht von
dieser Codex-Sitzung erzeugte `chatgpt`-Anfrage las dieselbe Datei erfolgreich.
Die genaue Oberfläche war aus dem Datensatz allein nicht belegbar. Der Nutzer
hat den echten ChatGPT-Abruf inzwischen ausdrücklich bestätigt: Task
`chatgpt-file-verification-20261018-1311`, completed,9117Bytes vollständig.
Bestehenden Beleg übernommen, keinen neuen Lauf ausgeführt. [Reparatur, genaue Abrufe und Grenzen](REPAIR-PROJECT-ACCESS-20261018.md).
Die folgenden Angaben vom17.10. sind historische Belege.

Stand der Prüfung: 17. Oktober 2026. Der private OpenAI-Tunnel läuft; Prozess, Health und Readiness wurden lokal geprüft. OpenAI hat Discovery-Anfragen über den Tunnel an KiraBridge weitergeleitet. Die lokalen Tunnel-Metriken bestätigen zusätzlich echte `tools/call`-Anfragen mit Transportstatus 200. Der Nutzer hat eine erfolgreiche Statusabfrage aus seinem ChatGPT-Chat mit Version 0.2.0, aktivem Dispatcher und erkannten Codex-/Grok-Programmen zurückgemeldet. Der genaue Inhalt dieser Antwort ist ein Nutzerbericht; die Metriken geben keinen einzelnen Werkzeugnamen oder dessen Ergebnis wieder. Gemeinsame Ende-zu-Ende-Tests von Aufgabenfreigabe, Ausführung und Ergebnisabruf aus ChatGPT stehen noch aus. Der [Betriebsnachweis](evidence/local-operation-2026-10-17.json) unterscheidet diese Belegarten und hält auch zwei Transportantworten mit Status 409 fest. Aus diesen wird kein Ausführungsstatus abgeleitet und kein Auftrag automatisch wiederholt.

`bridge_health` gibt derzeit fest `chatgpt_integration="unverified"` aus; `kirabridge chatgpt status` gibt unabhängig von der gemessenen Tunnelbereitschaft `chatgpt_tool_call="unverified"` aus. Diese Felder erkennen einen durchgeführten Kontotest nicht automatisch und werden nicht allein aufgrund eines laufenden Tunnels auf Erfolg gesetzt.

## Vorbereitet auf diesem Mac

Der offizielle `tunnel-client` v0.0.16 ist einschließlich Begleitprogramm installiert; das Release-Archiv wurde gegen die veröffentlichten SHA-256-Summen geprüft. Der Nutzer hat den Tunnel `kira` angelegt. Das lokale Profil und der Runtime-Alias heißen `kirabridge`. Der getrennte lokale Principal `chatgpt` verbindet den Stdio-Proxy mit dem authentifizierten KiraBridge-Dienst. Laufzeitschlüssel und lokale Zugangsdaten werden mit Modus 0600 gespeichert; ihre Werte gehören nicht ins Repository.

```sh
kirabridge chatgpt status
kirabridge chatgpt setup
```

`status` prüft die vorhandene Verbindung. `setup` dient der einmaligen Kontoeinrichtung und muss für eine gesunde bestehende Verbindung nicht erneut durchlaufen werden. Der lokale interaktive Assistent öffnet die offiziellen OpenAI-Kontoseiten, nimmt die vorhandene Tunnel-ID entgegen und liest einen eingeschränkten Runtime-Schlüssel mit `getpass`, ohne ihn auszugeben oder als Prozessargument weiterzureichen. Der Schlüssel wird ausschließlich in einer separaten lokalen Datei mit Modus 0600 gespeichert. Die native Tunnel-Verwaltung erhält eine `file:`-Referenz. Der Assistent ergänzt eine eigene `chatgpt`-Identität, startet den lokalen Dienst neu und wartet auf dessen authentifizierte Dispatcher-Statusantwort, bevor er `tunnel-client runtimes connect` startet. Diese begrenzte Wiederholung betrifft ausschließlich die Statusabfrage. Erfolg wird nur bei nachgewiesenem Tunnelprozess, Health und Readiness gemeldet; die tatsächliche ChatGPT-Toolausführung bleibt eine eigene Prüfung.

Der Nutzer hat die Kontoschritte selbst im autorisierten Zielkonto durchgeführt. Sein eigener eingeschränkter Laufzeitschlüssel wurde lokal eingegeben. Der Codex-CLI-Login wurde nicht als Platform-Runtime-Schlüssel umgedeutet. Das ChatGPT-Plugin verwendet die Verbindungsmethode Tunnel und keine zusätzliche OAuth-Anmeldung.

Für diesen privaten Einzelbenutzer-Anschluss übernimmt der Tunnel die kontrollierte Workspace-Verbindung und der lokale Proxy die eigene KiraBridge-Authentifizierung. Das ist keine behauptete OAuth-Anbindung mit getrennten Identitäten für beliebige Workspace-Mitglieder. Eine solche Mehrbenutzer-Anbindung benötigt den zusätzlich beschriebenen Identity Provider.

## Freigaben für ChatGPT-Aufträge

Die lokale Freigabeseite ist [KiraBridge auf diesem Mac](http://127.0.0.1:8766/). Sie wird über `kirabridge approvals` oder „KiraBridge Freigaben.command“ auf dem Schreibtisch geöffnet und angemeldet. Anfragen erscheinen dort automatisch. `task_request` und `bridge_health` liefern die Adresse als `local_approval_url`. Der Agent soll diesen Link nur bei `approval_required=true` zur Entscheidung nennen und danach mit `task_get` weiter prüfen. Beim hier eingerichteten `automatic`/`approval_required=false` braucht es keinen Freigabeklick; direkt Ergebnis/Ereignisse abrufen. Alte zwischengespeicherte Toolbeschreibungen sind kein Ersatz für den tatsächlich zurückgegebenen Modus. IDs müssen nicht zwischen Chats kopiert werden.

Die Freigabeseite ist ein getrennter lokaler Dienst und wird nicht durch den OpenAI-Tunnel freigegeben. Ein lokaler Ende-zu-Ende-Test mit dem `chatgpt`-Principal hat MCP-Anfrage, Browserfreigabe, tatsächliche Dateilisten-Ausführung und Ergebnisabruf geprüft. Ein isolierter echter Browser hat auch den Freigabeklick und die Ergebnisanzeige erfolgreich durchlaufen. Für einen aus der ChatGPT-Unterhaltung selbst ausgelösten Ausführungsauftrag bleibt die Herkunft weiterhin getrennt nachzuweisen.

## Technische Voraussetzungen

Die offiziellen OpenAI-Unterlagen beschreiben für ChatGPT einen erreichbaren MCP-Endpunkt und die zugehörige Workspace-/Developer-Mode-Berechtigung. Ein lokaler stdio-Eintrag allein verbindet keine ChatGPT-Cloudsitzung mit dem Mac. Für private Netze dokumentiert OpenAI einen Secure MCP Tunnel mit eigener Platform-Berechtigung, Tunnel-ID und Laufzeitschlüssel. Diese private Verbindung wurde mit dem vom Nutzer angelegten Tunnel eingerichtet. [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)

OpenAI beschreibt OAuth für personenbezogene Daten und Schreibzugriffe. Ein eigener statischer Bearer-Token des jetzigen KiraBridge-HTTP-Servers ist kein nachgewiesenes ChatGPT-Anmeldeverfahren. Für einen direkten OAuth-Anschluss fehlen hier noch ein ausgewählter Authorization Server, dessen geprüfte Token-/Audience-Validierung, Discovery/Protected-Resource-Metadaten und die Freigabe im Zielworkspace. ChatGPT unterstützt laut offizieller Auth-Dokumentation keine beliebigen kundeneigenen API-Keys als Ersatz für diesen Flow. [Offizielle Authentifizierungsanforderungen](https://developers.openai.com/plugins/build/auth)

Ein öffentlich erreichbarer HTTPS-Endpunkt ist eine alternative Infrastrukturentscheidung. KiraBridge richtet ihn nicht eigenständig ein. Plan- und Workspace-Verfügbarkeit müssen im Zielkonto geprüft werden; aus einem vorhandenen MCP SDK folgt keine Berechtigung im ChatGPT-Produkt. [Offizieller MCP-/App-Quickstart](https://developers.openai.com/plugins/build/app-quickstart)

## Ausstehender Integrationsnachweis

1. Einen tatsächlichen Toolaufruf aus dem Zielchat unabhängig mit einem entsprechenden Ergebnisbeleg abgleichen. Der bisherige Statusaufruf wurde vom Nutzer zurückgemeldet; die Tunnelprotokolle bestätigen Discovery und Weiterleitung und die Metriken belegen `tools/call`. Der konkrete Werkzeugname und das Ergebnis dieses einzelnen Aufrufs sind darin nicht enthalten.
2. Den vorbereiteten harmlosen Dateiabruf aus der Ziel-ChatGPT-Unterhaltung verwenden und Empfang, Ausführung und Ergebnisabruf anhand derselben Task-ID prüfen. Im automatischen Modus ohne Freigabeklick; der unveränderte vorbereitete Auftrag darf idempotent wieder abgerufen werden.
3. Unberechtigte Aufrufe und Principal-Trennung zusätzlich über die konkrete ChatGPT-Verbindung prüfen.
4. Falls eine Mehrbenutzer-Anbindung gewünscht wird: Identity Provider auswählen, OAuth-Resource-Server-Integration implementieren und Tokenziel, Scopes, Ablauf und Erneuerung testen.

Der Nutzer meldet das angelegte ChatGPT-Plugin und eine erfolgreiche Statusantwort. Die private Tunnel-Runtime läuft. Es wurden kein zusätzlicher OAuth-Dienst und kein öffentliches Deployment eingerichtet. Für die Kosten der OpenAI-Dienste liegt hier keine verbindliche Kostenfreiheitsbestätigung vor; die Kontoverbindung ist kein Nachweis unbegrenzter oder kostenloser KI-Nutzung.

## Adapterquellen

Der Codex-Adapter basiert auf den dokumentierten JSONL-Ereignissen des nichtinteraktiven Modus. [OpenAI Docs: nichtinteraktiver Codex](https://developers.openai.com/codex/noninteractive)

Grok Build dokumentiert ACP-Initialisierung, Sitzungsanlage und `session/prompt`; die API dokumentiert Streaming-Response-IDs und Abschlussgründe. [Grok Build Headless/ACP](https://docs.x.ai/build/cli/headless-scripting), [Grok Streaming](https://docs.x.ai/developers/model-capabilities/text/streaming)


</details>
