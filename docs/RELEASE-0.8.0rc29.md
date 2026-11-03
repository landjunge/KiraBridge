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

Sourcepin `279afcc`: lokal für Intel gebaut und auf diesem Mac installiert,
laufender Daemon und alle 164 Pythondateien sowie native Dateien überprüft.
Sieben verfügbare Release-Assets mit Digests und erneutem Installer-Download
bestätigt. Lokale gezielte Tests und unabhängige Reviews bestanden; keine
GitHub Actions oder ARM-Builds. Bestehende Konfiguration, Daten und andere
Agentensitzungen erhalten; RC28-Rollback vorhanden.

Echte Apps-Vergleiche, je drei Gruppen:

| Gleicher Workload | Cloudaufrufe vorher → nachher | Median vorher → nachher |
| --- | ---: | ---: |
| Drei gemischte Lesewerkzeuge | 3 → 1 | 8,753 → 4,787 s |
| Taskstatus und Ereignisse | 2 → 1 | 6,210 → 3,210 s |
| Dateiaktion mit Abschlussnachweis | 2 → 1 | 5,607 → 1,990 s |

Insgesamt 21 → 9 Vergleichs-RPCs. Zusätzlich zwei getrennte Diagnoseaufrufe.
Dateien, Taskdaten und Ereignisse vollständig geprüft; keine erneute Ausführung
beim abgeschlossenen idempotenten Doppelaufruf. Der erste Bündelaufruf mit
9,106 s bleibt enthalten; n=3 und fehlende Voice-/Cloudtraces begrenzen
allgemeine Latenzzusagen. [Untersuchung und Messbelege](RC29-CLOUD-CALL-REDUCTION-20261103.md).
