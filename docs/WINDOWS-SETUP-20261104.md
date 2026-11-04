# Windows-Einrichtungsassistent: Prüfung vom 4. November 2026

**0.8.0rc37.dev1 ist als Windows-Kandidat lokal geprüft. Veröffentlichung,
Downloadprüfung und getrennte Installation sind noch in Arbeit.** Der vorhandene
macOS-Release RC36 bleibt davon getrennt. Diese Seite bestätigt noch keine
veröffentlichte oder dauerhaft laufende neue Installation.

Der neue Assistent führt in vier verständlichen Schritten durch den Windows-Start,
die Vorbereitung der Verbindung, das Hinzufügen in ChatGPT und einen frischen
Antwortcode. Die [Anleitung für Nutzer](WINDOWS-SETUP.md) beschreibt den Ablauf.
`Einrichtung-starten.cmd` übernimmt die Vorbereitung; Python- oder
PowerShell-Befehle sind dafür nicht erforderlich. Der offizielle Verbindungsclient
liegt mit geprüften Bytes im Paket und benötigt keinen zusätzlichen CDN-Download.

Die Zustimmung zur Tastatur- und Fenstersteuerung ist zunächst ausgeschaltet.
Der Runtime-Schlüssel gehört ausschließlich in das verdeckte Feld des
Assistenten. Er wird nach der Übergabe aus diesem Feld entfernt und nicht in
Diagnosemeldungen ausgegeben. Anmeldung, Tunnel und Kontoberechtigungen erfordern
weiterhin das eigene Konto. Für Windows ist eine eigene Verbindung vorgesehen;
vorhandene Mac-Verbindungen werden nicht übernommen.

## Frische native Abnahme

Alle **sieben** Phasen des Laufs `59659bd42fea49cd84ef869cd088fcf1` bestanden in
der bestehenden Windows-11-AMD64-VM mit Python **3.14.10**. Alle sieben Nachweise
gehören zu Quellstand `0a2f7cb8cf84d47462a094917241950a152fe364` und Manifest
`6b34b75caac1348ec18fc2a2f43d3a513f1c0a28bc479cd65c0ac217f9c3f9af`.
Es wurden keine älteren Phasen als aktuelle Abnahme wiederverwendet.
Die [bereinigte Zusammenfassung](evidence/windows-setup-native-20261104.json)
verknüpft diese Aussagen über Prüfsummen mit den privaten Originalberichten.

| Phase | Belegtes Ergebnis |
| --- | --- |
| Core | Vier native Prüfungen bestanden, keine übersprungen: private Dateien, Prozesssperre, ACL-Verweigerung und SQLite/Ereignisjournal. |
| Tastatur | Neun Fälle am eigenen Empfänger: acht echte Tasten für „Stern am“, US-/DE-Layout, AltGr, Unicode, Return, Backspace, erweiterter Pfeil und F2. Reihenfolge, Text und Ereigniszahl stimmten. |
| MCP | Authentifiziertes lokales HTTP lieferte acht Tasten mit 18 Ereignissen exakt. Dieselbe abgeschlossene Task-ID erzeugte beim erneuten Abruf null zusätzliche Ereignisse oder Taskübergänge. Veraltetes Ziel und entzogene Rechte erzeugten null Eingabe. |
| Preview | Ohne Zugangsdaten HTTP 401; genau acht Fähigkeiten und fünf Windows-Operationen; null Tasks. Der eigene Testprozess wurde beendet und unabhängig als abwesend bestätigt. |
| Shortcuts | Ctrl+A, Ctrl+S, Shift+Tab und Alt+F2: vier native Aufrufe, 16 Ereignisse, korrekte Modifier-Reihenfolge und echte WM_SYSKEY-Rückmeldung für Alt. Die Kontrolle mit bereits gehaltener Modifier-Taste erzeugte null Eingabe. |
| Fenster | Sieben Aktionen mit unabhängiger Windows-Rücklesung bestanden: Verschieben/Größe, Maximieren, Wiederherstellen, Minimieren, Wiederherstellen, Aktivieren und Schließen. Veraltetes Ziel und fehlende Rechte ließen das Hauptfenster unverändert. Alle eigenen Testfenster waren danach abwesend. |
| Einrichtung | Echtes sichtbares Tk **9.0.4**, Zustimmung aus, Schlüsselfeld verdeckt, neue isolierte Venv und installiertes Kandidaten-Wheel. Der echte Controller startete einen eigenen lokalen Server auf einem freien Testport und bestätigte einen authentifizierten simulierten Rückweg. |

Der Fenster-Schließauftrag bestätigte weiterhin nur die Annahme von `WM_CLOSE`:
`outcome:"requested"`, `observed:false`. Der unabhängige Empfänger sah danach
genau eine Schließnachricht am Hauptfenster und dessen Abwesenheit. Das Hilfsfenster
erhielt separat eine eigene Schließnachricht. Der Fenstertest sendete null
Tastaturereignisse. Globale Windows-Tastenkombinationen wurden nicht ausgeführt.

Die Tastatur-, MCP-, Shortcut- und Fenster-Fixtures hatten je einen getrennt
protokollierten normalen Bereitschaftsklick: drei Mausereignisse in einem
nativen Aufruf. Diese Vorbereitung gehört nicht zur Zahl der getesteten Tasten.
Keine Zwischenablage wurde verwendet; ungewisse Eingaben wurden nicht wiederholt.

