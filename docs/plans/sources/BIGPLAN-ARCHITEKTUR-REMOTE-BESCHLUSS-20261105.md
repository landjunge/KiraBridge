> **Nicht maßgeblich. Maßgeblich ist ThreadDesk-Thread `188ce4729a62` (Nutzerbeschluss 09.11.2026). Diese Datei ist Archiv bzw. technischer Spiegel.**

> Historischer Quellenstand aus `21d2e2cad8e9930931b02031addfc25d819a9ed3`,
> bei der Integration am 06.11.2026 bewahrt. Aktueller Quellen-, Prüf- und
> Installationsstand: [RC40-Integrationsnachweis](../../RC40-INTEGRATION-INSTALL-20261106.md).
> Datierte Plan- und Gateangaben sind keine neue Auftrags- oder Berechtigungsquelle.

Herkunft: Vom Nutzer im laufenden Codex-Chat am 5. November 2026 vollständig
übermittelter Beschlusstext als Antwort auf die Quellenfrage zur Bibliotheksdatei
`/big plan/Big-Plan-Architektur-und-Remote-2026-11-05.md`.
Der folgende Inhalt ist die bereitgestellte Primärquelle. Die Bibliotheksdatei
selbst wurde nicht unabhängig gelesen; ihre Dateimetadaten und die unten
genannten älteren Masterpläne sind damit nicht zusätzlich verifiziert.

---

# Big Plan – Architektur- und Remote-Beschluss
Stand: 5. November 2026. Status: bestätigte Planung, keine technische End-to-End-Abnahme.

## Herzstück der Serverversion (Priorität 1)
Unterwegs per Handy/ChatGPT einen Auftrag formulieren. ThreadDesk Server & Sync auf dem Debian-Server speichert freigegebene Aufgaben und Status; KiraBridge Server vermittelt authentifiziert an den erreichbaren Heimrechner. Der vorhandene KiraBridge Task-Manager/Auto-Next übernimmt ausschließlich explizit freigegebene READY-Aufgaben, genau einmal mit Idempotenz und Belegen. Lokale CLI-Agenten bearbeiten und melden Ergebnisse an ThreadDesk zurück. Verbindungsabbrüche, UNKNOWN, Konflikte und Wiederaufnahme ohne blindes Replay behandeln. Ein End-to-End-Test Handy → Debian → Mac → Agent → ThreadDesk ist offen.

## Fünf eigenständige Produkte
- KiraBridge: gemeinsamer Kern, CLI-Manager, Kommunikation, lokale Computersteuerung und optionaler Server-/Remote-Adapter.
- ThreadDesk: Arbeitsgedächtnis, Whiteboards, Aufgaben, Wissensgraph; Serverversion mit Offline-first- und bidirektionaler Synchronisierung.
- 4AllPass: Identitäten, Geheimnisse, API-Schlüssel und Berechtigungen; später integrieren.
- TollGate: Kosten- und Budgetkontrolle insbesondere für API-Nutzung; Abonnements bleiben zunächst Grundlage; parallel entwickeln.
- Agent Authority: unabhängiger read-only Beobachter für Aktionen, Delegationen und Nachweise; keine Steuerung.

## CLI-Ausbaustufe
Erste Priorität: Codex CLI, Grok Build CLI, Claude Code, Gemini CLI, Cursor Agent CLI als separate Adapter unter einem gemeinsamen CLI-Manager. Codex/Grok/Claude zuerst auf Übergaben testen, Gemini/Cursor anschließend. Kein permanenter Chefagent; Aufgabenübernahme über den bestehenden autorisierten Mechanismus. OpenCode, GitHub Copilot CLI und Aider bleiben im bereits beschlossenen Gesamtumfang, jedoch nachrangig.

## Plattformen und Server
Gemeinsamer plattformneutraler KiraBridge-Kern; separate OS-Adapter für macOS, Windows, Linux, statt dreifacher Implementierung der CLI-Logik. Windows-Testpaket für Dirk bleibt priorisiert. KiraBridge Server = derselbe Kern plus Serveradapter, nicht zweiter Kern. ThreadDesk Server = eigenständiger Dienst für Wissen/Sync. Beide können auf Debian laufen, bleiben logisch getrennt. Weitere Serverfunktionen der übrigen Produkte erst nach dem Kernweg ausbauen.

## Keine Doppelarbeit / Übergabe an beliebige Agenten
Vor jedem Auftrag: Bibliotheks-Masterplan, aktuelle ThreadDesk-Whiteboards, Repository/Branch/Commit, laufende Agenten/Tasks, bereits implementierte Schnittstellen, Test- und Installationsbelege lesen. Bereits begonnene Aufgaben nicht neu starten. Ein Schreiber je Worktree, revisionsgebundene Handoffs, Status getrennt als geplant / implementiert / getestet / installiert / live abgenommen. Vorhandene Entwicklungsstränge KiraBridge Server (`development/server` zunächst prüfen), ThreadDesk Server & Sync, CLI-Modularisierung und Auto-Next wiederverwenden. Kein neuer Dispatcher, kein zweites Queue-System, keine zweite Rechteengine. Kritische Änderungen, Merge, Release und Deployment nur mit passender Freigabe.

## Offene Abnahme
Tatsächlichen Stand aller fünf Produkte inventarisieren; bestehenden Auto-Next-Stand prüfen; Server-Identität, TLS, Geräte-Pairing, Berechtigungen, Offline-/Konfliktverhalten und End-to-End-Remote-Auftrag testen. Neue Planungsnotiz startet keine Prozesse.

Quellen: KiraBridge-Masterplan-2026-10-29; KiraBridge_Ausbauplan_2026-10-25_aktualisiert; KiraBridge_Integrationsplan_RC32_Windows_Server_2026-11-04; ThreadDesk-Koordinationsboard 482f593429ad, Beschlüsse 05.11.2026.
