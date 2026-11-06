# BP-REMOTE-02: isolierter Remote-Vertikalschnitt

Paket `BIGPLAN-REMOTE-SLICE-20261105-V1`, 05.11.2026. Implementierung in
Feature-Branches, keine produktive Aktivierung oder mobile Endabnahme.
Grundlage: [Remotevertrag v1](../contracts/remote-task-v1.md).

## Vorhandenen Kern verbinden

`HttpHandoffPeer` verbindet genau einen authentifizierten ThreadDesk-Benutzer und
ein Projekt mit dem optionalen TD-Serveradapter `threaddesk.handoff-http.v1`.
`Bridge(config, handoff_peer=peer)` delegiert die vorhandenen Handoff-Methoden
dorthin. Ohne diesen Parameter bleiben lokale MCP-/stdio-Aufrufe unverändert.
Der Server delegiert an dieselben `ThreadService`-/`McpBridge`-Methoden;
Quellrevision, Knowledge-Pin, Laufbindung und Return-Inbox bleiben maßgeblich.

`RemoteRelay` nimmt eine einzelne `intent`-Nachricht für `handoff.start` an.
Es verwendet vorhandene MCP-Aufrufe `task_get` und einmalig `task_submit`.
Kein neuer Dispatcher, Queue-Dienst, AutoNext-Worker oder Rechteaussteller.
`execution_binding` ist weiterhin ausschließlich eine Beobachtung und wird
nicht zugestellt. Whiteboardtext ist Kontext, keine Berechtigungsquelle.

Die Anwendung muss beide Peers ausdrücklich bereitstellen und deren Lebenszeit
mit `async with` verwalten. Der neue TD-HTTP-Endpunkt wird ausschließlich mit
`create_app(..., handoff_rpc=True)` registriert; Standardwert ist `False`.
Es gibt in diesem Paket keinen neuen Autostart oder produktiven CLI-Schalter.

## Identität und vorhandene Freigabe

Beide HTTP-Strecken verlangen HTTPS mit exakt gepinntem Nicht-CA-Zertifikat.
Der TLS-Kontext vertraut ausschließlich den einmal gelesenen, geprüften
Zertifikatsbytes und prüft Hostname, Gültigkeit und Schlüsselbesitz beim
Handshake, bevor HTTP-Zugangsdaten übertragen werden. Kein OS-Truststore wird
geändert. Der Geräteschlüsselhash stammt aus dem SPKI des gepinnten Zertifikats.
Nicht vorhandene Pin-Unterstützung wird ausdrücklich abgelehnt.

Service-/Tenantreferenz sind vorab konfigurierte Bezeichnungen. Die tatsächliche
TD-Benutzerbindung wird aus authentifiziertem Benutzer und Projekt berechnet;
die Projektgrenze wird vor jedem storeweiten Handoff-/Return-Lookup geprüft.
Das ist kein implementierter 4AllPass-/Pairing-/Tokenausgabedienst.

Ein vertrauenswürdiger lokaler Resolver liefert für eine opaque `grant_ref`
einen `NativeGrant`: unveränderliche Bindung, vorhandenen Core-Principal und
bereits regulär ausgestellten Core-Freigabetoken. Der Token steht weder im
Remotevertrag noch im Whiteboard. Der Relay stellt selbst keine Freigaben aus.
Die bestehende Core-Prüfung entscheidet abschließend über Rechte, Pfad,
Idempotenz, Tokenablauf und Task-Zulassung. Eine Schema-Prüfung ersetzt sie nicht.

## Ein Versuch und nachlesbare Ergebnisse

Vor dem einzigen möglichen Submit wird in demselben vorhandenen TD-
Handoffregister eine unveränderliche `remote_delivery`-Reservierung gespeichert
und unabhängig zurückgelesen. Sie bindet Handoff, Core-Auftrag, Gerät,
Operator-Scope, Principalhash, Requesthash und Envelopehash. Sie verändert
weder Threadrevision noch Knowledge-Pin und ist keine zweite Aufgabenliste.
Die bestehende Laufbindung muss zu ihr passen.
Der injizierte Peer bindet seinen Operator-Scope außerdem an Gerätename und
Schlüssel. Vor einer Laufbindung prüft der ausführende Core selbst den
eigenen konfigurierten TLS-Schlüssel und den gespeicherten ursprünglichen
Task-Requesthash gegen die Reservierung. Auch ein direkt erteilter Core-
Auftrag darf die für ein anderes Gerät reservierte Übergabe nicht übernehmen.

