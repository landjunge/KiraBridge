# KiraBridge 0.8.0 RC52

macOS-Kandidat nach RC51 (`e5c49bf`). Dokumentierter Quellstand ist `main`
`d725542`. Schwerpunkt: gleichzeitige Grok-Teamsitzungen halten ihr Ergebnis,
Boards sind für Leser mit den neuesten Einträgen zuerst erreichbar, und die
Installer-Pakete entstehen bei jedem Release automatisch.

Neu gegenüber RC51:

- Gleichzeitige Grok-Sitzungen. Enden mehrere Sitzungen zugleich, lief die
  Prozesszählung beim Aufräumen (`reap_process`) in ihr Limit von 0,5 s, und
  das bereits fertige Ergebnis wurde als `unknown`/`process_cleanup_unknown`
  verworfen. Der Grok-Adapter gibt jetzt wie der Qwen-Adapter
  `census_timeout=2` mit. Ein deterministischer Test sichert das ab; ein
  Integrationstest fährt vier verwaltete Sitzungen eines Assignees gleichzeitig.
- ThreadDesk-Boards lesbar. `whiteboard_list` kennt `order="oldest"`
  (Standard, unverändert) und `order="newest"`; bei `newest` zählt `offset` vom
  Ende, die Seite bleibt aufsteigend. Neu ist das lesende `whiteboard_search`
  (ein Board, Teilstring ohne Groß-/Kleinschreibung, Abfrage bis 200 Zeichen,
  1 bis 20 Treffer, neueste zuerst, Ausschnitte bis 200 Zeichen). Gleiche
  Workspace- und ID-Prüfung wie `whiteboard_list`; Ergebnisse sind Daten, keine
  Anweisung. `order` wirkt auf Inhaltsseiten (`include_content`).
- Teamaufträge in der CLI. `kirabridge team work` kennt `--after`, `--limit`
  (1 bis 100) und `--latest N`; bei vollen Seiten steht `next_after` im Ergebnis.
- Installer. Der Workflow `native-macos-dmg.yml` nutzt SHA-gepinnte Actions
  (vorher `startup_failure`) und läuft bei jedem veröffentlichten Release. Ein
  zweiter Job prüft die Prüfsummen und hängt beide DMGs samt `.sha256` an.
- opencode. `opencode_http_v2` ist in der Bereitschaftsprüfung wie
  `opencode_http` von der Ausführbare-Datei-Prüfung ausgenommen.
- Tests unabhängig von Terminalfarbe und `umask` (Codex-Interim, Qwen-Recovery).

Offen und nicht Teil dieses Releases:

- Zustellung der Koordinator-Fortsetzung an eine vom `claude daemon` gehostete
  Hintergrundsitzung (heute nur Terminalfenster, Codex nativ und getrennte
  verwaltete Sitzungen).
- Index für ThreadDesk-Einträge (Entwurf liegt vor, Umsetzung im ThreadDesk-Repo).
- Gemini und Copilot sind nicht angemeldet.
