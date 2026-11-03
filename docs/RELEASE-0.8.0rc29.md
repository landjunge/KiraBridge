# RC29 – weniger Cloudaufrufe für Lesen und kurze Aktionen

RC29 ergänzt RC28 um eine sichere allgemeine Sammelabfrage vorhandener
Lesewerkzeuge (`read_tools` beziehungsweise gecachtes `read_query` mit
`operation=tool.batch`). Status und Ereignisse bestehender Tasks kommen über
`task.observe` zusammen zurück. Kurze Aktionen geben ihren Abschluss möglichst
im ursprünglichen Aufruf zurück; ChatGPT muss ihn nicht pauschal nachfragen.
Gezielte Operationskataloge vermeiden unnötig vollständige Schemaantworten.

Normale Rechte-/Zielprüfungen, dauerhafte Task-IDs und Idempotenz bleiben erhalten.
Beobachtertimeouts beenden keine Ausführung und wiederholen keine Eingabe.
Submit-Endpunkte prüfen `task.read` vor Aufnahme; reine Write-only-Clients ohne
dieses Recht werden vorher abgewiesen. Bilder, generische Writes und rekursive
Batches sind nicht Teil des neuen JSON-Lesebündels.

Lokale gezielte Tests und unabhängige Reviews sind dokumentiert. Das Paket wird
auf diesem Mac ausschließlich für Intel gebaut, ohne GitHub Actions/ARM.
Download, produktive Installation und tatsächliche Cloud-Nachmessung werden erst
nach Erfolg als solche vermerkt. [Untersuchung und Messbelege](RC29-CLOUD-CALL-REDUCTION-20261103.md).
