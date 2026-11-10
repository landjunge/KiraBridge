# KiraBridge 0.8.0 RC46

macOS-Kandidat nach RC45 (`0b1d937`). Ziel: Der Installer verwaltet die ThreadDesk-Bibliothek
für Kira selbst, statt dass sie von Hand bereitgestellt und in der Konfiguration gewählt wird.

Neu gegenüber RC45:

- Das Paket enthält die ThreadDesk-Bibliothek am Pin des Repos (`LEGACY_TD` in
  `scripts/ci_remote_tests.py`, derselbe Stand wie die CI-Legacy-Spur, aktuell `aa940db`):
  `src` und `pyproject.toml` aus `git archive`, jede Datei mit SHA256 im Manifest.
- `install` legt sie einmal unter `install/shared/threaddesk-<pin>` ab. Eine vorhandene
  Bibliothek wird nur weiterverwendet, wenn sie bytegleich ist (`__pycache__` ausgenommen).
- `install` und Update setzen in einem vorhandenen `[threaddesk]`-Abschnitt nur
  `source_root` und `command` auf diese Bibliothek und das Python der aktiven Release.
  Die alte Konfiguration liegt im Transaktionsbackup (`config.before.toml`); `rollback`
  setzt genau diese zwei Werte zurück, solange sie seitdem niemand geändert hat. Andere
  Werte, Kommentare und Zugangsdaten bleiben unverändert. Ohne passenden Abschnitt wird
  nichts angelegt.
- Dynamische ThreadDesk-Werkzeuge tragen nur noch ein `td_`-Präfix: aus
  `td_td_whiteboard__*`, `td_td_graph__*`, `td_td_trash__*` und `td_td_library_usearch`
  werden `td_whiteboard__*`, `td_graph__*`, `td_trash__*` und `td_library_usearch`.
  ThreadDesk vergibt `td_` für seine Befehlswerkzeuge bereits selbst; KiraBridge setzte
  es ein zweites Mal davor. `_u` steht weiter für einen Unterstrich im Befehlsnamen.

Lokaler Intel-Build; kein öffentliches Release, kein Upload.
