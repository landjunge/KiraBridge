# Auftragsbezogene Modellwahl

`BP-DELEGATION-MODEL-SELECTION`, Entwicklungsboard `188ce4729a62`, Auftrag
`b6e656c4bf48` (SHA256 `3483440f315074f6e1551e50d157474f115f168ac66f4f7448f34bc0f1b6dc0a`),
exklusiver Claim `4c3ac98d6726`. Grundlage: `29dfdbdf2894b1fd216085d4eea666a5f381fbf3`.

Bei einer neuen Delegation gelten explizite Auftragsvorgaben je Feld vor dem
Workerprofil. Ungesetzte Felder wählt der vorhandene Router anhand der aktuellen
ThreadDesk-Matrix automatisch. Die Denkstufe des Koordinators ist davon getrennt.
Der [gemeinsame Masterprompt](cli-routing/PROJECT-ROLE-MASTERPROMPT.md) und die
Codex-/Grok-Skill-Einstiege verwenden dieselbe Regel. Die lokale gemeinsame
Skillreferenz und die Einstiege in Big Plan/Koordinator wurden mit Backup aktualisiert.

## Umsetzung

`ReadyCard`, `TeamWorkCreate` und `AgentInput` tragen optionale `model`-/`effort`-
Präferenzen durch die vorhandene Team/Core-Kette. TeamWork speichert sie in zwei
nullable Spalten. Seal und Ausführungsprüfung binden beide Werte. Ohne Vorgaben
bleiben bisherige Requestbytes und Idempotenzhashes erhalten. Kein neues Ledger.

Der vorhandene native Delegationshook setzt Auftragswerte vor `worker.routing`.
`WorkerRouting.effort` darf fehlen; `AgentConfig.model` wird beim Routing nicht mehr
implizit geerbt. Bewusste alte Pins nach `worker.routing.model` übernehmen, ohne
laufende Profile zu ändern. Ein gebundener Principal behält seine CLI. Automatische
CLI-Wahl erfolgt vor der neuen Zuordnung über denselben Router.

Explizite Werte ersetzen heuristische Eignung bzw. Aufwand, erhalten aber fachliche
Mindestanforderungen, Zugang, Fähigkeiten, Kontext- und Eigentumsgrenzen. Ungeroutete
und sichtbare Wege weisen neue Vorgaben mit `agent_selection_unsupported` zurück.
Unbekannte, leere oder nicht unterstützte Werte lösen keinen Ersatzstart aus.
`ultra` ist im eingeschränkten Weg ohne Unteragenten ausdrücklich nicht unterstützt.

`selected_parameters` erfasst die Wahl. Der Standalone-Launcher liest Modell/Effort
aus seinen tatsächlich erzeugten Argumenten und protokolliert den beobachteten
Prozessstart separat als `start_observation`. Der native Adapterweg beobachtet
vertrauenswürdige Spawncallbacks separat als `routing_start_observation`; dessen
Scope ist lokale Adapterkonfiguration und Prozess. Keiner der Belege attestiert
providerseitige effektive Denkstufen oder beweist selbst den fachlichen Abschluss.

## Berlin-Buch-Abnahme

Synthetisches Buchprojekt über Berlin, kein privates Manuskript und kein Ortsteiltest.
[Fixture mit zwei amtlichen Quellenparaphrasen](cli-routing/berlin-book-fixture.json),
[maschinenlesbarer Nachweis](cli-routing/evidence/berlin-book-selection-acceptance-20261106.json).
Matrix `c9a396be4081`, Revision 5, bei jedem Plan/Start frisch gelesen und geprüft.

| Auftrag | Auswahl | Bestätigter lokaler Start | Fachliche Prüfung |
|---|---|---|---|
| Formatierung, automatisch | Codex / gpt-6-luna / low | PID 10723; identische Parameter; Exit 0; 12,77 s | Markdown exakt wie erwartet; nativer Turn abgeschlossen |
| Quellenprüfung, explizit high, unabhängig von OpenAI | Grok / grok-4.7 / high | PID 11013; identische Parameter; Exit 0; 34,88 s | 4/4 Aussagen korrekt als belegt, widersprochen oder unbelegt eingeordnet; end_turn |

Grok meldet nativ `grok-4.7-build` statt der angeforderten ID `grok-4.7`.
Diese Abweichung bleibt erhalten; Aliasgleichheit ist nicht bewiesen. Effektive
Denkstufen bleiben bei beiden Providern unbestätigt. Der erste Grok-Auth-Preflight
blockierte vor jeder Admission. Nach erfolgreicher unabhängiger Login-/Modellprobe
wurde die ursprüngliche Task-ID genau einmal gestartet, ohne Konto- oder Modellfallback.

Auswahl vor Start: Boardeintrag `c272a2b9ab90`; tatsächlicher Start und Abnahme:
`5b648b7e5be3`. Beide unabhängig zurückgelesen. Vollständige private Receipts unter
`~/.local/state/bp-delegation-model-selection-20261106`.

## Verifikation und Laufzeitgrenze

254 gezielte Tests bestanden: 112 Router-/Native-/Auswahlfälle und 142 Agent-/Team-/
Dispatcher-/Koordinator-/Runtimefälle. Ruff Check/Format bestanden. Vier betroffene
Skillvalidierungen bestanden. Unabhängiger statischer Review ohne offene P1/P2.

Die Tests umfassen automatische Wahl, Auftragsvorrang vor Workerpins und Heuristik,
verbindlichen Mindestaufwand, Providerunabhängigkeit, unzulässige Auswahl vor Start,
Manipulation nach Versiegelung, unveränderte Serialisierung sowie getrennte
Auswahl-/Spawnnachweise. Anfangs fehlerhafte Testfixtures wurden korrigiert; die
fehlgeschlagenen Vorläufe sind keine bestandenen Tests.

Abnahme gilt für diesen Quellkandidaten, isolierten nativen Core und zwei eigene
lesende CLI-Prozesse. Primärer Bridge-Dienst, installierter Standalone-Launcher,
Supervisor, laufende Aufträge und globale Modelldefaults wurden nicht umgestellt.
Produktivinstallation bleibt ein gesonderter, gated Integrationsschritt.
