# KiraBridge 0.8.0rc24 – Intel macOS: Terminal und Zuverlässigkeit

Dieses Prerelease veröffentlicht den auf Intel macOS geprüften und installierten
Quellstand **023f70feefcf8fcaa17b0637738b02644ad6b357**. Das ZIP enthält genau
diesen Commit; spätere Dokumentationscommits ändern die Paketquelle nicht.

## Änderungen

- Terminal.app erzeugt und bestätigt ein separates physisches Fenster, bevor
  Befehle starten. Nonce, TTY, App-/Worker- und Prozessgeneration binden das Ziel;
  eine Creationreceipt bleibt bei ungewissem Ausgang erhalten. Nach bestätigtem
  Tab-Move werden wechselnde CG-Rollen korrekt zugeordnet und kurze AX-/CG-
  Übergangsdifferenzen begrenzt rein lesend beobachtet. Kein automatischer Replay.
- Konkrete Terminalauswahl hängt nicht mehr von unbeteiligten tmux-Abfragen ab.
  Eingabe prüft die vollständige Prozessgeneration unmittelbar vor dem Effekt;
  beschäftigte, veraltete oder mehrdeutige Ziele werden verweigert.
- MCP-Verbindungen behandeln konkurrierenden Verbindungsabbau und veraltete
  Kataloge konsistent. Admission, Locks und Gesamtaufrufe sind zeitlich begrenzt;
  validierte Kataloge sind größenbegrenzt, redundantes Listing entfällt.
- Native macOS-Kommunikation begrenzt Bootstrap-Ausgaben, Laufzeit und Frames.
  Accessibility setzt Beobachtungstimeouts früh; Console-Navigation bleibt auf
  die vorgesehene Origin und den eigenen Starterbeleg begrenzt.
- Dateiverschieben verwendet private Inode-/Sentinelbindung und überschreibt kein
  vorhandenes Ziel. Eine gleichzeitig neu angelegte Quelle bleibt erhalten;
  unterbrochene Vorgänge behalten Wiederherstellungsdaten statt automatischem Replay.

## Tatsächlich geprüft

Auf **Intel x86_64, macOS 15.7.4**, mit **Codex CLI 0.166.0**:

- Exakter offizieller Paket-Smoke: authentifizierter Dispatcher, geladener
  Quellvergleich, Korruptpaketverweigerung, Konfigurations- und Credentialerhalt.
- Reale native Abnahme desselben Pakets in einem isolierten Dispatcher: ein
  separates eigenes Terminalfenster, bestätigte Shell und Codex-Start,
  Ausgabelesen, lange Literalnachricht mit genau einem Paste/Return sowie
  `body_only_v1`-Handoff mit unabhängig gebundener Antwort.
- Busy-, Stale-PID- und mehrdeutige Geometrie wurden vor Eingabe verweigert.
- Unterstützte sichtbare Aktualisierung von Core, Freigabekonsole und App;
  tatsächliche Laufzeit-, Quellen-, Codesign- und Authentifizierungsprüfung.
  Der aktuelle MCP-Anschluss erreichte danach den neuen Dienst und las dessen
  Terminalausgabe. Konfiguration, Zugangsdaten und bestehende Agentensitzungen
  blieben erhalten; eigene Test-/Installationsfenster wurden geschlossen.

## Grenzen

- **Kein neuer vollständiger CI-Lauf und kein neuer plattformübergreifender
  Freigabenachweis.** Die finalen lokalen Änderungen sind hier für Intel macOS
  belegt. Dieses ZIP enthält eine native **x86_64**-App; es ist keine neue
  Apple-Silicon-, Linux- oder Windows-Abnahme.
- Die komplette Codex-Abnahme lief im isolierten Dispatcher mit exakt derselben
  Paketquelle. Die produktive Instanz wurde anschließend gesondert geprüft;
  eine zweite komplette Codex-Ausführung im Produktivdienst wird nicht behauptet.
- tmux war auf dem geprüften Mac nicht verfügbar. Bei unbeobachtbarem Desktop
  verweigert der Fensterpfad sicher. Das begrenzte geprüfte Codex-Eingabeprofil
  bedeutet keine allgemeine Unicode-/Geometriegarantie.
- Die bestehende Diagnosehistorie bleibt am Kapazitätslimit. Task-, Nachrichten-
  und Auditbelege bleiben unabhängig davon verfügbar.
- Native App ad hoc signiert; keine Apple-Notarisierung wird behauptet.
- Das Repository ist privat. Release und Download benötigen GitHub-Zugriff auf
  `landjunge/KiraBridge`; ein anonymer öffentlicher Download ist nicht verfügbar.

## Download und Integrität

**KiraBridge-0.8.0rc24-Intel-macOS.zip** – 2.900.052 Bytes.

SHA256: `ba68a3f42b09abf7c7aec11eaf913a994d5bfe2ed6036fe5c61d9a70e033dcd9`

Die gleichnamige `.sha256`-Datei und `PACKAGE-ACCEPTANCE-INTEL.json` liegen als
zusätzliche Release-Assets bei. Frühere Kandidatenhinweise innerhalb des
unveränderten ZIPs sind historische Checkpoints; diese Release Notes und der
Abnahmebeleg beschreiben den erreichten Stand.
