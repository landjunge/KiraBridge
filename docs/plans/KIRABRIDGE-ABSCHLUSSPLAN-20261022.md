# KiraBridge Abschlussplan — 22.10.2026
Status: Arbeitsplan, nicht als Release-Freigabe verstehen.

## Verifizierter Ausgangspunkt
Lokaler Commit dfbae48; viele vorhandene uncommittete Dateien erhalten. CLI-K1/K2 und Doctor-Reparatur lokal vorhanden. 17 gezielte Doctor-/Key-Provider-Tests bestanden (2026-10-22). Laufende RC13-Installation noch nicht aktualisiert. Kein Commit/Push für diese Arbeiten.

## Schrittfolge — einzeln nachweisen und abhaken
- [x] 0. Bestandsaufnahme und gezielte Testbasis ohne Änderungen an RC13.
- [ ] 1. Arbeitsstand sichern: Änderungsinventar, gesonderter Arbeitsbranch/Backup, bestehende Änderungen nicht überschreiben.
- [ ] 2. CLI K1/K2/K3/K4 bereinigen: Start ohne Argumente, Doctor, Diagnose, sichere Reparatur; weitere Angriffs- und Regressionstests. Keine produktive Reparatur ohne Freigabe.
- [ ] 3. Sicherheitsanbieter als Schnittstelle: Standalone macOS zuerst, Linux systemd separat; 4AllPass optional und nur nach geprüfter API. Geheimnisse nicht im Agentenkontext. Sichere Moduswahl und Wechsel sind eigenständige Abnahmepunkte.
- [ ] 4. Installer/RC13: lokale, private GitHub- und öffentliche Release-Stände vergleichen; gezielte Übernahme statt blindem Merge; Versionsnummern, Doctor, Start und Rollback konsistent machen.
- [ ] 5. Universelle Tool-Adapter: Capability-Discovery und standardisierte, minimale Adapterverträge. Bestehende ThreadDesk-Anbindung bewahren; Block Designer, Agent Authority, Tollgate, 4AllPass erst nach API-Inventar als verfügbare Module melden.
- [ ] 6. UX: einfacher `kirabridge`-Start, übersichtliche Statusanzeige/ASCII, verständliche DE/EN-Meldungen, keine falschen grünen Zustände.
- [ ] 7. Tests: gezielte Unit-, Integrations-, Installer-/Rollback- und macOS/Linux-Prüfungen; Abdeckung dokumentieren, keine Doppelprüfung ohne Codeänderung.
- [ ] 8. Release: geprüften Stand in separatem PR/Commit, CI/Review, dann kontrollierte Installation und Rollback-Nachweis. Public nur freigegebene Dateien, keine Geheimnisse.
- [ ] 9. Abschlussbericht: SHA, Testbelege, offene Risiken, Versionsvergleich, tatsächliche Modulverfügbarkeit.

## Nicht als fertig behaupten
4AllPass-Schnittstelle, Block-Designer- und Agent-Authority-Adapter, Produktivfreigabe der Doctor-Reparatur, Linux-Server-Deployment und Release-Veröffentlichung stehen aus. Sicherheitskritische Aktionen bleiben begrenzt.
