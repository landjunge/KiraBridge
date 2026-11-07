# Terminalsteuerung: gezielte Reparatur · 27. Oktober 2026

## Ausgangspunkt und bestätigte Ursachen

Vor dieser Reparatur: integrierte und zuletzt nachgewiesen installierte Quelle
`9e8286092d05028f894c09a82587fa3ce4dabcaa`, Version `0.8.0rc17`, PR44.
RC17 war zuletzt ein GitHub-Release-Entwurf, keine bestätigte Veröffentlichung.
Diese Angaben sind der Ausgangsstand, keine Installations- oder Releasebehauptung
für den neuen Reparaturbranch `fix/terminal-control-20261027`.

Zwei konkrete Fehler sind am Ausgangsstand belegt:

1. Eine normale sichtbare Terminal.app-Shell läuft bei `session.input` mit
   `submit=false` in den zeilenabsendenden Transport. Dessen `send` lehnt vor
   nativer Eingabe mit `session_submit_required` ab, obwohl ein eigener
   Clipboard-/Paste-Pfad ohne Return vorhanden ist. Der separate Agentenpfad hatte
   bereits eine Paste-only-Behandlung; daraus folgt keine funktionierende
   Paste-only-Unterstützung für die normale Shell.
2. Die Bridge zeichnet `session_input_dispatch` bereits vor den weiteren
   Session-Prüfungen auf. Eine eindeutig vor dem Transport verweigerte Eingabe
   kann dadurch als möglicherweise ausgeführt und `unknown` erscheinen. Der
   eigene frühere Prüftask zeigte genau diese Kombination. Seine bestehende
   History bleibt erhalten; die Reparatur schreibt keine alten Zustände um.

Die älteren Bindungsreparaturen werden erhalten: frische tasklokale Auswahl statt
veralteter persistenter Agent-PID, eindeutige Fenster-/Tab-/TTY-/Shell-/Agentbindung,
Prozessgeneration und unverändertes sichtbares Eingabefeld vor Paste/Return.
Siehe [sichtbare Auswahl](VISIBLE-SELECTION-20261024.md). Historische Teststände
und damalige Fokusverweigerungen dort sind keine Abnahme dieses neuen Patches.
Ein Prozessname ist keine kryptografisch geprüfte Agentenidentität.

## Getrennte Verantwortlichkeiten und Schnittstelle

- **A / terminal_repair:** SessionManager und Terminal.app-Adapter. Normale Shell
  mit `submit=false` verwendet den vorhandenen sicheren Einfügepfad, prüft eine
  leere interaktive Eingabe, vollständige aktuelle TTY-Prozessmenge, Identitäten,
  Sichtbarkeit/Fokus und unveränderte Ansicht. Agenten behalten ihren eigenen
  taskgebundenen Auswahl-/Readiness-Pfad; keine Umleitung auf eine andere Sitzung.
- **C / receiver_contract_audit:** Dispatchbelege und Fehlerzustand in der Bridge,
  dazu unabhängige Sicherheitsprüfung. Optionaler interner Callback
  `before_transport` wird, sofern gesetzt, mit `await before_transport()` nach
  den Session-Vorprüfungen unmittelbar vor Übergabe an den Eingabetransport
  aufgerufen. Kein neues MCP-Recht und kein zusätzlicher externer Parameter.
- **B / whiteboard_repair:** bestehendes Arbeitswhiteboard, Plan und diese Doku.
- **Root:** Integrationsreview, erforderliche Gates, eigene isolierte sichtbare
  Intel-Mac-Abnahme und gegebenenfalls konkret freigegebene Paketinstallation.

Der Callback bezeichnet die konservative Grenze möglicher Eingabe, keinen
Empfangs-, Ausführungs- oder Abschlussbeweis. Prüfungen innerhalb des nativen
Transports können noch danach scheitern; ohne eindeutigen Beleg bleibt ein solcher
Ausgang unbekannt. Kein pauschales Exception-Whitelisting, kein automatischer
Wiederholungsversuch und keine erfundene Prozessbeendigung.

## Paste-only und Mehrzeilensicherheit

Normale Shell: `submit=false` bedeutet Einfügen ohne Return und ohne Behauptung,
Text sei ausgeführt worden. Ohne nachgewiesenen Bracketed-Paste-Vertrag dürfen
Zeilenumbrüche oder Steuerzeichen im eingefügten Text selbst Aktionen auslösen.
Der enge Shell-Pfad akzeptiert deshalb ausschließlich nichtleeren einzeiligen Text
ohne Steuerzeichen. Er entfernt oder ersetzt keine Zeichen stillschweigend.
Mehrzeilige Shell-Eingabe benötigt einen gesondert nachgewiesenen sicheren Vertrag;
sie wird nicht durch Aufteilen, verstecktes Absenden oder eine Ersatzsitzung emuliert.

