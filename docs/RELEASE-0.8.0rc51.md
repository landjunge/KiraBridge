# KiraBridge 0.8.0 RC51

macOS-Kandidat nach RC50 (`394cb3b`). Dokumentierter Quellstand ist `main`
`86a730d`. Schwerpunkt: Teamturns ohne Terminal, automatische
Koordinator-Fortsetzung und benannte Fehler statt stiller Misserfolge.

Neu gegenüber RC50:

- Codex-Teamturns ohne Terminal. Ein Worker mit
  `execution_scope = "existing_native_codex_root"` startet `NativeCodexTurns`
  über den App-Server (`turn/start`). Keine Fenstereingabe, kein Einfügen,
  kein Bildschirmlesen. Verwendet wird genau ein geladener, elternloser,
  untätiger Root-Thread, dessen aufgelöstes cwd dem Worker-cwd entspricht.
  Die Antwort steht im Turn-Protokoll (`reply_source = native_codex_app_server`,
  `terminal_input_attempted = false`).
- Automatische Koordinator-Fortsetzung. Ist `team.coordinator_resume` an,
  schreibt der Abschluss delegierter Arbeit eine Completion-Meldung der Quelle
  `team`. `resume_coordinators` legt daraus genau einen idempotenten
  Koordinationsauftrag für einen Auftraggeber mit gesetztem `agent` an. Die
  Option ist standardmäßig aus. Ein Auftrag an sich selbst erzeugt keine
  Meldung.
- Zurückgegebener Misserfolg. `normalize_failure` macht aus `success: false`
  ein Fehlerobjekt `{code, kind, retry_safe}` und bei ganzzahligem Exitcode
  zusätzlich `exit_code`. `retry_safe` gilt nur für einen Peer-Fehler, dessen
  `evidence.request_sent` falsch ist. Neustart und Abbruch des Dispatchers
  tragen eigene Codes: `dispatcher_restart` und `dispatcher_shutdown`.
- Ehrliche Auswahlfehler. Ein gekürzter Terminalkatalog ergibt
  `session_catalog_incomplete` mit
  `provider_error.reason = catalog_truncated`. Ein vollständiger Katalog, der
  das Pane nicht mehr trifft, ergibt `session_selection_changed` mit
  `provider_error.reason` `expected_pid_changed`, `window_changed` oder
  `pane_missing`.
- Terminalsperre. Ein sicherer Abbruch, bevor die native Einfügung etwas
  sendet, endet als `interrupted` mit `preinput_abort` und nicht als
  sperrenhaltendes `unknown`. Nach einer unbestätigten Antwort gibt ein
  frischer Bereit-Befund derselben Bindung die Eingabesperre frei
  (`input_reservation_released`,
  `target_readiness = verified_ready_before_new_input`). Die alte Eingabe
  wird nicht wiederholt.
- Grok. `agents.<name>.model` ist optional und wird als `--model` übergeben.
  `grok_reasoning_effort` gilt nur bei `kind = grok_acp`, Muster
  `^[a-z]{1,16}$`, und wird als `--reasoning-effort` übergeben. Die
  ACP-Schicht ignoriert ausschließlich die unaufgeforderte Antwort-ID
  `skills-reload` ohne Turn-Inhalt; der Quellkommentar nennt dafür die
  Grok-CLI 1.0.89. Jede andere fremde ID bleibt `agent_identity`.
- Begrenzte Fehlerursache. Gemini und Copilot hängen
  `provider_error.diagnostic` nur an nicht-leeres, bereinigtes stderr,
  höchstens 200 Zeichen, nie an stdout. `opencode_http` und
  `opencode_http_v2` setzen bei Statusfehlern nur
  `provider_error.http_status` und übernehmen keinen Antwortkörper.
- Doku auf Deutsch und Englisch in `README.md`, `README.de.md`,
  `docs/TEAM-ORCHESTRATION.md` und `docs/NATIVE-CODEX-BINDING.md`. Diese
  Notiz ist ebenfalls zweisprachig.

Tests: Der übergebene Gesamtlauf vor den sechs Härtungs-Tests in `158cd80`
ist 6285 bestanden, 0 fehlgeschlagen, 120 übersprungen. CI von PR #208
(verify auf Python 3.11 und 3.13) wurde als grün übergeben. Dieser
Vorbereitungs-Commit hat den Gesamtlauf nicht erneut ausgeführt.

