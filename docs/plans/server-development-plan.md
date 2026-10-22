# KiraBridge Server — Entwicklungsplan (22.10.2026)

Status: Planung, keine Server-Implementierung oder Bereitstellung.

## Ziel
Gemeinsamer KiraBridge-Kern für lokale macOS- und entfernte Debian-Instanzen. Server-spezifische Komponenten bleiben im Branch `development/server`; lokale Arbeit im Branch `development/local`. Kein doppelter Kern und kein ungeprüfter Merge.

## Architektur
- Einheitlicher versionierter Modulvertrag mit Capability Discovery, Eingabevalidierung und nachvollziehbaren Fehlern.
- Adapter für ThreadDesk (Kontext/Dokumente), Block Designer (Design), Agent Authority (Identität, Delegation, Evidence), Tollgate (Budgets und Ressourcen) und 4AllPass (Tresor). Vorhandene APIs vor Implementierung prüfen.
- Agent Authority entscheidet Berechtigungen, Tollgate kontrolliert Budgets; KiraBridge transportiert und orchestriert, ohne diese Rollen zu duplizieren.
- 4AllPass-Zugriff nur nach expliziter Entsperrung, kein stiller Zugriff auf Geheimnisse; Sperren/Ruhezustand/Schließen entziehen Freigabe. Papierkorb endgültig leeren nur bei gesonderter aktiver Freigabe und ausdrücklichem Auftrag.

## Umsetzung in Etappen
1. Bestehenden KiraBridge-Kern und vorhandene Schnittstellen inventarisieren; keine Doppelprüfungen.
2. Gemeinsame Modul-Spezifikation und lokale/Server-Konfiguration definieren.
3. Debian-Serveradapter: authentifizierte Verbindung, TLS, eng begrenzte Rechte, Audit und robuste Fehlerbehandlung.
4. Ressourcenlimits, Rate-Limits, Recovery, Backup, Datenschutz/Löschfristen und Monitoring ergänzen.
5. Adapter je nach Verfügbarkeit der externen Module schrittweise integrieren; Sicherheits- und Kompatibilitätstests durchführen.
6. Dokumentieren und erst nach erfolgreicher Prüfung gezielt bereitstellen.

## Abgrenzung
Dieser Branch enthält zunächst nur den Plan. Keine Secrets einchecken, keine produktiven Serveränderungen, kein automatischer Push auf eine Laufzeitumgebung. Gemeinsame Kernänderungen sollen später kontrolliert zwischen den Zweigen geteilt werden.
