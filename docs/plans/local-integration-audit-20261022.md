# KiraBridge Local – konsolidierter Abgleich (2026-10-22)

## Verifizierte Ausgangslage
- Laufende Mac-Installation: KiraBridge 0.8.0rc13, Dispatcher aktiv (keine End-to-End-Bestätigung der ChatGPT-Integration).
- Original-Arbeitsverzeichnis: /Users/landjunge/KiraBridge, Branch fix/visible-busy-idle-20261021, Commit dfbae480; uncommitted Dateien bewusst unberührt.
- Sicherung: /Users/landjunge/KiraBridge-safety-20261022; tracked.patch, staged.patch und untracked.tar mit SHA-256 erfolgreich verifiziert.
- Separater Integrations-Worktree: /Users/landjunge/KiraBridge-local-integration-20261022, Ausgangscommit e818ced von development/local.

## Abgehakt: identischer Inhalt in beiden Git-Ständen
- src/kirabridge/platform_adapters/codex_state.py
- src/kirabridge/visible_handoff.py
- src/kirabridge/visible_readiness.py

## Inhaltliche Differenzen – nicht blind zusammenführen
- src/kirabridge/message_manager/receiver.py: Mac enthält zusätzliche Warteschlangen-, Wiederholungs- und Fehlerbehandlung.
- src/kirabridge/task_manager/manager.py: Freigabe in Transaktion, getrennte Worker-Lanes.
- src/kirabridge/bridge_core/config.py: Sprachkanal, sichtbare Terminalbindung, Berechtigungen, Output-History.
- src/kirabridge/mcp_gateway/server.py: Mac enthält Terminal-, Session-, Completion- und Read-Query-Funktionen; development/local enthält dynamische ThreadDesk-Werkzeuge.
- src/kirabridge/cli.py: Funktionssignaturen weitgehend gleich, Implementierung und uncommitted Änderungen müssen berücksichtigt werden.

## Besonders zu bewahren
- Nur in development/local: src/kirabridge/threaddesk_dynamic.py sowie install_ui.py, installation.py und setup_dependencies.py.
- Nur im Mac-HEAD: Terminal-/Session-/Voice-/Output-History-/Control-Center-Module und Tests.
- Dokumentation, Icons und Installer nicht versehentlich aus dem Ziel entfernen.

## Nächste sichere Integrationsschritte
1. Existierende Tests und Belege den jeweiligen Komponenten zuordnen; bereits geprüfte unveränderte Komponenten nicht erneut testen.
2. Für die MCP-Schnittstelle einen expliziten, rückwärtskompatiblen Adapter planen, der dynamische ThreadDesk-Tools und die Mac-Session-Funktionen gemeinsam anbietet.
3. Receiver, Taskmanager und Konfiguration auf API-Vertragsänderungen vergleichen; nur fehlende Funktionalität übertragen.
4. CLI und Installer getrennt prüfen, da uncommitted Änderungen und Dateien im Ziel vorhanden sind.
5. Änderungen in kleinen Commits im Integrations-Worktree durchführen, jeweils nur betroffene Tests; erst nach erfolgreichem Ergebnis nach development/local pushen.

Keine automatische Gesamtzusammenführung, kein Main-/Server-Merge, keine Geheimnisse ins Repository.
