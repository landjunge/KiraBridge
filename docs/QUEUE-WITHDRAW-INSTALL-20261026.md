# Alte Queue-Einträge und die Reservierung vom 21. Oktober

Stand vor Paketaktivierung: Der Nutzer verlangt die alten blockierten Einträge
zurückzunehmen und die anschließende Installation im sichtbaren Terminal zu sehen.
Die drei laufenden Codex-Sitzungen und sämtliche Historie bleiben erhalten.

## Gezielte Reparatur

`queue.control` unterstützt zusätzlich `withdraw` mit ausdrücklich bestätigtem
`acknowledge_execution_unknown: true`, aktueller Eintragsrevision und unveränderten
Rechte-/Ownership-/Freigabeprüfungen. Nur unbekannte Ausführungen sind so aus der
aktiven Ansicht rücknehmbar. Eine separate additive Tabelle `queue_withdrawals`
speichert die Rücknahme; Auftrag, Ergebnis und Ereignisse bleiben unverändert.
Diese Ansichtsrücknahme gibt **keine Ausführungsreservierung** frei und beendet
keinen Prozess. Eine ältere Runtime kann die Einträge wieder anzeigen, sie aber
nicht automatisch ausführen: ihr Originalzustand bleibt `unknown`.

Für die tatsächliche alte Zustellsperre gibt es einen getrennten, strengeren Weg:
`retire` mit derselben ausdrücklichen Bestätigung prüft das **gespeicherte
Originalziel**, nicht irgendein gerade offenes Codex-Fenster. Eine ungefilterte
native Fensterinventur muss die ursprüngliche Fenster-ID als abwesend zeigen;
zwei erfolgreiche globale PID-Inventuren vor und nach dieser Beobachtung müssen
sowohl die ursprüngliche Shell- als auch Agent-PID als abwesend bestätigen.
Existierende oder wiederverwendete PIDs, unvollständige Daten, Beobachtungsfehler,
Rechteänderungen und geänderte Revisionen verweigern die Aktion. Der bisherige
Retire-Weg über ein positiv bereites zugeordnetes Ziel bleibt erhalten.

Eine erfolgreiche Gone-Rücknahme setzt die vorhandenen Holds für genau den
alten Handoff und seine Nachricht. Sie beendet kein aktuelles Terminal, sendet
keine Eingabe und beansprucht keinen Abschluss externer oder abgekoppelter Arbeit.
Ausführung bleibt `unknown`; nur die belegbar veraltete Zustellreservierung entfällt.
Readbacks zeigen jetzt ausdrücklich `delivery_retired` und
`execution_reservation_active`; historische Unsicherheit wird damit nicht mehr
als aktive Sperre dargestellt. Eine reine Ansichtsrücknahme setzt diese
Reservierung weiterhin **nicht** außer Kraft.

## Tatsächliche Vorprüfung auf diesem Mac

Auf Intel-macOS 15.7.4 wurde der neue reine Beobachtungspfad mit der tatsächlich
erteilten Codex-Policy und einem eigenen isolierten Security-Store ausgeführt:
Originalfenster `22104`, Shell `94023` und Agent `68530` fehlen. Die produktive
Datenbank wurde dabei nicht geöffnet; kein Fenster aktiviert und kein Zeichen
oder Signal gesendet. Der Handoff
`channel-dae0da0ab69449999007d02ef3c137d5` ist **noch nicht zurückgenommen**, solange
dieses Paket nicht aktiviert und die eigentliche kontrollierte Aktion ausgeführt ist.
Eine spätere Aktion prüft diese Voraussetzungen erneut; der lokale Vorbeleg ist
kein wiederverwendbares Rücknahmetoken.

19 gezielte Rücknahmefälle, 26 Prüfungen des Gone-Retire-Pfads und direkt betroffener
Regressionen sowie drei neue Statusfälle mit vier direkten Regressionen sind in den
jeweiligen Teamphasen belegt. Diese Mengen überlappen; sie werden nicht addiert.
Root hat nach Integration die drei neuen Testdateien gemeinsam geprüft:
**44 bestanden in 2,68 Sekunden**, Ruff/Format ebenfalls bestanden. Die gemeinsame
Prüfung ist wegen der geteilten Revisionen, Status- und Controllerpfade erforderlich;
keine lokale Anwendungsgesamtsuite wurde vorsorglich wiederholt.

## Bereits erfolgte begrenzte Bereinigung

Vor Installation konnten elf alte, nie beanspruchte Nachrichten über das vorhandene
`queue.control` zurückgenommen werden. Weitere 25 bereits zugestellte Nachrichten
ohne Ausführungsjob wurden unter der tatsächlichen Empfängeridentität gelesen und
quittiert und anschließend mit `queue.control` bestätigt. Ihre Inhaltshashes bleiben
gleich. Eine nach der Bestandsaufnahme neu eingegangene Nachricht wurde ausgeschlossen.
Das sind keine beendeten Agent-Aufträge. Die 26 unbekannten Task-Ausführungen sowie
die beiden unsicheren Nachrichten und alte Handoffreservierung sind noch erhalten.

## Paket und sichtbare Aktivierung

Aus dem finalen sauberen Commit zweimal bauen und SHA-256-Summen vergleichen,
danach genau ein passender nativer Paket-Smoke und ein isolierter Upgrade-/Rollback-
Test von der tatsächlich installierten Quelle `012b592` mit dem gebauten Paket.
Bestehende Konfiguration, Credentials und Berechtigungen bleiben beim Produktiv-
Upgrade erhalten; kein neues Full-Access-Profil und keine TCC-Änderung.

Die Aktivierung soll in einem neu geöffneten, eindeutig bestätigten sichtbaren
Terminal stattfinden; der launchd-Dienst läuft anschließend unabhängig davon.
Die technisch notwendige Reihenfolge Paketaktivierung → neuer Retire-Aufruf ist
mit der ursprünglichen Anweisung Bereinigung → Installation abzustimmen. Keine
Produktivaktivierung oder erfolgreiche Entfernung als erledigt behaupten, bevor
sie tatsächlich durchgeführt und unabhängig zurückgelesen wurde. Pflichtchecks,
fehlende gehostete Mac-/ARM-Abnahme und normale Merge-/Release-Gates bleiben erhalten.

**English:** Withdrawal hides an uncertain queue entry while preserving its execution
state and history. It never releases an execution reservation. Retirement is separate:
the new explicit path proves that the stored original window and both original PIDs
are absent, with fail-closed permissions and revision checks. A retired handoff remains
historically `unknown` but is explicitly marked as no longer reserving delivery.
No running Codex session is stopped. Candidate activation and actual retirement
remain pending until the built package and authorized sequence are verified.

[Structured preflight evidence](evidence/queue-withdraw-install-preflight-20261026.json)
