# Architekturentscheidung: KiraBridge als universelle Verbindungsschicht
Datum: 2026-10-22. Status: Nutzerentscheidung dokumentiert, Umsetzung je Adapter offen.

KiraBridge soll jedes geeignete Tool über vorhandene Standards (MCP, lokale APIs, authentifizierte Netzwerk-APIs) verbinden können. Ein neues Tool benötigt möglichst nur einen Adapter mit Version, Capability-Discovery, Ein-/Ausgabeschema, nachvollziehbaren Fehlern und minimalen Berechtigungen; keine neue Bridge-Architektur. Keine doppelte Modulsteuerung aufbauen, bevor bestehende Komponenten geprüft sind.

Rollen: KiraBridge = Kommunikation und Auftragsvermittlung; ThreadDesk = Aufgaben/Kontext; Agent Authority = Identitäts-, Delegations- und Berechtigungsnachweise (externe Identitäten nicht pauschal als bestätigt behandeln); Tollgate = Ressourcen- und Budgetgrenzen, soweit nicht bereits anderweitig abgedeckt; 4AllPass = Tresore/Schlüssel/Geheimnisse; Block Designer = Grafikbearbeitung. Alle bleiben eigenständige Produkte.

Sicherheit: Tool-Verfügbarkeit ist keine Ausführungsberechtigung. Kein automatisches Übertragen von Tresorrechten an andere Adapter. Für 4AllPass gesonderte Freigaben, bei gesperrter Sitzung keine Tresoraktionen. Block Designer braucht keine eigene Ampel für normale Designarbeiten; Betriebssystemrechte gelten weiterhin.

Umsetzung: zuerst bestehende APIs und Fähigkeiten inventarisieren, dann schlanke Adapter bauen, isoliert testen und anschließend pro Tool integrieren. Brainstormings für Block Designer und Agent Authority liegen separat unter docs/brainstorm. Diese Entscheidung ist keine Behauptung einer bereits fertigen universellen Anbindung.
