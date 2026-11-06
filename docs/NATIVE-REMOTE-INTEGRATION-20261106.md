# Native Koordination und Remote-Handoff: lokaler Integrationskandidat

Dieser Kandidat verbindet den geprüften nativen Stand
`017dc44458eaf5087a349a937c2ae7066ca58485` mit dem Remote-Produktvertrag und
den R2-Harnessdateien aus `21d2e2cad8e9930931b02031addfc25d819a9ed3`.
Die unveränderten Remote-Dateien stammen aus den zusammengehörigen Änderungen
`eb5c8c6`, `8628fd9`, `96acb71`, `279abc4` und `21d2e2c`.
Der lesende Integrationsaudit ist in ThreadDesk `188ce4729a62/03419aa35d8a`
festgehalten. Historische Windows-/Preflightberichte erteilen keine Freigabe.

Vier gemeinsame Schnittstellen sind kombiniert:

- `Bridge(config, *, routing_guard=None, handoff_peer=None)` erhält beide
  optionalen Wege. Der HandoffManager bekommt nur den expliziten Peer.
- Der HandoffManager bewahrt den lokalen Standardweg und prüft bei einem
  Remote-Peer die vorhandene Geräte-/Requestreservierung vor Ausführung.
- Der Store gibt den unveränderlichen Requesthash im eigenen Readback als
  `request_sha256` zurück. Die native TeamSeal-/ManagedWorker-Claimprüfung
  bleibt erhalten.
- `Peer.certificate_sha256` ergänzt explizite TLS-Leafpins. Ungepinnte Peers
  behalten ihre bisherigen Trust-/Transportregeln.

Native Routing bleibt opt-in. Ein ausgegebener TD-Handoff oder RemoteGrant
ersetzt keine TeamSeal, keine bestehende Ressourcenfreigabe und keine
Operatorentscheidung. Graphprojekt, Thread, HTTP-Transportprojekt und Coretask
behalten ihre unterschiedlichen Identitäten. UNKNOWN wird weiter nur gelesen,
nicht erneut eingereicht oder unter anderer Kennung wiederholt.

Für die Remote-Tests ist der unveränderte TD-M4-Snapshot
`a0dd4c39478b031e0e31d335c2a15435dfbc52eb` über
`KIRABRIDGE_TEST_REMOTE_THREADDESK_SOURCE` ausdrücklich einzubinden.
Ein übersprungenes Modul ist kein Testnachweis. Die R2-Rekonstruktion von
Core-/DB-/TLS-Objekten im selben Testprozess ist kein OS-Prozessneustart.
Ein späteres R3-Testpaket muss nach seiner Übernahme auf dem kombinierten
Quellstand gesondert ausgeführt und dokumentiert werden.

Dieser Stand ist eine lokale Quellenintegration. Testergebnisse, unabhängige
Abnahme und die tatsächlichen Pins stehen im zugehörigen ThreadDesk-Ergebnis
und privaten Handoff. Installation, produktive Remote-/Mehrbenutzerabnahme,
Windows-Testfreigabe und Veröffentlichung sind daraus nicht abgeleitet.
Die bisherigen negativen Reviews und historischen UNKNOWN-Belege bleiben
unverändert erhalten.
