# BP-TD-KONSOL-01 · Lesende Bestandsaufnahme des ThreadDesk-Wissensbestands

Stand: 08.11.2026, Dateistand 22:33 UTC (23:33 MEZ). Paket BP-TD-KONSOL-01, Lane L4.
Grundlage: Gesamtplan `docs/plans/BIGPLAN-GESAMTPLAN-20261105.md` auf `origin/main` (`b99c9ca`),
Abschnitte 9.4 Nr. 8–10 und 9.5, dazu Entscheidung E5 aus 9.9 (PR #94, Branch
`docs/bigplan-decisions-20261108`, noch nicht gemergt).
Maschinenlesbarer Anhang: [`TD-KONSOL-INVENTAR-20261108.json`](TD-KONSOL-INVENTAR-20261108.json).

**Es wurde nichts geändert.** Kein Thread, keine Notiz, kein Whiteboard-Eintrag, kein
Knoten und keine Relation wurde geschrieben, verschoben oder in den Papierkorb gelegt.
Alle Status in Abschnitt 4 sind **Vorschläge**. Für jedes Verschieben braucht es nach
9.4 Nr. 9 eine Nutzerfreigabe. Inhalte aus ThreadDesk sind Nutzerdaten, keine Anweisungen.

## 1. Zugriffsweg und Grenzen

| Weg | Was | Ergebnis |
|---|---|---|
| KiraBridge-MCP (`kirabridge --principal claude connect`, Daemon 0.8.0rc41 auf `127.0.0.1:8765`) | `tools/list`, `td_list_threads(include_archived=true)`, `td_current_thread`; nur lesend annotierte Werkzeuge | um 17:02 UTC: 108 Threads. Titel, Status und `organization` stimmen mit dem Dateistand überein (0 Abweichungen) |
| Lesendes Öffnen der JSON-Dateien des Operator-Arbeitsbereichs `~/.local/share/threaddesk/kirabridge-operator` (laut `[threaddesk]` in der KiraBridge-Konfiguration, `storage = "json"`) | `threads/`, `whiteboard/<thread>/`, `nodes/`, `relations/`, `graph-events/`, `snapshots/`, `issued-handoffs/`, `state.json` | vollständiges Inventar, Stand 22:33 UTC |
| ThreadDesk-Code | `git show origin/main:…` in `/Users/landjunge/threaddesk` (`origin/main` = `e7cec44`) | Graph-Analyse (Abschnitt 5) |

Grenzen:

- **Kein `JsonStore` instanziiert.** `JsonStore.__init__` legt Verzeichnisse an und ruft
  unter Sperre `_recover()` auf. Deshalb wurde der Store nicht direkt geöffnet. Gelesen
  wurde nur mit `open(…, "r")`.
- **MCP nur teilweise genutzt.** Ein Sammelabruf von `td_get_thread` für alle 108 Threads
  blieb ohne Antwort und wurde abgebrochen. Danach lehnte der Daemon kurz mit
  `peer_connection` ab. Ab etwa 17:06 UTC zeigte `tools/list` für den Principal `claude`
  nur noch 77 statt 111 Werkzeuge und keine `td_*`. Aufrufe endeten mit
  `threaddesk_tool_denied`. Ursache nicht untersucht, nichts repariert. Die Detaildaten
  stammen deshalb aus dem lesenden Dateizugriff.
- **Daten in Bewegung.** Zwei Loop-Agenten schreiben weiter Berichte (6.2). Zahlen zu
  Whiteboard-Einträgen gelten für 22:33 UTC.
- **Notizen-Anzahl.** ThreadDesk speichert Notizen als **ein** Textfeld
  (`context.notes`). Angegeben sind Zeichen; Absätze stehen im JSON (`notes_paragraphs`).
  „Einträge“ sind Whiteboard-Einträge (append-only, je eine Datei).
- **Nicht vollständig gelesen:** Arbeitsboard `188ce4729a62` (345 909 Zeichen,
  581 Einträge), `3e706958488c` (8 364 Einträge) und die einzelnen Berichtsthreads. Die
  Bewertung stützt sich dort auf Struktur, Kopfzeilen und ID-Verweise.
- `library-files/` und `management-operations/` (596 Quittungen) wurden nicht ausgewertet.

## 2. Summen

| Größe | Wert |
|---|---|
| Threads | 108 (idea 102, archived 4, active 1, paused 1) |
| davon Whiteboards (nach `WhiteboardService.exists`: `extra.whiteboard` oder ≥ 1 Eintrag) | 90 |
| Whiteboard-Einträge gesamt | 17 329 (davon 8 196 in den 78 Berichtsthreads, 8 364 in `3e706958488c`) |
| Snapshots | 2 (beide zu synthetischen Threads) |
| Gespeicherte Graphknoten / Relationen / Graph-Ereignisse | 3 / 1 / 6, alle aus der synthetischen Abnahme C03 vom 18.10. (`67f9698601df`) |
| Papierkorb | leer (kein Verzeichnis `trash/`) |
| Threads mit `organization` | 13 |
| Abgeleitete Kanten aus `related_thread_ids` / `parent_thread_id` | 24 (15 / 9) |
| Aktueller Thread (`state.json`) | `450d3dc1c6d2` |

Gruppen: Big Plan 3 · Big-Plan-Berichte 78 · Koordination/Arbeitsboards 4 ·
Brainstorming/Ideen/Pläne 9 · Produkte/Quellbereiche 9 · Test/synthetisch 5.

## 3. Inventar

Spalten: Typ (`whiteboard` nach der Regel oben, sonst `thread`), Notizen in Zeichen,
Einträge = Whiteboard-Einträge, letzte Änderung = `updated_at` in UTC. Graphkanten:
Keiner dieser Threads hat gespeicherte Relationen. Gespeicherte Knoten hat nur
`67f9698601df` (3). Textverweise auf andere Thread-IDs stehen im JSON (`text_thread_refs`).

