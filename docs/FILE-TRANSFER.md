# File-byte transfer / Dateiübertragung · RC16 candidate

## Deutsch

Opt-in-Funktion; keine vorhandene Freigabe wird erweitert. KiraBridge überträgt
unveränderte Bytes, Metadaten und SHA-256. ThreadDesk muss den
[v1-Vertrag](THREADDESK-FILE-TRANSFER-V1.md) implementieren; aktuell ist dessen
Produkt-Abnahme offen. Ein Dateiname, Link, Queue-Beleg oder Commit-Ack ist kein
abgeschlossener Import. Erst `state=stored`, `import_successful=true` und eine
unabhängig abgefragte, streng geprüfte dauerhafte Speicherbestätigung zählen.

Die [offizielle Host-Dokumentation](https://developers.openai.com/plugins/reference)
beschreibt optionale Dateiauswahl und `openai/fileParams`. Verfügbarkeit hängt vom
Host/Konto ab. Es gibt hier keinen verifizierten vollständigen Bibliothekszugriff.
Keine 275-Dateien-/23-Ordner-Inventur wird vorausgesetzt. Alternativ ausdrücklich
bereitgestellte Exporte verwenden. Google Drive oder Compliance-Exporte erfordern
eigene Autorisierung und sind nicht automatisch angebunden.

Nur in einer geprüften eigenen Konfiguration aktivieren; produktive Konfiguration
wurde in diesem Auftrag nicht verändert. Beispiel mit ausdrücklich gewähltem Export:

```toml
[file_transfer]
enabled = true
export_roots = ["/absolute/authorized-export"]
allowed_projects = ["my-project"]
source_hosts = []
```

Für Host-Dateiparameter ausschließlich die tatsächlich autorisierten HTTPS-Hosts
in `source_hosts` aufnehmen. Keine Wildcards, Cookies, fremden Tokens oder beliebigen
Download-URLs verwenden. Die konfigurierte ThreadDesk-MCP-Verbindung bleibt separat:
fester ausführbarer Prozess, feste Argumente, eigener Workspace, keine URL vom Modell.
Der Betreiber muss beide Enden und Zielprojekte autorisieren.

Der Principal braucht `files.prepare`, `files.transfer`, `files.inspect`; lokale
Exporte zusätzlich `file.read` und passende `roots`/`read_roots`. `export_roots`
begrenzt zusätzlich. Die bestehende Einzelgenehmigung gilt weiterhin; bei manueller
Freigabe Status über exakt genehmigte `files.inventory`/`files.status`-Tasks abfragen.
Kein Werkzeug erteilt sich Rechte. Quelle und Ziel werden bei Ausführung erneut geprüft.

1. `operation_catalog` und `bridge_health` lesen: verfügbar, autorisiert und
   tatsächlich ausführbar sind verschiedene Aussagen.
2. `file_transfer_prepare(file, project_id, task_id, idempotency_key, ...)` nimmt
   Host-Dateiparameter; `file_transfer_export(path, ...)` einen autorisierten Export.
   Optionale Felder: `folder`, `library_path`, `source_version`, `expected_sha256`.
   Fehlender Originalname erhält einen neutralen Ersatz; unbekannter Pfad/Version
   bleibt unbekannt. Vorbereitung erzeugt einen unveränderlichen privaten Snapshot
   und `transfer_id` (Ergebnisfeld `id`), noch keinen Import.
3. `file_transfer_start(transfer_id, task_id, idempotency_key)` sendet echte Chunks.
   `file_transfer_status`/`file_transfer_inventory` zeigen eigenen Fortschritt.
4. `file_transfer_pause` fordert einen Checkpoint an. Nach Unterbrechung/Neustart
   mit gleicher Transfer-ID, aber **neuer Task-ID und neuem Idempotenzschlüssel**
   ausdrücklich fortsetzen. Erst Empfängerstatus/Präfixhash abgleichen; keine blinde
   Wiederholung unklarer Schreibzugriffe. Bei Widerspruch abbrechen, nichts überschreiben.

Status: `detected` → `authorized` → `running` → `transferred` → `stored`;
`paused`/`failed` sind getrennt. Gespeicherte Bestätigung belegt den Zeitpunkt des
Abschlusses; sie überwacht keine spätere Löschung in ThreadDesk. Temporäre Quell-URLs
bleiben nur kurz im Speicher; vor abgeschlossener Vorbereitung nach Neustart neu
bereitstellen. Fertige Snapshots/Checkpoints bleiben für Wiederaufnahme erhalten.

Standardgrenzen: 2 GiB/Datei, 8 GiB/2048 Snapshots insgesamt, 256 KiB-Chunks,
10.000 ZIP-Einträge, 16 MiB ZIP-Verzeichnis, 8 GiB entpackte Prüfbytes, Verhältnis
200. ZIP/Office-Container werden ohne Extraktion geprüft. Gefährliche Pfade,
Symlinks, verschlüsselte Archive und erkannte Geheimnisse werden abgelehnt.
Geheimniserkennung ist keine Garantie für beliebige unbekannte Secret-Formate;
Betreiber muss die ausdrücklich gewählten Dateien prüfen. Originale bleiben erhalten.

Fehlercodes statt Quellinhalte/URLs protokollieren. `transfer_*` mit Status und
sicherer Transfer-ID untersuchen; keine Tokens/Download-URLs in Tickets kopieren.
Ein fehlender Receiver-Vertrag oder eine falsche Bestätigung bleibt ein Fehler.
Text, PDF, Office, Bilder, ZIP, Audio, Video und andere Bytes werden nicht konvertiert;
Darstellung und dauerhafte Projektzuordnung gehören ThreadDesk.

Migration: additive `kb_file_transfers`-Tabelle im vorhandenen Aufgabenstore;
bestehende Aufgaben und Dateien bleiben erhalten. Beim Rückfall auf eine ältere
Version deren Konfigurationsparser beachten: neue `[file_transfer]`-/`client_type`-
Felder nur in einer separat geprüften kompatiblen Konfiguration verwenden. Nie
aktuelle Datenbanken durch alte Backups ersetzen. Staging wird nicht automatisch
gelöscht; Quotenfehler erfordern eine geprüfte Aufbewahrungsentscheidung.

## English

This opt-in candidate transfers unchanged bytes and SHA-256, not links. Enable only
in an explicitly authorized configuration with export roots, destination project IDs
and, for host-selected files, exact HTTPS source hosts. Existing principal capabilities,
source scopes and exact-task approvals still apply; no credentials or permissions
are inferred. The optional official host file picker is not a Library enumeration API.
Local exports are the supported alternative; Drive/Compliance require separate authority.

Prepare using `file_transfer_prepare` or `file_transfer_export`; use the returned
`id` as `transfer_id` with `file_transfer_start`. Inventory/status are principal-scoped.
Pause/resume uses the same transfer ID with a new task ID/key, verifying the receiver
checkpoint and prefix before more writes. Original files remain unchanged. Temporary
URLs are ephemeral; complete snapshots/checkpoints survive restart. Default bounded
limits, secret/archive/path validation and migration constraints are detailed above.
Only independently fetched, matching durable `stored` receipts establish import;
`transferred` and accepted tasks do not. Cached receipts establish completion time,
not continuous monitoring of subsequent receiver deletions.

ThreadDesk owns persistent storage, project attachment, search and viewing.
Its actual v1 implementation and product acceptance remain outstanding. Tests use
isolated disk-backed and real-MCP **contract fixtures**, never a disguised production
ThreadDesk import. See [architecture review](MODULARITY-REVIEW-20261024.md),
[contract](THREADDESK-FILE-TRANSFER-V1.md) and [test evidence](ACCEPTANCE-MACOS-RC16.md).