Agenteneingabefelder bleiben getrennt: vorhandene geprüfte Paste-/Widgetbeobachtung,
Readiness und Inhaltsbindung gelten weiterhin. Ein sichtbares offenes Agentenfenster
beweist keine Leerlaufbereitschaft. Reale Aktivität, Mehrdeutigkeit, veraltete PID,
Zielwechsel oder bereits vorhandene Nutzereingabe verweigern den Zugriff.
Clipboard-Snapshot, Generationsprüfung und bestätigte Wiederherstellung bleiben
bestehen. Authentifizierung, explizite Rechte und optionale Eingabefreigaben werden
nicht durch den neuen Transportpfad ersetzt.

## Erforderlicher Abnahmeumfang

Der Plan wurde vor der Umsetzung gespeichert. Der nachfolgende Ergebnisabschnitt
trennt inzwischen ausgeführte Prüfungen von weiter offenen Integrations- und
Installationsschritten. Erforderlich sind ausschließlich die betroffenen Regressionen
und unmittelbar relevanten Sicherheitsprüfungen:

- Normale Shell, `submit=false`: exakt autorisierter Text im richtigen Ziel,
  kein Return; Mehrzeilen-/Steuerzeichenablehnung vor möglichem Transport.
- Aktuelle Zielbindung, stale PID, geänderte Ansicht und Busy-Ziel: kein
  Ausweichen und keine Eingabe bei verweigerter Vorprüfung.
- Dispatchgrenze: bestätigte Vorabverweigerung `failed`, nach möglicherweise
  versandter Eingabe `unknown`; Idempotenz und Wiederanlauf ohne zweite Eingabe.
- Bestehende Agenten-Paste-only-Route sowie Clipboard-/Fokus-/Identitätsschutz.

Root führt anschließend genau die nötige echte macOS-Abnahme im eigenen sichtbaren
Testkontext mit privater Konfiguration, State und Workspace aus. Frischen Quellpin,
Fenster/Tab/TTY/UID/PID/Startidentitäten und vorherige Fremdfenster festhalten.
Nach Paste-only den sichtbaren Text unabhängig lesen und vor jedem separaten Return
belegen, dass die eigene erwartete Ausgabedatei unverändert beziehungsweise nicht
angelegt ist. Ein abgeschlossener Paste-Task ist kein ausgeführter Shellbefehl.
Nur die eigene nachweislich leere sichere Testumgebung schließen und ihre Abwesenheit
unabhängig bestätigen; bei unklarem Zustand erhalten und nicht erneut eingeben.

Die vorhandenen Skripte `scripts/accept_visible_selection.py` und
`scripts/accept_visible_terminal.py` liefern Teilbausteine, sind aber keine bereits
bestandene neue Abnahme. Das erste prüft ein eigenes `head`-Eingabefixture statt
normaler Shell und ruft Return separat auf; das zweite prüft einen breiteren
Fenster-Lifecycle. Nicht beide vollständig wiederholen, um diesen engen Fix zu testen.
Genaue Befehle, Quellstände, Ergebnisse, begründete Wiederholungen und verbleibende
Grenzen werden nach tatsächlicher Ausführung hier beziehungsweise im PR ergänzt.

## Ergebnisse der gezielten Prüfung

Beleg: [strukturierte Intel-Nachweise](evidence/terminal-input-20261027.json).
Getesteter Programmstand `7cbf343c3dc0325a39cefc4e01f7cecfa26af74f`; die vier
betroffenen Programmdateien sind dort einzeln mit SHA-256 gepinnt.

- A: 47 gezielte Session-/Adapter-, Clipboard-, Identitäts-, Steuerzeichen- und
  Policy-Fälle bestanden. Drei Fälle prüfen LF/CRLF/CR tatsächlich mit JXA,
  aber ohne GUI. Die Shellprüfung normalisiert die vom Mac gelieferten
  Prozesszeilentrenner und validiert den effektiven Text nach der Freigabe.
- C: 21 gezielte Dispatch-/Buffer-/Wiederanlauffälle bestanden. Eine freigegebene
  Eingabe darf im eigentümergebundenen Zustand `accepted` oder `running` einmalig
  reserviert werden; Reservierung ist noch kein Eingabeversuch. Andere Zustände,
  falscher Eigentümer, geänderte Argumente und erneute Reservierung bleiben verboten.
- Root: drei zusätzliche unmittelbar nötige Integrationsfälle verbinden reale
  SessionManager- und Buffer-Implementierung mit der neuen Bridge-Callbackgrenze.
  Alle bestanden; keine lokale Gesamtsuite wiederholt. Ruff/Diffprüfungen der
  Änderungen bestanden. Notwendige Tests wurden nach konkreten Fehlern gezielt
  korrigiert beziehungsweise wiederholt, keine fehlgeschlagenen Läufe verschwiegen.
