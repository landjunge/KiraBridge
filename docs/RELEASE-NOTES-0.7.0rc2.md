# KiraBridge 0.7.0rc2 — Grok app connector / private release candidate

## Deutsch

KiraBridge unterstützt zusätzlich zum bestehenden Grok-CLI-/ACP-Arbeitsagenten
einen eigenen OAuth-geschützten MCP-Eingang für die Grok-Web-/Handy-App.
`grok` und `grok_app` sind getrennte authentifizierte Identitäten. Die App kann
über die vorhandenen Werkzeuge Teamnachrichten, Aufträge und bewusst geteilte
Ergebnisse austauschen. Ihre Rolle und die konfigurierte Policy begrenzen die
Aufrufe weiterhin; private Aufgaben anderer Zugänge werden nicht freigegeben.

Der getrennte Gateway bindet an Loopback. Ein eigener Cloudflare-Quick-Tunnel
stellt ausschließlich diesen Eingang per HTTPS bereit. Hauptdienst und lokale
Freigabeseite bleiben privat. Alternativ kann eine bereits eingerichtete eigene
HTTPS-Adresse verwendet werden. Der Quick-Tunnel benötigt kein zusätzliches
Cloudflare-Konto; seine Adresse ist vorübergehend und kann sich beim Neustart
ändern. Dann ist eine neue Grok-Verknüpfung erforderlich.

Die Anmeldung verwendet das MCP-SDK mit OAuth-Code-Flow, PKCE S256, gebundener
Resource und einer einmaligen lokalen Verknüpfungsfreigabe. Beide Fenster zeigen
dieselbe Verbindungskennung. Rotierende Refresh-Tokens, Replay-Sperren, exakte
Rücksprungadressen, begrenzte Registrierungen und private SQLite-Persistenz sind
implementiert. Bestehende Daten werden additiv migriert. Öffentliche Anfragen
erhalten keine privaten Bridge-Zugangsdaten.

`kirabridge grok-connector setup`, `start`, `status`, `stop`, `approve` und `revoke`
ergänzen den lokalen Bereich **Grok App**. Standard ist das begrenzte Teamprofil;
das ausdrücklich gewählte Profil `same-as-chatgpt` übernimmt die vorhandene
ChatGPT-Policy in einen eigenen Zugang. Bestehende Zugangsdaten und automatische
Auftragsfreigaben bleiben erhalten. Der Supervisor startet keine Modellschleife
und unterbricht keine interaktive Codex-/Grok-Sitzung.

Ein kontrollierter OAuth-/MCP-Test ist kein Nachweis für eine echte Grok-App-
oder Eve-Sprachsitzung. Die gewünschte Sitzung muss selbst einen Werkzeugaufruf
ausführen; eine Anbieterbeschränkung des Sprachmodus lässt sich lokal nicht
aufheben. Es wird keine zusätzliche kostenpflichtige Voice-API eingerichtet.

Die Teamfunktionen und CLI-Adapter aus 0.7.0rc1 sind enthalten. Die lokale
Installation verwendet weiterhin ihren gezielten Backport auf der bestehenden
Runtime; dieses saubere Paket ersetzt fremde lokale Erweiterungen nicht.
Die bestehende Lizenz und ältere eingefrorene RC-Artefakte bleiben unverändert.

[Einrichtung und tatsächliche Grenzen](GROK-APP-CONNECTOR.md) ·
[Prüfnachweis](evidence/grok-app-connector-20261019.json) ·
[Team](TEAM-ORCHESTRATION.md) · [Anbieter](providers/README.md).

## English

A separate authenticated MCP connector supports the Grok web/mobile application
alongside the existing Grok CLI/ACP worker. The fixed `grok_app` identity is
distinct from `grok`. Existing tools provide addressed team messages, delegated
work and deliberately shared results; roles do not widen operating-system
permissions or expose private tasks.

The loopback-only OAuth gateway has its own outbound HTTPS tunnel. The private
daemon and operator console are not forwarded. An accountless Cloudflare Quick
Tunnel is temporary: a changed address requires reconnection. An existing stable
HTTPS origin can alternatively be configured.

The MCP SDK implements authorization-code flow, PKCE S256, resource binding and
a one-time local authorization, with matching connection references in both
windows. Refresh rotation, replay protection, exact redirect validation, bounded
registration and persistent private SQLite state are included. Code-only and
refresh-capable clients use their registered grants. Existing state migrates
without resetting previous approvals or audit history.

Use `kirabridge grok-connector` and the local **Grok App** panel. The default
profile provides team access; an explicit initial `same-as-chatgpt` selection
copies the current ChatGPT policy to a separate credential. Existing automatic
task approval and running interactive sessions remain intact.

A controlled OAuth/MCP test does not establish an actual Grok app or Eve voice
call. Verify a tool call from that specific session. Provider-side voice-tool
availability remains a separate requirement; no paid voice API is installed.
The previous team/CLI features, license and frozen RC artifacts are retained.
