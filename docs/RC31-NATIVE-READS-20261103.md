# RC31: weniger UI-Leseaufrufe und schnellere Task-Ereignisse

Ausgangspunkt ist der geprüfte RC30 auf `main` `21a6abd`. Die bisherigen
RC27–RC30-Optimierungen bleiben erhalten. Dieser Auftrag arbeitet ausschließlich
auf `perf/rc31-latency-20261103` im eigenen Worktree. Drei native Team-Agenten
übernahmen Accessibility, Backendmessung und unabhängigen Review; Root integriert
die direkte Leseroute, prüft die Ergebnisse und baut das Intel-Paket.

Die andere Codex-Instanz arbeitet separat am Windows-/VM-Zweig. Dessen Dateien,
Branches, VM und laufende Sitzungen wurden nicht verändert. Die produktive
RC30-Installation bleibt während dieser parallelen Arbeit erhalten; ein
Installationsneustart würde bestehende native Worker-/Elementhandles ungültig
machen. RC31 wird als getrenntes geprüftes Paket bereitgestellt.

## Was bereits optimiert war

RC27 reduzierte wiederholte Discovery-/Schemaarbeit, RC28 führte echte
Tastensequenzen und Read-Batches ein. RC29 bündelte gemischte Reads und lieferte
kurze Taskabschlüsse direkt zurück. RC30 vermied wiederholtes Laden großer
Ausgaben, erneute Metaschemaprüfung und doppelte JSON-Darstellungen im optionalen
kompakten Batchformat. Siehe die jeweiligen datierten Berichte.

Die RC30-Apps-Messung zeigt weiterhin Sekunden je äußerem Aufruf. Lokale
Millisekunden allein lösen diesen Engpass nicht. RC31 verkürzt deshalb auch
ganze Leseabläufe, statt lediglich dieselben Aufrufe schneller abzuarbeiten.

## Direkte native JSON-Reads

Der vorhandene, auch für gecachte Clients verfügbare `read_query` akzeptiert:

```json
{
  "query": {
    "operation": "native.read",
    "native_operation": "accessibility.inspect",
    "arguments": {
      "pid": 123,
      "expected_started_at": 123.0,
      "max_depth": 20,
      "max_nodes": 256,
      "tree_budget_ms": 1500
    },
    "max_bytes": 262144
  }
}
```

PID/Startwert sind durch eine frische `apps.list`-Beobachtung zu ersetzen.
Die eigentliche native Antwort steht unter `result`.

Die feste Whitelist umfasst `apps.list`, `apps.inspect`, `windows.list`,
`windows.inspect`, `accessibility.status` und `accessibility.inspect`. Jeder
Read nutzt die vorhandenen typisierten Schemas, Plattform-/Zielprüfungen und
denselben nativen Transport. Rechte müssen die Operation aktuell automatisch
erlauben. Sonst wird vor Ausführung `approval_required` zurückgegeben; der
bestehende `task_request`-Weg bleibt für freizugebende Reads verfügbar.

Auch nach Transport-Lock/Prozessstart wird unmittelbar vor dem Senden erneut auf
Rechteentzug oder Wechsel zu manueller Freigabe geprüft. Zwei konfigurierbare
Leseplätze und ein äußeres 12-Sekunden-Budget begrenzen auch das Warten auf den
Transport. Ein Abbruch wiederholt keine Operation. Wird ein laufender nativer
Read abgebrochen, kann der vorhandene Transport seinen Worker verwerfen;
anschließend müssen Elementhandles frisch gelesen werden.

Es entstehen keine Tasks, Events, Completionrouten oder Notices. Der direkte
Pfad liefert JSON; Eingaben, Capture/Bilder und Rechteanfragen gehören nicht zu
dieser Whitelist. `read.batch` und `tool.batch` funktionieren über denselben
Alias; alle inneren Argumente werden vor dem ersten Read geprüft. Native
Einzelantworten sind auf 512 KiB begrenzt, der Default bleibt 32 KiB. Dateien und
andere bisherige Reads behalten ihr 64-KiB-Limit. `read.batch` erlaubt weiter
höchstens 256 KiB an kombinierten angeforderten Budgets. Ein zu großer vollständiger
nativer Rückgabekörper führt ausdrücklich zu `native_read_result_limit`.

## Begrenzter Accessibility-Baum

Bei `accessibility.inspect` aktiviert `max_depth>0` eine neue Baumansicht.
`max_depth=0` behält den bisherigen einzelnen Inspektions-/Paginierungsvertrag.
Baummodus liefert eine flache Knotenliste mit `element_token`, `parent_token`,
Tiefe, normaler Einzelknotenrevision und Angaben zu fehlenden Kindern. Root,
Appidentität, Worker-PID und Generation bleiben verfügbar. Es gibt in diesem
Modus keine zusätzliche Legacy-Kinder-/Wertpagination. Rootrevision und
Einzelknotenrevision sind ausdrücklich keine atomare Baumrevision.

