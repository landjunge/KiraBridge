# KiraBridge 0.8.0 RC57

macOS-Kandidat nach RC56. Schwerpunkt: Limits und Budgets in TollGate.

Neu gegenüber RC56:

- TollGate-Budgetprüfung je Agentenlauf (#235): Vor jedem Lauf fragt KiraBridge einmal die lesende Funktion
  `agent_gate` von TollGate. Nur ein vom Nutzer gesetztes Tagesbudget (Hülle in TollGate), das durch gemessene Kosten
  erreicht ist, lehnt den Lauf ab (`tollgate_budget_reached`). Ein erschöpfter Abo-Plan wird nur vermerkt
  (`plan_exhausted`), nie als Sperre. Ist TollGate nicht installiert, nicht festgelegt, antwortet zu langsam
  oder falsch, läuft der Lauf unverändert weiter (`tollgate_unavailable`). Schalter `workflow_control.budget`
  (Standard an, aus = kein Aufruf). Wirksam wird die Prüfung erst, wenn das Paket `tollgate` in der Umgebung
  installiert und über `workflow_control.source_package_sha256` festgelegt ist.
- ACP-PAP-Host-Adapter (#234), standardmäßig aus.

Offen und nicht Teil dieses Releases:

- Apple-Silicon-Installer, solange das Runner-Guthaben fehlt (Variable `BUILD_APPLE_SILICON`).
- Anmeldung von Gemini und Copilot, Passwort für den opencode-Server.
