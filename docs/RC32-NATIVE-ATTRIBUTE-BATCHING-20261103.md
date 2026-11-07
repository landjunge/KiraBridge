# RC32: gebündelte native Accessibility-Attribute

Ausgangspunkt ist der geprüfte RC31-Abschluss `0f554bc`. Der neue Branch
`perf/rc32-native-ipc-20261103` arbeitet in einem eigenen Worktree. Die vorhandenen
RC31-Änderungen bleiben enthalten. Drei native Team-Agenten untersuchten getrennt
die Attributabfragen, tatsächliche Datei-/Hashkosten und den Apple-API-Vertrag;
Root integriert, misst und bereitet das lokale Intel-Paket vor.

Die produktive RC30 und der parallele Windows-/VM-Auftrag bleiben erhalten.
Es werden keine fremden Anwendungen bedient, keine Dienste oder Agenten neu
gestartet und keine neuen OS-Rechte angefordert. Der bestehende Windows-Eintrag
`10ef546d2b06` und das gemeinsame ThreadDesk-Whiteboard wurden gelesen. Neue
Arbeit ist dort unter `ea8a825b8ec9` nach beobachteter Revision 498 angehängt und
anschließend vollständig unabhängig zurückgelesen worden.

## Ein kleinerer nativer Leseschritt

RC31 vermeidet viele Cloud-/Modellübergaben mit seiner optionalen Baumansicht.
Innerhalb jeder Knotenbeobachtung wurden dennoch 13 Attribute einzeln abgefragt,
dazu die Aktionsnamen. Bei sicheren Feldern entfällt die Wertabfrage. Ein regulärer
Baumknoten benötigt zwei solche Beobachtungen und zwei Kinderabfragen zur
Stabilitätsprüfung: **30 öffentliche AX-Copy-/Action-Aufrufe**, sicher **28**.

RC32 verwendet im optionalen Baummodus `AXUIElementCopyMultipleAttributeValues`:
zuerst Rolle/Subrolle, dann die restlichen Attribute. Ein sicher klassifiziertes
Feld wird ohne `AXValue` angefragt. Die Aktionsnamen bleiben ein eigener Aufruf.
Das ergibt drei statt 14 Aufrufe je normaler Beobachtung und **acht statt 30 je
vollständigem regulärem Baumknoten**; bei sicheren Knoten acht statt 28.

Der kanonische Formatter für Ausgabe und Revision bleibt identisch. Die bisherige
einzelne Standardinspektion wird nicht verändert. Die beiden Beobachtungen,
Kindidentitäts-/Eigentümerprüfungen, Tokens, laufenden PID-/Startidentitäten und
Zeit-/Größenlimits bleiben erhalten. Es gibt keinen Wert- oder Ergebniscache.

Der lokale Apple-SDK-Header `AXUIElement.h` dokumentiert positionsgebundene
Batchergebnisse. `CFNull` und eingebettete `AXValue(.axError)` werden explizit
behandelt. Nur unterstützte Abwesenheit (`attributeUnsupported`/`noValue`) wird
weggelassen. Ungültige Typen, Länge, Transportfehler oder ein als Fehler
verpacktes `success` werden abgewiesen. Der öffentliche API-Aufruf ist nicht als
atomarer Snapshot oder als genau ein physischer IPC dokumentiert.

Wenn die gesamte Mehrfachattribut-API ausdrücklich `notImplemented` zurückgibt,
beginnt eine vollständige frische Einzelbeobachtung im selben Deadlinebudget.
Bereits gelesene Felder werden dabei nicht wiederverwendet. Ein inzwischen sicher
gewordenes Feld wird erneut klassifiziert. Einzelne Fehler-Slots und Zeitfehler
starten diesen Kompatibilitätsweg nicht.

## Gemessene Aufrufzahlen und Tests

Der synthetische Harness ruft denselben produktiven Planer und Decoder mit
kontrollierten CF-Werten auf. Er zählt die tatsächlich durchlaufenen
API-Grenzen; künstliche Wartezeiten werden nicht verwendet. Normaler Payload,
Revision und Geometrie sind bytegleich zum ursprünglichen Einzelpfad.

| Kontrollierte Beobachtung | Einzelpfad | RC32-Batchpfad |
| --- | ---: | ---: |
| Normaler Knoten: Attribute + Aktionen | 13 + 1 | 2 + 1 |
| Sicheres Feld: Attribute + Aktionen | 12 + 1 | 2 + 1 |
| Daraus abgeleitet: zwei Beobachtungen + Kinder, normal | 30 | 8 |
| Daraus abgeleitet: zwei Beobachtungen + Kinder, sicher | 28 | 8 |

Der [synthetische Beleg](evidence/rc32-accessibility-batches-20261103.json) trennt
gemessene Callbackzahlen und abgeleitete Zahlen je Baumknoten. Er enthält zwölf
einmal erfasste Szenarien mit Quellen-/Binaryhashes. Diese Zahlen beweisen keine
entsprechende prozentuale Cloud- oder gesamte macOS-Beschleunigung.

