# Abnahmestand 0.1.0

Datum: 17. Oktober 2026. Bezug: [ursprünglicher Entwicklungsplan](DEVELOPMENT_PLAN.md). Dieser Stand dokumentiert die tatsächlich vorhandene Implementierung; daraus folgt keine pauschale Produktionsfreigabe oder erfolgreiche externe Integration.

## Planabdeckung

| Arbeitspaket | Stand |
|---|---|
| Foundation | Python-Paket, alle elf Module, typisierte API v1, TOML-Policy, SQLite-Schema v1, WAL/FULL, private Zustandsdateien |
| Reliable dispatch | Persistenz vor Dispatch, Receipt-ID, getrennte Zustände, exakte Idempotenz, Leases, exklusiver Dispatcher, Ereignisse, Wiederherstellung nach echtem SIGKILL |
| Agent adapter | Codex JSONL, Grok Build ACP v1, Grok API Streaming; Identitätsprüfung und Abschlussbelege; Protokolltests gegen kontrollierte Gegenstellen |
| Desktop tools | Geschützte Dateioperationen, Terminal-/Prozessgruppensteuerung, begrenzte Ausgabe, Zeitlimits, Beenden unter Last, Unicode-Clipboard und Schreibbestätigung |
| MCP connectivity | Echtes stdio und Streamable HTTP, mehrere HTTP-Clients mit getrennten Rechten, ausgehender Clientpool, TLS mit aktiver Zertifikatsprüfung |
| Cross-platform | macOS Intel lokal geprüft; Linux-Implementierung und CI-Matrix vorhanden; Windows verweigert nicht implementierte native Operationen ausdrücklich |
| Integration extensions | Versioniertes AgentAdapter-Register und PlatformAdapter-Protokoll; optionale externe Systeme nicht gekoppelt oder verändert |

## Abnahmekriterien und konkrete Tests

- Dauerhafte Speicherung vor Dispatch und belegte Zustandsfolge: `test_persist_before_dispatch_and_evidence`.
- Doppelte Einreichung führt zu genau einer Ausführung: `test_idempotency_executes_once`.
- Neustart und echter Prozessabbruch führen zu `unknown` ohne erneute Ausführung: `test_restart_preserves_queue_and_never_reexecutes_unknown`, `test_real_dispatcher_sigkill_never_duplicates`.
- Empfang, Sitzung, Lauf und Abschluss werden unterschieden: `test_codex_requires_completion_event`, `test_grok_acp_session_and_completion`, `test_grok_api_requires_server_completion`.
- Fehlende/fremde/verbrauchte/abgelaufene Freigaben scheitern; kein zweiter Principal erhält Ergebnisse: Security-Tests und `test_multiple_real_http_clients_do_not_cross_principals`.
- Terminal-Metazeichen werden wörtlich übergeben; Pfad- und Symlink-Ausbrüche werden abgelehnt; eigene Prozesse bleiben kontrollierbar: Desktop-/Boundary-Tests.
- Unbekannte Ausgänge werden nicht automatisch wiederholt: Grok-Transport- und MCP-Client-Timeout-Tests. Kontrollierte Retries benötigen einen nachgewiesenen Nichtstart und enden spätestens beim dritten Versuch.
- Clipboard-Tests nutzen einen isolierten Backend-Simulator; keine persönliche Zwischenablage wird gelesen oder verändert.
- `test_real_tls_with_certificate_validation` verwendet einen temporären vertrauenswürdig eingebundenen Testaussteller. Es wird kein `verify=False` verwendet.

Lokale Prüfung auf macOS 15.7.4, Intel x86_64, Python 3.11.15: **64 Tests bestanden in 15,59 Sekunden**, Ruff und Paketbau erfolgreich. Plattformübergreifende CI-Ergebnisse werden am Implementierungscommit festgehalten.

## Lokale Ressourcenmessung

`uv run python scripts/benchmark_idle.py --seconds 5`, privates temporäres Datenverzeichnis, MCP-Werkzeugregister geladen, zwei Ausführungs- und ein Steuerungs-Worker:

```json
{
  "os": "Darwin",
  "architecture": "x86_64",
  "python": "3.11.15",
  "idle_seconds": 5.001,
  "cpu_seconds": 0.001487,
  "cpu_percent_one_core": 0.03,
  "peak_rss_mib": 55.61,
  "gpu_required": false
}
```

Das ist eine lokale Leerlaufmessung über fünf Sekunden, kein Last- oder Langzeitbenchmark. Agentenprozesse und deren Speicherverbrauch sind darin nicht enthalten.

## Ausstehende oder bewusst optionale Nachweise

- Echte authentifizierte Codex-/Grok-Providerläufe und deren konkrete CLI-Versionen: nicht ausgeführt. Automatische Tests verwenden Protokollsimulatoren.
- ChatGPT-Verbindung im Zielworkspace sowie OAuth-/Tunnel-Einrichtung: nicht vorhanden; Voraussetzungen sind in [CHATGPT.md](CHATGPT.md) belegt.
- Linux-Zwischenablage in einer echten grafischen Wayland-/X11-Sitzung: benötigt diese Sitzung; Routing und Textübertragungslogik sind getrennt getestet.
- Windows-Nativadapter: Erweiterungspunkt, keine behauptete Windows-Laufzeitunterstützung.
- Bilder, Datei-Clipboard, PTY/interactive stdin, Claude Code, Gemini CLI, OpenCode und A2A: künftige Adapter/Funktionen, nicht als funktionierend ausgewiesen.
- ThreadDesk, Agent Authority, Tollgate und SSH: optionale Integrationen; keine vorhandenen Projekte, Dienste oder Agenten wurden verändert oder beendet.
- Öffentliche Bereitstellung, produktiver Dienststart und unabhängiger Sicherheitstest: nicht durchgeführt. Service-Dateien sind nicht installierte Vorlagen.