## Was der Einrichtungstest bestätigt

Der lokale Rückweg wurde um **2026-11-04 20:04:30.962155 UTC** bestätigt.
Der Prüfbeleg trägt ausdrücklich `simulated:true`, `local_test_verified:true`,
`verified:false` und `cloud_attested:false`. Die GUI zeigte weiter an, dass die
ChatGPT-Verbindung noch offen ist. Der Einrichtungstest sendete keine Tasten,
bewegte keine Fenster, startete keinen Tunnel und kontaktierte kein Nutzerkonto.

Die offizielle Verbindungshilfe **v0.0.19** wurde aus dem geprüften Paket-ZIP
installiert. Der Versionscheck verlangt die tatsächliche vollständige Ausgabe
mit Git-SHA `01d67bb4da0d8359b808b4761f8db171ab682cd7`; eine passende nackte
Versionsnummer genügt nicht. CLI-Hilfe und Profilparser bestanden. Im lokalen
`doctor` bestanden Konfiguration, Profil, Schlüssel-Format, Ziel, Erreichbarkeit,
Health und UI. **Der vollständige Doctor bestand nicht:** `oauth_metadata:FAIL`,
Exitcode 2; der hier nicht verwendete Codex-Plugin-Check war `SKIP`. Dieser
begrenzte lokale Test weist keine OAuth-, Konto- oder Cloud-Verbindung nach.

Vor dem Stoppen des eigenen Testservers wurden null Tasks bestätigt. Sein
behaltener Prozess-Handle wurde für den begrenzten Stop-Fallback verwendet;
die ursprüngliche Prozessgeneration und der Listener waren danach unabhängig
abwesend. Die eigene Tk-Oberfläche wurde ebenfalls geschlossen. Testzustand und
Originalberichte bleiben für die spätere Prüfung erhalten.

Der zusätzliche Vorher-/Nachher-Bericht bestätigt unveränderte Modulbytes,
Zugangsdaten, Starter, Prozessgenerationen und Listener der vorhandenen
dev2-/dev3-/RC33-Installationen auf **8765, 8766 und 8767**. Der Assistent nutzt
später einen eigenen Zustand und standardmäßig **8768**; die Abnahme verwendete
einen eigenen freien Port. Sie ersetzt keinen Installationsnachweis.

## Frühere Versuche und Korrekturen

V1 und V4 wurden vor dem absendenden Return abgebrochen. Es wurde kein nativer
Testauftrag daraus ausgeführt oder wiederholt. V2 bestand sechs Fensteraktionen;
ein Lese-Rennen im Harness verhinderte den anschließenden Schließtest.
Es gab keinen Hauptfenster-Schließtask; die eigenen Fenster wurden dennoch
als abwesend bestätigt. Die Harness-Korrektur bleibt von Produktfehlern getrennt.

V3 zeigte die echte GUI und startete den lokalen Server, endete aber mit
`RuntimeError` vor den Clientprüfungen. Weil noch Phase und UI-Status fehlten,
lässt sich die ursprüngliche Ursache nur auf diesen Abschnitt eingrenzen;
ein Client-Downloadfehler ist daraus nicht bewiesen. Die unabhängige
Abwesenheitsprüfung meldete zusätzlich `BridgeError` nach dem eigenen Stop.

Danach kamen dauerhaft gespeicherte Phasen und bereinigte UI-Fehlermeldungen,
der ausschließlich private Paket-Client-Cache, die korrekte Erkennung beendeter
Prozesse sowie der exakte Versionsvergleich nach dem offiziellen Go-Quellcode
hinzu. Der frische V5-Lauf bestand mit diesen Korrekturen. Frühere Fehlerberichte
bleiben unverändert; sie werden nicht nachträglich zu Erfolgen erklärt.

Vor dieser Abnahme bestanden außerdem **370 gezielte lokale Prüfungen** sowie
die vorgesehenen Ruff-, Format-, Lock- und Diffprüfungen. Lokale Hosttests ersetzen
keine native Abnahme; die sieben Gastphasen sind getrennte Nachweise.

## Grenzen und Auslieferung

Die Messungen und Rückwege dieses Laufs sind **lokal in der VM**. Sie belegen
keine ChatGPT-/Voice-Latenz und keinen Ende-zu-Ende-Aufruf über die Cloud. Ein
echter ChatGPT-Prüfauftrag mit eigenem Konto bleibt offen. Auch dessen späterer
Antwortcode ist eine Bestätigung des vom Nutzer durchlaufenen Rückwegs, keine
kryptographische Cloud-Herkunftsbestätigung.

Veröffentlichung, frischer Paketdownload und neue sichtbare Installation stehen
für diesen Bericht noch aus. Der Kandidat umfasst 179 Python-Module; das
geprüfte Wheel hat SHA256
`faa2d7cbad3f99881080b4291e94f2d77008e6d36642fbdcb56dd17b7dc11366`.
Nur der abschließend dokumentierte veröffentlichte Download kann die
Verfügbarkeit belegen. Ein Windows-Dienst, automatische Anmeldung oder Änderungen
an Systemrechten sind nicht Teil des Assistenten. Allgemeine Windows-Datei-,
Prozess- und Terminalwerkzeuge bleiben außerhalb dieser Vorschau.
