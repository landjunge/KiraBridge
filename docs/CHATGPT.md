# ChatGPT-Anbindung: Tunnel aktiv, Statusabfrage zurückgemeldet

**Fortschreibung18.10.2026:** Die lokale Bridge läuft auf0.5.1. Direkte
Projektlesung wurde über die verbundene KiraBridge-App dieser Codex-Sitzung
tatsächlich bis zum vollständigen Ergebnis geprüft, einschließlich erneutem
Abruf nach Tunnel-Wiederverbindung ohne Doppelauftrag. Eine weitere, nicht von
dieser Codex-Sitzung erzeugte `chatgpt`-Anfrage las dieselbe Datei erfolgreich.
Die genaue Oberfläche dieses anderen Clients ist daraus nicht belegbar; der
abschließende Abruf in der separaten Ziel-ChatGPT-/iPhone-Unterhaltung bleibt
ausdrücklich ausstehend. [Reparatur, genaue Abrufe und Grenzen](REPAIR-PROJECT-ACCESS-20261018.md).
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

