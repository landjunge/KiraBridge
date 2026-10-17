# ChatGPT-Anbindung: geprüft, nicht aktiviert

Stand der Prüfung: 17. Oktober 2026. KiraBridge implementiert MCP-Transporte und lokale Bearer-Authentifizierung. Eine funktionierende Integration im konkreten ChatGPT-Konto wurde **nicht** nachgewiesen. `bridge_health` meldet deshalb `chatgpt_integration="unverified"`.

## Vorbereitet auf diesem Mac

Der offizielle `tunnel-client` v0.0.16 ist einschließlich Begleitprogramm installiert; das Release-Archiv wurde gegen die veröffentlichten SHA-256-Summen geprüft. Es existiert noch kein lokales Tunnelprofil und keine Runtime-Alias-Verbindung. Ein Tunnel wird nicht mit einer erfundenen ID gestartet.

```sh
kirabridge chatgpt status
kirabridge chatgpt setup
```

`setup` ist ein lokaler interaktiver Assistent. Er öffnet die offiziellen OpenAI-Kontoseiten, nimmt die vorhandene Tunnel-ID entgegen und liest einen eingeschränkten Runtime-Schlüssel mit `getpass`, ohne ihn auszugeben oder als Prozessargument weiterzureichen. Der Schlüssel wird ausschließlich in einer separaten lokalen Datei mit Modus 0600 gespeichert. Die native Tunnel-Verwaltung erhält eine `file:`-Referenz. Der Assistent ergänzt eine eigene `chatgpt`-Identität, startet den lokalen Dienst neu und nutzt `tunnel-client runtimes connect`. Erfolg wird nur bei nachgewiesenem Prozess, Health und Readiness gemeldet; die tatsächliche ChatGPT-Toolausführung bleibt eine eigene Prüfung.

Die Kontoschritte können hier nicht automatisch durchgeführt werden: Es liegen weder eine Tunnel-ID noch eine geeignete Runtime-Berechtigung vor. Der Codex-CLI-Login ist kein dafür ausgegebener Platform-Runtime-Schlüssel. Schlüssel gehören nicht in den Chat. Das Auswählen/Anlegen des privaten Tunnels und die Plugin-Freigabe erfolgen im autorisierten Zielkonto.

Für diesen privaten Einzelbenutzer-Anschluss übernimmt der Tunnel die kontrollierte Workspace-Verbindung und der lokale Proxy die eigene KiraBridge-Authentifizierung. Das ist keine behauptete OAuth-Anbindung mit getrennten Identitäten für beliebige Workspace-Mitglieder. Eine solche Mehrbenutzer-Anbindung benötigt den zusätzlich beschriebenen Identity Provider.

## Technische Voraussetzungen

Die offiziellen OpenAI-Unterlagen beschreiben für ChatGPT einen erreichbaren MCP-Endpunkt und die zugehörige Workspace-/Developer-Mode-Berechtigung. Ein lokaler stdio-Eintrag allein verbindet keine ChatGPT-Cloudsitzung mit dem Mac. Für private Netze dokumentiert OpenAI einen Secure MCP Tunnel mit eigener Platform-Berechtigung, Tunnel-ID und Laufzeitschlüssel. Diese Infrastruktur wurde nicht angelegt. [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)

OpenAI beschreibt OAuth für personenbezogene Daten und Schreibzugriffe. Ein eigener statischer Bearer-Token des jetzigen KiraBridge-HTTP-Servers ist kein nachgewiesenes ChatGPT-Anmeldeverfahren. Für einen direkten OAuth-Anschluss fehlen hier noch ein ausgewählter Authorization Server, dessen geprüfte Token-/Audience-Validierung, Discovery/Protected-Resource-Metadaten und die Freigabe im Zielworkspace. ChatGPT unterstützt laut offizieller Auth-Dokumentation keine beliebigen kundeneigenen API-Keys als Ersatz für diesen Flow. [Offizielle Authentifizierungsanforderungen](https://developers.openai.com/plugins/build/auth)

Ein öffentlich erreichbarer HTTPS-Endpunkt ist eine alternative Infrastrukturentscheidung. KiraBridge richtet ihn nicht eigenständig ein. Plan- und Workspace-Verfügbarkeit müssen im Zielkonto geprüft werden; aus einem vorhandenen MCP SDK folgt keine Berechtigung im ChatGPT-Produkt. [Offizieller MCP-/App-Quickstart](https://developers.openai.com/plugins/build/app-quickstart)

## Ausstehender Integrationsnachweis

1. Zielworkspace, Developer Mode, Benutzer-/Adminrechte und zugelassenes Transport-/Authentifizierungsverfahren feststellen.
2. Privaten Tunnel oder ausdrücklich genehmigte HTTPS-Infrastruktur bereitstellen; Authentifizierung und Netzgrenzen prüfen.
3. Falls OAuth nötig: Resource-Server-Integration gegen den gewählten Identity Provider implementieren und Tokenziel, Scopes, Ablauf und Erneuerung testen.
4. Tools im Zielkonto einlesen; unberechtigte Aufrufe und Principal-Trennung testen.
5. Einen einzeln freigegebenen Testauftrag senden und Empfang, Ausführung und Ergebnis in KiraBridge unabhängig prüfen.

Es wurden weder eine ChatGPT-App erstellt noch ein Tunnel, OAuth-Dienst oder öffentliches Deployment gestartet.

## Adapterquellen

Der Codex-Adapter basiert auf den dokumentierten JSONL-Ereignissen des nichtinteraktiven Modus. [OpenAI Docs: nichtinteraktiver Codex](https://developers.openai.com/codex/noninteractive)

Grok Build dokumentiert ACP-Initialisierung, Sitzungsanlage und `session/prompt`; die API dokumentiert Streaming-Response-IDs und Abschlussgründe. [Grok Build Headless/ACP](https://docs.x.ai/build/cli/headless-scripting), [Grok Streaming](https://docs.x.ai/developers/model-capabilities/text/streaming)

