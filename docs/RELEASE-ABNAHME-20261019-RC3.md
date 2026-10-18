# KiraBridge · private RC3-Abnahme · 19.10.2026

Neuer eigenständiger Kandidat `0.6.0rc3`, Basis `ae15715` mit geprüftem
Anwendungscode bis `612a5c8`. Vollständiger endgültiger Quellpin wird beim Bau in
`release.json` sowie im separaten Artefakt-/Prüfmanifest aufgezeichnet.
Historische [RC2-Belege](RELEASE-ABNAHME-20261018.md), Tags und Assets bleiben
unverändert. Dies ist keine Abnahme aller Tools oder der laufenden Installation.

## Vorgesehene gezielte Paketabnahme

Vor Freigabe des privaten Entwurfs: einmaliger bestehender CI-Paketlauf auf
macOS15/Apple Silicon und Ubuntu24.04 x86_64; dieselbe isolierte Paketprobe auf
macOS15/Intel. Zu prüfen: Version/Quellpin, bytegleiche LICENSE in allen Formaten,
Operatoranleitungen, gehashtes Startpaket, authentifizierter isolierter Dispatcher,
konkrete Readiness/geladener Quellabgleich, erneute Vorbereitung ohne Konfig-/
Schlüsseländerung, verwalteter Upgradeweg und Ablehnung beschädigter Pakete.
Nur synthetische Konfiguration/Dateien; keine Nutzerkonten, persönlichen Dienste,
Agenten-/Modellaufträge oder Tunnel. Tatsächliche Ergebnisse stehen im neuen
Prüfmanifest und plattformspezifischen Smoke-Beleg; dieser Absatz ist kein Ergebnis.

## Vor öffentlicher Freigabe offen

- Ausdrückliche Freigabe genau des vollständigen Veröffentlichungspakets.
- Bedienabnahme auf frischer Benutzerinstallation mit tatsächlicher
  macOS-/Linux-Benutzerdienstintegration und Einrichtung des vorgesehenen Chats.
- Zielkonto-/Workspace-/Tunnelberechtigung, soweit vom jeweiligen Anbieter nötig.
- Drittanbieterbedingungen und Wartungs-/Sicherheitsbewertung des auf
  Intel-macOS begrenzten cryptography48.0.1-Pins; kein unabhängiges Sicherheitsaudit.
- Optionaler ThreadDesk-/TollGate-Betrieb benötigt separat geprüfte lokale Quellen,
  eigene feste Konfiguration und konkrete Rechte. Kein Budget-/Protected-Host-
  oder allgemeiner Geheimnis-Isolationsnachweis durch dieses Paket.

Lizenz unverändert: Netzwerkpunkt Personal Use License1.0, Deutsch maßgeblich,
SHA256 `3316d5eda60ac1fea355aa43d196feea3567384179b55ca88c8636c0322021ec`.
Individuell, kein OSI-Standard und nicht anwaltlich geprüft. KiraBridge bleibt
privat; keine öffentliche Discussion, DNS-/Hostingänderung oder automatische
Umstellung der gesunden Betreiberinstallation.

## English

New private `0.6.0rc3` candidate; exact final source and actual test results are
recorded in package metadata and the evidence manifest, not inferred from this
checklist. Earlier RC2 artifacts remain immutable. Isolated platform checks do
not prove a fresh user service or a new ChatGPT account. Publication needs an
explicit decision for this exact package, fresh install/user-service/chat
acceptance, third-party terms and review of the older Intel dependency pin.
ThreadDesk/TollGate are optional external local sources, not automatically bundled.
No public release, Discussion or change to the healthy operator installation.