Die finale gezielte Integrationsrunde bestand mit **74 Tests in 72,96 s**:
26 neue Batchfälle, 39 bestehende Baumfälle und neun Fälle der unveränderten
Standardinspektion. Enthalten sind Positionsdekodierung, echte Geometrie-CF-Werte,
sichere Felder, frische Kompatibilitätsbeobachtung nach Klassifikationswechsel,
Fehler-/Deadlinefälle sowie unveränderte normale Ausgaben und Revisionen.
Frühere Teilrunden werden nicht zusätzlich summiert. Unabhängiger Produktreview
ohne offene Blocker; Ruff, Format, Diff und Lock geprüft.

## Der untersuchte Integritätspfad bleibt erhalten

Ein weiterer Agent maß den originalen Python-/Transportpfad mit echten privaten
Info.plist-/Binärdateien und einem Protokollfixture im Speicher. Native Prozesse,
produktive Dateien, UI oder Credentials wurden dafür nicht verwendet. Ein
`native.read` führt drei frische Metadaten-/SHA-Beobachtungen und sechs private
Dateilesungen aus. Das sind die Beobachtungen vor/nach Revalidierung und unter
der Transportsperre.

| Kontrollierte Binärgröße | Gesamter Read, P50 | Metadaten, P50 |
| --- | ---: | ---: |
| 32 KiB | 2,44 ms | 1,18 ms |
| 1 MiB | 13,92 ms | 12,29 ms |
| 4 MiB | 50,42 ms | 48,69 ms |

Je 30 Samples, alle erhalten, gleiche Ausgaben und unveränderte Quellen. Diese
Dateigrößen sind Fixtures und keine Behauptung über das installierte Binary.
Die hohen Tailwerte bei 4 MiB enthalten konkurrierende Prozessplanung und werden
nicht vollständig dem Hashen zugeschrieben. Vermeidbare Providerkopien versprechen
hier nur einen kleinen Zusatzgewinn. Die drei frischen Integritätsprüfungen
werden beibehalten; kein Cache über eine Rechte-/Lockgrenze.
[Profilbeleg](evidence/rc32-native-metadata-profile-20261103.json),
[Reproskript](../scripts/benchmark_native_metadata.py).

## Zusätzlicher echter AX-Vergleich

Für einen optionalen Zeitvergleich gibt es einen eigenen Fixture-Helper. Er
prüft vorhandene Accessibility-Rechte ohne Prompt, verwendet ausschließlich zwölf
eigene statische Buttons in einer eigenen Hintergrundanwendung und verlangt
identische Daten/Revisionen. Vorgesehen sind abwechselnde Reihenfolge,
vollständige Rohsamples, kein verworfener Warm-up und eine unabhängige
Abwesenheitsprüfung des eigenen Prozesses. Andere Anwendungen werden nicht gelesen.

Der erste Aufbauversuch startete das Fixture-Binary direkt. `launchDate` ist laut
lokalem `NSRunningApplication.h` bei Starts ohne LaunchServices nicht garantiert;
der Nil-Guard beendet den Provider vor seiner Readydatei. Diese Ursache ist eine
durch Quelle/SDK gestützte Schlussfolgerung; Exitcode und Stderr des ersten
Providers wurden nicht aufgezeichnet. Es wurden keine Zeitmesswerte gewonnen.
Die damalige Meldung `window_created=false` ist als unbekannt korrigiert: Die
Fensteranlage lag vor dem Readycheck. Der eigene Prozess wurde nachweislich
abgewartet; eine unabhängige Startidentitätsprüfung ist für diesen ersten Versuch
nicht belegt. [Erster Aufbauversuch](evidence/rc32-owned-ax-timing-20261103.json).

Der folgende Versuch stoppte vor dem App-Start an einer fehlenden Python-
`os.listxattr`-Funktion. Eigenes Inventar und unabhängiger Readback waren leer;
es gab keine native Messung. Die Vorprüfung nutzt jetzt das vorhandene
macOS-`xattr`. [Vorprüfungsbeleg](evidence/rc32-owned-ax-launchservices-20261103.json).

Der korrigierte Launcher verwendet `NSWorkspace.OpenConfiguration` mit
`activates=false`, ohne Recent-Items-/fremde App-Substitution und ohne eigene
Promptanforderung. Er bindet die von LaunchServices zurückgegebene PID/Startzeit
an den einzigartigen privaten Bundlepfad. Ein ungewisser Start wird nicht
wiederholt oder durch ein sofort leeres Inventar als abgeschlossen ausgegeben;
seine Fixture bleibt für die Klärung erhalten.

Der korrigierte echte Vergleich bestand. Ein privates AppKit-Fenster mit zwölf
statischen eigenen Buttons wurde ohne Aktivierungsanforderung gestartet. Ein
getrennter Reader verglich die ursprüngliche strikte Einzelbeobachtung und den
neuen Batchpfad an genau denselben zwölf Elementen in derselben Anwendung.
Beide Attributgruppen wurden für alle Zielknoten vor der Zeitserie auf
Unterstützung geprüft. Das ist ein Setup-/Warm-cache-Schritt vor beiden Pfaden;
alle anschließend gemessenen Samples bleiben erhalten.