Existiert bereits der exakt passende Core-Task, wird ausschließlich gelesen,
auch bei UNKNOWN oder abgelaufenem Zustellfenster. Fehlt der Core-Task nach einer
früheren Reservierung, bleibt die Zustellung unklar: kein erneutes Submit,
keine automatische Wiederaufnahme. Ein verlorener Submit-Return wird anhand
derselben Task-ID und des vom Core nachlesbaren ursprünglichen Requesthashs
aufgeklärt. Fremde oder geänderte Tasks werden nicht übernommen.

Unklare Schreibantworten, TLS-/Transportabbrüche oder fehlende Quittungen dürfen
keinen neuen Ausführungsversuch auslösen. Ein bekanntes HTTP-4xx ist eine
Ablehnung; ein fehlender eindeutiger Schreibbeleg bleibt UNKNOWN. Quelle und
Core haben weiterhin ihre eigenen vorhandenen Idempotenz- und Quellprüfungen.

Ergebnisse laufen über die vorhandene strikte Return-Inbox und den ursprünglichen
Thread zurück. `completed` bedeutet abgeschlossener Core-Auftrag, nicht
fachlich abgenommen. Der Relay erzeugt weder `acceptance_receipt` noch
`display_receipt` und behauptet keine mobile Anzeige.

## Ausdrückliche Grenzen

- Remote-`review_return` und `answer_handoff_question` sind vollständig gesperrt,
  auch mit Cookie/CSRF. Der vorhandene TD-Owner-Token kann selbst eine
  Browser-Sitzung öffnen und beweist deshalb keine unabhängige Operatorrolle.
  Ergebnisse bleiben `delivered_unverified`, Fragen warten ohne Autoresume.
  Bestehende lokale Operatorwege sind davon getrennt; Remoteabnahme bleibt offen.
- Die installierte sichtbare Agentenroute unterstützt den strukturierten
  `handoff_reply`-Start bisher nicht. Dieser Fehler wird unverändert abgelehnt;
  es gibt keinen stillen Wechsel zu Queue/API und keine Konfigurationslockerung.
  Der positive lokale Test nutzt ausdrücklich ein eigenes verwaltetes Testprofil.
- Lokale Zertifikate/Grants sind Testdaten. Produktives Pairing, Widerruf,
  Debian-Erreichbarkeit, Handy-/Chat-Annahme und Darstellung sind noch offen.
- Windows/Linux werden mit gemeinsamen Tests geschützt; native Abnahme dieses
  Remote-Pakets dort wurde nicht ausgeführt. Fehlendes optionales `cryptography`
  sperrt nur die explizite Pin-Funktion, nicht Legacy-Imports.

## Prüfnachweise und Einstieg

`tests/test_remote_relay.py` verbindet tatsächliche lokale TLS-Endpunkte,
temporäre TD-Stores, vorhandenen KB-MCP und Core-Task-Store. Der CLI-Agent ist
eine deterministische lokale Fixture ohne Anbieteraufruf. Getrennt geprüft:
Zweierfolge, genau ein Start, Quittung/Return/Whiteboard-Readback, neuer
Relay-Kontext, verlorene Submitantwort, Reservierungscrash, Abbruch, UNKNOWN,
falsches Gerät/Projekt/Grant/Pfad, Ablauf und beibehaltener Visible-Schutz.
`tests/test_remote_handoff_peer.py` prüft simulierte fehlerhafte HTTP-Antworten.
TD prüft seinen Adapter und Bearer→Login→Cookie-Selbstabnahme separat.

Für die Integrationsdatei `KIRABRIDGE_TEST_REMOTE_THREADDESK_SOURCE` auf den geprüften
TD-`src`-Pfad setzen. Sie benötigt beide bestehenden Python-Abhängigkeitssätze.
Ohne TD-Quelle wird sie ausdrücklich übersprungen, nicht als bestanden gezählt.
Die bestehende Legacy-MCP-Variable bleibt getrennt; vorhandene CI-Pins werden
durch diesen optionalen Test nicht auf eine ungeprüfte neue Gegenstelle geändert.
Der Paket-Schemakopie wird Bytegleichheit zum geprüften Vertrag abverlangt.
Exakte Testläufe, Review-Pins, offene Diffs und Übergabe stehen unter
`~/.local/share/kirabridge/backups/bigplan-remote-slice-20261105-v1/`.

Nächster produktiver Schritt erst nach unabhängigem Review und geklärtem
zulässigem Agenten-/Operatorweg: Gerätebindung und tatsächlichen Handyweg
als BP-REMOTE-03 prüfen. Bestehenden Windows-Auftrag für Dirk nicht doppeln.
README/Webseite/Downloads erhalten keine Verfügbarkeitsbehauptung, solange
dieses interne Paket weder integriert noch installiert oder abgenommen ist.