### 3.1 Alle Threads außer den Berichten

| ID | Titel | Typ | Status | Notizen | Einträge | letzte Änderung | parent | related |
|---|---|---|---|---|---|---|---|---|
| `3e706958488c` | Big Plan · Agentenübersicht · Kira | whiteboard | idea | 91111 | 8364 | 2026-11-08 22:33 | – | – |
| `a17c937b7553` | Big Plan · Gemeinsame Produkt-Icons und Designsystem | thread | idea | 4737 | 0 | 2026-11-08 12:00 | – | – |
| `c9a396be4081` | Big Plan · KI-/CLI-Fähigkeitsmatrix und intelligente Delegation | thread | idea | 24198 | 0 | 2026-11-06 23:59 | – | – |
| `fdc7959f7dec` | Bibliothek → ThreadDesk \| Konsolidierung 23.10.2026 | thread | idea | 40186 | 0 | 2026-10-23 05:43 | – | – |
| `f014aeed7384` | Bibliotheksimport – Wissen und Brainstormings | whiteboard | idea | 3564 | 4 | 2026-10-26 15:57 | `fdc7959f7dec` | `c6b016d836d3`, `a6fe31f58501` |
| `1deb9d17dd28` | Brainstorming · Werkzeugfamilie, Graph & Produktarchitektur · 08.11.2026 | thread | idea | 11224 | 0 | 2026-11-08 16:10 | – | `482f593429ad`, `c2d4c7bc985a`, `188ce4729a62`, `a6fe31f58501` |
| `6b5b73b9de36` | Gesamtplan ThreadDesk & 4AllPass – 20.10.2026 | whiteboard | archived | 97200 | 1 | 2026-11-07 11:59 | – | – |
| `c6b016d836d3` | Ideen, Medien & weitere Projekte | thread | idea | 0 | 0 | 2026-10-24 16:06 | `fdc7959f7dec` | – |
| `455dad75c60f` | KiraBridge – OpenAI-Zulassung: Voraussetzungen und Beispiele | thread | paused | 1690 | 0 | 2026-11-08 10:34 | – | – |
| `597fd5fcb040` | KiraBridge – Sichtbarkeit, Community und schrittweise Veröffentlichung | thread | idea | 1150 | 0 | 2026-11-07 22:28 | – | – |
| `30e962aaed81` | Ocean – App und KiraBridge-Anbindung | whiteboard | idea | 1255 | 1 | 2026-11-05 20:53 | – | – |
| `450d3dc1c6d2` | ThreadDesk · Wissensgraph und Brainstorming-Konsolidierung | whiteboard | idea | 3539 | 1 | 2026-11-08 16:43 | – | `1deb9d17dd28`, `188ce4729a62`, `482f593429ad`, `a6fe31f58501`, `c2d4c7bc985a` |
| `482f593429ad` | KiraBridge und ThreadDesk – gemeinsame Koordination | whiteboard | idea | 31527 | 108 | 2026-11-08 16:12 | – | `188ce4729a62`, `c2d4c7bc985a` |
| `1b7530de7c5f` | KiraBridge – Reparatur 2026 | whiteboard | idea | 11371 | 40 | 2026-11-01 09:27 | – | – |
| `0ab8b95a7369` | KiraBridge – macOS-Integration \| Entwicklungsplan | thread | idea | 68500 | 0 | 2026-10-31 19:52 | – | – |
| `188ce4729a62` | ThreadDesk und KiraBridge – Wechselentwicklung durch Codex | whiteboard | active | 345909 | 581 | 2026-11-08 17:10 | – | – |
| `911bb6f922e2` | 4AllPass – Projektpläne | thread | idea | 747 | 0 | 2026-11-07 11:59 | `fdc7959f7dec` | – |
| `dc200bb01137` | Agent Authority – Forschung & Belege | thread | idea | 345 | 0 | 2026-11-07 11:59 | `fdc7959f7dec` | – |
| `346577d6367e` | Buschradio – Interview-Schnittworkflow | thread | idea | 0 | 0 | 2026-11-07 13:35 | – | – |
| `ecd8609518c1` | KI-Hilfezentrum & offene Tools | thread | idea | 0 | 0 | 2026-10-23 02:20 | `fdc7959f7dec` | – |
| `d2b41e5dad06` | KiraBridge – Releases & Übergaben | thread | idea | 1030 | 0 | 2026-10-23 05:36 | `fdc7959f7dec` | – |
| `eb4870dda203` | NetzwerkPunkt – Plattform & Gestaltung | thread | idea | 0 | 0 | 2026-10-23 02:20 | `fdc7959f7dec` | – |
| `c2d4c7bc985a` | ThreadDesk Server & Sync | whiteboard | idea | 2049 | 23 | 2026-11-07 12:59 | – | `188ce4729a62`, `482f593429ad` |
| `a6fe31f58501` | ThreadDesk – Quellen & Masterfassungen | thread | idea | 1408 | 0 | 2026-11-07 11:59 | `fdc7959f7dec` | – |
| `138fb6baeff2` | TollGate – Planung | thread | idea | 344 | 0 | 2026-11-07 11:59 | `fdc7959f7dec` | – |
| `234b5f3544ad` | Big Plan · Isolierter Praxistest · Codex → Grok | thread | idea | 733 | 0 | 2026-11-06 13:57 | – | – |
| `b87de46d2b54` | KiraBridge Schnittstellenprobe | whiteboard | idea | 0 | 5 | 2026-10-29 00:13 | – | – |
| `67f9698601df` | Synthetic C03 operator acceptance 20261018 | thread | archived | 0 | 0 | 2026-10-23 02:22 | – | – |
| `4de1f7c607ec` | Synthetic M2 acceptance: ask which color, then create one proof file | whiteboard | archived | 0 | 4 | 2026-10-23 02:22 | – | – |
| `a39d1e7e1a9a` | Synthetischer Stoppnachweis / synthetic stop acceptance 2026-10-19 | whiteboard | archived | 0 | 1 | 2026-10-23 02:22 | – | – |

