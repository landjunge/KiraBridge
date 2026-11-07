# RC28: identische Einzeltasten und weitere Leseoperationen

Diese Messung ergänzt die RC27-Berichte. Alle Tastaturarme erzeugen exakt
**acht echte native Key-down/Key-up-Paare für „Stern am“**. Weder Unicode-
Blocktexteinfügung noch Clipboardzugriff ersetzt die Tastendrücke.
Gemessen sind private lokale MCP-HTTP-Server, der Stdio-Proxy-Klassenpfad und
der native macOS-Empfänger. Sprache, Modell und ChatGPT-Cloud gehören nicht
zu diesen Zeiten; dafür enthält der Hauptbericht separate Frontdoor-Messungen.

## Acht gleiche native Tastendrücke

Unverändertes kompiliertes RC27-KiraBridge-Binary und identische UUID-Kopien der
vorhandenen KeyboardFixture. RC27 wurde über sein installiertes Pythonpaket,
der Kandidat über den neuen Quellbaum geladen; damit keine vermischten Module.
Der Empfänger wurde außerhalb jeder Zeitmessung über seinen eigenen begrenzten
Testkanal geleert. Kandidatenarme wechselten die Reihenfolge pro Runde.

| Arm | Runden | MCP-Aufrufe | Native Paare | Gesamtzeit aller Runden | P50 Runde | P95 Runde |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| RC27, 8 einzelne `keyboard_control`-Calls | 5 | 40 | 40 | 7383,12 ms | 1459,77 ms | 1562,06 ms |
| Kandidat, dieselben 8 einzelnen Calls | 5 | 40 | 40 | 7081,90 ms | 1391,00 ms | 1520,09 ms |
| Kandidat, 1 `keyboard_sequence` mit denselben 8 Schritten | 5 | 5 | 40 | 5547,49 ms | 1090,48 ms | 1188,90 ms |

Für einzelne RPCs: RC27 P50/P95 164,71/237,56 ms (n=40), Kandidat
164,12/177,80 ms (n=40). Die fünf Sequenz-RPCs: 1036,11/1135,21 ms.
Rundenzeiten enthalten jeweils unabhängiges Empfänger-Rücklesen.
P95 verwendet den nächsten Rang `ceil(0,95*n)`; bei fünf Runden ist dies der
beobachtete Maximalwert und keine belastbare Populationsgrenze.

Nach jeder Runde stimmten Hash, acht UTF-8-/UTF-16-Einheiten, Cursorposition 8,
acht Down- und acht Up-Ereignisse. Kein Return, keine verworfenen Eventrecords,
Clipboardgeneration unverändert. Die Wiederholung einer bereits abgeschlossenen
Sequenz mit identischen Task-/Idempotenzschlüsseln erzeugte **keine neuen Events**.
Ungewisse Mutationen werden niemals erneut abgesendet; der Harness stoppt dann.

Das ist ein begrenzter lokaler Gewinn. Er erklärt und beseitigt die vom Nutzer
gemessenen 42,504 Sekunden für acht separate Voice-Aufrufe nicht allein.
Eine bekannte Folge mit acht physischen Tastendrücken benötigt mit der neuen API
nur eine Plattformübergabe. Interaktive Entscheidungen zwischen einzelnen Tasten
bleiben getrennte Aufrufe und behalten deren externe Latenz.

[Native Rohstatistik und Empfängerbelege](evidence/rc28-native-key-comparison-20261103.json).
Die vollständigen privaten Laufbelege liegen im projektüblichen Backupverzeichnis.
Der Baseline-Keyteil bestand vollständig; erst der nachgelagerte optionale
Lesevergleich traf einen fehlenden `policy.inspect`-Grant im privaten Testprincipal.
Der gesamte erste Harnesslauf wird deshalb nicht als bestanden ausgegeben.
Seine bereits erfolgreichen 40 Tastendrücke wurden für eine schönere Gesamt-
Erfolgsmeldung nicht erneut gesendet. Der Kandidatenlauf einschließlich Cleanup
bestand vollständig. Eigener Empfänger, Worker und HTTP-Endpoint sind jeweils
unabhängig als beendet beziehungsweise abwesend geprüft.

## Vier weitere Werkzeuge und drei identische Leseabfragen

Je zehn Beobachtungen, gleiche begrenzte Rechte und eigene unveränderte Testdatei,
kein produktiver Dienst und kein nativer Worker. Domänenreihenfolge rotiert.

| Werkzeug | RC27 P50/P95 ms | Kandidat P50/P95 ms |
| --- | ---: | ---: |
| Health | 12,48 / 13,57 | 12,93 / 14,48 |
| Clipboard-Fähigkeitsinfo, kein Inhalt | 6,25 / 6,75 | 6,52 / 7,47 |
| Eigene Policy | 25,80 / 27,08 | 24,02 / 25,15 |
| Operationskatalog | 26,49 / 27,88 | 26,48 / 27,60 |

Hier ist kein großer lokaler Latenzgewinn nachgewiesen. Die SDK-JSON-Größe sank
bei Health 37540→32889 und beim Katalog 51477→43598 Bytes. Bei der kleinen
Clipboard-Info stieg sie durch die neue Timing-Metadatenbeobachtung 482→804 Bytes.
Dies sind serialisierte SDK-Ergebnisse, keine vollständige HTTP-Wire-Aufzeichnung.

Für dieselben drei Abfragen `file.read`, `file.list`, `platform.status` am
Kandidaten wechselten je zehn Runden drei Einzel-RPCs und ein `read_queries`-RPC:
P50/P95 **67,46/128,42 ms → 55,99/57,63 ms**, Gesamtzeit **733,90 → 558,31 ms**.
Anzahl: jeweils 30 fachliche Reads, aber 30→10 MCP-Aufrufe. Dateiinhalt und
Datei-/Verzeichnisidentitäten wurden exakt verglichen. Bei der Plattformabfrage
wurde ausschließlich das erwartungsgemäß bei jedem OS-Probe neue `observed_at`
normalisiert; Rechte, Zustände und Revisionen blieben Teil des Vergleichs.

[Zusammenfassung](evidence/rc28-read-comparison-20261103.json),
[RC27-Beobachtungen](evidence/rc28-baseline-read-tools-20261103.json),
[vollständiger finaler Kandidatenlauf](evidence/rc28-candidate-read-tools-final-20261103.json).
Frühe Harnessfehler (fehlender Testgrant, Vergleich dynamischer Beobachtungszeiten,
CLI-Ausgabefehler nach erfolgreicher Gruppenmessung) sind als solche erhalten.
Sie sind keine Produktfehler und werden nicht zu bestandenen Gesamtchecks umetikettiert.

Reproduktion: `scripts/accept_native_keyboard_macos.py --scenario sequence-latency`
mit `--sequence-mode single|both`, mindestens fünf Runden und explizitem `--execute`;
exakte native Pins und frisches privates Evidenzverzeichnis sind erforderlich.
Lesevergleich: `scripts/benchmark_backend_reads.py` mit mindestens zehn Wiederholungen,
frischem State-Verzeichnis und dem gewünschten Pythonpaket in `PYTHONPATH`.
Fünf gezielte Harnessprüfungen bestanden: P95-/Eventzählung, abgeschlossene
Idempotenz, Stop bei ungewissem Ergebnis und zehn nur lesende Samples pro Domäne.