Bekannte Grenzen: Der native Codex-Pfad braucht genau einen geladenen
Codex-Root im cwd des Workers. Gemini bricht ohne vorhandene Google-Anmeldung
oder gesetzten API-Schlüssel mit `agent_auth_required` ab. Eine eigene
Anmeldeprüfung für die Copilot-CLI steht in diesem Adapter nicht; ob die
CLI selbst eine Anmeldung verlangt, ist hier nicht als Codepfad belegt.
`opencode_http` lehnt HTTP-4xx ab (401/403 als `agent_auth`, 404 als
`session_unknown`, andere 4xx als `agent_rejected`); eine konkrete
Umgebungsursache für ein lebendes 4xx ist offen. Installation und
Live-Abnahme auf macOS stehen aus. Keine Veröffentlichung und keine
Installation wird behauptet.

---

# KiraBridge 0.8.0 RC51 (EN)

macOS candidate after RC50 (`394cb3b`). The documented source is `main`
`86a730d`. Focus: team turns without a terminal, automatic coordinator
resume, and named failures instead of silent ones.

Changes since RC50:

- Codex team turns without a terminal. A worker with
  `execution_scope = "existing_native_codex_root"` starts `NativeCodexTurns`
  through the app server (`turn/start`). There is no window input, paste, or
  screen reading. The path uses exactly one loaded, parentless, idle root
  thread whose resolved cwd equals the worker cwd. The answer comes from the
  turn record (`reply_source = native_codex_app_server`,
  `terminal_input_attempted = false`).
- Automatic coordinator resume. When `team.coordinator_resume` is on, the
  finish of delegated work records one completion notice with source `team`.
  `resume_coordinators` creates exactly one idempotent coordination task for
  an assigner that has `agent` set. The option defaults to off. Work assigned
  to its own assignee records no notice.
- Returned failure. `normalize_failure` turns `success: false` into an error
  object `{code, kind, retry_safe}`, plus `exit_code` when the exit code is
  an integer. `retry_safe` is true only for a peer error whose
  `evidence.request_sent` is false. Dispatcher restart and shutdown carry
  their own codes: `dispatcher_restart` and `dispatcher_shutdown`.
- Honest selection errors. A short terminal catalog raises
  `session_catalog_incomplete` with
  `provider_error.reason = catalog_truncated`. A complete catalog that no
  longer matches the pane raises `session_selection_changed` with
  `provider_error.reason` `expected_pid_changed`, `window_changed`, or
  `pane_missing`.
- Terminal lock. A safe abort before the native insert sends anything ends
  as `interrupted` with `preinput_abort`, not as a lock-holding `unknown`.
  After an unconfirmed reply, a fresh ready check of the same binding
  releases the input lock (`input_reservation_released`,
  `target_readiness = verified_ready_before_new_input`). The old input is
  not sent again.
- Grok. `agents.<name>.model` is optional and is passed as `--model`.
  `grok_reasoning_effort` is accepted only for `kind = grok_acp`, pattern
  `^[a-z]{1,16}$`, and is passed as `--reasoning-effort`. The ACP layer
  ignores only the unsolicited response id `skills-reload` that carries no
  turn content; the source comment names Grok CLI 1.0.89 for that notice.
  Every other stray id stays `agent_identity`.
- Bounded failure cause. Gemini and Copilot attach
  `provider_error.diagnostic` only from non-empty sanitized stderr, at most
  200 characters, never from stdout. `opencode_http` and `opencode_http_v2`
  set only `provider_error.http_status` on status failures and do not copy
  the response body.
- Documentation in German and English in `README.md`, `README.de.md`,
  `docs/TEAM-ORCHESTRATION.md`, and `docs/NATIVE-CODEX-BINDING.md`. These
  notes are bilingual as well.

Tests: The supplied full run before the six hardening tests in `158cd80` is
6285 passed, 0 failed, 120 skipped. CI for PR #208 (verify on Python 3.11
and 3.13) was supplied as green. This preparation commit did not re-run
that full suite.

Known limits: The native Codex path needs exactly one loaded Codex root in
the worker cwd. Gemini fails with `agent_auth_required` unless an existing
Google login or the configured API key is present. This Copilot adapter has
no login check of its own; whether the CLI itself requires a login is not
shown as a code path here. `opencode_http` rejects HTTP 4xx (401/403 as
`agent_auth`, 404 as `session_unknown`, other 4xx as `agent_rejected`); a
concrete environmental cause for a live 4xx remains open. Installation and
live acceptance on macOS are still outstanding. No publication and no
installation is claimed.
