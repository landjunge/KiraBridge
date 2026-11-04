# Unabhängiger Merge-Review: macOS / gemeinsame Runtime

4. November 2026, Spezialagent `macos_audit`. Ausschließlich lesender Review des
laufenden Integrationsmerges in
`/Users/landjunge/KiraBridge-worktrees/integration-dev3-rc32-20261104`.
Beobachteter HEAD `090fcaf66bf4a4ce840e4b3176317d7eb811b84e`, MERGE_HEAD
`62aae9d2d2a3e28967573c86fd64dbad9914f9e8`. Keine Tests, Builds, Pythonimporte des
Produkts, Native-/UI-Aufrufe oder Worktreeänderungen durch diesen Reviewer.
Diese externe Reviewdatei ist die einzige Schreibaktion.

Ergebnis: **Keine blockierenden fachlichen Integrationsfehler gefunden.**
Gemeinsame Bridge-/MCP-/Store-Hunks erhalten beide Entwicklungsarme.

## Fachlicher Review

- `bridge_core/bridge.py`: Windows-INPUTS und die beiden Windows-Manager ergänzen
  die RC32-Bridge. `NativeQueries` wird weiterhin mit `self.macos` und
  `self.system_modules` gebunden. Keine Umdeutung von Windows-Handleverträgen in
  macOS-Elementtokens. `platform_operation` wählt den macOS-Provider nur bei
  `darwin` und exakter Mitgliedschaft in dessen Deskriptoren, nicht allein über
  den gemeinsamen Wortanfang `windows.`. Windows-Taskvalidierung verweigert
  Windowsverträge auf anderen Hosts vor Enqueue; der separate Dispatch ruft die
  Windows-Manager auf. Die RC31-Ereignisoptimierung behält frische
  `task.read`-/Eigentümerprüfung und lädt keine Taskausgabe.
- `mcp_gateway/server.py`: Beide Windows-Kataloge werden mit frischer
  Principalentscheidung ergänzt; sie verursachen keine native
  Backendkonstruktion. RC31-Direktlese-Hinweise und Read-Schemadokumentation bleiben
  erhalten. Die Windows-Desktopoperationen erhalten wie macOS-Tastatureffekte
  13 Sekunden Inlinewartezeit; durable Ausführungsfristen werden nicht verändert.
- `task_manager/store.py`: Windows-ACL-/WAL-/SHM-Prüfungen und RC31-Ereignisindex
  bleiben gleichzeitig erhalten. Der POSIX-Zweig verwendet unverändert
  `O_NOFOLLOW`, owner-only Datei und Modusprüfung; Windows-APIs werden darin nicht
  konstruiert. `events_task_seq` wird weiterhin in der bestehenden
  Starttransaktion angelegt, auch bei bestehendem Schema.
- Import-/Startseitenwirkungen: Windows-Tastatur/-Fensterdateien definieren beim
  Import Schemata, ctypes-Strukturen und Klassen; `WinDLL` wird erst in einer
  guarded Native-API-Konstruktion aufgerufen. Managerkonstruktion speichert nur
  Factory, Host und gemeinsame Desktoptransaktion. Keine zusätzliche Datei,
  Sitzung, DLL, nativer Worker oder OS-Rechteanfrage durch diese Ergänzung.
  `NativeQueries.__init__` speichert nur Referenzen und Zähler.
- Gemeinsame Plattformdateien: Änderungen an RuntimeLock, privaten Dateien,
  EventJournal, private_directory und ProcessOutputStore verzweigen explizit nach
  `os.name`/`sys.platform`. POSIX behält seine vorhandenen Pfade. Windows
  ProcessOutput bleibt ausdrücklich geschlossen, solange sein sicherer Adapter
  fehlt; keine neue ungesicherte Prozess-/Dateifunktion durch den Merge.

## Bytegleichheit zum RC32-Stand

Alle folgenden Dateien wurden direkt byteweise gegen `d8bbe61` verglichen und
sind **identisch**:

- Sechs native Swift-Produktquellen: SystemControl, SystemBridge, SystemServices,
  SystemKeyboard, SystemShortcuts, SystemSpecialKeys.
- NativeQueries, read_query, MCP proxy, macOS control_models, system_transport,
  provider und capabilities.
- Die drei Swift-Fixtures AccessibilityBatchHarness, AccessibilityTreeHarness,
  AccessibilityTimingHarness.

`SystemControl.swift` SHA256 bleibt
`3b578d5ae885bd833c3f338b7b1c1c04e938308258df069386c9d37479721ace`.
Damit sind die bereits sourcegebundenen RC32-Komponentenbelege für unveränderte
Swiftquellen weiterhin einschlägig. Dieser Review ist kein neuer Native-Testlauf
und kein Paketnachweis des Integrationspins.

`native.read` bleibt die exakte Sechser-Whitelist mit macOS-Provider, frischer
automatischer Freigabe, Before-Send-Revalidierung, äußerer Frist und
Größen-/Slotgrenzen. Die neue Testparametrisierung ergänzt `win32` neben `linux`
in `test_native_capability_unavailable_never_dispatches`; sie prüft eine
merge-relevante Trennung ohne produktive OS-Aufrufe. Der Reviewer führte den Test
nicht aus.

## Nachvollziehbarkeit des begutachteten Pythonstands

| Datei | SHA256 beim Review |
| --- | --- |
| `src/kirabridge/bridge_core/bridge.py` | `d20207365280184c793def14eeb97c02b390053400ddaf1b0046d7373749641f` |
| `src/kirabridge/mcp_gateway/server.py` | `4fa4965c0cdc6bb2d842b877076bed5c7c34cdd4b51749ab154ae728b662c2b2` |
| `src/kirabridge/task_manager/store.py` | `e4afbf6849e508dba1cc18720b5063f2c791baf45b571eaee348df9ed46ab285` |

Zusätzlich lesender AST-Vergleich: Gegen RC32 ändern sich in Bridge ausschließlich
`__init__`, `validate`, `platform_status`, `_execute_operation`; gegen Windows
ausschließlich `__init__` und `events`. In Store ändert sich nur `__init__`.
Das entspricht der vorgesehenen Vereinigung. In MCP kommen gegen RC32 die
Windows-Katalog-/Timeoutpfade, gegen Windows die RC31-Read-Dokumentation hinzu.

Die drei Versionsdateien enthalten im Arbeitsbaum konsistent
`0.8.0rc33.dev1`; während dieses laufenden Reviews waren ihre Indexeinträge noch
als `UU` markiert. Das ist ein erwarteter Zwischenzustand des Root-Mergevorgangs,
kein Hinweis auf verbleibende Konfliktmarker im Dateiinhalt. Vor Commit müssen
die Auflösungen gestaged und Index/Diff/Lock nochmals bestätigt werden.

## Grenzen und Abschlussvoraussetzungen

Der lesende Review ersetzt keine frischen Integrationschecks der geänderten
Python-/Store-/MCP-Verbindungen. Deren Ausführung und Resultate dokumentiert Root.
Keine Installation, Veröffentlichung oder neue Plattformabnahme des
Integrationspins wird durch diese statische Bewertung bestätigt. Historische
Paket-/Installationsbelege behalten ihre ursprünglichen Pins und Reichweiten.
