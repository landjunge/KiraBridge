# KiraBridge 0.8.0 RC45

macOS-Kandidat nach RC44 (`54daa24`). Ziel: Kira arbeitet mit ThreadDesk v0.2.0 statt
mit dem alten Stand `770bbc9` (TD-P15).

Neu gegenüber RC44:

- ThreadDesk-Pin auf TD_PIN_SHORT (v0.2.0 plus
  [ThreadDesk PR #111](https://github.com/landjunge/threaddesk/pull/111)). Er gilt für
  die CI-Legacy-Spur, `scripts/ci_remote_tests.py` und `scripts/install_cli_routing.py`.
  Das Paket liefert ThreadDesk nicht mit. Die Quelle liegt weiter unter
  `~/.local/share/kirabridge/install/shared/threaddesk-<sha>/src` und wird über
  `threaddesk.source_root` in der Konfiguration gewählt.
- Mit 0.2 sieht Kira über den dynamischen ThreadDesk-Katalog zusätzlich Whiteboard
  (`td_td_whiteboard__*`), Graph und Relationen (`td_td_graph__*`), Papierkorb
  (`td_td_trash__*`, Schreiben über `td_command_invoke`) und die Suche
  (`td_search_threads`).
- `td_get_thread` und `td_generate_prompt` liefern höchstens 100000 Zeichen und melden
  `truncated` und `next_offset`. Mit `max_chars` und `offset` kann Kira weiterblättern.

Lokaler Intel-Build; kein öffentliches Release, kein Upload.
