# KB-C05: Begrenztes PNG-Lesen / bounded PNG reads

## Deutsch

**Integriert und in der verbundenen ChatGPT-App tatsächlich als Bild empfangen.**
Die ursprüngliche isolierte Quellprüfung wurde anschließend durch kontrolliertes
Laden des lokalen0.5.2-Backports df995f6 ergänzt. Kein aktualisierter Release-Download
und keine Zusage automatischer Push-Zustellung.
Der bestehende Task-/SQLite-/MCP-Rückweg wird wiederverwendet; keine zweite Queue.

`file.image` ist eine **eigene Capability**, nicht automatisch Bestandteil von
`file.read`. Der lokale Betreiber muss sie einem vorhandenen Principal ausdrücklich
erteilen und einen geeigneten Dienststand kontrolliert laden. Bestehende `roots` und
`read_roots` gelten; private Bridge-Zustandsverzeichnisse, Traversal und Symlinks bleiben
gesperrt. Das Betriebssystemkonto/Installation bleibt die bestehende Vertrauensgrenze.
Die Änderung fügt keine Konfigurationsfreigabe und keinen Terminal-/Interpreterweg hinzu.

Vorprüfung: `bridge_readiness` mit `operations:["file.image"]` und
`image_paths:["ABSOLUTER_ERLAUBTER_PNG_PFAD"]`. Sie prüft Recht, Descriptorzugang und
reguläre Datei, **keine PNG-Daten und keine Clientanzeige**. Der tatsächliche Auftrag
wiederholt die Prüfungen und validiert dann den Inhalt. Der vorhandene Freigabemodus
(`manual`/`automatic`) bleibt maßgeblich.

Genauer vorbereiteter MCP-Abruf (Pfad nach Integration/geladenem Stand einsetzen;
dieses Beispiel wurde nicht an die Nutzer-Runtime gesendet):

```json
{
  "request": {
    "task_id": "kb-image-acceptance-20261018-1",
    "idempotency_key": "kb-image-acceptance-20261018-1",
    "operation": "file.image",
    "arguments": {
      "path": "/Users/landjunge/KiraBridge/tests/fixtures/images/own-rgb-32x24.png"
    }
  }
}
```

Einmal an `task_request` senden; Empfang ist noch keine Ausführung. Bei unklarer
Antwort oder Wiederverbindung `task_get({"task_id":"kb-image-acceptance-20261018-1"})`
lesen, **keine neue Kennung erzeugen**. Nur der gespeicherte Eigentümer mit `task.read`
kann seinen Auftrag lesen. Wie bei bestehenden Textaufträgen bleiben bereits
autorisierte Ergebnisse für diesen Eigentümer abrufbar; Rechteänderungen verhindern
neue Ausführung, löschen aber keine historischen Nutzdaten.

Erst `completed` eines `file.image`-Tasks liefert zusätzlich zum normalen
MCP-Text-/`structuredContent`-Metadatensatz einen echten `ImageContent`-Block:
`type:image`, `mimeType:image/png`, Base64-Snapshot in `data`. Die Metadaten enthalten
`bytes`, `width`, `height`, `content_sha256`, `captured_at`, `source_mtime_ns` und
`source_scope`. Das Bild wird nicht zusätzlich als langer Base64-Text ausgegeben.
Andere Operationen und Fehler behalten ihr bisheriges JSON-Format und erzeugen kein
Bild. Ein gespeicherter Pfad oder die Metadaten allein belegen keine Sichtbarkeit.
Die tatsächliche App muss das Bild zeigen/lesen können; dieser Nachweis bleibt separat.

Grenzen:

- Genau ein statisches PNG pro Task; höchstens 1 MiB Datei, 2048 Pixel je Seite,
  4.194.304 Pixel, 512 Chunks und 2 MiB komplette serialisierte MCP-Toolantwort.
- Unterstützt: 8-Bit RGB/RGBA, ohne Interlace; optionale feste `cHRM`/`gAMA`/`sRGB`/
  `pHYs`-Chunks. Palette/Graustufen, ICC/Textdaten, APNG, unbekannte Chunks und andere
  Bildformate werden abgelehnt. Keine Thumbnail-Konvertierung oder neue Abhängigkeit.
- Signatur, Reihenfolge/Längen/CRC, vollständiger Zlib-Datenstrom, tatsächliche begrenzte
  Zeilendaten und Filtertypen werden geprüft. Maximale entpackte Daten: 16.779.264 Byte;
  nicht nur eine behauptete Bildgröße. Überläufe/trunkierte Daten erzeugen kein Bild.
- Der Descriptor wird während des Reads auf Größen-/mtime-/ctime-Änderung geprüft.
  Das ist ein Snapshot mit Hash und Zeitpunkt, keine spätere Aktualitätsgarantie oder
  externe Beglaubigung. `task_get` öffnet die Quelle nie erneut; auch nach Änderung,
  Entfernung oder Dienstneustart bleibt das ursprüngliche Ergebnis erhalten.
- Bildbytes liegen in der bestehenden privaten Task-Datenbank (0700-Verzeichnis,
  0600-Datenbank; keine neue Verschlüsselungsbehauptung). Audit/Events enthalten nur
  die vorhandenen Zustands-/Hashbelege. Keine automatische Löschung oder zweiter Cache.