Zuordnung zu den Gruppen:

- **Big Plan:** `3e706958488c`, `a17c937b7553`, `c9a396be4081`.
- **Koordination/Arbeitsboards:** `188ce4729a62` (laut `AGENTS.md` Arbeitsgedächtnis),
  `482f593429ad`, `0ab8b95a7369`, `1b7530de7c5f`.
- **Brainstorming/Ideen/Pläne:** `1deb9d17dd28`, `450d3dc1c6d2`, `f014aeed7384`,
  `fdc7959f7dec`, `c6b016d836d3`, `597fd5fcb040`, `455dad75c60f`, `30e962aaed81`,
  `6b5b73b9de36`.
- **Produkte/Quellbereiche:** `911bb6f922e2` (4AllPass), `dc200bb01137` (Agent Authority),
  `138fb6baeff2` (TollGate), `a6fe31f58501`, `d2b41e5dad06`, `c2d4c7bc985a`,
  `ecd8609518c1`, `eb4870dda203`, `346577d6367e` (Buschradio, Medienprojekt).
- **Test/synthetisch:** `67f9698601df`, `4de1f7c607ec`, `a39d1e7e1a9a` (alle archiviert),
  `b87de46d2b54` (Testboard), `234b5f3544ad` (Praxistest mit erfundenen Angaben).

### 3.2 Berichte „Big Plan · Bericht · …“ (78)

Alle sind Whiteboards mit Status `idea`, ohne `organization` und nur mit Einträgen vom
Typ `progress` (Schema `bigplan.agent-report.v1`). Angelegt ab 05.11.2026. Sie werden von
`3e706958488c` per Text-ID gesammelt (78 Verweise), sind aber **nicht** als Kinder
verknüpft. Nach Agent: Codex 22, Codex Worker 14, Codex Verifier 8, Grok 7, Codex Loop 5,
Grok Review 5, Grok Worker 3, übrige je 1–2. 20 Berichte haben höchstens 3 Einträge.

