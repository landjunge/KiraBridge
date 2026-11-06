# CI temp scope / CI-Temporärdaten

Stand / Date: 2026-11-06 · BP-CI-TEMP-SCOPE-FIX-20261106
Basis / Base: `ed35490cbcf0be68b48c25914632e0882651a8f0`

## Deutsch

Run42193459301/Attempt1 scheiterte in beiden Legacy-Lanes. Die Logs enthalten
ENOSPC/SQLiteFull und separate Testvertragsfehler; Remote und Build liefen nicht.
Die beiden Netcup-Runner nutzten dasselbe `/tmp`-tmpfs. Die spätere lesende
Inventur fand dort wieder6.748.487.680Bytes frei und995.757 freie Inodes. Der
historische Peak wurde nicht gemessen. Das belegt weder einen dauerhaften
Platzmangel noch, dass sämtliche Testfehler dadurch verursacht wurden.

Verify setzt nun vor dem ersten Pythonstart ein jobeigenes `TMPDIR` unter dem
vorhandenen `runner.temp` und legt das Verzeichnis als ersten Schritt frisch an:
`kb-ci-<run>-<attempt>-<python>-tmp`. Vorhandene Verzeichnisse werden nicht
wiederverwendet oder gelöscht. Die Variablen gelten auch für die bestehenden
UV-Sync-/Buildschritte; Python muss sie bereits beim Interpreterstart erhalten.
Kinder mit absichtlich bereinigten Umgebungen übernehmen TMPDIR nicht automatisch.
Die expliziten pytest-`tmp_path`-Daten bleiben durch den Basetemp-Pfad gebunden.

[scripts/ci_remote_tests.py](../scripts/ci_remote_tests.py) bindet das explizite
`--runner-temp` an das vorhandene `RUNNER_TEMP`, prüft absolute und tatsächlich
aufgelöste Pfade, Run-/Attempt-/Pythonidentität, die erwartete Job-/Lanezuordnung
und Pythons tatsächliche `tempfile.gettempdir()`-Auswahl. Ein anderer gecachter
Pfad oder ein stiller Fallback wird nicht durch Cache-Reset repariert. Das
Tempverzeichnis muss auf demselben Device wie sein Runner-Parent liegen.

Jede Lane bekommt ein frisches Reportverzeichnis
`kb-ci-<run>-<attempt>-<python>-<lane>` und explizites pytest-`--basetemp`
`<report>/pytest-basetemp`. So darf pytest nur sein neu geschaffenes Basetemp
initialisieren; alte Läufe sind keine Cleanup-Ziele dieses Helfers. Der Aufruf
braucht `RUNNER_TEMP`, `TMPDIR`, `GITHUB_RUN_ID`, `GITHUB_RUN_ATTEMPT`, `UV_PYTHON`
und die schon bestehenden expliziten Sourceenvs/PYTHONPATH. Für lokale enge Proben
werden ausschließlich eigene frische Testverzeichnisse und ein vorhandener
Interpreter verwendet, keine Runner- oder Systemverzeichnisse.

Provenienzfeld `temp_scope` protokolliert Input-/Resolve-/effektive Pythonpfade,
pytest-Basetemp, Devices und tatsächliche `statvfs`-Werte für Gesamt-/freie/
verfügbare Bytes und Inodes. Vor- und Nachlaufmessungen sind Momentaufnahmen;
fehlende Nachlauftelemetrie wird ausdrücklich erfasst und verdeckt nicht den
ursprünglichen Test-/Gatefehler. Workspace- und Root-Devices werden mitberichtet,
nicht aus einem Jobanzeigenamen geraten. Die vorhandenen Runner.temp-Pfade lagen
bei der Hostinventur auf Root-ext4; dies ist keine Garantie für andere Runner
oder zukünftige Belegung. Es gibt keine erfundene Mindestgröße oder Platzgarantie.

Source-/Import-/JUnit-Frische-/0Skip-Gates, Auswahl der Legacy-/Remotefälle,
Jobnamen, Timeouts und Kostentrigger bleiben erhalten. Die separat korrigierte
Frische-Testfixture in `tests/test_ci_remote_tests.py` ist nicht Teil dieses
Patches. [test_ci_temp_scope.py](../tests/test_ci_temp_scope.py) prüft in frischen
Pythonkindern reale Tempdateien und einen kleinen pytest-`tmp_path`-Fall sowie
fehlende/ungültige/externe Parents, andere Job-/Lanepfade, Symlink-Auswege,
Wiederverwendung und eine bereits falsche Python-Tempauswahl. Es wird keine
56er-/29er-Produktsuite wiederholt.

Keine OS-/Mount-/Quota-/Serviceänderung, kein Hostcleanup und kein automatischer
CI-Start. Die alten pytest240/241 und Rohbelege bleiben erhalten. Root integriert
nach unabhängigem Review zusammen mit den getrennten Testvertragskorrekturen.
Dieser interne CI-Patch ändert keine README-/Webseiten-/Downloadverfügbarkeit.

## English

Verify now creates a fresh job-specific TMPDIR under the existing runner.temp
before Python starts. The helper verifies the declared runner parent, resolved
run/attempt/Python/lane paths and Python's actual tempfile selection, refusing
external paths, stale caches and reused report directories. Each lane receives
an explicit fresh pytest basetemp under its report directory.

Temp provenance records real paths, device IDs and OS-reported byte/inode
capacity counters before and after the run. These observations provide no
future space guarantee; no mount, quota, service or system configuration changes
are made. Existing source/import/freshness/no-skip gates, test selection,
timeouts and cost controls are preserved. The separate timestamp-fixture repair
is outside this patch. Focused hermetic tests use fresh local Python children;
no remote integration suite or CI rerun is started. Earlier run artifacts and
pytest directories are preserved.
