# RC33 auf Intel installiert · 0.9.0 wegen Funktionsfehler gestoppt

Stand: 4. November 2026, 12:41 UTC. Der Nutzer hat bei Sperre, Berechtigungsproblem
oder fehlender Kompatibilität ausdrücklich einen Stopp verlangt. Die aktuelle
Installation, die Funktionsabnahme und die weitere Releasearbeit sind deshalb
getrennt zu bewerten.

| Bereich | Nachgewiesener Stand |
| --- | --- |
| Merge | PR58 gemergt; RC33-Paket-/Tagquelle `ce0687dd8831dae261bf285922a146bcf3aedc41`, keine neue Zusammenführung |
| RC33-Release | Elf vorhandene Assets erneut gegen GitHub-Größen/Digests und bereits heruntergeladene Bytes geprüft; unverändert |
| Intel-Kompatibilität | x86_64, macOS15.7.4, Paketminimum12.0, strikte Signaturen und 606 Installermanifestdateien geprüft |
| RC33-Installation Intel | Sichtbarer, eigener Terminal; 12:27:06–12:27:39UTC, Exit0; tatsächlich laufender Core21571/RC33/Sourcece0687d |
| RC33-Funktionsabnahme Intel | Erster Texttask nach Annahme/Start beim Native-Commit `unknown / keyboard_unsupported`; keine positive Tastatureingabe bestätigt |
| Return / Shortcuts / Fenstersteuerung | Nach diesem Fehler **nicht ausgeführt**, weder bestanden noch als Fehler dieser Funktionen bewertet |
| Windows RC33 | Vorhandener unabhängiger Nachweis08:53UTC: PID5956/8767, 174 Module, dev2/dev3 erhalten; VM12:12UTC als laufend beobachtet, keine neue Gast-Livenessprüfung |
| 0.9.0 Builds / Releases / Installationen | Nicht begonnen; keine Sourceänderungen, Pakete, Tags, Veröffentlichungen oder Installationen für0.9.0 |

## Sicherung, kontrollierte Umschaltung und Erhalt

Vor Installation wurde RC30 separat privat gesichert:
`~/.local/share/kirabridge/backups/rc33-intel-install-20261104T122400Z`.
Die Sicherung enthält zwölf relevante Config-/Credential-/Dienst-/Launcherdateien,
ein konsistentes SQLite-Backup mit `integrity_check=ok`, die Desktop-App und die
Bindung an den erhaltenen alten Releaseordner. Geheimnisse wurden nicht ausgegeben.

Der produktive Installer erzeugte zusätzlich den unmittelbaren Rückweg
`~/.local/share/kirabridge/install/backups/20261104-132711-8d912eff` auf
`0.8.0rc30-2d540ee05f94`. Er enthält Transaktion, vorherige Definitionen,
Konfiguration, Credentials, App und konsistente SQLite-Sicherung. Ein Rückfall
muss die bestehende Installer-Rollbackfunktion verwenden und neue Nutzerdaten
erhalten; keine alte Datenbank über spätere Ergebnisse kopieren.

Der tatsächliche neue Core hat PID21571, Start12:27:23.796691UTC, Instanz
`0c145048b0b34e3f81ad4b157515ec40`, Version0.8.0rc33, Native-Sourcece0687d.
Permissionrevision ist unverändert. Unabhängig bestätigt: sieben Configdateien,
Tabellenschema, ursprüngliche Rows von elf Inventaren und alle sieben unmittelbar
vor dem Wechsel erfassten Agent-/Shellidentitäten erhalten. Alle174 installierten
Pythonmodule stimmen mit veröffentlichtem Wheel und Source überein; Nativebytes,
Modi und Desktoppin ebenfalls. Der eigene Installationstab wurde geschlossen;
Abwesenheit zweimal und vier aktuelle Fremdpaare/CG1604+2831 erhalten bestätigt.