| ID | Agent | Lauf | Einträge | letzter Eintrag (UTC) |
|---|---|---|---|---|
| `315b2543b087` | Claude | claude-f8f2c01c | 2 | 2026-11-08 16:12 |
| `579b10d4aea7` | Codex Loop Core | codex-loop-core-20261105 | 8 | 2026-11-05 22:04 |
| `476d16c5eab4` | Codex Loop Review | codex-loop-review-20261105 | 13 | 2026-11-05 22:06 |
| `62e09d54117c` | Codex Loop | codex-bigplan-loop | 3867 | 2026-11-08 22:33 |
| `a28c9c458c23` | Codex Loop | codex-loop-20261105 | 5 | 2026-11-05 21:44 |
| `b32da470feb0` | Codex Loop | codex-loop-20261105-v2 | 5 | 2026-11-05 21:48 |
| `b0e8b298bf41` | Codex Loop | codex-loop-20261105-v3 | 5 | 2026-11-05 21:57 |
| `fd9b340d4c50` | Codex Loop | codex-loop-20261105-v4 | 5 | 2026-11-05 21:59 |
| `6e6b360a5cee` | Codex M3 Final Review | codex-m3-plan-final-review-20261106 | 19 | 2026-11-06 03:15 |
| `0c2bfd2e81c0` | Codex Projektmemory-Review | codex-project-memory-review-20261106 | 40 | 2026-11-06 01:49 |
| `d2d0ef6efc12` | Codex Review | codex-review-reports-01a1ad8f | 2 | 2026-11-05 21:23 |
| `14cf6a115659` | Codex Verifier | codex-bigplan-loop-tw-0a62a51dacdb4f39925bdb5f5297de4f | 10 | 2026-11-07 05:30 |
| `98188e97dfee` | Codex Verifier | codex-bigplan-loop-tw-3558ab5798bc49aeaed11a1610d3192d | 11 | 2026-11-07 05:30 |
| `ea18023431e1` | Codex Verifier | codex-bigplan-loop-tw-45cafde06fae4ca592d6c76745e9f387 | 12 | 2026-11-07 05:30 |
| `6965901172b9` | Codex Verifier | codex-bigplan-loop-tw-652390fbf5be4ea192f0f2642fca05c3 | 14 | 2026-11-07 05:30 |
| `9b2f894b1f3f` | Codex Verifier | codex-bigplan-loop-tw-90841bd88ee6453a9fe7d75a704f742c | 14 | 2026-11-07 05:30 |
| `63e1039ba589` | Codex Verifier | codex-bigplan-loop-tw-dcec15c6423e4c3a8cbf7cf4bf021899 | 12 | 2026-11-07 05:30 |
| `6582ff36dcac` | Codex Verifier | codex-bigplan-loop-tw-e8f894c5d413418f8354b4494a751bb5 | 17 | 2026-11-07 05:30 |
| `6307e1a241e5` | Codex Verifier | codex-bigplan-loop-tw-f3431a36953946ce940ff61049cac0cb | 16 | 2026-11-07 05:30 |
| `be9ec8243225` | Codex Worker | codex-bigplan-loop-tw-2322ac1b859644e493c656a2eb548407 | 10 | 2026-11-07 05:30 |
| `092259284cec` | Codex Worker | codex-bigplan-loop-tw-36bedad76b854cf582e8ec5e2d4c0e7b | 12 | 2026-11-07 05:30 |
| `5ba0b2bbd9b8` | Codex Worker | codex-bigplan-loop-tw-3ef02983b58f4f91a0af38863eaf1c95 | 11 | 2026-11-07 05:30 |
| `04cb3e018431` | Codex Worker | codex-bigplan-loop-tw-41512ed0d8084ccd95cf6600689f24b8 | 12 | 2026-11-07 05:30 |
| `b87abba1a3e0` | Codex Worker | codex-bigplan-loop-tw-7dbee6e349dc4776882f508550c172de | 16 | 2026-11-07 05:30 |
| `072e79731065` | Codex Worker | codex-bigplan-loop-tw-95442057b05e4d9db0531475fa796939 | 16 | 2026-11-07 05:29 |
| `6064e294f576` | Codex Worker | codex-bigplan-loop-tw-a88563b9942d4991b3916e93d8b446e1 | 13 | 2026-11-07 05:30 |
| `50f7af5cba21` | Codex Worker | codex-bigplan-loop-tw-b3e2570314b14fe59ce7cb8b54d48d79 | 11 | 2026-11-07 05:30 |
| `a64c121f7267` | Codex Worker | codex-bigplan-loop-tw-ed9b1adb411341c79e907fcb21798db6 | 13 | 2026-11-07 05:30 |
| `1d297b3ea49f` | Codex Worker | codex-bigplan-loop-tw-fe93b617356144e39db41f5ebc13402f | 16 | 2026-11-07 05:30 |
| `0df8b3863ff0` | Codex Worker | codex-loop-20261105-tw-61205ca8bd97403c8896e2b4f7ad4663 | 2 | 2026-11-05 21:41 |
| `09e1afcf937c` | Codex Worker | codex-loop-20261105-v2-tw-610d71548a514b1fa7c1a97c94acaa5a | 3 | 2026-11-05 21:45 |
| `4f1dc49cc430` | Codex Worker | codex-loop-20261105-v3-tw-e5ee37f1b30b41628b40e15d2194b165 | 2 | 2026-11-05 21:50 |
| `47cffc352a11` | Codex Worker | codex-loop-20261105-v4-tw-d62e69414bc840a388052153292c9233 | 2 | 2026-11-05 21:57 |
| `36722a01a76d` | Codex | codex-01a1a7d1-aa13-79b2-8a83-6dc50d800674 | 265 | 2026-11-06 09:47 |
| `327db862b0f3` | Codex | codex-01a1ad8f-7c0b-7e90-9b55-391a8ea815b3 | 15 | 2026-11-05 22:12 |
| `90dbd8b3a889` | Codex | codex-01a1ada2-3f47-7d03-8d5c-21d5501fbac4 | 13 | 2026-11-05 22:06 |
| `205f2635ac92` | Codex | codex-01a1adf9-98b1-7b03-a991-d79ca1d3e688 | 5 | 2026-11-05 23:15 |
| `d5e9f661c6e2` | Codex | codex-01a1ae37-7e1e-72f0-8cbd-4eca62cf69e0 | 253 | 2026-11-06 12:04 |
| `21abc5f8222c` | Codex | codex-01a1ae97-e364-7012-8fc1-a9d65e4398b4 | 103 | 2026-11-06 15:12 |
| `fa4147696509` | Codex | codex-01a1aec9-256a-7fd1-9d3a-40f2d02085a6 | 68 | 2026-11-06 15:25 |
| `605aa9dc29bb` | Codex | codex-01a1aec9-68b2-7d23-aa8f-774440cd25a2-native-review | 66 | 2026-11-06 12:14 |
| `15657f0b1c77` | Codex | codex-01a1b03d-25cd-7130-b14d-a88e7dcddf74 | 27 | 2026-11-06 11:54 |
| `9d506b20be44` | Codex | codex-01a1b03d-25cd-7130-b14d-a88e7dcddf74-coordinator-audit | 25 | 2026-11-06 10:58 |
| `1655dd3350ed` | Codex | codex-01a1b0cb-2dd1-7100-b636-4e1cafe3b869 | 59 | 2026-11-06 15:02 |
| `65674c4d419d` | Codex | codex-01a1b0cd-ed35-7b12-8823-468b09db5907 | 8 | 2026-11-06 12:27 |
| `38f3bcd9da5b` | Codex | codex-01a1b0ce-139f-7862-ac53-dde11892f023 | 18 | 2026-11-06 15:50 |
| `7e5f57874203` | Codex | codex-01a1b10a-957f-7622-ba78-2fd04b43c0db | 40 | 2026-11-06 16:01 |
| `08801be0692a` | Codex | codex-01a1b195-d8b0-7873-9576-20ae23a2384b | 76 | 2026-11-06 21:12 |
| `f6bec0eef975` | Codex | codex-01a1b2d4-b8a5-7990-9b3a-5222b227339b | 45 | 2026-11-06 23:29 |
| `80aa29e4699a` | Codex | codex-debian-release-20261107 | 126 | 2026-11-07 15:11 |
| `37f54a849854` | Codex | codex-integration-review-20261106 | 1 | 2026-11-06 12:21 |
| `407a1050011d` | Codex | codex-m3-plan-review-20261106 | 9 | 2026-11-06 02:37 |
| `7a441bf5b957` | Codex | codex-td-integration-20261106-child | 2 | 2026-11-06 12:22 |
| `3dac6d943319` | Codex | codex-windows-coordinator-20261107 | 15 | 2026-11-07 05:36 |
| `1b8464692073` | Codex | codex-windows-installer-finish-20261107 | 43 | 2026-11-07 15:15 |
| `fdcff53efdbf` | Codex-Sourceprüfer | codex-01a1ade6-829c-7f63-b57c-f03f1ea06402 | 1 | 2026-11-05 22:52 |
| `1d86a37fb69a` | Codex-Sourceprüfer | codex-windows-evidence-check-run-20261105-v1 | 2 | 2026-11-05 22:52 |
| `08efce352d6e` | Grok (Codex-Beobachtung) | grok-argv-fix-review-20261106-02 | 3 | 2026-11-06 14:13 |
| `9e0bb55ffeec` | Grok (Codex-Beobachtung) | grok-observation-review-20261106-01 | 2 | 2026-11-06 13:56 |
| `ae9ebbd939f3` | Grok C1 Review | grok-coord-native-c1-review-20261106-v1 | 2 | 2026-11-06 03:19 |
| `4a5b71763953` | Grok Review | codex-bigplan-loop-tw-370d0f8da6c7486494c378d8d1aae6d9 | 10 | 2026-11-07 05:30 |
| `f92ba6d1d7d5` | Grok Review | codex-bigplan-loop-tw-88e242c082bc4fda9025c53dac6a978b | 13 | 2026-11-07 05:30 |
| `52daa8c8af4c` | Grok Review | codex-bigplan-loop-tw-a725cb3759574909a4ed326ac057ef51 | 16 | 2026-11-07 05:30 |
| `edd5586a8d1a` | Grok Review | codex-loop-20261105-v3-tw-bf91a2f49cff473d94f50f3042075bfe | 3 | 2026-11-05 21:50 |
| `2dd94ba190bb` | Grok Review | codex-loop-20261105-v4-tw-53844dbeec304080abc3fbdba481fb3a | 2 | 2026-11-05 21:57 |
| `4236f48b3e05` | Grok Worker | codex-bigplan-loop-tw-06e5cf9aee164d0c88942471bb48a5e5 | 6 | 2026-11-07 05:31 |
| `076cea0cf2d9` | Grok Worker | codex-bigplan-loop-tw-24ed407f152d4f60a8c268c99cc9196d | 2 | 2026-11-07 05:31 |
| `e834c98e8d3f` | Grok Worker | codex-bigplan-loop-tw-630b7963bd274595b06f4d41a71334a4 | 6 | 2026-11-07 05:30 |
| `db5b34346962` | Grok | grok-01a1ad13-c817-7690-b6c8-f23dede3707f | 3 | 2026-11-05 22:13 |
| `916495322834` | Grok | grok-01a1b302-38c0-7731-884e-9ab5688ab010 | 3 | 2026-11-06 23:03 |
| `26b749296cff` | Grok | grok-58655-kb-win-supervisor-bind-20261107 | 2588 | 2026-11-08 22:33 |
| `73ff5360c994` | Grok | grok-linux-server-20261107 | 5 | 2026-11-07 07:33 |
| `3615a21c3c4a` | Grok | grok-recovery-integration-20261107 | 5 | 2026-11-07 10:41 |
| `3e20980eda6d` | Grok | grok-threaddesk-server-sync-vserver-20261107 | 5 | 2026-11-07 12:59 |
| `ef2c3593b082` | Grok | win-parity-grok-20261106-impl-49758 | 12 | 2026-11-06 22:14 |
| `79d061062b72` | Grok-Review (Codex-Beobachtung) | grok-01a1ae81-0f50-72c0-a01d-e0b77e0ed295 | 1 | 2026-11-06 02:56 |
| `149056c87287` | Grok-Review (Codex-Beobachtung) | grok-01a1aea9-8f6f-7740-8fe0-2561eb1eb2f0 | 1 | 2026-11-06 02:55 |
| `68b89273f315` | Grok-Routerreview | grok-windows-evidence-review-20261105-v1 | 7 | 2026-11-05 22:48 |

