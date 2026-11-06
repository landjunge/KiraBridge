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
| Fortsetzung im bestehenden Auftrag | `4b821c6` ergänzt die interne Zuordnung vorhandener Karten, gemeinsame logische Claims, Wiederherstellung versiegelter Aufträge und Completion-Verarbeitung. Der separate lokale Supervisor läuft aus `ed313e0`. Zwei konkrete Textaufgaben wurden mit vier nativen Codex-Turns und zwei technischen Abnahmen bearbeitet; der Folgestart erfolgte 10,13 Sekunden nach der ersten Abnahme. Das belegt keinen nativen Coding-Schreiblauf. |
| Gespeicherte Statuszeiten | `fccd2cb`, enthalten in `ed313e0`, projiziert gebundene Corezeitpunkte und Receipt-Abnahmezeiten ohne neue Ausführung. Fehlende, ungültige oder ungeordnete Zeitwerte bleiben unbekannt. Der Integrationsnachtest der fünf direkt betroffenen Testdateien bestand mit 48 Fällen in 38,42 Sekunden ohne Skips, Fehler oder Fehlschläge. |
| Korrigierte Receiptbindung der Statuszeiten | Der unabhängige Nachreview von `ed313e0` fand einen P2: fehlende Core-IDs konnten durch `None == None` eine Abnahmezeit liefern. Diese Integration verlangt deshalb vor dem Receiptvergleich eine nichtleere Core-ID. Die neue API-Regressionsprobe scheiterte zuerst am unveränderten alten Produktcode; nach der Korrektur bestanden alle sechs Timingfälle in 10,55 Sekunden. Der alte Review bleibt `NEEDS_FIX`; der unabhängige Nachcheck der Korrektur wird getrennt festgehalten. |
| Lokales Pythonpaket PK1 | Das Wheel aus `c38a894` bestand zwei lokale Core-/MCP-Smokes mit deterministischen CLI-Fixtures. Der unabhängige Evidenzreview bestätigt 221 damalige Produktdateien einschließlich vier Schemas, 138 aufgezeichnete Wheelimporte und acht Requestbindungen. Dieser Paketstand enthält die späteren Fortsetzungs- und Zeitprojektionsänderungen nicht; er ist kein Paketnachweis des gesamten aktuellen Quellstands. |
| Erster Linuxlauf und Korrekturen | [Run 42193459301](https://github.com/landjunge/KiraBridge/actions/runs/42193459301) auf `ed35490` scheiterte in beiden Legacy-Lanes; Remote-Lane und Build wurden nicht ausgeführt. Die Rohlogs enthalten Speicherfehler und überholte Testfixtures. `6068605` und `a1e7e5c` korrigieren die Fixtures; `9c07ebf` mit Folgefix `89946f6` bindet temporäre Dateien an frischen jobeigenen Runner-Speicher. Der ursprüngliche unzulässige Workflowkontext auf `9c07ebf` bleibt historisch `NEEDS_FIX`. Die Korrekturen sind lokal geprüft; eine tatsächliche neue Linux-CI-Abnahme bleibt ein eigenes Gate. |

Die bisherigen Integrationsläufe mit 111 bestandenen Fällen und 24
Dependency-Setupfehlern sowie dem gezielten erfolgreichen Nachlauf dieser 24
Fälle bleiben getrennte Belege. Sie werden weder zu einem neuen sauberen
135er-Lauf erklärt noch durch den späteren 29er-Lauf ersetzt. Dasselbe gilt für
überlappende Gate-, Schema- und Quellenreviewfälle.
Auch der 48er-Integrationslauf vor dem abschließenden Receiptbindungsfix und die
sechs danach gezielt geprüften Timingfälle werden nicht addiert. Der eigene
aktive Supervisor auf `ed313e0` enthält diesen letzten Quellenfix noch nicht.
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

Die Hauptinstallation bleibt RC39 aus `8d331314b608`; sie wurde für diese
Integration nicht ersetzt. Der eigene lokale Koordinator-Supervisor wurde
gesondert aus `ed313e0` aktiviert und behält seinen geschützten Runtime-Worktree.
Der ursprüngliche Codingauftrag T1 bleibt `UNKNOWN/agent_timeout` und wird nicht
wiederholt; sein fachlicher Inhalt wurde in einem getrennten Checkout erledigt.
Installation des Hauptprodukts, reale Providerketten, produktiver Remoteweg,
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
[Remote-CI-Quellenbindung](REMOTE-CI-PIN-GATE-20261106.md) ·
[jobeigener CI-Speicher](CI-TEMP-SCOPE-20261106.md) ·
[Fortsetzung und lokale Betriebsbelege](COORDINATOR-CONTINUATION-20261106.md).

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

The dedicated local supervisor now uses `ed313e0`; the primary RC39 installation
remains unchanged. Two native text tasks produced four Codex turns, two technical
acceptances and a follow-up start after 10.13 seconds. The combined local tests of
the five affected continuation/runtime/timing modules passed 48 cases. The first
actual Linux CI run failed before the remote lane and build. Scoped fixture and
temporary-storage corrections require their own subsequent CI acceptance. The
earlier PK1 wheel evidence applies to `c38a894`, before these new product changes.

A final independent review found that a receipt lacking a Core identity could
expose an acceptance time on `ed313e0`. This integration requires a nonempty Core
identity before comparing the receipt. The original API regression failed first;
the corrected timing module then passed six cases. These overlap the preceding
48-case run and are not added to it. The separate supervisor still uses `ed313e0`
until its runtime source is updated; historical negative evidence is retained.
