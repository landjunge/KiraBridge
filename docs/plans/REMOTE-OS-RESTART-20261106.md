# R3: dauerhafte Remotequittung nach echtem Core-Prozessrestart

Aktueller zusammengeführter Stand: [Integrationsübersicht](../BIGPLAN-INTEGRATION-STATUS-20261106.md).
Der unten noch folgende unabhängige Integrationsnachtest ist inzwischen erfolgt;
die ursprünglichen R3-Quell- und Laufbelege bleiben als Checkpoint erhalten.

06.11.2026 · Auftrag BP-REMOTE-OS-RESTART-20261106-R3.
Karte 188ce4729a62/83c362aa0e0a (#285), Claim 1c81e7674083 (#288).
Einziger Writer Codex01a1a7d1; eigener Worktree remote-os-restart-20261106,
Branch test/remote-os-restart-20261106-r3.

## Quelle und begrenzte Erweiterung

Ausgangsstand ist ausdrücklich R2
21d2e2cad8e9930931b02031addfc25d819a9ed3, nicht der weiterentwickelte native
Koordinations-/Masterstand. Produktdateien bleiben unverändert. Der TD-Export
a0dd4c39478b031e0e31d335c2a15435dfbc52eb aus R2 wird ausschließlich gelesen.
Alle 276 Dateien stimmen vor dem Test mit seinem vorhandenen Manifest überein;
Nachprüfung und SHA-Pins stehen im R3-Handoff.

R2 hatte Core-/SQLiteobjekte innerhalb eines Prozesses neu geöffnet. R3 erweitert
nur diese offene Grenze: eigene echte Core-Pythonprozesse mit privaten
Datenbanken, Zertifikaten und Loopbackports beenden, mit neuer PID/Runtimeinstanz
starten und dieselbe gespeicherte Quittung über den bestehenden Relay lesen.
Die 26 R2-Fälle und die M3-/M4-/C1-Abnahme werden nicht wiederholt.

## Zwei echte OS-Fälle

| Fall | Prozesswechsel | Exit vor/nach Restart | Test |
| --- | --- | --- | --- |
| SIGTERM nach dauerhaftem Abschluss | 50957 → 50968 | 0 / 0 | 1 bestanden, 7,68s |
| SIGKILL nach dauerhaftem Abschluss | 51081 → 51093 | −9 / 0 | 1 bestanden, 8,22s |

Der kontrollierte Punkt ist in beiden Fällen derselbe: Coretask completed mit
Receipt und finished-Zeit aus SQLite mode=ro gelesen, CLI-Fixture beendet und
genau ein ausgeführter Lauf, TD-Return tatsächlich als issued_bound ohne
Annahmeentscheidung zurückgelesen. Erst danach erhält der eigene Core das Signal.
Der harte Abbruch erzeugt bewusst keinen künstlichen UNKNOWN: Der nachgewiesene
Abschluss bleibt abgeschlossen. Ein Abbruch während aktiver Arbeit ist nicht
Teil dieser Prüfung und daraus nicht abgedeckt.

Nach Neustart unterscheiden sich PID und Core-instance_id; der startupbeobachtete
Produktbaumhash ist gleich. Der neue Relayclient liest auch nach Ablauf des
ursprünglichen Zustellfensters dieselbe Task-ID, denselben Receipt und dasselbe
Result. Seine reconcile-Abfrage und der erneut gelesene TD-Return stimmen ebenfalls.
Je isoliertem Fall bleiben alle Zähler bei genau eins:

- echter clientseitiger MCP-Aufruf task_submit;
- serverseitiger Eintritt in Bridge.submit, mit Task-/Requesthash protokolliert;
- dauerhaft gespeicherter Coretask;
- Aufruf des bereits vorhandenen deterministischen lokalen Python-Agenten.

Es gibt keine zweite Zustellung nach Restart und keine neue Queue. Die gleichen
Testtasknamen der zwei unabhängigen Fälle gehören jeweils zu eigenen Tenantdaten,
Gerätezertifikaten, Workspaces und Datenbanken; innerhalb eines Falls bleibt die
Originalkennung über den Prozesswechsel erhalten.

## Wiederverwendeter Testpfad und wichtige Profilgrenze

certificate, tls_server, intent, relay, final und configure kommen aus den
vorhandenen R2-/Handoff-Testhilfen. Der TD-HTTP-Server bleibt im Testelternprozess.
Das neue Child startet den echten Core, authentifiziertes MCP-HTTPS und den
bestehenden HttpHandoffPeer mit echter Leaf-/Geräteschlüsselbindung. Ein zuvor
gebundener Loopback-Socket wird ausschließlich an das eigene Child vererbt.
Zugangsdaten und Zertifikatschlüssel sind private synthetische Testdaten;
der Childlog und Belegtrace enthalten keine Granttoken.

Die Agentenroute bleibt genau die ausdrücklich synthetische R2-In-Memory-Fixture.
Der erste Vorbereitungsversuch scheiterte vor jeder Zustellung: Der unveränderte
Produktparser lehnt visible_handoffs.enabled=false als persistierte Konfiguration
korrekt ab. In dieser Testdatenbank standen 0 Tasks, die Fixture lief 0-mal.
Dieses rote Vorbereitungslog wird erhalten; es ist kein Produktregressionsbefund.

Der Childbootstrap validiert anschließend reguläre Konfiguration und
rekonstruiert nur im Testprozess die bereits von conftest verwendete
In-Memory-Fixture. Er bindet deren Executable ausdrücklich an owned-codex im
privaten Testverzeichnis und kennzeichnet die Readybelege mit
r2-owned-python-agent. Keine Änderung am Produktparser oder Visible-Gate.
Das beweist ausdrücklich kein produktiv konfigurierbares Managed-Profil,
keinen Fallback der sichtbaren Terminalroute und keine NativeMaster-Integration.
Der vertrauenswürdige synthetische lokale Grant benutzt dieselbe vorhandene
SecurityManager-API wie R2; im Elternprozess startet kein zweiter Dispatcher.

Uvicorn behandelt SIGTERM; der eingebettete Testbootstrap lässt nach dessen
Signalwiederholung den Bridge-Kontext geordnet schließen. Die Lifecyclebelege
enthalten ready, http_stopped und core_closed für normale Enden. Beim SIGKILL
fehlt ein solcher Abschluss erwartungsgemäß; der OS-Wait liefert −9.
Alle vier Corekinder werden mit ihren ursprünglichen eigenen Handles abgewartet.
Eine unabhängige ps-Abfrage fand anschließend keine dieser vier PIDs mehr.
Private TLS-Server/Clients werden durch vorhandene Contextmanager geschlossen.

## Prüfung wiederholen und Belege

Explizite Umgebung wie bei R2, vorhandene Pythonabhängigkeiten ohne Neuinstallation:

    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
    KIRABRIDGE_TEST_REMOTE_THREADDESK_SOURCE=/GEPRUEFTER/TD-a0dd-SNAPSHOT/src \
    /Users/landjunge/KiraBridge/.venv/bin/python -c \
    'import sys; sys.path.append("/usr/local/lib/python3.11/site-packages"); import pytest; raise SystemExit(pytest.main(["-q", "tests/test_remote_os_restart.py"]))'

Die beiden Fälle wurden gezielt getrennt ausgeführt; bestandenes SIGTERM wurde
für den SIGKILL-Fall nicht erneut gestartet. Richtige Nachweise sind die zwei
separaten Logs, keine erfundene gemeinsame Laufzeit. Ruff/Format-/Diffprüfung
und Quellmanifest werden separat festgehalten. Unabhängiger Review, endgültiger
Commit und die genaue Artefaktliste stehen im Handoff:
~/.local/share/kirabridge/backups/bigplan-remote-os-restart-20261106-r3/.
Je Fall liegt r3-evidence.json neben privatem Lifecyclelog und Core-Datenbank.

## Grenzen und nächster Schritt

Lokal getestet auf dem vorhandenen Intel-Mac; keine Windows-/Linux-VM-Abnahme.
Keine echte Codex-/Grok-/sonstige Modellanfrage, keine Zusatzabrechnung.
Nicht geprüft: In-flight-Abbruch/UNKNOWN-Recovery, TD-Prozessrestart/Hardkill,
Maschinenneustart, launchd/systemd, Handy/Browser und produktive Remoteumgebung.
Keine Änderungen an Debian, VMs, Produktinstallation, Nutzerprofilen oder
historischen UNKNOWNs. Windows-W1-Freeze und offene Policy-Frage bleiben
außerhalb dieses Pakets. README/Website brauchen für diesen internen
Testnachweis keine neue Produktverfügbarkeitsaussage.

Nächster begrenzter Schritt: unabhängige Prüfung der R3-Belege und der getrennt
untersuchten R2-/NativeMaster-Integrationsgrenzen. Erst ein gesonderter geeigneter
Integrations-/Stagingauftrag kann ein tatsächlich konfigurierbares Profil und
dessen Remoteabnahme belegen. Keine automatische Installation aus diesen Tests.
