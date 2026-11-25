# KiraBridge 0.8.0 RC49

macOS-Kandidat nach RC48 (`48c6351`). Schwerpunkt: Zuverlässigkeit der sichtbaren
CLI-Sitzungen (Start, Bindung, Eingabe, Return, Busy/Unknown, Antwortrückgabe).

Neu gegenüber RC48:

- [PR #153](https://github.com/landjunge/KiraBridge/pull/153): CLI-Start meldet Prozess-
  und Bindungszustand getrennt, prüft TTY/Prozessherkunft und erhält Unsicherheit ohne
  Replay. Gemeinsamer, sitzungsgebundener ACP-Client; Grok-ACP migriert; neuer,
  textgebundener OpenCode-ACP-Adapter (`opencode acp`) mit isoliertem Profil.
  Session-Open meldet Mehrdeutigkeiten explizit; Binding-Refresh abgesichert.
- [PR #154](https://github.com/landjunge/KiraBridge/pull/154): Der native Schutz zählt die
  eigenen Electron-Helper der Ziel-App (z. B. `OpenCode Helper`, `Helper (Renderer)`)
  nicht mehr als gehostete Agenten. Echte Agenten-CLIs, TTY-Kinder und unvollständige
  Beobachtungen blockieren weiterhin; Signal-/Identitäts-/AX-Guards bleiben unverändert.
- [PR #155](https://github.com/landjunge/KiraBridge/pull/155): Sichtbare Eingabe
  klassifiziert Leerheit an der Quelle. Shell-Prompts nach unfertiger Ausgabe werden über
  zshs `PROMPT_SP`-Marker korrekt als leer erkannt; Grok-Platzhalter (`Build anything`)
  gelten als leer, echte Entwürfe weiter als belegt, unbekannte Frames als `unknown`.
  Neuer OpenCode-Composer-Adapter; Return nach dem Paste wird über den beobachteten
  Leerzustand freigegeben. Behebt die wiederkehrenden Fehler aus #51 und #144.

Tests: Linux-Verify 3.11/3.13; native Swift-Fixture plus 146 native/desktop-nahe Tests;
fokussierte Sichtbar-/Sitzungs-/Adapter-Suiten mit 279 + 481 + 213 + 105 bestandenen
Tests; Ruff und Format grün. Die praktische macOS-Abnahme der Kette wird getrennt vom
Artefakt dokumentiert.

Bekannte Grenzen: OpenCode-Langtexte bleiben konservativ; ohne konfigurierte sichtbare
OpenCode-Bindung bleibt `visible_target_missing` ein Betreiber-Thema. Ein exakt als
`Build anything` getippter Grok-Text ist vom Platzhalter nicht unterscheidbar.

---

# KiraBridge 0.8.0 RC49 (EN)

macOS candidate after RC48 (`48c6351`). Focus: reliability of visible CLI sessions
(start, binding, input, Return, busy/unknown, answer return).

Changes since RC48:

- PR #153: CLI start reports process and binding state separately, verifies the launched
  TTY/process ancestry and preserves uncertainty without replay. Shared session-bound ACP
  client; Grok ACP migrated; new text-only OpenCode ACP adapter (`opencode acp`) with an
  isolated profile. Session open reports ambiguity explicitly; binding refresh hardened.
- PR #154: the native guard no longer treats the target app's own Electron helpers
  (`OpenCode Helper`, `Helper (Renderer)`) as hosted agents. Real agent CLIs, TTY children
  and incomplete observations still block; signal/identity/AX guards are unchanged.
- PR #155: visible-input emptiness is classified at the source. Shell prompts after
  unfinished output are recognised via zsh's `PROMPT_SP` marker; Grok placeholders
  (`Build anything`) count as empty, real drafts stay nonempty, unknown frames stay
  `unknown`. New OpenCode composer adapter; Return after paste is released by the observed
  empty state. Fixes the recurring #51/#144 failures.

Tests: Linux Verify 3.11/3.13; native Swift fixture plus 146 native/desktop-adjacent
tests; focused visible/session/adapter suites with 279 + 481 + 213 + 105 passing tests;
Ruff and format green. The practical macOS chain acceptance is documented separately
from the artifact.

Known limits: OpenCode long payloads stay conservative; without a configured visible
OpenCode binding, `visible_target_missing` remains an operator task. Grok text typed
exactly as `Build anything` is indistinguishable from the placeholder.
