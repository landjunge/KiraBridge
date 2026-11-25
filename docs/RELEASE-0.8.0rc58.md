# KiraBridge 0.8.0 RC58

macOS-Kandidat nach RC57. Schwerpunkt: sicheres Zustellen und stabile Terminalerkennung.

Neu gegenüber RC57:

- **Terminalerkennung (#238):** In den Dock minimierte Fenster zählen nicht mehr als offen und
  werden nicht mit gleich großen Fenstern verschmolzen; Fenster beendeter Shells markieren den
  Katalog nicht mehr als unvollständig; minimierte Fenster sind keine Tippziele. Eine TTY ohne
  benutzereigene, aber mit fremden Prozessen bleibt dagegen ausdrücklich als unvollständig
  gemeldet, weil sie nicht als eigene Sitzung darstellbar ist. Ein Hintergrundjob mit `ppid 1`
  gilt nicht als zweite Shell-Wurzel, Layoutänderungen brechen keinen Versand ab, und für
  ungeeignete Fenster wird der tatsächliche Grund gemeldet.
- **Weniger native Aufrufe (#238):** Kein zweiter Bildschirmread innerhalb der Sperre, der
  Ergebnisread nutzt die beim Versand beobachtete Zeile, die Fensterprüfung endet beim ersten
  geeigneten Shell. Sichtbare Kommandos schreiben bei jedem Ausgang (Setupfehler, Unterbrechung,
  Exit-Code) eine atomare Quittung; Kommandoordner werden nach dem Lesen entfernt und nach drei
  Tagen bereinigt. Agentenfenster-Bindungen werden beim Start und alle 90 Sekunden gegen einen
  frischen Katalog geprüft (nur lesend); eine tote Bindung läuft über die vorhandene
  Abwesenheits- und Einzelagenten-Ersetzung statt veraltet stehen zu bleiben.
- **Zustellung an CLI-Agenten (#239):** Die Bereitschaft wird je CLI genauer gelesen —
  Claude betrachtet den ganzen Block über der Eingabe (alte „working"-Wörter im Scrollback
  zählen nicht mehr) und bestätigt den Paste aus dem aktuellen Eingabefeld statt aus der
  Historie, inklusive gefaltetem Paste-Marker; Codex ignoriert alte Busy-Wörter, kennt
  Platzhalterhinweise und gleicht vollbreite logische Zeilen sowohl gegen Leerzeilen- als auch
  gegen Zusatz-Leerzeichen-Darstellung ab; Grok prüft Nutzlasten mit Rand-Leerzeichen an den
  Composer-Zellen statt sie abzulehnen. Ein Geometrie-Abbruch verlangt jetzt eine nicht
  aufzählbare Vollzeilen-Nutzlast.
- **Unbekannter Paste-Lock:** Ein Handoff, dessen Paste-Ausgang unbekannt blieb, wird nur durch
  eine frische, positive Bereitschaftsbeobachtung desselben Fensters (leeres, idle Eingabefeld)
  freigegeben. Text im Feld hält die Sperre; der alte Auftrag bleibt `unknown` und wird nie
  erneut gesendet.
- **Dokumentation:** Der RC39-Bericht kennzeichnet seine damalige Regel „nie automatisch
  entsperren" als durch `db2f7c5` überholt (#240).

Unverändert bleiben Identitätsbindung, Fokus-/PID-/TTY-Prüfungen, Reservierungen, der Schutz vor
dem falschen Fenster und vor fremden Eingaben sowie die Regel, einen unklaren Ausgang nie zu
wiederholen.

Offen und nicht Teil dieses Releases:

- Apple-Silicon-Installer, solange das Runner-Guthaben fehlt (Variable `BUILD_APPLE_SILICON`).
- TollGate-Adapter über die lesende Budgetprüfung hinaus: sinnvoll erst, wenn in TollGate ein
  Limit für einen Agenten gesetzt ist.
- Anmeldung von Gemini und Copilot, Passwort für den opencode-Server.
