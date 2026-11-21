# KiraBridge 0.8.0 RC59

macOS-Kandidat nach RC58. Schwerpunkt: Messbarkeit und Coordinator-Aufstieg in einem Befehl.

Neu gegenüber RC58:

- **Ein-Befehl-Onboarding (#245):** `kirabridge team onboard <team_id> <identity> [--coordinator]`.
  Das Daemon-Werkzeug `team_onboard_register` lässt ausschließlich die Owner-Identität `local` zu,
  ergänzt `[principals.<id>]` plus `[team.workers.<id>]` und einen erzeugten Token erst, wenn der
  Kandidat das strenge Konfigmodell besteht; es hält zeitgestempelte Sicherungen beider Dateien,
  stellt bei jedem Fehler beides wieder her, ist beim Wiederholen idempotent und gibt niemals
  Tokenwerte aus. Die CLI orchestriert den Rest: Neuladen nur im Leerlauf (aktive Teamarbeit oder
  `--no-restart` halten an), ein Rollenaufruf mit Revisions-CAS und genau einem erneuten Versuch,
  danach verpflichtender Readback von Owner, Koordinator, Revision, Mitgliedschaft und wartender
  Inbox-Seite. Die Eigenbeförderung eines Agenten bleibt blockiert; halbierte Registrierungen halten
  konservativ an. Dies ist ein Quellstand, keine produktive Installation dieses Auftrags.
- **Start-Anker im Teamauftrag (#244):** `team_work.started` wird beim Dispatch gesetzt
  (`COALESCE(started,?)`) und durch die Beobachtung nie gelöscht (`COALESCE(?,started)`); echte
  Kern-Evidenz verfeinert den Anker weiterhin. Zeitüberschreitungs-/Wiederaufnahme-Läufe, die nie
  den RUNNING-Zustand erreichen, verlieren ihren Startzeitstempel nicht mehr. Das
  Reprocess-Verhalten (ein gesetzter `started` bleibt) ist wie bisher unverändert.
- **Installationsbereitschaft (#243):** Der macOS-Installer benennt die tatsächliche Ursache, wenn
  die Daemon-Bereitschaft fehlschlägt, statt nur einen allgemeinen Fehler zu melden.
- **Abnahme-Härtung (#242):** Die Release-Download-Abnahme prüft den veröffentlichten
  RC58-Bootstrap; frühere Belege (u. a. RC57/RC58) bleiben gültig, die Intel-Abnahme deckt
  macOS 15.7.4 (x86_64) — Apple-Silicon und macOS 26 bleiben ohne eigenen Nachweis.

Unverändert bleiben Identitätsbindung, Fokus-/PID-/TTY-Prüfungen, Reservierungen, der Schutz vor
dem falschen Fenster und vor fremden Eingaben sowie die Regel, einen unklaren Ausgang nie zu
wiederholen. ACP-PAP-Host bleibt opt-in und Standard aus.

Offen und nicht Teil dieses Releases:

- Apple-Silicon-Installer, solange das Runner-Guthaben fehlt (Variable `BUILD_APPLE_SILICON`).
- TollGate-Adapter über die lesende Budgetprüfung hinaus: sinnvoll erst, wenn in TollGate ein
  Limit für einen Agenten gesetzt ist.
- Anmeldung von Gemini und Copilot; das Free-Modell `opencode/deepseek-v4.1-flash-free` antwortet
  aktuell nicht innerhalb des Worker-Budgets und bleibt als Arbeiter geparkt (Retest nötig).
- `team onboard` ist implementiert und abgenommen, aber erst nach diesem Release produktiv wirksam;
  dieser Auftrag hat es nicht gegen die laufende Produktivinstallation ausgeführt.
