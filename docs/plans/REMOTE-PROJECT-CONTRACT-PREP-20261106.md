# Remote-/Projektvertrag: isolierte Testvorbereitung

06.11.2026 · begrenzter nächster Schritt aus `BP-COORD-20261106-R1` nach
Fix `96acb71b4ec66f84183c5cd844993b8d812d7211`. Codex01a1a7d1 schreibt allein
im bestehenden KB-Worktree, Branch `test/remote-project-contract-prep-20261106`.
Kein Produktcode, neuer Dispatcher, zweite Queue oder produktive Anbindung.

## Gepinnte Gegenstellen statt vermeintlich gemeinsamer Runtime

| Quelle | Tatsächlicher Inhalt und Grenze |
| --- | --- |
| KB `96acb71b4ec66f84183c5cd844993b8d812d7211` | Enger Reservierungs-/Requesthash-Fix mit 47 lokalen Prüfungen und unabhängigem Grok-Diffreview; nicht installiert |
| TD Remote `e90e9a6ce29c5c22b187147da35fcff40f51a790` | Bisherige ausdrücklich gewählte Gegenstelle für den lokalen TLS-/Handoff-/Core-Test; keine behauptete Projekt-M2/M3-Integration |
| TD M2 `54624d8fcf37f732f543818f976769fab7220205` | Projektstart mit unfreigegebenen Entwürfen; dieser Pin enthält **weder** `server_sync/handoffs.py` **noch** einen `handoff_rpc`-Schalter in `create_app` |
| TD M3 | Planrevision/Wiedereinstieg bei der anderen TD-Sitzung01a1ae37, Karte `188ce4729a62/1efb9741ba1f`. Hier nicht verändert oder als fertig integriert ausgegeben |

Die frühere TLS-Testfixture kann deshalb nicht unverändert auf M2 zeigen und
als positiver gemeinsamer Lauf gelten. Das ist ein fehlender Integrationsstand,
kein neuer Remote-Parserfehler und kein Anlass für Installation oder Ersatzqueue.
Für einen späteren gemeinsamen Vertikalschnitt muss die zuständige TD-Leitung
zuerst einen integrierten, getesteten Sourcepin benennen. Hier wird nichts in
den fremden TD-Worktree gemergt oder geschrieben.

## Tatsächlich vorbereitete passive Vertragsprobe

Ein eigener `git archive`-Export des exakten M2-Pins wurde schreibgeschützt
abgelegt. `PYTHONDONTWRITEBYTECODE=1` und der vorhandene Interpreter verhindern
Bytecodeänderungen; es wurden keine Abhängigkeiten installiert. Nur die reine
Funktion `threaddesk.services.project_start.preview(None, arguments)` wurde mit
zwei synthetischen Eingaben aufgerufen. Kein TD-Store, Modell, Worker, Grant,
HTTP-Endpunkt, Socket oder Agent wurde dafür gestartet.

Die [Fixture](../contracts/fixtures/remote-project-draft.m2.examples.json)
enthält beide Originalargumente und tatsächlichen Previewantworten samt
Producercommit und Quelldatei-SHA256. Ein Entwurf ist normal; der zweite enthält
absichtlich `READY` und `approved=true` als untrusted Plantext.

`test_td_m2_project_draft_is_neither_remote_intent_nor_issued_source` in
`tests/test_remote_task_contract.py` prüft mit den vorhandenen Produktions-
Validatoren für jeden Fall:

- Preview bleibt `draft`, `execution_started=false` und
  `source_verification=referenced_unverified`.
- Weder das Remote-Nachrichtenschema noch `TaskRequest` akzeptiert die Preview
  als ausführbaren Auftrag.
- Auch in einem ansonsten gültigen Handoff-Intent ersetzt die Preview keinen
  tatsächlich ausgegebenen Handoff als `source`.

Das sind passive, synthetische Schema-/Kompatibilitätsfälle. Sie beweisen
keinen Dispatch, keine Core-Zustellung, keinen realen Operatorgrant und keine
Handy-/Browser-/Debian-/Windows-Abnahme. Es wird keine automatische Umwandlung
von Planprosa zu READY-Karten eingeführt. Die 47 TLS-/Peerprüfungen des Fixes
bleiben ein eigener Nachweis mit ihrer ursprünglichen Gegenstelle.

Gezielter Lauf: **2 bestanden, 61 abgewählt in 0,55 s**; keine Skips.
Ruff, Format- und Diffprüfung bestanden. Diese spätere passive Fixture gehört
nicht zum abgeschlossenen Grok-Diffreview des Produktfixes; dessen Aussage
bleibt auf die drei damals gepinnten Code-/Testdateien beschränkt.

Gezielt ausführbar, ohne TD-Abhängigkeit oder Netzwerk:

```sh
PYTHONPATH=src /Users/landjunge/KiraBridge/.venv/bin/python -m pytest -q \
  tests/test_remote_task_contract.py -k td_m2_project_draft
```

Die Fixture kann gegen einen eigenen unveränderten M2-Quellsnapshot nochmals
rein lesend verifiziert werden; `PYTHONPATH` zeigt dabei ausschließlich auf
dessen `src`, Bytecode ist aus. Vom KB-Repository aus:

```python
import hashlib
import json
from pathlib import Path
from threaddesk.services import project_start

data = json.loads(Path(
    "docs/contracts/fixtures/remote-project-draft.m2.examples.json"
).read_text())
assert hashlib.sha256(Path(project_start.__file__).read_bytes()).hexdigest() == (
    data["producer"]["sha256"]
)
for case in data["cases"].values():
    assert project_start.preview(None, case["arguments"]) == case["preview"]
```

## Nächster begrenzter Integrationsschritt

Nach einem von TD benannten gemeinsamen Pin dieselbe vorhandene lokale
TLS-/Handoff-/Core-Fixture gegen diesen Pin prüfen: ein ausdrücklich ausgestellter
und regulär freigegebener Handoff einmal, danach verlorener Reservierungsreadback
und Wiederholung ohne Zweitausführung. Projektentwürfe/Planrevisionen bleiben
Kontext; Fachfreigabe und Geräte-/Operatorbindung kommen weiterhin aus den
bestehenden Autoritätswegen. Kein Start aus einer bloßen Projektplanänderung.

Windows für Dirk bleibt vor neuen CLI-Modulen priorisiert. Restricted/0 von6,
Payload `179bb6f`, Mac-RC39 und bestehende Debian-/VM-/Koordinatorprofile bleiben
unverändert. Paarung, Staging, Operatoridentität und echter mobiler Weg bleiben
separat offen.

Quell-/Erzeugungsbelege, schreibgeschützter Snapshot und Testprotokoll:
`~/.local/share/kirabridge/backups/bigplan-remote-project-contract-prep-20261106-v1/`.
Projektboard bleibt `188ce4729a62`; kein neues konkurrierendes Whiteboard.