| Echter eigener AX-Workload, zwölf Knoten je Runde | RC31-Einzelpfad | RC32-Batchpfad |
| --- | ---: | ---: |
| Wallzeit P50 | 16,856 ms | 8,138 ms |
| Wallzeit P95 (Nearest Rank) | 18,448 ms | 8,627 ms |

20 Runden mit abwechselnder Reihenfolge, gleicher optimierter Helper-Binary,
identischer Provider-PID/Startzeit und unveränderten Quellen. Alle 20 vollständigen
JSON-Ergebnisse einschließlich Revisionen waren in beiden Pfaden exakt gleich.
Die native Wall-Medianzeit ist damit etwa **51,7 % kürzer**. Die Zahl beschreibt
zwölf eigene AppKit-Buttonbeobachtungen und keine vollständige Baum-/Cloud-/
Voiceaufgabe. Die vor/nach jeder echten Baumknotenbeobachtung bestehenden
Kinder-/Zielprüfungen wurden in diesem Zeitvergleich nicht zusätzlich ausgeführt;
sie sind in der abgeleiteten 30→8-Zählung separat berücksichtigt.

Der Provider blieb während der Messung inaktiv, der beobachtete Vordergrund war
vor Start, bei Readiness und nach Messung jeweils Terminal-PID 852. Nach einem
PID-/Start-/Bundlepfadgebundenen SIGTERM bestätigte ein unabhängiger Inventarread
die Abwesenheit des eigenen Providers. Das eine eigene Testfenster ist geschlossen.
Keine neue AX-Freigabe, kein Tastatur-/Clipboardaufruf und keine fremde
Fensterbedienung. Ein während der Zeitserie verwendeter skalarer Fallback ist
nicht gesondert instrumentiert; die Batchunterstützung ist durch die vorherigen
erfolgreichen Prüfungen aller Zielknoten belegt.
[Echte Rohsamples und Erhaltung](evidence/rc32-owned-ax-launchservices-fixed-20261103.json),
[Reproskript](../scripts/benchmark_accessibility_native.py).

## Abnahme und Auslieferung

Die Produktänderung ist ausschließlich die gebündelte optionale Baumbeobachtung
in `SystemControl.swift`; der Versionsstand ist 0.8.0rc32. Alle übrigen
RC31-Python-/Guardpfade bleiben unverändert. Die 74 gezielten Tests sowie
unabhängige Produkt- und Messreviews sind die Entwicklungsabnahme.
[Validierung](evidence/rc32-validation-20261103.json),
[unabhängiger Review](evidence/rc32-independent-review-20261103.json).

Der lokale Intel-Build auf **`300df69ec55d236ef1059d1b146a0ff89c2f003c`** bestand.
Der isolierte Installer-/Starttest bestätigt authentifizierten Dispatcher,
konkrete Lesevoraussetzungen, Ablehnung eines beschädigten Pakets und unveränderte
eigene Testkonfiguration/Credentials. Der unabhängige Paketreview bestätigt
578 sichere Tar-Member, 166 Pythondateien bytegleich zwischen Git/Tar/Wheel,
native x86_64-Architektur, gültige Signaturen und Versions-/Sourcepin,
579 Installer-Manifestdateien sowie alle 583 ZIP-Dateien einschließlich Modi.
[Paketreview](evidence/rc32-package-review-20261103.json).

[Prerelease v0.8.0rc32](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc32)
ist veröffentlicht. Alle sieben hochgeladenen Assets wurden unabhängig in Größe
und GitHub-SHA256 gegen die lokalen Dateien geprüft. Nach Veröffentlichung wurde
der Intel-Installer erneut heruntergeladen: **3.459.081 Bytes**, SHA-256
`9dc2d582f3a8075a06d8a84ae36e6fbf1da2075a0fa308a7ebb84e04acbf72c3`.
Der Release-Tag zeigt exakt auf `300df69`; keine GitHub Actions.
[Auslieferungsbeleg](evidence/rc32-release-20261103.json).

[Draft-PR #57](https://github.com/landjunge/KiraBridge/pull/57) ist auf RC31/PR56
gestapelt. `main` bleibt `21a6abd`, RC31-Abschluss bleibt `0f554bc`.
Spätere Abschlussdokumentation ändert den geprüften Paketpin nicht.
Die produktive RC30 läuft weiterhin mit **PID 66439**, Start **03:30:12 UTC**,
Instanz `777222cce58e4b38b503c2f3d20900e1`, Dispatcher aktiv. Es gab keinen
Produktiv-/Tunnel-/Agentneustart während der parallelen Windows-/VM-Arbeit.

Der Abschluss wurde im vorhandenen ThreadDesk-Whiteboard `188ce4729a62` nach
beobachteter Revision 500 angehängt, stabile Operation
`rc32-native-batching-released-300df69-20261103`. Eintrag `21e2d94c3b2a`, Ordinal 140,
wurde danach unabhängig vollständig und zeichengenau zurückgelesen. Bestehende
Beiträge bleiben erhalten.