## 4. Status-Vorschläge für Brainstorming- und Ideenthreads

Statuswerte nach 9 („übernommen / vorgemerkt / verlinkt“) und 9.4 Nr. 9 („Kandidat für
reversiblen Papierkorb nach vollständiger Einarbeitung“). Fundstellen beziehen sich auf
den Gesamtplan, E-Nummern auf 9.9 in PR #94.

| Thread | Vorschlag | Fundstelle im Big Plan | Begründung |
|---|---|---|---|
| `1deb9d17dd28` Brainstorming Werkzeugfamilie | **übernommen** | G1–G4 (9.3); 9.4 Nr. 8–11; BP-TD-GRAPH-01, -KONSOL-01, -ARCHIV-01, BP-AA-02 (9.5); Rest in 9.6; E1 | Ursprung von `450d3dc1c6d2` und Träger des Nutzerzeugnisses. Ein Destillat-Zielthread existiert noch nicht. **Kein** Papierkorb-Kandidat. |
| `450d3dc1c6d2` Wissensgraph und Konsolidierung | **übernommen** | 9.4 Nr. 8–10; 9.5; E5 | Aktueller Thread. Die Wiedereinstiegsnotiz („Claudes Ergebnis noch nicht bekannt“) ist überholt, denn PR #93 ist gemergt (`f706031`). Behalten. |
| `455dad75c60f` OpenAI-Zulassung (paused) | **übernommen** | 9.4 Nr. 5; BP-OPENAI-99 | Die sechs Punkte stehen inhaltsgleich im Plan. Der Thread selbst sagt: „eigenständige Recherche bleibt bestehen“. Behalten. |
| `c9a396be4081` CLI-Matrix | **übernommen** | 9.1; 9.4 Nr. 2; BP-CLI-02, BP-COORD-02; E2 | Lebende Fachmatrix. Behalten. |
| `a17c937b7553` Produkt-Icons | **übernommen** | 9.4 Nr. 4; BP-LAUNCHER-01 | Hält Icon-Herkunft und SHA-256. Behalten. |
| `597fd5fcb040` Sichtbarkeit/Community | **verlinkt** | 9.1 (Nachsatz); 9.6 | Eigener Beschluss vom 07.11.; bleibt laut Plan dort. |
| `30e962aaed81` Ocean | **verlinkt** | 1 und 3.4; `docs/plans/OCEAN-MCP-ADAPTER-20261105.md` | Recherchebericht mit Bibliotheks-Hash. Bleibt Quelle. |
| `6b5b73b9de36` Gesamtplan 20.10. (archiviert) | **verlinkt** (historisch) | nicht namentlich genannt | Originaltext mit SHA-256, über Beschreibung und Notizen verteilt. Nicht in den Papierkorb, solange BP-TD-ARCHIV-01 kein verifiziertes Archiv bietet. |
| `fdc7959f7dec` Bibliothek → ThreadDesk 23.10. | **verlinkt**, nicht eingearbeitet | kein Treffer | **Elternthread von 9 Threads.** Dieser Cluster fehlt in 9.1. Offen: B1, B2, C1, C2, E1. D1 („Testthreads archivieren“) ist erledigt, denn die drei synthetischen Threads sind archiviert. Strukturknoten, kein Papierkorb. |
| `f014aeed7384` Bibliotheksimport, Masterübersicht 26.10. | **verlinkt**, nicht eingearbeitet | kein Treffer | Offene Prüfpunkte: tatsächlich importierte Dateien mit haltbarem Receipt, Hash-Dubletten, neuester Masterstand. Der Big Plan hat keine Position für den Bibliotheksimport. |
| `c6b016d836d3` Ideen, Medien & weitere Projekte | **vorgemerkt** (Vorschlag) | kein Treffer („Forgejo“: 0) | Brainstorming vom 24.10.: Forgejo auf dem Debian-Server als zusätzliche Git-Sicherung. Vorschlag: in 9.6 aufnehmen. Bis dahin behalten. |
| `234b5f3544ad` Isolierter Praxistest | **Kandidat** für reversiblen Papierkorb, **nach Prüfung** | kein Treffer | Test mit erfundenen Angaben. Die Notizen enthalten aber eine echte Beobachtung zu RC40: Der Terminal-Schließdialog bleibt offen, während `session.close` `closed: true` meldet. Erst prüfen, ob das anderswo erfasst ist. |
| `67f9698601df`, `4de1f7c607ec`, `a39d1e7e1a9a` (synthetisch, archiviert) | **Kandidat** für reversiblen Papierkorb | 9.1 nennt die synthetische Relation | `67f9698601df` besitzt alle 3 Knoten und die einzige Relation. Der Papierkorb nimmt sie als Referenzen mit, der Graph hätte danach keine gespeicherten Knoten mehr. `4de1…` und `a39d…` werden von je einem `issued-handoff` referenziert. |
| `b87de46d2b54` Schnittstellenprobe | **Kandidat** nach Prüfung | kein Treffer | Testboard mit 5 Einträgen. `1b7530de7c5f` verweist im Text darauf. |

