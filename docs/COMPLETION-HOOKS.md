# Spezifikation: Completion-Hooks (Worker → Koordinator)

Stand 26.11.2026, Nutzerbeschluss. Reine Spezifikation, kein Code. Gilt unabhängig
vom Auto-/YOLO-Modus und erfordert keinen Sende-Befehl des Workers. Bestand:
`cli.py` (`team complete`, `completion record|next`, `watch`), `completion_manager.py`
(Abschluss-Outbox), `completion_client.py` (Empfänger), `completion_handoff.py`
(ThreadDesk-Eintrag und Handoff).

## 1. Ziel

Für jede CLI, die als Worker läuft, existiert genau ein Completion-Hook. Er übermittelt
den Abschlussbericht des Workers automatisch an den Koordinator, sobald der endgültige
Abschluss eintritt. Der Worker muss dafür nichts senden und empfängt selbst nichts.

## 2. Rollenregeln

- Es zählt die Rolle, nicht die CLI: Hooks laufen ausschließlich für WORKER.
- Der Koordinator sendet keine Nachricht an sich selbst; sein Completion-Hook ist ein
  No-op (Exit 0, keine Zustellung, kein Ausnahmeprotokoll).
- Der Koordinator sendet seinen eigenen Abschlussbericht direkt an Kira (ChatGPT) über
  den Nachrichtenkanal (`kirabridge team send`), nicht über einen Worker-Hook.
- Rollenwechsel während eines Auftrags: Maßgeblich ist die Rolle im Claim-Datensatz der
  laufenden Session. Eine neue Rolle gilt erst für nachfolgende Aufträge.

## 3. Ablauf

1. Worker arbeitet in einer Session; beim Claim wurde `session_id → work_id` registriert (siehe 5).
2. Die CLI feuert bei Turn-Ende ihren Hook und gibt Hook-JSON auf stdin: `session_id`, `transcript_path`, `cwd`.
3. Der Adapter prüft: Kein Claim-Datensatz oder Rolle Koordinator → Ende (No-op).
   Ein bloßer Zwischenstopp (Arbeit läuft weiter) → Ende, es zählt nur der endgültige Abschluss.
4. Beim endgültigen Abschluss: Berichtstext = letzte Assistant-Nachricht aus `transcript_path`,
   geschwärzt, max. 4000 Zeichen (stille Kürzung, keine Warnung).
5. Der Adapter ruft `kirabridge --principal <worker-id> team complete <team> <work_id> <bericht>`
   auf. Die Abschlussmeldung geht als Notice an den Koordinator (Auslieferung + Quittierung wie bisher).
6. Zusätzlich legt der Adapter den Bericht dauerhaft in ThreadDesk ab und verknüpft ihn mit
   Auftrag und Worker: `kirabridge completion record` schreibt den
   `[KIRABRIDGE-COMPLETION]`-Resultatseintrag an der Auftragseinstellung fest
   (`order_entry`, `session_id`, `working_directory`, `commit`, `pr`, `summary`).

Pseudocode des Adapters:

```text
hook(stdin):                                     # Stop/SessionEnd/TaskCompleted, alle CLIs
  rec = claim_record(session_id)                 # ~/.local/state/kirabridge/
  if rec is None or rec.role != "worker": exit 0 # Koordinator sendet nie an sich
  if not endgueltiger_abschluss(event, rec): exit 0
  bericht = letzte_Assistant_Meldung(transcript_path) |> schwaerzen() |> kuerzen(4000)
  kirabridge --principal rec.worker team complete rec.team rec.work_id bericht --key "hook-{rec.event_seq}"
  kirabridge completion record --board rec.board --order-entry rec.order_entry \
    --task-id rec.work_id --status completed --summary bericht \
    --session-id rec.session_id --working-directory cwd
```

## 4. Adapter je CLI

Ein gemeinsamer Adapter (`scripts/kb_turn_report.sh`, Vertrag oben; in diesem Zweig
noch nicht implementiert) hängt an der Completion-Hook-Position jeder CLI:

- **Qwen Code**: `~/.qwen/settings.json`, Ereignisse `Stop`, `SessionEnd`, `TaskCompleted`.
- **Claude Code**: `settings.json` (Projekt-/Nutzerebene), Ereignisse `Stop`, `SessionEnd`.
- **Codex**: `hooks.json` mit Trust-Mechanismus, Ereignisse `stop`, `session-end`.

