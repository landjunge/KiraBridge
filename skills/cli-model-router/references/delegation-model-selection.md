# Gemeinsame Auswahlregel und Projektrollen-Masterprompt

Vertrag für `BP-DELEGATION-MODEL-SELECTION`, 06.11.2026. Dieser Text gilt für
Codex- und Grok-Einstieg. Die vom Nutzer eingesetzte Instanz koordiniert.

## Bei projektbezogener Rollenübernahme laden

Lade diesen Vertrag, den konkreten Auftrag, bestehende Arbeitsbindungen und die
aktuelle ThreadDesk-Matrix `c9a396be4081`. Ermittle vorhandene Sitzungen und deren
Claims, bevor du neue Arbeit zuordnest. Eine Matrix ist Fähigkeitsnachweis, keine
Ausführungsfreigabe. Die Denkstufe des Koordinators ist von der des Workers getrennt.
Eine Rollenübernahme stellt weder eine laufende Sitzung noch globale Defaults um.

## Unmittelbar vor jeder neuen Delegation anwenden

Explizite CLI-, Modell- und Denkstufenvorgaben des aktuellen Arbeitsauftrags haben
je Feld Vorrang. Sonst gelten ausdrücklich gesetzte Anforderungen des zugeordneten
Workerprofils; für ungesetzte Felder wählt der vorhandene Router automatisch anhand
von Aufgabe, Eignung, Aufwand, Zugang und tatsächlich unterstützten Kombinationen.
Eine spätere Auftragsvorgabe ersetzt ältere Rollenbeispiele nur für diesen Auftrag.
Die Koordinator-Denkstufe ist kein Workerdefault. Es gibt keine feste Anbieterrolle.

Explizite Wahl ersetzt die heuristische Eignungs-/Aufwandspräferenz des jeweiligen
Feldes, aber keine verbindliche `min_effort`-Anforderung, Providerunabhängigkeit,
Fähigkeit, Kontextgrenze oder Autorisierung. Nicht unterstützte Vorgaben mit Grund
melden und ohne Ersatzstart stoppen. Der eingeschränkte Startweg unterstützt
`ultra` wegen seines Unteragentenmodus nicht. Keine stillen Modell-, Konto-, API-
oder Denkstufenwechsel. Aktuelle Matrix, Zugang, Version und Claim am Effektpunkt prüfen.

Vor der Zuordnung eines neuen CLI-Workers kann `bigplan-delegate` CLI, Modell und
Denkstufe auswählen (`explicit_cli`, `explicit_model`, `explicit_effort`). Bei der
nativen versiegelten Team/Core-Ausführung stehen `model` und `effort` im einzelnen
Auftrag (`ReadyCard` → `TeamWorkCreate` → `AgentInput`). Der bereits gebundene
Principal und seine CLI bleiben fest; eine andere CLI erfordert eine passende neue
Zuordnung vor der Versiegelung. Beide Wege verwenden denselben Auswahl-/Prüfhook.
Sichtbare oder ungeroutete Wege dürfen solche neuen Vorgaben nicht ignorieren:
`agent_selection_unsupported` bedeutet, dass dieser Weg sie nicht umsetzen kann.

## Auswahl und bestätigten Start getrennt festhalten

Vor dem Start in ThreadDesk Auftrag/Claim, Matrixrevision, gewählte CLI, Modell und
Denkstufe festhalten. Danach die tatsächlich übergebenen lokalen Parameter und
beobachteten Prozessstart samt Kennung und Vergleich protokollieren. Ein Plan ist
kein Start; ein Prozessstart ist kein abgeschlossener Modellturn. Providerseitige
Modell-/Effortwerte bleiben ohne native Metadaten unbekannt. Abweichende gemeldete
Modell-IDs als Abweichung erhalten, keine Aliasgleichheit erfinden. Ergebnis und
Abnahme getrennt bewerten. UNKNOWN anhand der Originalkennung klären, nie blind
wiederholen. Laufende Aufträge behalten ihre ursprüngliche Bindung.

## Migration aus dem früheren C2-Vertrag

`WorkerRouting.effort` darf fehlen: das bedeutet automatische Wahl. Bei gerouteten
Workers wird `AgentConfig.model` nicht mehr still als explizite Anforderung geerbt.
Ein bewusst gewünschter alter Modellpin gehört in `worker.routing.model`; eine
Auftragsvorgabe hat weiterhin Vorrang. Bestehende laufende Profile nicht umschreiben.
Fehlende neue Auftragsfelder werden nicht serialisiert: alte Core-/Team-Requesthashes
bleiben identisch. Neue Präferenzen sind Teil der vorhandenen Versiegelung und
Idempotenz, ohne zweites Ledger.
