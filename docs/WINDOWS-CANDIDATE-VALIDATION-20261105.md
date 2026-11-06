> Historischer Quellenstand aus `21d2e2cad8e9930931b02031addfc25d819a9ed3`,
> bei der Integration am 06.11.2026 bewahrt. Aktueller Quellen-, Prüf- und
> Installationsstand: [RC40-Integrationsnachweis](RC40-INTEGRATION-INSTALL-20261106.md).
> Datierte Plan- und Gateangaben sind keine neue Auftrags- oder Berechtigungsquelle.

# Windows-Kandidatenprüfung

Beobachtet auf Basis `511f289fc5109f5d6893d5df8843254628c385ba`: `pyproject.toml`
und `src/kirabridge/__init__.py` nennen `0.8.0rc39`. Unter `src/kirabridge/`
liegen 189 Python-Module. Diese Zahl ist eine Beobachtung, kein Paketpin.
Dieser Patch ändert die Laufzeitmodule nicht.

`scripts/build_windows_dev_kit.py` behält ohne `--candidate-version` den
historischen RC33-Pfad: Version `0.8.0rc33`, Komponentenreuse nur bei genau
174 laufzeitgleichen Modulen, sechs passende Gastberichte. `scripts/start_windows_preview.cmd`
startet weiterhin nur diese RC33-Vorschau. Diesen Pfad nicht durch Hochzählen
der Versionsnummer ersetzen.

## Kandidat prüfen

Der Kandidatenplan liest Modul- und Harnessbytes aus dem angegebenen Git-Commit,
benötigt dafür Python 3.11 oder neuer (Standardbibliothek `tomllib`),
vergleicht sie mit `source.zip` und dem `kirabridge`-Wheel und verlangt sechs
frische Berichte `report-<run>-<phase>.json`. Jeder Bericht muss `evidence_platform`
`win32`, dieselbe `candidate_version`, denselben `source_commit`, die SHA256-Karten
`runtime_module_sha256` und `harness_sha256` sowie den daraus berechneten
`inventory_sha256` tragen. Zusätzlich bindet `version_file_sha256` die exakten
Bytes von `pyproject.toml` und `src/kirabridge/__init__.py` aus dem eingefrorenen
Commit. Projektversion, eindeutige literale Runtimeversion und explizite
Kandidatenversion müssen gleich sein; Kandidatencode wird dafür nicht importiert
oder ausgeführt. Dynamische Versionsmodule werden abgelehnt. Die Versionsdateien
im Source-ZIP müssen ebenfalls bytegleich sein.
Nicht-Core-Phasen brauchen zusätzlich `artifact.platform`
`nt`. Fehlt das Inventar, weicht ein Modul ab, fehlt ein Modul oder kommt eines
hinzu, endet die Prüfung mit Fehler. Wiederverwendung älterer Phasen ist im
Kandidatenpfad abgelehnt. Ohne `--build` entsteht nur der Plan, kein ZIP.
Jeder Bericht wird einmal gelesen; Candidateprüfung, Inhaltsprüfung und
exportierter Rohdatenhash beziehen sich auf dieselben Bytes. Ein atomarer
Dateiaustausch nach dieser Aufnahme kann den exportierten Nachweis nicht mehr
ersetzen. Bei einem späteren freigegebenen Build stammt auch der ZIP-Name aus
der geprüften Paketversion, nicht aus der historischen RC33-Konstante.

```bash
python3.11 scripts/build_windows_dev_kit.py \
  --staging-dir <eigenes-staging> \
  --guest-reports-dir <eigene-win32-berichte> \
  --out-dir <neues-leeres-verzeichnis> \
  --source-commit <40-stelliges-commit> \
  --candidate-version 0.8.0rc39
```

Die Version muss explizit sein. Der Validator liest sie nicht selbst aus dem
Worktree und erklärt einen grünen Plan nicht zur nativen Abnahme.

## Offene native Gates

Der [optionale Producer für neue Gastläufe](WINDOWS-CANDIDATE-PRODUCER-20261105.md)
erfasst diese Bindung vor/nach jeder Phase im bestehenden Runner. Kandidaten mit
diesem Collector binden zusätzlich dessen drei Producerdateien und den tatsächlich
gestarteten Bootstrap. Alte RC33-Berichte werden nicht nachträglich ergänzt.

Für `0.8.0rc39` und den aktuellen Modulstand gibt es hier keine frischen
Windows-Gastberichte. Diese Prüfung startet keine VM, lädt nichts herunter,
baut kein Release-Paket und installiert nichts. macOS-Nachweise und die
RC33-Berichte bleiben an ihre eigene Quelle gebunden; sie werden nicht zu
Win32-Nachweisen umetikettiert. Native Abnahme bleibt: sechs Phasen eines
Windows-Gasts, gebunden an genau dieses Quellinventar, inklusive Harnessbytes.
Erst danach wäre `--build` ein Paketplan mit Belegen, immer noch keine
Hardware- oder Cloud-Abnahme.