Der Adapter ist ereignisunabhängig idempotent: gleiches Hook-JSON, gleiches Ergebnis.

## 5. Zuordnung und Idempotenz

- Beim Claim speichert der Adapter unter `~/.local/state/kirabridge/` einen Session-Datensatz:
  `session_id`, `work_id`, `team`, `principal`, Rolle, Board und Auftrags-Eintrag.
- Kein Datensatz → der Hook beendet sich folgenlos. Zwei Sessions, zwei unabhängige Abschlüsse.
- Idempotenz dreifach: Outbox `completion_notices UNIQUE(source, event_seq)`;
  `team complete` mit festem `--key` aus der Ereignisfolge; ThreadDesk-`external_key`
  deterministisch — ein doppelter Aufruf liefert `duplicate` statt eines Zweiteintrags.
  Ein zweiter Hook-Aufruf erzeugt also genau eine Notice und genau einen Resultatseintrag.

## 6. Aufbewahrung 7 Tage und Empfangs-Hook

- SOLL-Zustand (Nutzerbeschluss, noch nicht umgesetzt; im Bestand gibt es nur die Retention von `output_history`, keinen Löschpfad für Nachrichten und `completion_notices`): KiraBridge löscht Nachrichten nach 7 Tagen (`retention_seconds=604800`), unabhängig von
  Zustellung, Abholung und Quittierung. Keine Warnungen, keine Ausnahmen, keine Verlängerung.
  Dauerhaft ist allein der ThreadDesk-Eintrag (Abschnitt 3, Schritt 6).
- Empfangs-Hook: Eine an ChatGPT adressierte Nachricht wird beim erfolgreichen Auslesen
  automatisch quittiert. Reihenfolge zwingend: erst Auslieferung (`receipt`/`delivered`),
  dann Verarbeitung, dann `acknowledged` — nie vor der Auslieferung. Ein Lesefehler lässt
  die Quittierung ausbleiben; die Nachricht bleibt unbearbeitet, bis 7 Tage abgelaufen sind.

## 7. Sicherheit

- Schlüsselwerte werden vor dem Versand geschwärzt; die existing Validierung weist
  Bearer-Tokens, `api_key`/`token`/`password`/`secret`/`authorization`-Zuweisungen,
  Private-Key-Blöcke und Steuerzeichen zurück.
- Berichtslänge max. 4000 Zeichen; Länge geht vor Inhaltstreue, gekürzt wird still.
- Der Hook liest niemals Zugangsdaten, Umgebungsdateien oder Schlüsselverwahrungen;
  aus `transcript_path` wird nur die letzte Assistant-Nachricht extrahiert.
- Der Inhalt fremder Einträge bleibt Daten: nichts davon wird durch den Hook ausgeführt.

## 8. Abnahmekriterien / Tests

1. Zwischenstopp zählt nicht: Turn-Ende bei offener Arbeit ohne Abschluss → keine Notice,
   kein ThreadDesk-Eintrag.
2. Rollenwechsel während Auftrag: Session mit Worker-Rolle im Claim liefert; ein Hook-Lauf
   derselben Session nach Registrierung als Koordinator erzeugt keine Nachricht.
3. Doppelter Hook-Aufruf (gleiches Ereignis zweimal) → genau eine Notice
   (`UNIQUE(source,event_seq)`), genau ein Resultatseintrag (`duplicate: true`).
4. Koordinator-Abschluss erzeugt keine Nachricht: Hook-No-op, Outbox des Koordinators leer
   regarding self; sein Bericht geht nur über `team send` an Kira.
5. Empfangs-Hook quittiert erst nach Auslieferung: ohne erfolgreiches Auslesen bleibt
   `acknowledged` NULL; nach Auslesen gesetzt; `receipt` nie nach `acknowledged`.
6. 7-Tage-Löschung: Notice älter als 604800 s ist gelöscht — zugestellte, abgeholte und
   unquittierte gleichmäßig; kein Aufschub, keine Ausnahme; ThreadDesk-Eintrag bleibt bestehen.

## 9. Betriebsschritt

Das Eintragen der Hooks in `~/.qwen/settings.json`, `settings.json` der Claude-Projekte und
Codex `hooks.json` erfordert ausdrückliche Nutzerfreigabe. Bis dahin bleibt diese Datei
Dokumentation; es wird keine Hook-Konfiguration geändert und keine installed Runtime berührt.