Kein einziger Brainstorming-Thread ist heute „vollständig eingearbeitet“ im Sinn von
9.4 Nr. 9. Dafür fehlt ein Zielthread oder Destillat in ThreadDesk, das die Inhalte mit
Herkunft trägt. Bis dahin sind nur die synthetischen und Test-Threads Kandidaten.

### 4.1 Offene Fragen, die erhalten bleiben müssen

1. **Statusmodell:** `450d3dc1c6d2` unterscheidet „neu/verknüpft, geprüft, übernommen,
   archiviert“, der Big Plan „übernommen, vorgemerkt, verlinkt, archiviert“. „Geprüft“
   fehlt im Plan. Welche Liste gilt für den späteren Knotenstatus?
2. **Bibliotheksimport** (`fdc7959f7dec`, `f014aeed7384`): Welche Dateien sind mit
   Receipt importiert, welche sind per Hash identisch, was ist der neueste Masterstand?
   Gehört das als Paket in den Big Plan?
3. **Vollständige ThreadDesk-Bedienung über KiraBridge** (TO-DO 28.10. in
   `482f593429ad`, Abnahmeziel in ThreadDesk `AGENTS.md`): Im Big Plan steht dazu keine
   Position. Am nächsten liegt BP-TD-AGENT-01.
4. **Flugschreiber, Mehrnutzer, Vermarktung** (`1deb9d17dd28`): Datenumfang,
   Aufbewahrung, Datenschutz und Performance sind laut 9.6 offen.
5. **Nutzerzeugnis:** vor externer Nutzung mit dem Funktionsumfang abgleichen und
   Einwilligung einholen (9.6).
6. **Forgejo** (`c6b016d836d3`): Serveraufwand, Sicherheit, Backups, Runner sind ungeklärt.
7. **Berichtsthreads:** Sollen sie per `parent_thread_id` unter `3e706958488c` hängen,
   statt nur per Text-ID gesammelt zu werden? Das wäre ein Schreibvorgang und braucht
   eine Freigabe.

### 4.2 Abgleich mit Big Plan 9.1

- 9.1 nennt nur `related_thread_ids` und Text-IDs. **Die 9 `parent_thread_id`-Kanten
  fehlen.** `138fb6baeff2`, `911bb6f922e2`, `a6fe31f58501`, `c6b016d836d3`, `d2b41e5dad06`,
  `dc200bb01137`, `eb4870dda203`, `ecd8609518c1` und `f014aeed7384` hängen alle unter
  `fdc7959f7dec`. Dazu kommen `f014aeed7384 → c6b016d836d3, a6fe31f58501`
  (`related_thread_ids`). E5 schließt `parent_thread_id` bereits ein.
- Die Angaben zu den `related_thread_ids` der Threads `450d…`, `1deb…`, `482f…`, `c2d4…`
  stimmen. „Keine echten Graphkanten außer der synthetischen Relation vom 18.10.“ stimmt.