Grenzen: Tiefe 32, 512 Knoten, 512 KiB Baumdaten, 5 Sekunden kooperatives
Baumbudget; Default Tiefe 0, 256 Knoten, 256 KiB und 1,5 Sekunden. Die direkte
Leseroute reduziert das angeforderte Baumbudget zusätzlich um eine Reserve für
den äußeren Antwortkörper und prüft dessen tatsächliche Gesamtgröße. Zyklen und
geteilte Knoten werden dedupliziert. Kindreferenzen und native Arrays sind
begrenzt. Nicht beobachtbare/malformed native Daten werden nicht als leerer,
vollständiger Baum ausgegeben.

Jeder Knoten wird lokal vor/nach dem Lesen auf Metadaten-/Kinderänderungen
geprüft. Es bleibt ein **nicht atomarer** Blick auf eine veränderliche Oberfläche.
Eine begrenzte Antwort nennt fehlende Fronten und Gründe. Dafür können die
zurückgegebenen Knoten als Wurzeln weiterer Reads dienen. Principal, PID,
Startzeit und native Workeridentität bleiben gebunden; spätere Mutationen prüfen
die normale aktuelle Einzelknotenrevision. Sichere Eingabefelder liefern weder
Wert noch daraus abgeleiteten Hash. Ein noch laufender AX-Aufruf kann das
kooperative Deadlineende um seine auf höchstens 100 ms gesetzte IPC-Frist
überschreiten; lokale Serialisierung ist ebenfalls Teil der Restarbeit.

## Vergleichsmessungen

| Gleicher kontrollierter Workload | RC30 | RC31 |
| --- | ---: | ---: |
| Nativer JSON-Read über echten lokalen HTTP-/MCP-SDK-Pfad, P50/P95 | 14,23 / 34,00 ms | 7,58 / 10,07 ms |
| Persistente Tasks / Events / Notices bei 30 solchen Reads | 30 / 150 / 30 | 0 / 0 / 0 |
| Vollständiger synthetischer Baum mit 121 Knoten | 40 Einzelinspektionen innerer Knoten | 1 Baumoperation |
| Ereignisse eines Tasks mit 4-MiB-Ausgabe bei 100.005 Events, P50/P95 | 36,40 / 45,83 ms | 0,049 / 0,110 ms |
| Derselbe Ereignispfad bei 40.005 Events, P50/P95 | 30,75 / 75,19 ms | 0,047 / 0,058 ms |

Beim nativen HTTP-Vergleich: je 30 Samples, gleiche Grants, identische normalisierte
native Argumente und exakt gleiches JSON-Ergebnis; jeweils **ein** HTTP-Aufruf
pro Read auf beiden Seiten. Echter MCP-SDK 1.30, synthetischer nativer Rückgabepfad,
kein OS-Worker. Wall-/CPU-Einzelwerte, Quellenhashes und Resultathashes sind
gespeichert. Alle Samples bleiben enthalten. Es gab keine Completionpolls oder
ACKs in den Messungen. Die 46,75 % kürzere Medianzeit betrifft diese lokale
Strecke, nicht die Cloud. [Reproskript](../scripts/benchmark_native_reads.py),
[Vorher](evidence/rc31-native-reads-before-20261103.json),
[Nachher](evidence/rc31-native-reads-after-20261103.json).

Der Baumvergleich nutzt dieselbe produktive Swift-Traversierung mit synthetischen
Knoten: vollständiger 121-Knoten-Baum (67.574 Baumbytes bei 256-KiB-Budget),
sichtbarer Zieltext, identische normale
Knotenrevisionen, keine nativen UI-/Permission-/Inputaufrufe. 40→1 belegt weniger
logische Beobachtungsoperationen; es ist keine Browser-/Apps-/Voice-Zeitmessung.
[Baum-/Grenzfallbeleg](evidence/rc31-accessibility-tree-20261103.json).

Ereignismessung: je 30 Samples mit eigenen temporären Daten. Die Zielereignisse
liegen vor 40.000 beziehungsweise 100.000 späteren fremden Events; keine
behauptete allgemeine Verteilung. RC31 prüft Taskleserecht/Eigentümer frisch,
ohne für einen reinen Ereignisabruf große Taskausgabe oder Fehlerdiagnostik zu
laden. Ein additiver `(task_id,seq)`-Index verhindert das Durchlaufen fremder
Historie. Einmaliger Indexaufbau separat: etwa 19 ms bei 40k und 64 ms bei 100k.
Zeilen, Schema-Version und bestehende Lesesemantik bleiben erhalten; fehlschlagender
Aufbau rollt zurück. Ergebnis-JSON identisch, Ausgabeauflösungen 1→0.
[Reproskript](../scripts/benchmark_task_event_hotpaths.py),
[100k vorher](evidence/rc31-task-events-before-20261103.json),
[100k nachher](evidence/rc31-task-events-after-20261103.json),
[40k vorher](evidence/rc31-task-events-40k-before-20261103.json),
[40k nachher](evidence/rc31-task-events-40k-after-20261103.json).

