# Big Plan: aktueller Integrationsstand

6. November 2026. Diese Übersicht führt die angenommenen Quellpakete und ihre
Prüfgrenzen zusammen. Die ursprünglichen Paketberichte bleiben historische
Checkpoints; ein dort damaliger offener Nachtest ist kein neuer Arbeitsauftrag.
Das laufende Arbeitsgedächtnis bleibt ThreadDesk `188ce4729a62` mit der gemeinsamen
Koordination `482f593429ad`.

| Bereich | Quellen und belegter Stand |
| --- | --- |
| Native Koordination und Routing | C1 `0e755e8` und korrigiertes C2 `843db41` integriert. C2 ist unabhängig angenommen; der frühere Pin `6159640` bleibt mit seinen roten Belegen verworfen. Bestehende Claims, Seals, Budgets und Leases tragen die Autorität. |
| CLI-Rückmeldungen | `cb87a9e` hält Antworten und Ergebnisse passiv im richtigen Postfach. Empfang, Verarbeitung und Arbeitsstart bleiben unterschiedliche Zustände. Installierte ältere Clients können ausdrücklich `--inbox-only` verwenden. Ein verarbeitetes Resultat löst keinen weiteren Bestätigungs-Prompt aus. |
| Fehlerdiagnostik | Transportkorrektur `da8b265` und begrenzte native Fehlerbelege `a821d60` sind unabhängig angenommen und integriert. Historische UNKNOWNs bleiben erhalten. |
| Remote und nativer Core | Remote-R2-Dateien aus `21d2e2c` wurden mit dem nativen Stand kombiniert. Produktpin `2b18cad` hat einen unabhängigen Schnittstellenreview mit 13 verschiedenen Gegenproben; die getrennten Teilläufe werden nicht addiert. |
| Prozessneustarts | R3 `478e4f4`, integriert als `6067fb0`, belegt SIGTERM und SIGKILL nach dauerhaftem Abschluss. R4 `4609424` belegt SIGKILL während einer begonnenen synthetischen Ausführung: derselbe Receipt wird als `UNKNOWN` mit `dispatcher_restart` gelesen, ohne zweite Einreichung oder Ausführung. R4 hat zusätzlich einen unabhängigen Quellenreview. |
| Gemeinsamer Remote-Nachtest | Am Integrationspin `c38a8945b38d3d27a3878efa6ba396ee22163665` bestanden 29 Fälle in 66,67 Sekunden: 26 R2, zwei R3 und ein R4; null Skips, Fehler oder Fehlschläge. Tatsächliche Quellenimporte, beide Gitpins und die gelockte Testumgebung sind im ausführenden Prozess gebunden. |
| Automatische CI-Kosten | `9233443` ist nach unabhängigem Nachreview angenommen. Automatische Ereignisse wählen vorhandene Linuxrunner; Hosted-Macs und Paketworkflows benötigen einen manuellen Lauf. Alle Plattformprüfungen bleiben als eigene Gates erhalten. Der frühere falsche Case-Beleg auf `7adb9d2` bleibt historisch `NEEDS_FIX`. |
| Remote-CI | Der korrigierte Pin `c78800c` ergänzt gelockte M4-Testabhängigkeiten, getrennte TD770-/M4-Testprozesse und frische JUnit-Nachweise ohne Remote-Skips. Der unabhängige Nachreview `188ce4729a62/80977bbb5d7a` ist angenommen. Der frühere Pin `45cb47f` bleibt wegen übersehener JUnit-Aggregatzähler `NEEDS_FIX`; seine tatsächlichen konsistenten Läufe bleiben gültige Belege. Der tatsächliche CI-Lauf wird gesondert im Board festgehalten. |

Die bisherigen Integrationsläufe mit 111 bestandenen Fällen und 24
Dependency-Setupfehlern sowie dem gezielten erfolgreichen Nachlauf dieser 24
Fälle bleiben getrennte Belege. Sie werden weder zu einem neuen sauberen
135er-Lauf erklärt noch durch den späteren 29er-Lauf ersetzt. Dasselbe gilt für
überlappende Gate-, Schema- und Quellenreviewfälle.
Der korrigierte Validator bestätigte den unveränderten echten 29er-Bericht mit
dessen ursprünglicher Startzeit und Exitcode erneut; dafür wurde kein
Prozesslauf wiederholt. Die 56 Gatefälle des Autors und acht unabhängigen
gezielten Gegenproben sind eigene Prüfumfänge.

## Betrieb und offene Wirkungen

Die Prüfungen verwenden eigene Datenbanken, TLS-Endpunkte und begrenzte
deterministische CLI-Fixtures. Beim R4-Fall wurden tatsächlicher Beginn,
Running-Zustand, Receipt, neuer Core-PID und neue Generation geprüft. Beide
Coreprozesse und die Fixture waren danach nachweislich beendet. Es wird kein
erfolgreiches Ergebnis aus dem UNKNOWN-Zustand abgeleitet.

Der separat neue kurze Grok-Transporttest antwortete einmal korrekt. Die CLI
meldete `grok-4.7-build` bei angefordertem `grok-4.7`; effektive Denkstufe und
Aliasgleichheit sind damit nicht bewiesen. Dieser Versuch wiederholt keinen
historischen Grok-Review und belegt keine vollständige Providerkette.

Die lokalen Quellenprüfungen ändern keine installierte KiraBridge und aktivieren
kein produktives AutoNext-Profil. Zuletzt beobachtet wurde RC39 aus
`8d331314b608`. Installation, reale Providerketten, produktiver Remoteweg,
Mehrbenutzer-, Mobile- und native Plattformabnahmen behalten ihren eigenen Status.
Eine abgesicherte Quellenbranch ist keine Release- oder Downloadzusage.

Windows für Dirk bleibt bei null gestarteten nativen Phasen. Die konkrete
unbeantwortete Ausnahme für den einen hashgepinnten Runner-Kindprozess mit
`-ExecutionPolicy Bypass` wird aus einer allgemeinen Fortsetzung nicht abgeleitet.
Das stoppt unabhängige autorisierte Entwicklungsarbeit nicht. Historische
Host-/Grok-UNKNOWNs, VM-/Policy-/Profilzustände bleiben davon unberührt.

## Einstieg

[Nativer Core/MCP-Vertrag](COORDINATOR-NATIVE-20261106.md) ·
[versiegeltes Routing](COORDINATOR-NATIVE-ROUTING-20261106.md) ·
[Remoteintegration](NATIVE-REMOTE-INTEGRATION-20261106.md) ·
[R3-Prozessneustarts](plans/REMOTE-OS-RESTART-20261106.md) ·
[R4-InFlight-Recovery](plans/REMOTE-INFLIGHT-RECOVERY-20261106.md) ·
[CI-Kostengates](CI-COST-GATES-20261106.md) ·
[Remote-CI-Quellenbindung](REMOTE-CI-PIN-GATE-20261106.md).

## English

The integrated source combines native coordination/routing, passive result
delivery, bounded diagnostics and the existing remote contract. The combined
local locked test run passed 29 remote cases, including completed-task restarts
and one in-flight Core crash. The latter preserves the original receipt as
UNKNOWN without resubmission. Earlier failed, partial and overlapping runs stay
separate evidence. Historical package checkpoints do not request repeated work.
CI source review, actual CI execution, installation and live platform/provider
acceptance are separate states. Automatic hosted-Mac fanout is disabled in the
reviewed workflow revision; manual platform checks remain required where applicable.
