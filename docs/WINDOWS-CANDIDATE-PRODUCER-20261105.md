# Windows: Quellengebundene Berichte aus neuen Gastläufen

Paket `BIGPLAN-WINDOWS-EVIDENCE-PRODUCER-20261105-V1`, 05.11.2026.
Quellschritt auf Basis8628fd9; kein neues Kit, kein nativer Win32-Pass.
Der [bestehende Kandidatenvalidator](WINDOWS-CANDIDATE-VALIDATION-20261105.md)
und der historische RC33-Pfad bleiben erhalten.

## Ablauf im bestehenden Gast-Runner

Der optionale Parameter `-CandidateVersion 0.8.0rc39` verlangt einen expliziten
`-ExpectedManifestSha256`-Pin. Ohne Kandidatenparameter bleibt das historische
Runnerformat bestehen. Ein Kandidatenlauf installiert keinen RC33-Desktoplink.
Für spätere eigene Windows-Testläufe:

```powershell
.\guest_runner.ps1 -BootstrapUrl <vorhandener-isolierter-bootstrap> `
  -WorkName <neuer-eigener-lauf> -ReusePreparedPython `
  -ExpectedManifestSha256 <geprüfter-manifesthash> -CandidateVersion 0.8.0rc39
```

Das ist keine Aufforderung, einen alten WorkName, eine UNKNOWN-Ausführung oder
eine alte Bootstrap-URL erneut zu verwenden. Der gewählte Quellcommit muss den
neuen Producer enthalten; bestehende Source-/Wheel-/Interpretergates gelten.

`windows_candidate_evidence.py` ist eine begrenzte Beobachtung, kein Executor
oder Reportkonverter. Der native CLI-Aufruf verlangt `os.name=nt` und
`sys.platform=win32`, verweigert andere Hosts ohne Ergebnis und prüft, dass
Python tatsächlich aus dem geprüften `src/kirabridge` importieren würde.

Er liest das einmal gepinnte Manifest, prüft Archivhash/-größe/Gitkommentar,
verweigert unsichere/doppelte Archivnamen und vergleicht das tatsächliche
extrahierte Modulset samt Bytes, sechs Harnesses, Versionsdateien und drei
Producerdateien mit dem Archiv. Ausgeführter `guest_runner.ps1` muss ebenfalls
dieselben Bytes wie im Kandidatenarchiv haben. Das Inventar wird durch dieselbe
`candidate_inventory`-Funktion wie beim Paketvalidator berechnet; kein zweites
Hashformat. Die reine Python-Prüffunktion erzeugt keinen Plattformnachweis.

Vor jeder Phase speichert `Run-Once` seine bestehende exklusive Attempt-Receipt.
Danach wird vor der nativen Aktion die Source erneut beobachtet. Eine geänderte
Bindung stoppt vor dem Start. Die bereits vorhandene native Prozessverwaltung
führt genau den bisherigen begrenzten Harness aus. Nach der Phase werden
dieselben Dateien erneut beobachtet; erst bei unverändertem Inventar ergänzt
der Runner seinen frisch erzeugten Bericht um Version, Commit, Inventar und
Plattform. Keine CLI akzeptiert einen alten Report als Eingabe zum Beschriften.

Frühere Attempts ohne finalen Report, Fehler oder UNKNOWN bleiben gestoppt.
Vorhandene Kandidatenreports dürfen nur mit derselben Manifest-/Source-/
Inventarbindung erneut veröffentlicht werden; keine erneute native Ausführung.
Alte RC33-Reports werden im Kandidatenmodus abgelehnt und unverändert erhalten.

## Paketvalidator und Grenzen

Enthält ein Kandidatencommit den neuen Collector, gehören zusätzlich
`windows_guest_runner.ps1`, `windows_candidate_evidence.py` und
`build_windows_dev_kit.py` in dessen Harnesshashkarte. Unvollständige Producer,
geänderte Bootstrapbytes und falsche Source-ZIP-Bytes werden abgelehnt. Ältere
Kandidaten ohne Collector und der unveränderte RC33-Pfad behalten ihren Vertrag.

Gepinnte Dateien und Vorher-/Nachher-Fingerprints sind lokale Belege, keine
Remoteattestation gegen einen bösartigen Gast. Gleichbleibende Hashes beweisen
keine Veränderungen mit zwischenzeitlicher vollständiger Rücksetzung.
Vollständige native Phasen, null Skips/Fehler, echte Artefakte und Quellbindung
bleiben nötig. Ein erzeugtes Inventar oder erfolgreicher Plan ist kein Paketpass.

Portable Tests verwenden synthetische Quellen/Reports. Lokales PowerShell7
führt die tatsächliche `Run-Once`-Funktion mit synthetischen Kindprozessen aus:
Erfolg/Legacy, Änderung vor/nach Phase, alter ungebundener Report, Fehler und
UNKNOWN, jeweils ohne zweite Ausführung oder Reportüberschreiben. Das schützt
die Ablaufänderung, belegt aber weder PowerShell5.1 noch Win32/Windows11,
Installations-/Terminal-/CLI-Parität oder Dirks konkrete Umgebung.
Keine produktive Installation, VM, Cloud-CI oder Provideraktion durch Tests.

Private Quell-/Test-/Review-/Übergabenachweise:
`~/.local/share/kirabridge/backups/bigplan-windows-evidence-20261105-v1/`.
Nächster Punkt ist ein frisch freigegebener nativer Gastlauf nach VM-/Ressourcen-
und Quellpinprüfung; bisherige Previewinstallationen nicht ersetzen.
