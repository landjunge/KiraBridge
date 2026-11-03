# RC32 – weniger native Attributabfragen innerhalb eines UI-Baums

RC32 baut auf RC31 auf und bündelt die macOS-Attributabfragen innerhalb der
optional aktivierten Accessibility-Baumansicht. Zwei Attributgruppen und eine
Aktionsabfrage ersetzen 13 einzelne Attributabfragen plus Aktionsabfrage je
regulärer Knotenbeobachtung. Mit beiden Stabilitätsbeobachtungen und Kinderprüfungen
sinkt die Zahl der öffentlichen AX-API-Aufrufe pro regulärem Baumknoten von 30 auf 8.

Sichere Felder werden zuerst anhand ihrer Rolle/Subrolle erkannt; ihr Wert wird
auch im gebündelten Pfad nicht angefragt. Ausgabe und Einzelknotenrevision bleiben
gleich. Wenn die Anwendung den gesamten Mehrfachattributaufruf ausdrücklich nicht
implementiert, startet eine vollständige frische Einzelbeobachtung im selben
Zeitbudget. Andere Fehler werden nicht als leere Felder ausgegeben. Die bisherige
einzelne Standardinspektion bleibt unverändert.

Die drei frischen nativen Datei-/SHA-Integritätsprüfungen bleiben erhalten. Ihr
gemessener Aufwand rechtfertigt keinen Cache über Rechte-/Transportsperrgrenzen.
Die Verringerung der API-Aufrufzahl ist keine Aussage über dieselbe prozentuale
Beschleunigung von macOS, Cloud oder Voice. Im echten kontrollierten AppKit-Test
mit zwölf eigenen Buttons sank die native Medianzeit bei identischen Ergebnissen
von 16,856 auf 8,138 ms (rund 51,7 % weniger Zeit, 20 abwechselnde Runden).
74 gezielte Tests bestanden. Paketabnahme und genaue Grenzen werden im RC32-Bericht
gesondert ausgewiesen.

RC32 enthält auch die RC31-Optimierungen. Die produktive RC30 läuft während der
parallelen Windows-/VM-Arbeit weiter; dieses Paket wird dabei nicht automatisch
installiert. Alle Tests und Builds erfolgen lokal für Intel-macOS.

[Messungen und Auslieferungsstand](https://github.com/landjunge/KiraBridge/blob/perf/rc32-native-ipc-20261103/docs/RC32-NATIVE-ATTRIBUTE-BATCHING-20261103.md).
