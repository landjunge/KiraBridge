# KiraBridge 0.8.0 RC42

macOS-Intel-Kandidat für Paket BP-KB-REL-42 (macOS-Stabilität). Er hebt den
aktuellen `main` ohne weitere Codeänderung auf RC42, damit die installierte
Mac-Laufzeit eindeutig dem aktuellen Quellstand entspricht.

Enthalten seit dem installierten RC40 (`d12838a`) bzw. den RC41-Zwischenständen:

- Opt-in-Zeitmessung für Terminal- und Sitzungspfad (`KIRABRIDGE_TIMING=1`, PR #80).
- Parallele Terminalkatalogabfrage und kurz zwischengespeicherte Bildschirmsperrprüfung (PR #83).
- Stopp-Wettlauf nach Statusbericht behoben (PR #77); sichtbare Busy/Idle-Erkennung (PR #84).
- Agent-CLIs erhalten den Prozesskontonamen für Schlüsselbund-Logins (PR #86).
- Versionsanzeige in Konsole und App, klareres Installerdesign (PR #88).
- Lesbarer Live-Doctor und Endprüfung im Installer (PR #91).

Quellenintegration, CI, Paketabnahme, Installation und Betrieb werden getrennt im
datierten Installationsnachweis festgehalten. Historische UNKNOWN-Belege bleiben
unverändert; dieses Release wiederholt sie nicht und schaltet AutoNext nicht ein.

Lokaler Intel-Build; kein öffentliches Release, kein Upload. Linux bleibt beim
separat veröffentlichten `linux-v0.8.0rc41`; Windows und ARM sind hier nicht abgenommen.
