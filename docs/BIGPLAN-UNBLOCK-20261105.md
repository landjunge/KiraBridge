# BIG PLAN: technische Blockaden gezielt lösen

Fortsetzung von BIGPLAN-AUTONEXT-20261104-V1 nach ausdrücklichem Nutzerauftrag
vom 05.11.2026, die belegten Blockaden zu reparieren. Keine zweite Automatisierung
und keine pauschale Bearbeitung historischer Ideen. Neue isolierte Arbeitskopie
`KiraBridge-worktrees/bigplan-unblock-20261105`, Branch
`fix/bigplan-unblock-20261105`, Basis2a8d2fe. Bestehende Eingabereparaturf69a047
(einschließlich147e6f8) unverändert integriert, keine Doppelentwicklung.

## Reparaturen

TerminalWindowProof band bisher die sichtbare Hostkontinuität zwingend an die
Gleichheit eines AXWindow-Handles. Beim beobachteten Tabwechsel blieben die
bisherigen Tab-Referenzen erhalten, während sich das AXWindow-Handle änderte.
Die korrigierte Bindung verlangt die vollständige eindeutige geordnete alte
Tabpartition plus genau einen neuen ausgewählten Tab. App-/Workergeneration,
Nonce, logische Fenster-/TTY-Inventur sowie unveränderte fremde CG-/AX-Flächen
bleiben geprüft. Nach dem einen aufgezeichneten Detach braucht ein ersetztes
AXWindow zusätzlich dieselbe CG-Fläche oder dieselbe eigene Tab-Referenz.
Unbestätigte doppelte Identitätswechsel bleiben UNKNOWN. Die Prüfung wurde
präzisiert, nicht ersatzlos entfernt. Apple-Grundlagen: SCWindow.windowID ist die
CG-Kennung; AXUIElementGetPid liefert die Prozesszuordnung eines AX-Objekts.

AutoNext ignorierte ausdrücklich retirierte/gehaltene Lieferungen bisher nicht,
obwohl die bestehenden Dispatcher deren Holds berücksichtigen. Die korrigierte
Admission berücksichtigt diese Holds nur für queued/UNKNOWN-Nachrichten und
UNKNOWN-Handoffs. Laufende Receiver und aktive Paste-/Return-Vorgänge bleiben
bindend. Reine Withdrawals und UNKNOWN-Teamarbeit geben keine Ressourcen frei.
Alte Daten, Ausführungszustände und Payloads werden nicht umgeschrieben.

Sechs alte eigene Handoffreservierungen wurden über das vorhandene
queue_control/retire mit exakter beobachteter Revision und strengem
Originalziel-Abwesenheitsnachweis regulär retirert. Die ursprünglichen Fenster
und beide PIDs mussten nachweislich fehlen. Jeder Kontrolltask completed;
Originalzustand jeweils weiterhinUNKNOWN, kein Replay, keine Stopbehauptung.
Aktuelle fremde Grok-Arbeit wurde nicht abgebrochen.

## Reale begrenzte Abnahme

Der vorhandene Intel-Codex-Handoff-Harness erhält einen expliziten optionalen
AutoNext-Abnahmeschritt. Es bleibt derselbe eigene sichtbare Testtab und derselbe
private authentifizierte Bridge-/TeamDispatcher-Prozess. Der Harness sperrt
zusätzliche Fenster, versteckte Ausführung und tmux-Fallback weiterhin.
Keine produktive globale Profil-/Sandbox-/Zugangsänderung.

Nur mit --autonext-budget-source und bestehendem
--autonext-board-workspace: aktuelle echte Codex-Quota, ChatGPT-Anmeldung ohne
API-Schlüssel, höchstens zwei read-only-Karten mit exakt vorher gebundenem
Ergebnishash auf dem bestehenden Board482f593429ad. Quelle und Claims werden
separat zurückgelesen. Der vorher tatsächlich geprüfte native Core-Handoff
liefert den Startanker. Die beiden Folgeaufträge benötigen abgeschlossenen Core,
Turnnachweis und genaue Antwort vor dem nächsten Claim. Temporäre Rollen,
Tokens und begrenzte Profile existieren nur im eigenen QA-Prozess. Auch beim
Fehler werden Dispatcher und Token sauber beendet; keine Wiederholung.

Diese reale Providerabnahme ist ausdrücklich keine Freigabe sämtlicher
Produktionsaufträge oder Abnahme von Grok/Windows. Fehlende fachliche READY-Karten
werden nicht aus alten Brainstormingtexten hergestellt. Windows für Dirk bleibt
die nächste fachliche Priorität nach belastbarer Weitergabekette.

## Belege und Status

Private Sicherung und Laufbelege:
`~/.local/share/kirabridge/backups/bigplan-unblock-20261105T053718/`.
Online-DB-Sicherung integrity_check=ok; aktive Konfiguration/Credentials/Key
privat gesichert, vollständiges vorheriges Installationsarchiv referenziert.

Gezielter Rootlauf253Tests bestanden. Hold-Unterauftrag101Tests bestanden;
Fenster-Unterauftrag32+4Tests bestanden. Läufe überlappen, keine künstliche Summe.
Unabhängiges lesendes Review der beiden Produktreparaturen ohne blockierenden
Befund. Reale Abnahme, Paket- und Installationsstand werden als eigene
Laufnachweise dokumentiert; bis dahin nicht als bestanden oder aktiv behauptet.
README DE/EN, Webseite und Abbildungen benötigen für die begrenzte technische
Quellkorrektur keine Neugestaltung. Installationsweg bleibt der reguläre Installer
mit Quellpin, Sicherung, sichtbarem eigenem Fenster, Idle- und Rollbackprüfungen.
