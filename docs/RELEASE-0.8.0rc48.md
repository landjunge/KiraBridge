# KiraBridge 0.8.0 RC48

macOS-Kandidat nach RC47 (`eddf88e`).

Neu gegenüber RC47:

- [PR #147](https://github.com/landjunge/KiraBridge/pull/147): Sichtbare Eingabe an
  die Grok-CLI wiederhergestellt, wenn der Kasten keinen erkannten Titelrand hat.
  Ein unlesbarer Kasten ist kein Beleg; die exakte Beobachtung nach dem Paste
  entscheidet weiter. Der Fokusaufbau erhält acht begrenzte Versuche innerhalb
  des bestehenden 30-Sekunden-Mutationsbudgets. Behebt die Regression aus
  RC47/PR 143 (71 Handoff-Tests und ein Lint-Fehler auf `main`).
- [PR #146](https://github.com/landjunge/KiraBridge/pull/146): `live_logs` /
  `logs.live` – begrenzte Live-Logs und Status für jede von KiraBridge
  gestartete CLI und jeden Agenten. Je Task eine Quelle mit stdout, stderr und
  Adapter-Events, Cursor-Lesen, expliziten Drop-Zählern; streng
  principal-getrennt, reine Beobachtung ohne Anhängen, Wiederholen oder Eingabe.
  `agent_status` enthält eine textfreie `live_logs`-Zusammenfassung.
- [PR #148](https://github.com/landjunge/KiraBridge/pull/148): Bremsen im direkten
  Übergabepfad entfernt, ohne Identität, Authentifizierung, Dedupe oder No-Replay
  zu ändern: Der Laufdeckel je Konversation gilt als rollierendes
  Ein-Stunden-Fenster statt lebenslang, der Stundendeckel zählt je Empfänger
  statt global, und die Standardwerte erlauben 16 Läufe bzw. 64 Nachrichten je
  Konversation.

Tests: vollständige macOS-Suite auf Intel `5446 passed, 89 skipped`
(ein umgebungsbedingter Fehlschlag durch gesetzte `KIRABRIDGE_*_TOKEN`-Variablen;
ohne diese Variablen grün). Linux-Verify 3.11 und 3.13 grün.

---

# KiraBridge 0.8.0 RC48 (EN)

macOS candidate after RC47 (`eddf88e`).

Changes since RC47:

- PR #147: visible input to the Grok CLI restored when the box title is not
  recognized. An unreadable box is not proof; the exact post-paste observation
  stays authoritative. Focus acquisition gets eight bounded attempts inside the
  existing 30-second mutation budget. Repairs the RC47/PR 143 regression
  (71 handover tests and one lint error on `main`).
- PR #146: `live_logs` / `logs.live` - bounded live logs and status for every
  CLI and agent run by KiraBridge. One source per task with stdout, stderr and
  adapter events, cursor reads and explicit drop counters; strictly
  principal-scoped, observation only (no attach, replay or input).
  `agent_status` includes a text-free `live_logs` summary.
- PR #148: removed avoidable brakes from the direct handover path without
  changing identity, authentication, dedupe or no-replay: the per-conversation
  run ceiling is a rolling one-hour window instead of a lifetime cap, the hourly
  ceiling is counted per recipient instead of globally, and the defaults allow
  16 runs / 64 messages per conversation.

Tests: full Intel macOS suite `5446 passed, 89 skipped` (one environment-induced
failure from exported `KIRABRIDGE_*_TOKEN` variables; green without them).
Linux Verify 3.11 and 3.13 green.