## Konkreter Funktionsblocker

Ein gesonderter geprüfter Validator verband sich mit dem **tatsächlich laufenden**
Loopback-Core über die vorhandene Codex-Identität. Es wurde kein privater Core
als Produktionsnachweis verwendet. Vor den Effekten bestätigte der native
Worker Accessibility und PostEvents als vorhanden; kein Grant wurde angefordert.
Eine UUID-eigene Test-App wurde erfolgreich gestartet.

Der erste Texttask
`prod-accept-cbb3af3579a14cbeb00037368c2a8b72-text` wurde angenommen und gestartet,
Versuch1. Originalzustand ist **unknown**, Fehlercode **keyboard_unsupported**,
Resultat/Abschluss fehlen. Letzter Nachweis ist `native_keyboard_commit_attempt`,
Transfer `44ee79243f1f3774e8a36c6ae3161566e7faf548b2db96d0de34f63af559498f`.
`automatic_retry=false`, `safe_to_retry=false`. Das ist kein bloßer Argumentfehler:
installiertes Modell und tatsächlicher Argumenthash stimmen; Preflight war
autorisiert, automatisch und bereit, ohne fehlende Capabilities.

Der frische private Receiver-Snapshot um12:40:41UTC zeigte leeren Text sowie
Eventsequenz/Down/Up/Return jeweils0. Diese Beobachtung ist kein positiver
Eingabe- oder endgültiger Zero-Effect-Receipt; der Originaltask bleibt unknown.
Kein Resend, keine zweite Eingabe und keine Fortsetzung mit Return/Shortcut/
Fensteraktionen. Die eigene Fixture PID22540, Start1793795676.863694,
Fenster2910 wurde von uns nicht beendet und war beim Snapshot noch vorhanden.
Die unveränderte Fixture hat einen eigenen600s-Timer. Um12:47:51UTC bestätigte
ein separater reiner Kernel-Prozessreadback PID22540 als abwesend; kein manueller
Close/Kill wurde ausgeführt. Der Originaltask bleibt unverändert unknown.

Der genaue native Guard ist aus den vorhandenen Belegen nicht eindeutig
bestimmbar: `system_transport.py` ersetzt die native Detailmessage durch einen
generischen Text. Keine Rechteausweitung, Produktreparatur, weitere
Neuinstallation oder blinder Rollback wurde daraus abgeleitet. Der Diagnose-
Observer meldet außerdem sein bestehendes Auditbudget als erschöpft; weder
Historie gelöscht noch Quote geändert, und kein Kausalzusammenhang behauptet.

## 0.9.0 und nächste Voraussetzung

Die Windows-, macOS- und Releaseagenten haben ausschließlich lesend vorbereitet.
Eine gemeinsame0.9.0-Quelle, je ein Windows-/Intelpaket, Prüfsummen, Release Notes,
VM-Abnahme und kontrollierte Installationen sind geplant, aber **nicht gebaut
oder freigegeben**. Windows würde eigene Pfade/Port8768 verwenden und dev2/dev3/
RC33 schützen; tatsächliche Modulzahl und finale gemeinsame Commitbindung wären
frisch zu prüfen. Kein ARM-/Cloud-CI-Lauf wurde gestartet.

Vor Fortsetzung muss der native Commitfehler geklärt und die positive Abnahme
am echten Core nachgewiesen werden. Die hier verlangte Stoppgrenze wird
eingehalten; kein fehlender Nachweis wird durch einen Versionssprung ersetzt.

Maschinenlesbar: [Installations- und Gatebelege](evidence/rc33-intel-install-090-gate-20261104.json).
Lokaler Audit mit unveränderten Rohbelegen:
`/Users/landjunge/KiraBridge-release-090-audit-20261104/`, insbesondere `JOURNAL.md`,
`rc33-production-functional-01/diagnosis-readonly/DIAGNOSIS.md` und `team/`.
