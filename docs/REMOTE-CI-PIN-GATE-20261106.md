# Remote CI source and execution gate / Quellen- und Ausführungsgate

Stand / Date: 2026-11-06. Auftrag / Task: BP-REMOTE-CI-PIN-GATE-20261106.
Basis / Base: `9233443a4a7b3057d9b3ab8eb58966acf01f21b5` (separate cost gate).

## Deutsch

Verify behält seine Jobnamen, Linuxrunner, manuellen macOS-Umfang und Kostentrigger.
Die bestehende Legacy-Suite bleibt an TD `770bbc9f0c0a02699cc93cad47d2e2c3782f7080`
und TollGate `53fc57cc2e082d022e65e5929cb2a1e186fba852` gebunden. Nur
`test_remote_relay.py` (R2) und `test_remote_os_restart.py` (R3) werden daraus
explizit ausgenommen; reine KB-Contract-/Peerfälle bleiben regulär enthalten.

Ein zweiter öffentlicher TD-Checkout bindet die Remote-Suite an M4
`a0dd4c39478b031e0e31d335c2a15435dfbc52eb`. Ein zweiter frischer Pythonprozess
setzt beide TD-Sourceenvs und PYTHONPATH auf genau KB-src und M4-src. Keine
sys.modules-Löschung oder Modulneuladung simuliert die Isolation. R3 erfordert
POSIX; fehlende Voraussetzung ist ein Fehler des Gates, kein akzeptierter Skip.
R4 ist ein getrennter Auftrag und gehört nicht zu diesem Gate.

Die testbezogene Gruppe `remote-ci` enthält M4s vollständige Basis-/Servergrenzen:
pypdf>=6.19,<7, jsonschema==4.25.1, fastapi>=0.110 und die mit KB geschnittenen
uvicorn>=0.54,<1 sowie httpx>=0.28,<1. UV hat den Lock regulär neu aufgelöst:
FastAPI0.162.0, Pypdf6.21.4, jsonschema4.25.1; Uvicorn0.54.0 und HTTPX0.28.1
bleiben erhalten. Annotated-doc0.0.5 und OpenTelemetry-API1.45.2 kommen als
FastAPI-Abhängigkeiten hinzu. Keine manuell erfundenen Lockzeilen, globalen
site-packages oder TD-Packageinstallation. Runtime-Downloads sind ausgeschaltet.
Die Änderung des gemeinsam gelockten jsonschema wird durch gezielte KB-Contract-
und MCP-Schemafälle geprüft; das ersetzt keine vollständige Plattformabnahme.

[scripts/ci_remote_tests.py](../scripts/ci_remote_tests.py) prüft vor pytest.main
im selben Interpreter HEAD, tatsächliche Commitblobs, nicht getrackte Quelldateien,
276 M4-src-Dateien, konkrete KB-/TD-Importe, gecachte Module und die Herkunft der
installierten Distributionen. Nach pytest werden Quellen und Importe erneut
geprüft. Jeder Aufruf braucht ein neues Berichtverzeichnis. Provenienz erfasst
Interpreter/Version, argv/pytest-Argumente, cwd, ausgewählte Umgebungswerte,
Importdateien, Dependencies und Quellmanifeste; sie wird auch ins CI-Log geschrieben.
JUnit erhält eine zufällige laufgebundene Suitekennung. Remote akzeptiert nur
echten Exit0, einen frischen vollständigen Bericht, 0Skipped/Errors/Failures und
positive tatsächliche testcase-Zahlen **in beiden** Modulen. Fehlender, leerer,
veralteter, einmoduliger oder fehlerhafter Bericht scheitert. Die statische aktuelle
Auswahl entspricht 26 R2- und 2 R3-Fällen; allein die spätere Ausführung belegt sie.
Die absichtlichen Skips anderer Legacyplattformen sind davon getrennt.

CI-Aufrufe stehen in [ci.yml](../.github/workflows/ci.yml). Lokal dieselben
Umgebungswerte setzen, `--expected-kb` auf den vollen eigenen Commit und `--td`
auf einen eigenen sauberen Checkout setzen; `--report-dir` darf noch nicht
existieren. Nur einen vorhandenen Interpreter verwenden. Ein lokaler enger Lauf
auf macOS Intel ist keine Linux-/Hosted-/ARM-/Remoteproduktivabnahme. Dieser
Quellpatch startet weder Actions noch Provider, Dienste oder VMs und installiert
kein Produkt. Root übernimmt Freeze und unabhängigen Review vor einem koordinierten
Push. README DE/EN, Webseite und Downloads sind durch diesen internen CI-Patch
inhaltlich nicht betroffen. Fehlerläufe bleiben in privaten Nachweisen erhalten.

## English

Verify preserves the existing cost gate, job names, Linux runners and explicit
manual macOS scope. Legacy tests retain TD770 and TollGate at the full pins above,
excluding only the R2 relay and R3 OS-restart modules. Pure KB contract/peer tests
remain in the regular suite. A second pinned M4 checkout and a fresh Python
process run exactly R2/R3 with both TD source variables and an explicit KB/M4
PYTHONPATH. Python module caches are never rewritten to imitate isolation.

The locked test-only `remote-ci` group respects all M4 base/server requirements,
including exact jsonschema4.25.1. No global dependency overlay or TD distribution
is installed. Python runtime downloads are disabled. The helper verifies actual
source blobs, the 276-file M4 source inventory, imports and dependency origins in
the interpreter that calls pytest.main, then verifies sources/imports again.
Provenance records interpreter, command, environment, paths, versions and pins.
A fresh run directory, unique suite binding, true pytest exit0, fresh JUnit,
zero skips/errors/failures and positive executed case counts in **both** modules
are required. Old/empty/missing/partial reports cannot grant acceptance. R4,
actual hosted CI, Linux/ARM acceptance and deployment remain separate. Negative
gate and focused schema tests are in [test_ci_remote_tests.py](../tests/test_ci_remote_tests.py),
[test_remote_task_contract.py](../tests/test_remote_task_contract.py) and
[test_mcp_schema_validation.py](../tests/test_mcp_schema_validation.py).
