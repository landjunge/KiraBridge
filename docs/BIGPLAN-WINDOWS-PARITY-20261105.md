> **Nicht maßgeblich. Maßgeblich ist ThreadDesk-Thread `188ce4729a62` (Nutzerbeschluss 09.11.2026). Diese Datei ist Archiv bzw. technischer Spiegel.**

> Historischer Quellenstand aus `21d2e2cad8e9930931b02031addfc25d819a9ed3`,
> bei der Integration am 06.11.2026 bewahrt. Aktueller Quellen-, Prüf- und
> Installationsstand: [RC40-Integrationsnachweis](RC40-INTEGRATION-INSTALL-20261106.md).
> Datierte Plan- und Gateangaben sind keine neue Auftrags- oder Berechtigungsquelle.

# Windows für Dirk: belegter Bestand und nächster Schritt

Auftrag `bigplan-windows-parity-audit-20261105-v1`, Karte
`482f593429ad/c803df9cc369`. Am 05.11.2026 von Codex/root unter derselben ID
abgeglichen. Keine erneute Queuezustellung: kein Team-/Corelauf für diese Karte
vorhanden, globale alte AutoNext-Instanz aus, reservierter Worktree sauber und
Bericht bislang nicht angelegt. Der neue separate Koordinatorloop ist aktiv,
meldet `complete/no_authorized_ready_card` und wurde nicht verändert.

Dieser Dokumentationsbranch basiert weiterhin auf `511f289fc5109f5d6893d5df8843254628c385ba`.
Geprüfte weiterentwickelte Quelle: Koordinationsworktree bis
`8628fd92743cbc08aa968c8b59a5ab892cb88cdf`. Der bereits integrierte Grok-Patch
`070ea70` mit Rootkorrekturen `ae699cb` wird nicht neu beauftragt.

| Bereich | Implementiert / belegt | Grenze |
|---|---|---|
| Win32-Core | Owner-/ACL-/Reparseprüfung, private Dateien, Prozesslock, SQLite-/Eventjournal; vier native Harnessfälle vorhanden | Historische RC33-Belege, kein aktueller gemeinsamer Core-/RC39-Paritätspass |
| Tastatur und Fenster | Gebundene native Ziele, Sequenz, Modifierfreigabe, Shortcuts, Fensterstatus/Geometrie und reguläres WM_CLOSE | Anfrage/Zustellung bleiben von tatsächlicher Anwendungsverarbeitung getrennt |
| Windows-Preview | Authentifizierter Loopback-MCP HTTP/stdio, acht eingeschränkte Capabilities; keine Eingabe beim Start | Allgemeine Datei-/Prozess-/Terminal-/CLI-Steuerung ist nicht im Preview freigegeben |
| CLI-Semantik / Sitzungen | Gemeinsame Codex-/Grok-/weitere Providerlogik vorhanden | Terminal.app-Transport prüft `darwin`; kein vorhandener Windows-Tab-/TTY-/CLI-Rücklesepass daraus ableitbar |
| Team/AutoNext | Gemeinsamer Core-/Claim-/Idempotenzcode vorhanden; Mac-Belege und neuer isolierter Mac-Koordinator getrennt | Kein Windows-Dienst-/Neustart-/CLI-E2E-Nachweis |
| Windows-Kit | Quellengebundener RC33-Paketpfad und neuer expliziter Kandidatenvalidator vorhanden | Neue Modul-/Harness-/Versionsinventare brauchen passende im Gast erzeugte Berichte |

Frisch bytegleich zur RC33-Quelle `ce0687dd8831dae261bf285922a146bcf3aedc41`:
vier native Windowsbackenddateien (`keyboard.py`, `windows.py`,
`filesystem_security.py`, `locking.py`), `windows_preview.py` sowie die fünf
`accept_windows_*`-Harnesses. Das beweist Wiederverwendbarkeit dieser Dateien,
keinen aktuellen nativen Pass des veränderten gemeinsamen Cores.

Das vorhandene ZIP
`KiraBridge-integration-audit-20261104/release-rc33-final/KiraBridge-0.8.0rc33-Windows-Dev-Kit.zip`
wurde erneut nur gelesen: SHA256
`1002e68cbef96c7fd9a383d542beb5abc727f5843316352a65638fe4266a919a`.
Keine Änderung am Artefakt oder historischem Installationsstand. Die laufende
Mac-Bridge bleibt RC39@`8d331314b608`, PID40336; das ist kein Windowsbeleg.
Kein laufender VM-Prozess wurde bei diesem Abgleich gefunden. Eine VM-Identität,
Ressourcen, aktiver Gast oder Dirks tatsächliche Windows-/CLI-Konfiguration
wurden nicht frisch nativ geprüft.

## Konkreter fehlender letzter Schritt

Der vorhandene `windows_guest_runner.ps1` erstellt je Phase `phase`, Prozess-ID,
Exitcode, Manifesthash und Artefakt, aber noch kein neues Kandidateninventar.
`require_windows_candidate_report` verlangt hingegen native Plattform,
Kandidatenversion, Commit und exakte Modul-/Harness-/Versionshashkarten.
Ohne Produzent kann ein legitimer neuer Lauf diesen Vertrag nicht erfüllen.
Alte Berichte nachträglich um diese Angaben zu ergänzen wäre kein Nachweis.

Nächstes begrenztes Quellpaket:
`BIGPLAN-WINDOWS-EVIDENCE-PRODUCER-20261105-V1` auf eigenem Branch ab8628fd9.
Bestehenden Runner optional ergänzen, tatsächliche extrahierte Quellen gegen
gepinntes Archiv vor und nach jeder Phase prüfen, nur den frisch entstandenen
Bericht binden, Runner-/Collectorbytes mitbinden. Bestehende Vier-/Sechsphasen-
Gates, RC33-Defaults, Exklusivreceipts und UNKNOWN ohne Replay erhalten.
Gezielte portable und lokale PowerShell-Vertragstests sind keine Win32-Abnahme.

Danach getrennt: exakte Kandidatenquelle einfrieren; vorhandenen Windows-Gast
und seine Ressourcen/Identität prüfen; neuen disjunkten eigenen Testlauf mit
allen sechs passenden Phasen durchführen. Vorhandene Installationen/Arbeiten
erhalten. Erst mit diesen Belegen neues Dirk-Kit bauen; Installation, Upgrade,
Rollback und angebotene Fähigkeiten nativ prüfen. Kein Versand, keine neue
OS-Installation und keine Windows-Terminal-/Agentenparität ohne Nachweis.