## 5. Graph-Vorarbeit für BP-TD-GRAPH-01

### 5.1 Abgeleitete Kanten (24)

Richtung wie gespeichert: Quelle → Ziel. „WB“ heißt, der Thread ist ein Whiteboard und
damit heute als Knoten `wb-<id>` im Graphen sichtbar.

| Quelle | Ziel | Feld | Gegenrichtung | Quelle WB | Ziel WB |
|---|---|---|---|---|---|
| `138fb6baeff2` | `fdc7959f7dec` | parent_thread_id | nein | nein | nein |
| `1deb9d17dd28` | `482f593429ad` | related_thread_ids | nein | nein | ja |
| `1deb9d17dd28` | `c2d4c7bc985a` | related_thread_ids | nein | nein | ja |
| `1deb9d17dd28` | `188ce4729a62` | related_thread_ids | nein | nein | ja |
| `1deb9d17dd28` | `a6fe31f58501` | related_thread_ids | nein | nein | nein |
| `450d3dc1c6d2` | `1deb9d17dd28` | related_thread_ids | nein | ja | nein |
| `450d3dc1c6d2` | `188ce4729a62` | related_thread_ids | nein | ja | ja |
| `450d3dc1c6d2` | `482f593429ad` | related_thread_ids | nein | ja | ja |
| `450d3dc1c6d2` | `a6fe31f58501` | related_thread_ids | nein | ja | nein |
| `450d3dc1c6d2` | `c2d4c7bc985a` | related_thread_ids | nein | ja | ja |
| `482f593429ad` | `188ce4729a62` | related_thread_ids | nein | ja | ja |
| `482f593429ad` | `c2d4c7bc985a` | related_thread_ids | ja | ja | ja |
| `911bb6f922e2` | `fdc7959f7dec` | parent_thread_id | nein | nein | nein |
| `a6fe31f58501` | `fdc7959f7dec` | parent_thread_id | nein | nein | nein |
| `c2d4c7bc985a` | `188ce4729a62` | related_thread_ids | nein | ja | ja |
| `c2d4c7bc985a` | `482f593429ad` | related_thread_ids | ja | ja | ja |
| `c6b016d836d3` | `fdc7959f7dec` | parent_thread_id | nein | nein | nein |
| `d2b41e5dad06` | `fdc7959f7dec` | parent_thread_id | nein | nein | nein |
| `dc200bb01137` | `fdc7959f7dec` | parent_thread_id | nein | nein | nein |
| `eb4870dda203` | `fdc7959f7dec` | parent_thread_id | nein | nein | nein |
| `ecd8609518c1` | `fdc7959f7dec` | parent_thread_id | nein | nein | nein |
| `f014aeed7384` | `c6b016d836d3` | related_thread_ids | nein | ja | nein |
| `f014aeed7384` | `a6fe31f58501` | related_thread_ids | nein | ja | nein |
| `f014aeed7384` | `fdc7959f7dec` | parent_thread_id | nein | ja | nein |

Alle Ziele existieren. Es gibt keine Zyklen über `parent_thread_id`. Nur **7 von 24**
Kanten verbinden zwei Whiteboards. Die anderen 17 berühren mindestens einen der
10 Threads ohne Whiteboard, und solche Threads sind heute **kein Graphknoten**. Betroffen
sind `1deb9d17dd28`, `fdc7959f7dec`, `a6fe31f58501`, `c6b016d836d3`, `d2b41e5dad06`,
`ecd8609518c1`, `eb4870dda203` und die drei Produktthreads.

### 5.2 Wo der Graph heute Kanten liest (`threaddesk` `origin/main` `e7cec44`)

- `ThreadDeskService.graph()` in `src/threaddesk/api/service.py` (ab Z. 288) baut den
  Basisgraphen. Knoten sind `store.list_nodes()`, die Whiteboard-Projektion
  `WhiteboardService.graph_nodes()` (`wb-<thread_id>`, nur für Whiteboards) und die
  sichtbaren Bibliotheksknoten. Kanten sind `store.list_relations()`,
  `library_relations()` (abgeleitet, `metadata.derived = True`, `source = "library"`)
  und `WhiteboardService.graph_relations()` (`wb-rel-…`, `references` zu Knoten mit
  gleichem `metadata.thread_id`).
- `GraphReadService.query()` in `src/threaddesk/services/graph_read.py` filtert diesen
  Basisgraphen (Text, Art, Status, Projekt, Nachbarschaft `center`/`hops` über alle
  Relationen) und liefert `threaddesk.graph.v2`. Kanten werden nur ausgegeben, wenn beide
  Enden auf der Seite sind. UI: `GET/POST /api/graph/v2` (`ui/command_router.py`),
  Altweg `GET /api/graph` (`ui/server.py`).
- Darstellung in `src/threaddesk/ui/static/map.js` (Z. 303 ff.). Der Stil kommt aus
  `EDGE[relation.kind]` (`map-shapes.js`, Z. 25). `related_to` ist schon gestrichelt
  (`3 7`). Der Tooltip zeigt nur `relation.kind`, `metadata` wird nicht gelesen.
- `related_thread_ids` und `parent_thread_id` werden nur in `thread_management.py`
  (schreiben und validieren, mit Zyklusprüfung für Eltern), `mcp.py` (Schema) und
  `trash.py` (Z. 161, als Referenzen beim Papierkorb) verwendet. **Der Graph liest sie
  nicht.** Das bestätigt den Stand in E5.
- Änderungserkennung: `GraphChangeService` (`graph_changes.py`) beobachtet unter anderem
  das Verzeichnis `threads/`. Ob eine reine Organisationsänderung (atomarer Ersatz der
  Thread-Datei) dort sicher eine neue Kennung erzeugt, ist zu prüfen.

