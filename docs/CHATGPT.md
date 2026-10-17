# ChatGPT-Anbindung: geprüft, nicht aktiviert

Stand der Prüfung: 17. Oktober 2026. KiraBridge implementiert MCP-Transporte und lokale Bearer-Authentifizierung. Eine funktionierende Integration im konkreten ChatGPT-Konto wurde **nicht** nachgewiesen. `bridge_health` meldet deshalb `chatgpt_integration="unverified"`.

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