- Fehlercodes umfassen `image_invalid`, `image_limit`, `image_changed` sowie vorhandene
  Pfad-/Rechtefehler. Fehler nach Eintritt in die lokale Operation bleiben gemäß dem
  konservativen bestehenden Taskmodell `unknown`, ohne automatischen Neustart.

## English

**Integrated and received as an actual image in the connected ChatGPT App.** The
original isolated source checks were followed by controlled loading of local0.5.2
backport df995f6. Frozen release artifacts are unchanged. This is polling through
the existing task store, not push.

The separate `file.image` capability must be explicitly granted by the local operator.
It uses existing `roots`/`read_roots`, descriptor-relative no-symlink access and the
private-state exclusion. `bridge_readiness(image_paths:[...],operations:["file.image"])`
checks access prerequisites only; actual task execution validates the PNG. Submit the
example above once through `task_request`, then poll `task_get` with the same task ID.
Never restart uncertain work using a new ID.

An owned completed image task returns metadata plus an MCP `ImageContent` PNG block.
Other tasks retain their JSON format. Source bytes are captured once in the existing
private task result, with SHA256, dimensions, capture time and source mtime. Reconnect
and restart read this same snapshot without reopening the file. Saved results remain
owner-readable with `task.read`, just like existing text results; revoking a capability
prevents new execution and does not erase historical data. No image bytes enter audit
or event records.

Limits: one static PNG, 1 MiB, 2048 pixels per side/4,194,304 pixels, 512 chunks and
2 MiB for the entire serialized tool response. Only non-interlaced RGB/RGBA8 with
optional fixed-size colour/physical metadata is supported. CRC, chunk order, the full
bounded compressed row stream (at most 16,779,264 decoded bytes) and filter types are
checked. Other formats, palettes, text/ICC metadata, animation, malformed/truncated or
oversized content fail closed. No Pillow dependency or automatic image conversion.
Snapshot hashes do not establish current source freshness or remote attestation.

## Nachweise / evidence

- `tests/test_images.py`: **21 gezielte Tests**, Python 3.11.15/macOS,
  MCP SDK 1.30.0 / pytest 9.1.1, bestanden.
  Including real authenticated local MCP HTTP output, separate principals, unchanged
  ordinary JSON, daemon-client reconnect, Bridge/store restart after source removal,
  one original execution, read-only roots, capability denial, private-state exclusion,
  symlinks/FIFO, invalid/corrupt/compressed overflow/changed-source cases, whole response
  budget and image-free audit/events.
- Additional affected-path compatibility: `tests/test_readiness.py` and the two existing
  MCP tests `test_multiple_real_http_clients_do_not_cross_principals` /
  `test_real_stdio_roundtrip`: **6 passed**. No model/provider calls or user data.
- Ruff check/format of modified Python files passed. Existing CI runs independently;
  these local checks are not a claim that all hosted platforms passed.
- Own synthetic fixture: `tests/fixtures/images/own-rgb-32x24.png`, 32×24 RGB,
  104 bytes, four coloured quadrants, generated solely from Python standard-library
  bytes/CRC/Zlib; no external image, personal data or image-generation service.
  SHA256 `cabc398201d3063c587946158c88a4a4d4dadc023bb99d61f944302a01ad19e2`.
- At the original worker checkpoint, still required: integrate/load the reviewed source;
  explicitly configure the separate
  capability for the intended principal; one real connected ChatGPT invocation must
  receive and inspect the image and retain task ID/source/runtime evidence. This worker
  did not change live configuration, reload a daemon or submit that acceptance task.

## Tatsächliche App-Abnahme / real connected App acceptance

Task seven-c05-20261018-image lief als chatgpt genau einmal, completed/Versuch1.
task_get lieferte Textmetadaten UND ImageContent: die eigene32×24-Fixture mit vier
sichtbaren Farbquadranten,104Bytes und obigem SHA256. Nach kontrolliertem
Dienstneustart lieferte dieselbe Task erneut denselben Bildblock/Hash, ohne neue
Ausführung; die gespeicherte Task blieb vollständig unverändert. Die Quelldatei
wurde bei dieser echten App-Probe erhalten; die Entfernen-/Reconnect-Gegenfälle
stammen aus den oben getrennten lokalen Tests.

Die eigene Capability wurde ausschließlich den vorhandenen local/chatgpt-Profilen
ergänzt. Andere Rechte, Zugänge und385 frühere Tasks blieben erhalten. Konfiguration
weiter0600, Backup unter ~/.local/share/kirabridge/workflow-reads-20261018/.
[Quittungen und Runtimefingerabdrücke](evidence/workflow-reads-chatgpt-20261018.json).
Kein gesamter Mac-Neustart, keine Gesamtprojekt- oder Nutzerabnahme.

The connected App received the real image, then the same stored snapshot after
a controlled service restart, with one running event and attempt1. Source removal
was tested only in the separate isolated suite. Existing credentials, service
settings and historical tasks were preserved. This is not an overall acceptance.
