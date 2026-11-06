# Abschlussregel des Big-Plan-Koordinators

Eine Workerlieferung allein ist keine Abnahme. Der Supervisor meldet den
Abschluss erst mit gespeichertem aufgabenbezogenem Abnahmebeleg und verifiziertem
Board-Readback derselben Grant-/Task-Kombination. Der Receipt-Hash im Board muss
mit dem gespeicherten Receipt übereinstimmen.

Die Abschlussmeldung verwendet pro Aufgabe eine stabile Report-ID und festen
Inhalt. Innerhalb eines Laufs wird sie einmal versucht; nach Neustart dedupliziert
der vorhandene Reportempfänger dieselbe ID. Ein Transportfehler gilt weiterhin
als unbekannte Zustellung, nicht als bestätigte Meldung. Keine neue Queue.

Fehlende Abnahme, fehlender Board-Readback oder widersprüchlicher Receipt werden
im Status unter `closure.missing` benannt. Der Auftrag bleibt fachlich offen.
Terminale Zustände lösen kein Completion-Statuswarten und keine periodischen
Koordinatorberichte aus. Neue Belege können den offenen Zustand auflösen;
unabhängige Folgeaufgaben bleiben möglich. Lokale Supervisor-/Inbox-Verarbeitung
bleibt aktiv und ist kein neuer Statusprompt an einen Worker.

Gezielte Prüfung: `tests/test_coordinator_closure.py`,
`tests/test_coordinator_continuation.py`, `tests/test_coordinator_runtime.py`.
Produktive Aktivierung und menschliche Produktabnahme sind getrennte Schritte.
