# R4: UNKNOWN nach Core-Abbruch während begonnener Fixture

06.11.2026 · BP-REMOTE-INFLIGHT-RECOVERY-20261106-R4.
Task188ce4729a62/44db82af029a (#311), Claim e7fdc51f2fba (#312).
Einziger Writer Codex01a1a7d1, eigener Branch
test/remote-inflight-recovery-20261106-r4.

## Quelle und einziger neuer Fall

Basis ist der angenommene kombinierte Stand
6067fb0907bcdeaf91ef3ea6608b1468190a2536. Produktdateien bleiben bytegleich.
Der schreibgeschützte TD-M4-Export
a0dd4c39478b031e0e31d335c2a15435dfbc52eb wurde vor und nach dem Lauf in
allen 276 Dateien gegen das vorhandene R2-Manifest geprüft.

R4 verwendet das vorhandene R3-TLS-/Core-/TD-Harness und fügt genau einen
ausgeführten POSIX-Fall hinzu. R3s zwei Abschluss-Restartfälle und frühere
R2-/Native-/M4-Suiten wurden nicht erneut ausgeführt. Das isolierte
In-Memory-Agentenprofil von R2 bleibt eine ausdrücklich synthetische Fixture,
kein produktiv konfiguriertes Remoteprofil oder sichtbarer Terminalfallback.
Quelle und lokale Prüfung sind keine produktive Remoteabnahme.

## Beobachtung und geprüfter Recoveryvertrag

Der echte Core nahm genau einen Remoteauftrag an. Die eigene Pythonfixture
schrieb ihren Counter und einen Startmarker mit fsync. Ihr Nonce-/PID-/PPID-Beleg
wurde zusätzlich mit frischem ps als lebender Prozess unter diesem Core bestätigt.
MCP-Readback und SQLite mode=ro zeigten running mit nichtleerem Receipt.
Erst danach erhielt das selbst erzeugte Corehandle SIGKILL.

| Beleg | Tatsächlich beobachtet |
| --- | --- |
| Core vor Kill | PID56254, aktive Fixture PID56262, Task running |
| Coreende | OS-Exit −9 |
| Neuer Core | PID56269, andere Runtimegeneration, gleiche private Datenbank |
| Originaltask | remote-inflight-one |
| Erhaltener Receipt | c6f45b6f-a14f-4404-ab26-32b7405b44a1 |
| Recovery | unknown, reason=dispatcher_restart |
| Abschluss/Ergebnis | finished=null, result=null |
| Zähler über den gesamten Fall | 1 ClientSubmit / 1 ServerBridgeSubmit / 1 Coretask / 1 Fixturestart |
| Aufräumen | Fixture selbst beendet; neuer Core geordnet beendet; alle drei PIDs abwesend |

Store.recover markiert auf diesem Quellstand noch accepted/running gespeicherte
Tasks beim exklusiven Dispatcherstart als UNKNOWN und erhält die letzte
Beobachtung. Diese wurde nach dem Kill, vor dem neuen Corestart, aus der
Datenbank gesichert und mit dem Recoverybeleg verglichen. Dadurch wird
fortlaufender Fortschritt vor dem Kill nicht mit einem zufälligen älteren
MCP-Snapshot verwechselt.

Der neue Relayclient liest über deliver und reconcile denselben Task und
Receipt, auch mit abgelaufenem Zustellfenster. Er sendet keinen zweiten Submit.
Nach vollständigem Cleanup wurden DB und Servertrace erneut gelesen:
ein unveränderter UNKNOWN, kein Ergebnis und weiterhin genau ein Submit/Start.
Kein No-effect, Completion, TD-Return oder Operatorentscheid wird daraus erfunden.
Die TD-Testwhiteboardprüfung zeigte keinen synthetischen Ergebnistext.

## Begrenzte Fixture und Ownership

Die neue kleine Pythonfixture läuft ausschließlich als owned-codex im privaten
Testverzeichnis. Sie liest den Testprompt, emittiert lediglich thread.started und
turn.started und wartet auf eine private Nonce-Datei. Sie liefert absichtlich
keine Agentenantwort und kein turn.completed. Counter und Start-/Exitmarker
werden dauerhaft geschrieben; Marker werden atomar ersetzt.

Ein eigener Zehnsekunden-Alarm begrenzt auch das anfängliche stdin-Warten.
Zusätzlich ist die Warteschleife zeitlich begrenzt. Der Elternprozess setzt
sein Freigabesignal im finally-Block, auch bei fehlerhafter Prüfung.
Im beobachteten Lauf endete die Fixture durch Freigabe nach knapp drei Sekunden.
Die Deadline-Auslösung selbst wurde nicht zusätzlich provoziert.
Die im Exitmarker wiederverwendete PPID bezeichnet den ursprünglichen Elternprozess.

Nur der ursprüngliche eigene Core-Prozesshandle wurde hart beendet. Die
Fixture-PID wurde ausschließlich gelesen, nie signalisiert. Eine Abwesenheits-
prüfung nach dem Exitmarker und anschließend erneut nach dem Test fand weder
Fixture noch alten/neuen Core. Fremde Prozesse, VMs und produktive Dienste waren
keine Ziele. Private TD-/TLS-Ressourcen schließen über bestehende Contextmanager.

## V5-Provenienz und Ergebnis

Der einzige Test bestand im ersten Lauf: 1 passed, 0 errors/failures/skips,
7,23s. Zwei anyio-AssertRewritewarnungen aus den vorab importierten
Testabhängigkeiten bleiben im vollständigen Log erhalten. Sie betreffen keine
übersprungenen R4-Assertions; es wurde nichts unterdrückt oder erneut ausgeführt.

Vor dem Test wurden tatsächlicher Interpreter, Aufruf, cwd, PYTHONPATH,
effektiver Importpfad und aufgelöste Projekt-/Dependencymodule gespeichert.
Der verwendete KB-Import stammt aus diesem Worktree, der TD-Import aus dem
gepinnten schreibgeschützten M4-Export. Die ursprünglichen editable-venv-Pfade
bleiben sichtbar im Beleg; sie wurden nicht global verändert.
Python3.11.15, FastAPI0.136.1 und Starlette1.8.0 wurden tatsächlich verwendet.
Weitere Versionen/Herkunftspfade stehen im maschinellen Laufbeleg.
Der bestehende globale Sitepackagespfad wurde nur lokal nach dem belegten
FastAPI-Fehlen im gewählten venv ergänzt. Keine Abhängigkeit wurde installiert.

Parent-Provenienz und vollständiger reproduzierbarer Aufruf stehen in
RUN-SCOPE.json und run-01-provenance.json. Die Child-Readybelege enthalten
zusätzlich Interpreter, cwd, PYTHONPATH, geladene Dependencypfade und den
startbeobachteten Produktbaumhash. Nach dem Lauf wurden die drei getesteten
Pythondateien erneut gegen die vorab gespeicherten Hashes abgeglichen.

Gezielter Testknoten:

    tests/test_remote_os_restart.py::test_inflight_core_kill_recovers_original_unknown_without_replay

Rohlog, JUnit, Fsyncmarker, Zustände vor/nach Kill/Restart, Lifecycletrace,
Counter, Datenbank und post-test-verification.json liegen privat unter
~/.local/share/kirabridge/backups/bigplan-remote-inflight-recovery-20261106-r4/.
Finale Quellpins/Manifest/Bundle und unabhängiger Reviewstatus stehen im Handoff.

## Verbleibende Grenzen

Der vorhandene Recovery-/NoReplay-Vertrag hielt für genau diesen lokalen Fall;
kein Produktfix war dafür erforderlich. Kein Nachweis für echte Modellanbieter,
produktive Remoteprofile, Handy/Browser, TD-Prozessrestart, Maschinenneustart,
Dienstmanager oder Windows/Linux-VMs. Ebenso keine Behauptung einer
Paketabhängigkeits-/Installationsabnahme aus dieser vorhandenen Testumgebung.
Alte UNKNOWNs, Produktinstallation und Rechte wurden nicht verändert.
README/Website benötigen für diesen internen Test keine neue Verfügbarkeitsaussage.

Nächster Schritt: unabhängige Rootprüfung von Test-/Rohbelegen und exaktem
Quellpin. Integration, Push, Installation und weitere Abnahmen bleiben getrennte
Wirkungen. Dieses Paket startet keine weitere Test- oder Aufgabenserie.
