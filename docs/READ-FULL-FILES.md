# Dateien und Codex-Protokolle vollständig lesen / Read complete files and Codex logs

Berechtigter Gesamtzugriff hat keine Ein-Megabyte-Dateigrenze. Einzelne Antworten
sind begrenzte Seiten; der nächste Aufruf setzt am exakt zurückgegebenen Byteoffset
fort. Eine Seite ist nicht die ganze Datei. Bestehende Roots, Rechte, Credential-/
Stateausschlüsse und Schutz gegen Symlinks/Spezialdateien bleiben unverändert.

## Vollständiger Byteabruf

Im aktuellen KiraBridge-MCP-Zugang `read_query` verwenden:

```json
{"query":{"operation":"file.read","path":"/ausdruecklich/freigegebenes/protokoll.jsonl","offset":0,"max_bytes":65536,"encoding":"base64"}}
```

Dies ist ein Pfadbeispiel, kein behaupteter Bibliotheks- oder Dateizugriff.
Die Antwort enthält echte Originalbytes in `data_base64`, deren `content_sha256`,
`bytes`, `next_offset`, `size_observed`, `identity` und `eof`.
Für JEDE Folgeseite denselben Pfad und die anfängliche `identity` als
`expected_identity` verwenden; `offset` wird zum letzten `next_offset`.
Fortsetzen bis `eof:true`, nicht nach dem ersten vollen Antwortblock aufhören.
`truncated:true` bedeutet in dieser Dateiseite: weitere Dateibytes vorhanden.

Nach jeder Seite Base64 dekodieren und den Seiten-SHA-256 prüfen. Originalbytes
in Offsetreihenfolge zusammensetzen bzw. streamen; am Ende müssen Gesamtbytezahl
und SHA-256 mit dem freigegebenen stabilen Original/Export übereinstimmen.
UTF-8 erst über einen inkrementellen Decoder oder nach der Byte-Rekonstruktion
lesen. `text` ist eine kompatible Vorschau; `text_lossless:false` kennzeichnet
getrennte oder ungültige UTF-8-Sequenzen. Die Base64-Originalbytes gehen dabei
nicht verloren. Binär-, PDF-, Office-, Bild-, ZIP-, Audio- und Videodaten verwenden
entsprechend den Bytesmodus, nicht die Textvorschau.

Anfang: `offset:0`. Mitte: gewünschter Byteoffset. Ende: `tail:true` ohne positiven
Offset. Gesamtabruf beginnt immer bei0 und folgt lückenlos `next_offset` bis EOF.
Direkte Reads liefern höchstens64KiB pro Aufruf. Bestehendes `file.read` über
`task_request`/`action_request` unterstützt denselben Rangevertrag mit höchstens
1MiB pro Antwort. Das sind Seitenbudgets, keine Gesamtdateigrößenlimits.
Normale Aufgaben benötigen keine erfundene Events-Subscription.

## Aktive Protokolle und Originalerhalt

`identity` ist ein Metadaten-Änderungstoken, kein kryptografisch unveränderlicher
Snapshot. Append, Truncate oder Austausch führen bei gepinnter Folgeidentität
zu `file_changed`; gemischte Dateiversionen werden nicht als vollständiges Log
zurückgegeben. Für eine aktive Codex-Datei zuerst einen ausdrücklich autorisierten,
stabilen Export/Snapshot anlegen und diesen lesen. Das Original weder löschen,
verschieben noch überschreiben. Ein Terminalbildschirm ist kein Protokollarchiv.

Keine Zugangsdaten automatisch exportieren und keine neuen Roots still freigeben.
Eine nicht verfügbare ChatGPT-Bibliotheks-API wird durch dieses Dateimodul nicht
behauptet. Ein Operator-MCP-Test ist kein tatsächlicher ChatGPT-Hosttest.

## English

Read the authorized file in bounded pages until **EOF**, with no overall file-size
cap. Request `encoding:base64`; decode actual `data_base64`, verify each page SHA-256,
advance using `next_offset`, and pin the first `identity` as `expected_identity`.
Reassemble/decode bytes incrementally and verify the final size and SHA-256 against
the authorized stable source. `text` remains a compatibility preview; split UTF-8 is
explicitly marked instead of being claimed lossless. Beginning, arbitrary middle
byte offsets and tail reads are supported. Direct requests allow64KiB and legacy
task reads1MiB per page; those limits do not end the overall traversal.

A changing source fails with `file_changed`. For active logs, use a separately
authorized stable export and preserve the original. Existing authentication,
configured rights, root/credential exclusions and non-regular-file protections
remain effective. Live terminal captures are not complete archival logs. Actual
ChatGPT acceptance requires a real invocation from that Host and must not be
inferred from an operator probe.
