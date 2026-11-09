# BP-AUTO-01 · AutoNext-Abnahme 09.11.2026

Paket BP-AUTO-01 aus dem [Bauplan](plans/BIGPLAN-BAUPLAN-20261108.md), Stufe 2, Nachträge N1–N4.
Nutzerfreigabe vom 09.11.2026: „Ja, mit 2 Testkarten“. RC43 ist installiert (`f9e6ec8`).

**Ergebnis: Teilabnahme.** Gestoppt vor dem ersten Modelllauf. Es wurden keine Testkarten
angelegt, nichts zugeordnet und kein Codex- oder Grok-Aufruf gestartet. AutoNext steht am Ende
weiter auf `disabled / not_started`.

## Warum gestoppt

Der vorhandene Weg ([Koordinatorloop](COORDINATOR-LOOP.md),
[Fortsetzung](COORDINATOR-CONTINUATION-20261106.md)) kennt nur diese Kette:
Codex-Hauptturn, optional Grok-Review, danach immer ein eigener `codex_verify`.
Vor jedem Grant liest er den Kontingentbeleg über Codex `account/rateLimits/read`.
Einen Claude-Worker gibt es in dieser Kette nicht.

- Laut N1 steht nur Claude zur Verfügung. Codex und Grok fallen als Autor und Prüfer aus.
  Eine Karte würde also mindestens zwei Codex-Turns brauchen. Das wäre improvisiert und
  wurde deshalb nicht gemacht.
- Unabhängig davon sind die Zugangsbelege im Routingprofil (`routing.runtime.access`) am
  07.11.2026 um 22:59 UTC abgelaufen. Der Router würde jeden gerouteten Turn mit
  „access evidence needs refresh“ ablehnen.

## Befund zum Weg

- Im Fortsetzungsmodus (das Profil enthält `continuation`) verwendet `advance()` die
  `cards` aus `bigplan-loop approve` nicht. Ausgeführt wird nur eine Karte, die mit
  `bigplan-loop adopt` zugeordnet ist. Ihre CWD muss in `continuation.allowed_cwds` stehen,
  ihre Prüfbefehle müssen wörtlich in `continuation.checks` stehen.
- Beide Felder gehören zum festen Profilumfang. Wer sie ändert, beendet den Dienst
  (`Profile scope changed; explicit restart required`). Danach ist ein Kickstart des eigenen
  Labels nötig.
- Der Testbereich vom 05.11. (`coordinator-loop-taskspace-final-20261105`) ist zwar die
  Profil-CWD, steht aber nicht in `allowed_cwds`.
- Der Launcher `~/.local/bin/bigplan-loop` läuft aus dem Worktree
  `grok-windows-supervisor-20261107` (`0e22343`), nicht aus der RC43-Installation.

## Belegt

| Abnahmepunkt | Stand | Beleg |
|---|---|---|
| Leerer Katalog startet nichts | **erfüllt** | Profil `enabled=true`, keine zugeordnete READY-Karte. Status zeigt `autonext disabled/not_started`, `grant_id=null`, `selected_task=null`, `resource_stop=null`. Der neue Prozess hat keine Kindprozesse. Im Leerlauf gibt es keine Kontingentabfrage, denn `quota` läuft nur bei einer ausgewählten Aufgabe. |
| Neustart ohne Replay | **erfüllt für den Bestand** | Kickstart von `de.threaddesk.bigplan-coordinator` am 09.11. um 16:57:38 CET: PID 83004 → 61306, Exit-Code 0. Der lesende Zustandsabzug (`autonext_items`, `autonext_runs`, `team_work`, Grant-Caches, `process-output`) ist vorher und nach rund 90 s identisch (SHA256 `b12edddf…`). Das Profil ist unverändert (`12fd9ed3…`), die Quellrevision ebenfalls (`8ec41d66…`). Es bleibt bei 29 gehaltenen Karten mit denselben Gründen und ohne neuen Eintrag in `stderr.log`. |
| Unklare Wirkung nicht wiederholt | **erfüllt für den Bestand** | 5 UNKNOWN-TeamWorks bleiben UNKNOWN. 6 gestoppte Fortsetzungsgrants werden nicht wiederhergestellt, weil `restore()` nur Läufe übernimmt, die weder `complete` noch `stopped` sind. |
| Nicht freigegebene Karte bleibt unberührt | **nur Ersatzbeleg** | Die vorhandenen Karten mit `unassigned_source` (6 KB-WIN-Karten) und `outside_mandate` (8 Live-Karten vom 05.11.) bleiben vor und nach dem Neustart unberührt. Die geplante neue Kontrollkarte wurde nicht angelegt. |
| Zwei Testkarten je genau einmal, mit Quittung | **offen** | Nicht ausgeführt, siehe oben. |

Der produktive Bridge-Dienst und die sichtbaren Codex- und Grok-Bindungen wurden nicht berührt.
Es ging kein Fenster auf, es wurde kein API-Schlüssel verwendet und es entstanden keine Kosten.
Es wurde nichts gelöscht oder zurückgesetzt.

## Für den Abschluss nötig (Nutzerentscheidung)

1. **Entweder** für genau diese Abnahme zwei Codex-Turns je Karte im Abo freigeben. Dann:
   Zugangsbeleg im Routingprofil erneuern, einen disjunkten Testbereich und einen Dateicheck
   in `allowed_cwds` und `checks` aufnehmen und den eigenen Dienst neu starten. Danach zwei
   Testkarten und eine Kontrollkarte anlegen, nur die zwei Testkarten mit `adopt` zuordnen,
   Lauf und Quittungen prüfen und anschließend erneut einen Neustart prüfen.
2. **Oder** einen Claude-Worker als eigenes KB-Quellpaket für die Koordinatorkette bauen.
   Das ist eine Codeänderung mit eigener Prüfung und keine Abnahme.

Bis dahin bleibt AutoNext `disabled / not_started`. Der Dienst beobachtet weiter, ohne
Modellaufrufe.

## English

BP-AUTO-01 was accepted only in part. The loop stopped before the first model run. The only
coordinator chain uses Codex for both the main turn and the verifier, and it probes quota through
Codex. Per N1, only Claude is available, and the routing access evidence expired on 2026-11-07.
No cards were created or assigned and no Codex or Grok call was made.

Evidence covers the existing state only. An empty catalog starts nothing. A kickstart of the
coordinator's own label left the DB snapshot byte-identical, with no replay. Historical UNKNOWN
work stays UNKNOWN and unassigned cards stay untouched. In continuation mode, `approve` pins are
ignored and only `adopt`ed cards inside `allowed_cwds` and `checks` run. Changing either of those
requires a service restart. Completing the package needs a user decision: either allow
subscription Codex turns for this acceptance, or build a Claude worker first.