Diese verschiedenen lokalen Versuche sind nicht addierbar. Es gibt für RC31
keine neue produktive Apps-/Cloud-/Voice-Messung. Tatsächliche Oberflächen können
sich während des Lesens ändern oder innerhalb des Baumbudgets nur teilweise
beobachten lassen. Die vorherigen externen Latenzgrenzen bleiben ausdrücklich offen.

## Prüfung und Auslieferung

Die abschließende relevante Integrationsrunde bestand mit **380 Tests in 57,20 s**:
native Decoder/Swift-Traversierung, Altinspektion, direkte Reads, echter HTTP-SDK,
Batchvalidierung, späte Rechteänderungen an tatsächlichen Transport-Awaits,
Timeout/Cancel, Task-/Event-/Dateipfade und zentrale Rechte. Frühere Teilrunden
werden nicht zusätzlich summiert. Ein zunächst falsch angegebener Testdateiname
führte zu keinem Testlauf und wurde vor dieser Runde korrigiert.

Im vorhandenen Systemintegrationstest fehlten zwei bereits auf RC30 vorhandene
Keyboard-Read-Beispiele und die zugehörige Testfreigabe. Die Fehler wurden auf
archivierter RC30-Quelle reproduziert und ausschließlich in der lokalen
Testfixture ergänzt. Produktivrechte wurden nicht erweitert. Unabhängige Reviews
fanden eine materialisierte Batch-Defaultkante sowie falsch typisierte native
Arrays; beide wurden vor der abschließenden Runde korrigiert.

Ruff, Format-, Lock- und Diffprüfungen sind Teil der Abnahme. Alle Builds und
Tests laufen lokal auf diesem Intel-Mac. Keine GitHub Actions, keine fremde
Sitzungssteuerung und keine produktive Installation in diesem Parallelauftrag.
Der abschließende [Validierungsbeleg](evidence/rc31-validation-20261103.json)
enthält die tatsächlich ausgeführten Testdateien und Runtimehashes.

Der erste Paketbau auf `0ea050b` stoppte nach Wheel-/Nativekompilierung, weil die
versionsgebundene `RELEASE-0.8.0rc31.md` noch fehlte. Es entstand kein vollständiges
Paket und keine Veröffentlichung. Die fehlende Freigabenotiz wurde ergänzt;
der folgende saubere Build bekommt einen eigenen Sourcepin. Die Implementierung
und ihre 380 bestandenen Prüfungen bleiben unverändert.

Der vollständige lokale Intel-Build auf
**`fc4063fef33c273fe5b33aadea3f99dddf88b757`** bestand anschließend. Die isolierte
Paketinstallation, ein authentifizierter Dispatcherstart, konkrete Lesevoraussetzungen,
Ablehnung eines beschädigten Pakets sowie Erhalt der eigenen Testkonfiguration und
Credentials wurden erfolgreich geprüft. Produktiver Dienst/Tunnel wurden nicht
angesprochen. Die unabhängige Paketprüfung bestätigt 166 Pythondateien bytegenau
gegen Git, Tar und Wheel, native x86_64-Architektur, Signaturen/Sourcepin,
568 Installer-Manifestdateien und die vollständigen ZIP-Bytes.
[Paketreview](evidence/rc31-package-review-20261103.json).

[Prerelease v0.8.0rc31](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc31)
ist veröffentlicht. Alle sieben Assets sind vollständig hochgeladen; ihre Größen
und GitHub-SHA256-Digests stimmen unabhängig mit den lokalen Dateien überein.
Der Intel-Installer wurde nach Veröffentlichung erneut heruntergeladen und geprüft:
**3.411.769 Bytes**, SHA-256
`9f9cb87ec910faa197f26c12a221f81f62c2a9961b11352a22cb935d4ca0f2ec`.
Der Release-Tag zeigt exakt auf `fc4063f`; es gab keinen GitHub-Actions-Lauf.
[Auslieferungsbeleg](evidence/rc31-release-20261103.json).

Der Branch ist als [Draft-PR #56](https://github.com/landjunge/KiraBridge/pull/56)
gegen `main` reviewbar; `main` bleibt `21a6abd`. Spätere Abschlussdokumentation
ändert den geprüften Paketpin nicht. Auf dem Mac läuft weiterhin die ursprüngliche
RC30-Instanz **PID 66439**, Start **03:30:12 UTC**, Instanz
`777222cce58e4b38b503c2f3d20900e1`. Diese aktuelle Beobachtung bestätigt den
erhaltenen Dienst; eine RC31-Produktivinstallation oder Cloud-/Voiceabnahme wird
in diesem Parallelauftrag ausdrücklich nicht behauptet.

Der Abschluss wurde im vorhandenen ThreadDesk-Whiteboard `188ce4729a62` nach
beobachteter Revision 496 angehängt, stabile Operation
`rc31-released-isolated-fc4063f-20261103`. Eintrag `d146e3c19060`, Ordinal 136,
wurde anschließend unabhängig vollständig und zeichengenau zurückgelesen.
Bestehende Beiträge bleiben erhalten.