### 5.3 Was minimal nötig wäre (nur beschrieben, nicht gebaut)

1. **Kantenprojektion:** neue Funktion, etwa `thread_organization_relations(store, nodes)`,
   nach dem Muster von `library_relations`. Sie liest `context.extra.organization` aller
   nicht im Papierkorb liegenden Threads, auch archivierter. Sie erzeugt Kanten nur, wenn
   beide Enden als Knoten sichtbar sind:
   - `related_thread_ids` → `kind="related_to"`;
   - `parent_thread_id` → `kind="contains"` (Eltern → Kind);
   - `source="threaddesk.organization"`, `metadata={"derived": True, "projection":
     "thread_organization", "field": …}`, stabile ID per Hash über Feld, Quelle und Ziel
     (wie `library_relations`), Zeitstempel und Revision vom Quellthread.

   Aufruf in `ThreadDeskService.graph()` nach `boards.graph_relations(nodes)`. Gegenseitige
   `related`-Paare (`482f…` ↔ `c2d4…`) zu einer Kante zusammenfassen oder beide behalten:
   Das ist zu entscheiden.
2. **Thread-Endpunkte:** Ohne Zusatz erscheinen nur 7 Kanten. Damit `1deb9d17dd28` und
   der Cluster unter `fdc7959f7dec` sichtbar werden, braucht es eine schlanke, rein lesende
   Knotenprojektion für Threads ohne Whiteboard, z. B. `td-<thread_id>`. Ein neuer
   Eintrag in `NODE_KINDS` ist nicht zwingend: `document` oder `source` mit
   `metadata.projection="thread"` reicht. Alternative: Kanten nur auf vorhandene `wb-<id>`
   abbilden und den Rest bewusst weglassen. Dann fehlt aber der Brainstorming-Ursprung
   des Big Plans. Die Projektion braucht die gleiche Kollisionsprüfung wie
   `WhiteboardService.graph_nodes()`.
3. **Kennzeichnung in der Ansicht** (E5): In `map.js` bei `relation.metadata?.derived` eine
   eigene Klasse setzen, etwa `map-edge-derived`, und den Tooltip auf „abgeleitet ·
   related_thread_ids“ bzw. „… · parent_thread_id“ ändern. Dazu kommt ein i18n-Schlüssel.
   Das gilt dann auch für die heute schon abgeleiteten Bibliothekskanten.
4. **Abgrenzung:** Abgeleitete Kanten sind nicht speicherbar, löschbar oder
   wiederherstellbar. Papierkorb, Relationen-Endpunkte (`ThreadDeskService.relations()`
   liest nur `store.list_relations()`) und `GraphChangeService` dürfen sie nicht als
   gespeicherte Relationen behandeln. Die Graphregel aus ThreadDesk `AGENTS.md` bleibt:
   Graphöffnung ist keine Dateiaktivität.
5. **Tests:** Projektion für related, parent, archiviert, Papierkorb (Kante verschwindet,
   nach Wiederherstellung wieder da), fehlendes Ziel, Knotenfilter (`center`/`hops` nutzt
   abgeleitete Kanten), Kennzeichnung im JSON, keine Schreibzugriffe beim Lesen.

Mit diesem Bestand ergäben 1 + 2 + 3 zusammen 24 abgeleitete Kanten, 10 zusätzliche
Thread-Knoten und die bisherigen 3 + 1 synthetischen Elemente. Ob Kanten später echte
Relationen werden, bleibt nach E5 offen. Dieses Inventar schreibt dafür nichts um.

## 6. Nebenbefunde

1. **KiraBridge-MCP:** Während des Laufs verschwanden die `td_*`-Werkzeuge für
   `claude` (`threaddesk_tool_denied`, `tools/list` 111 → 77). Vorher gab es kurz
   `peer_connection`. Nicht untersucht, nichts geändert. Das sollte geklärt sein, bevor
   BP-TD-KONSOL-01 über MCP schreibt.
2. **Wachsende Berichtsthreads:** `3e706958488c` (8 364 Einträge, Akteur „Big Plan
   Reports“, Inhalt „Vorschau gekürzt…“), `62e09d54117c` (3 867, Codex Loop) und
   `26b749296cff` (2 588, Grok) bekommen auch um 22:33 UTC laufend `progress`-Einträge.
   Zwischen 17:00 und 22:33 UTC kamen bei `3e70…` rund 540 dazu, etwa alle 36 Sekunden
   einer. Whiteboards sind append-only. Ein Prüfauftrag zu Takt und Dedup ist sinnvoll,
   bevor der Graph Eintragszahlen anzeigt.
3. **Archivierter Plan als Whiteboard:** `6b5b73b9de36` ist archiviert, hat aber 1 Eintrag
   und erscheint deshalb als `wb-`Knoten mit Status `archived`.
4. **Leere Produktbereiche:** `c6b016d836d3`, `ecd8609518c1`, `eb4870dda203` und
   `346577d6367e` tragen Inhalt nur in der Beschreibung. Das ist kein Fehler, aber im
   Graphen fehlen dann Details.

## 7. Vorgeschlagene nächste Schritte (jeweils eigene Freigabe)

1. Nutzer oder Kira bestätigen die Status in Abschnitt 4 und entscheiden die offenen
   Fragen in 4.1.
2. Destillat-Zielthread oder -dokument mit Herkunft anlegen. Erst danach kann ein
   Brainstorming „vollständig eingearbeitet“ sein.
3. Konzept für BP-TD-ARCHIV-01 vor dem ersten Verschieben.
4. BP-TD-GRAPH-01 nach 5.3: zuerst Schritte 1 und 3, dann 2.
5. Nur mit Freigabe: synthetische Threads in den reversiblen Papierkorb, vorher Graph-
   und Handoff-Referenzen festhalten.