- Echte native Intel-Abnahme in genau einem eigenen Fenster `67312` / `ttys000`:
  veraltete PID vor Eingabe als `failed` verweigert, Ansicht unverändert.
  `submit=false` anschließend `completed`, Text exakt zurückgelesen und eigene
  Ausgabedatei vor Return nicht vorhanden. Erst ein separat ausdrücklich gesendetes
  Return führte den harmlosen eigenen Prüfbefehl aus. Die Quittung umfasst 21 Bytes,
  SHA-256 `e0d553299368b84500be75eee7de96c219ff4bb643ae36e8ee2831a08c3009a9`.
  Keine fremde Agentensitzung und keine produktive Konfiguration verändert.

Zwei Grenzen bleiben im Originalbeleg sichtbar: Der erste reine Katalogaufruf
scheiterte vor jeder Fensteröffnung mit der mehrdeutigen alten Fehlermeldung
(Timeout oder ungültiges JSON). Die gezielte Nachdiagnose lieferte wieder gültige
214-Byte-Metadaten in 0,288 Sekunden; keine bewiesene Ursachenreparatur behauptet.
Der native Harness prüfte nach dem separaten Return zunächst nur das Vorhandensein
der Quittung und las zu früh. Der unabhängige spätere Bytevergleich bestätigte sie
ohne erneute Eingabe; Originalfehler und ergänzte Quittierung bleiben erhalten.

Das eigene leere Prüffenster wird für den nächsten autorisierten Schritt behalten,
kein weiteres geöffnet. Cleanup/Abwesenheit, final integriertes Paket, verpflichtende
GitHub-Prüfungen, Merge und tatsächlich installierter Dienst sind zum Zeitpunkt dieses
isolierten Nachweises noch getrennt abzuschließen. Laufende Codex-/Grok-Sitzungen
und der tatsächliche ChatGPT-Sprachhost sind durch diesen Fixturetest nicht abgenommen.

## Integration und Betriebsgrenzen

Abgeschlossene Änderung prüfen, committen und pushen, normalen PR-/Review-/Checkweg
verwenden; fehlgeschlagene oder nicht gestartete Pflichtprüfungen nicht umgehen.
Hosted-/lokale Intel-Nachweise und ungeprüfte ARM-/andere Plattformen unterscheiden.
Produktivinstallation erst aus konkret geprüftem Paket und nach entsprechender
Freigabe sichtbar im bestätigten eigenen Terminal, mit Backup/Datenerhalt/Rollback
und unabhängigem Versions-/Quell-/Dienstreadback. launchd bleibt nach Schließen des
Terminal- oder Browserfensters aktiv. Keine produktiven Rechte, Credentials,
Konfigurationen, fremden Agentensitzungen oder Queues für eine Abnahme verändern.

Der Nutzer meldet den Readerzugang inzwischen funktionierend. Dieser Auftrag startet
weder Reader-/Hostblockdiagnose noch Bibliotheksimporte erneut. ThreadDesk/Codex2/3
bleiben eigene Arbeitsbereiche. Einziger Arbeitsplananhang ist im bestehenden
Whiteboard `188ce4729a62` bei Revision118 unabhängig bestätigt; kein konkurrierendes
Whiteboard. Weitergehende Terminal-, Queue- oder Providerumbauten aus PR38 bleiben
separat zu prüfen, keine parallele Neuimplementierung.

## English summary

The pre-repair source is RC17/main `9e828609`; the release was last observed as a
draft. Plain Terminal.app `submit=false` reaches a line-submitting path and is
rejected before input, while an early dispatch marker incorrectly permits an
`unknown` outcome. Preserve earlier task-local target/TTY/process-generation fixes.

Use the existing guarded paste transport for a confirmed empty plain shell, allowing
only single-line text without controls. Agent widgets retain their separate guarded
selection/readiness route. An optional awaited `before_transport` callback records
possible input only after session prechecks; it does not prove delivery or execution.
Definite pre-transport refusal and uncertain transport outcomes must remain distinct,
with no automatic replay. Targeted session/adapter (47), dispatch/buffer (21), and combined integration (3)
cases passed. An actual isolated visible Intel-Mac paste-only/readback and stale-PID
check passed, with original setup/receipt-timing failures preserved. This does not
claim actual voice-Host or live Codex/Grok input acceptance. Normal review/check gates precede merge;
only an explicitly approved verified package may be installed visibly with preserved
state and rollback. No Reader/Host investigation restart, foreign-session input or
Library-job replay is part of this repair.
