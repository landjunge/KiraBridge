# Bibliotheksübertragung: Schnittstelle und Kompatibilitätsstand

Stand: 25. Oktober 2026. Dieser Bericht beschreibt den geprüften Quelltext und die
Konfiguration; er ist keine Aktivierungs-, Import- oder Releaseabnahme.

## Vorhandene Module und Vertrag

PR [#33](https://github.com/landjunge/KiraBridge/pull/33), Quellstand
[`3fa1203`](https://github.com/landjunge/KiraBridge/commit/3fa1203), enthält den
ThreadDesk-Empfängeradapter bereits. Kein paralleler Empfänger wird benötigt.

- `src/kirabridge/file_transfer/sources.py` und `authorization.py`: ausdrücklich
  bereitgestellte Dateien beziehungsweise autorisierte Exporte und Zugriffsumfang.
- `file_transfer/service.py`, `repository.py` und `protocol.py`: Snapshots,
  Prüfsummen, persistente Checkpoints, Wiederaufnahme und Speicherquittungen.
- `file_transfer/threaddesk.py`: erkennt und bevorzugt `library_receive`,
  `library_receive_status`, `library_search` und `library_file_info`; unterstützt
  daneben den bisherigen `file_import_*`-Vertrag. Unklare Schreibausgänge werden
  durch Statusabfrage geklärt; Schreiboperationen werden nicht blind wiederholt.
- `mcp_gateway/file_tools.py`: freigegebene Transferwerkzeuge einschließlich
  Empfängerprüfung und Abbruch. Ein gespeicherter Dateiname oder Link genügt nicht
  als Importbeleg.
- `scripts/import_library_exports.py`: verwendet dieselben Besitzer und Adapter
  mit eigenem Prozess, Principal und Zustand sowie expliziten Exportwurzeln und
  bestehenden Thread-IDs. Es ersetzt keine globale Bibliotheks-API.

Die Pfade ohne Präfix in dieser Liste liegen unter `src/kirabridge/`.
Knowledge-Verwaltung bleibt ein eigener ThreadDesk-Zugang über
`threaddesk_manager.py` und die Operation `threaddesk.knowledge`.

## Aktive Konfiguration und getesteter Empfänger

Die am 25. Oktober ausschließlich lesend geprüfte lokale Konfiguration verweist
auf den eingefrorenen ThreadDesk-Quellstand
[`6c7d578a`](https://github.com/landjunge/threaddesk/commit/6c7d578a1edb612d0e8e6d99faa2953888d69bfb)
(`seven-tools-knowledge-pinned-20261018/src`, Modul
`threaddesk.ui.mcp_stdio`, JSON-Speicher). Dessen statische Werkzeugdeklaration
enthält `thread_manage`, `thread_operation_status`, `knowledge_manage`,
`get_reentry` sowie Snapshot-, Handoff- und Rückgabeoperationen. Sie enthält weder
`library_receive/status/search/file_info` noch `file_import_*`.
Damit ist der konfigurierte alte Quellpin eine konkrete Laufzeithürde für den
Dateiempfang. Im Rahmen dieser Prüfung wurden keine Module dieses Profils
importiert und kein neuer MCP-Aufruf oder Schreibzugriff ausgeführt. Eine
Quelldeklaration allein bestätigt keine aktuelle erfolgreiche Ausführung.

Der in PR33 verwendete und auch lokal vorhandene Empfängerquellstand
[`770bbc9f`](https://github.com/landjunge/threaddesk/commit/770bbc9f0c0a02699cc93cad47d2e2c3782f7080)
bietet die vier nativen Bibliothekswerkzeuge und weiterhin Knowledge-Verwaltung.
`.github/workflows/ci.yml` pinnt diesen Gegenpart ausdrücklich. Das ist keine
Behauptung, dass der aktive lokale ThreadDesk-Prozess bereits umgestellt wurde.

## Noch offene Einrichtung

Die gelesene ChatGPT-Policy besitzt bereits `full`/`automatic` und die Capabilities
`file.read`, `files.prepare`, `files.transfer`, `files.inspect` sowie
`threaddesk.read/manage/knowledge`. Zusätzliche pauschale ACLs lösen die folgenden
getrennten Hürden nicht:

1. `file_transfer.enabled` ist weiterhin deaktiviert. Exportwurzeln,
   Download-Hosts und erlaubte Ziele sind nicht eingerichtet.
2. Der konfigurierte ThreadDesk-Quellpin besitzt keinen Dateiempfänger. Ein neuer
   geprüfter Receiver benötigt eine ausdrücklich gewählte, abgenommene Umgebung.
   Dieser Auftrag wechselt kein produktives Profil und öffnet keinen vorhandenen
   Nutzerspeicher eigenmächtig mit einer neuen ThreadDesk-Version.
3. Für die historischen Inventare fehlen weiterhin echte autorisierte
   Originaldateien beziehungsweise ausgewählte Datei-Downloadfähigkeiten sowie
   ausdrücklich bestätigte Zielzuordnungen. Bibliotheks-IDs sind keine Downloads.

Die Vorbereitung muss Quelle und Ziel eindeutig binden. Ein reiner Wechsel der
Quellwurzel darf bestehende Transfer-IDs nicht auf ein anderes Ziel umdeuten.
Originale, vorhandene Quittungen und Audit-Historie bleiben erhalten. Der alte
queued Bibliotheksauftrag wird nicht erneut eingereicht oder parallel ausgeführt.

## Gezielte Checkpoint-Reparatur

Die neue Zielidentität berücksichtigt fünf Werte: Befehl, Argumente, Workspace,
Speicherart und `source_root`. Ältere Checkpoints verwendeten nur die ersten vier.
Der freigegebene Reparaturumfang ist eng: Bei **nicht gesetztem** `source_root`
wird eine fest definierte Sicht auf die alte Vier-Werte-Identität unterstützt,
um vorhandene Checkpoints wiederzuerkennen. Bereits bestehende Fünf-Werte-
Checkpoints bleiben unverändert gültig.

Bei gesetztem `source_root` bleibt ein abweichender alter Zielbezug gesperrt.
Es wird keine automatische Migration, keine Neuzuordnung und kein erneuter
Import erfunden. Die Umsetzung ist abgeschlossen und gezielt geprüft; siehe den aktuellen Nachweis unten.

## Belege und Grenzen

`docs/evidence/library-receive-adapter-20261024.json` dokumentiert frühere
isolierte Tests gegen ThreadDesk `770bbc9f`: 87 bestandene betroffene Prüfungen
und einen zusätzlichen Lost-Abort-/Revocation-Fall, unter anderem echte
MCP-Übertragung von Text und PNG, Neustart, Readback, Suche und Quittungsprüfung.
Diese vorhandenen Ergebnisse werden hier weder wiederholt noch als neue
25.-Oktober-Abnahme ausgegeben. Sie bestätigen keinen historischen Import.
Das damalige Inventar umfasste 275 Positionen: acht nur inventarisierte sensible
Positionen und 267 ohne verfügbare Quelldateien; historische Übertragungen: null.

Die aktuelle Nachprüfung umfasst Konfiguration, eingefrorene Quelldeklarationen
und vorhandene Belege. Kein produktiver Speicher, Profil, Credential, Terminal
oder laufender Auftrag wurde geändert. Nächster Schritt ist ausschließlich der
Abschluss der gezielten Checkpoint-Reparatur mit ihren notwendigen Prüfungen;
Receiver-Aktivierung und tatsächlicher Import bleiben gesonderte Abnahmen.

## English

PR33 already provides the modular ThreadDesk library receiver adapter; no second
implementation is needed. The configured frozen ThreadDesk source `6c7d578a`
supports thread and knowledge operations but lacks the file receiver. Existing
isolated evidence targets `770bbc9f`, not the active profile. ChatGPT already has
the relevant capabilities; the transfer module, explicit sources and destination
scopes still require setup. No historical library bytes were imported.

The targeted checkpoint fix is implemented and tested: recognize the fixed legacy four-part
identity only when no source root is configured, retain existing five-part
checkpoints, and reject ambiguous legacy destinations when a source root is set.
No automatic migration, duplicate import, profile switch is claimed. The current targeted tests are recorded below. Only configuration, source declarations and existing reports were
read during this audit.

## Aktuelle Umsetzung und notwendige Nachprüfungen

`file_transfer/threaddesk.py` liefert über `bind_destination()` eine eigene
Receiveransicht pro Operation. Legacy-Vierer-Checkpoints werden nur bei exakt
denselben vier Einstellungen und `source_root=None` erkannt. Ihre Ansicht bleibt
ausschließlich bei `file_import_*`, auch wenn beide Werkzeugfamilien vorhanden
sind; ein reiner nativer Empfänger ist dafür kein Ersatz. Die ursprüngliche
Fünffeld-Identität bleibt unverändert. Einstellungen werden vor Zugriff sowie nach
asynchronem Connect/Katalog erneut geprüft.

`file_transfer/service.py` verwendet dieselbe gebundene Ansicht für Transfer,
Statusklärung nach verlorenem Ack und Abbruch; kein Zurückfallen auf den globalen
Adapter. Generische Receiver ohne Bindungsfunktion behalten die strikte bisherige
Identitätsprüfung. Domain/Ports bleiben vom konkreten MCP-Adapter unabhängig.
Keine Datenbankmigration und keine Umschreibung von Manifest, Hash, Operation-ID,
Snapshot oder bestehenden Quittungen. Legacy-v1 unterstützt keinen Abort; dies
wird weiter ausdrücklich verweigert, statt einen nativen Ersatzabbruch zu senden.

Vorpatch-Reproduktion: beide relevanten Resume-Fälle scheiterten. Danach18
unterschiedliche gezielte Fälle bestanden: Bytefortsetzung ab4096, beide Toolfamilien,
native-only Verweigerung, fünf Konfigurationsdrifts während Connect, unveränderter
Checkpoint/Audit/Quittung, verlorenes Ack und derselbe Legacy-Statusweg, sowie direkt
betroffene generische/MCP-Regressionsfälle. Nur die zwei Resume-Fälle wurden nach
zusätzlichen Audit-Assertions gezielt erneut ausgeführt. Keine Gesamtsuite.

Root führte zusätzlich genau einen vorhandenen nativen Text-Ende-zu-Ende-Fall
mit echtem ThreadDesk-Code aus Pin770bbc9f auf diesem Intel-macOS aus:
**1 passed,10 deselected in1.83s**. Der Code wurde per `git archive` in den eigenen
Testbereich kopiert; keine Datei des fremden Worktrees oder Produktivspeichers
geändert. Tatsächliche gespeicherte Originalbytes, SHA-256, dauerhafte Quittung,
Neustart/Readback/Suche und unveränderte Dublettenquittung mit genau einem
Speichereintrag bestätigt. Dieser Fall ist nötig, weil auch aktuelle Fünferbindungen
eine eigene Adapteransicht erhalten. Es ist keine Abnahme des aktiven alten Profils
und kein Import einer historischen Nutzerdatei.

[Maschinenlesbarer Quell-/Test-/Hashnachweis](evidence/library-checkpoint-compat-20261025.json).
Unabhängiger lesender Teamreview fand keinen konkreten neuen Sicherheitsdefekt.

Verbleibende Grenze: bestehende Fünfer-Checkpoints enthalten weiterhin keinen
separaten historischen Protokoll-Pin. Diese Änderung verspricht dafür keine
beliebige Protokollmigration. Bei Mehrdeutigkeit kein automatisches Rebinding oder
Doppelimport; dies bleibt vor einem entsprechenden Empfängerwechsel zu klären.
Aktivierung und Produktionsintegration sind nicht Bestandteil dieses isolierten Fixes.

## GitHub-Abschluss und weiterer Bedarf

Codecommit `2dd091692d0066f5d45414415e255f6a9497e16d` gepusht, eigener
[PR35](https://github.com/landjunge/KiraBridge/pull/35) auf PR33 gestapelt.
Kein Merge und keine neue Installation: Verify-Jobs am Codepin starteten laut
Annotation121145115269 wegen Kontozahlung/Ausgabenlimit nicht. Die nachfolgenden
PR-Prüfungen lieferten ebenfalls keinen Pass. Keine Schutzprüfung umgangen.

Der Installationsbefehl wurde aus dem bereits tatsächlich geprüften012b592-Beleg
übernommen und nicht nochmals ausgeführt: er wählt das eindeutig benannte Paket,
statt über den alten generischen Bootstrap versehentlich auf main/b54 zurückzugehen.
Das Installationsdokument wird unverändert aus dem gepushten aktuellen Bericht
`bb30108` übernommen; der Bibliotheksfix ist nicht Bestandteil dieses Pakets.
Nur Dokumentationsangleichung, keine neue Paket-/macOS-Abnahme behauptet.

Produktiver Dienst zum Abschluss erneut authentifiziert gelesen: weiterhin
RC17/012b592, PID72612, Dispatcher aktiv. Keine Installation, kein Profilwechsel,
keine Originaldatei oder produktive Berechtigung durch diesen Schritt geändert.
Die Frage nach dem bereitgestellten Exportordner ist an den Nutzer gestellt.
Ohne echte Quelldateien kein Import; ohne gesondert abgenommenes Receiverprofil
keine ungeprüfte Öffnung des bisherigen produktiven Stores mit neuem ThreadDesk-Code.
Nächster konkreter Schritt: gewählten Export und bestehenden Zielthread prüfen,
Receiverumgebung konkret abnehmen; Pflicht-CI ermöglichen, dann PR32/33/35 normal
integrieren und erst aus integriertem geprüftem Stand neue Pakete erstellen.

Gemeinsames Whiteboard188ce4729a62: Aufgabenplan in Revision45, Ergebnis in
Revision46 gespeichert und jeweils unabhängig exakt zurückgelesen; Marker je einmal.
