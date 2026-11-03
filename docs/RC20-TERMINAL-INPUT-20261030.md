# RC20: direkte Terminaleingabe und sichtbares Codex-Eingabefeld

Nachtrag 31. Oktober 2026: Die Reparatur aus `881a53f` wurde anschließend
ausdrücklich zur Installation freigegeben, lokal gebaut und auf dem Intel-Mac
installiert und abgenommen. [Tatsächlicher Installations-/Neustartbeleg](RC20-881A53F-INSTALL-20261031.md).
Die folgenden Freigabeaussagen beschreiben den ursprünglichen Reparaturauftrag.

## Auftrag und Stand

Reparatur auf Basis `da1bdaed019c31aa11bb28a39ef8bead7e73c1d4`
(`0.8.0rc20`) im separaten Branch `fix/rc20-terminal-input-20261030`.
Der Auftrag umfasst Ursachenanalyse, Quellcodekorrektur, Tests, Dokumentation
und einen lokalen Git-Commit. Push, Installation und Veröffentlichung sind
ausdrücklich nicht freigegeben. Die Änderungen sind daher noch nicht im
produktiven KiraBridge-Dienst aktiviert.

## Ursachen

1. `Bridge.execute()` wandelte `session.input` mit `submit=true` für ein
   erkanntes Agententerminal in `AgentInput` um und rief den sichtbaren
   Agenten-Handoff auf. Dessen Auftragshülle mit Nachrichtenempfang, ACK,
   Antwortanweisung und Endmarker ist für adressierte Arbeitsaufträge vorgesehen.
   Als Folge wurde auch `/resume` in eine Modellnachricht eingebettet und
   verlor seine Bedeutung als interaktiver CLI-Befehl. Der Pfad mit
   `submit=false` fügte den Text bereits unverändert ein.
2. `visible_readiness.assess()` wertete `Back to bottom` beziehungsweise
   `enter/esc latest` als Zeichen einer unerreichbaren Eingabeansicht, bevor es
   den sichtbaren leeren Composer und dessen Footer vollständig prüfte.
   Die bekannten Codex-Zeilen `New activity · ↓ Back to bottom · esc` und
   `New activity · enter/esc latest` steuern aber den Transkriptbereich und
   können gleichzeitig mit dem aktuellen Composer sichtbar sein. Ohne separat
   gebundenes Rollout mit Idle-Nachweis führte dies zu
   `visible_target_scrolled`. Historische Navigationszeilen konnten zusätzlich
   die globale Busy-Musterprüfung treffen.

## Änderungen

`literal_session_input.py` übernimmt direkte Eingaben für erkannte CLI-Ziele.
`session.input` fügt den autorisierten Text unverändert ein. Bei `submit=true`
folgt genau ein separat protokollierter Return nach Prüfung der tatsächlichen
Eingabe. Bei `submit=false` bleibt es beim Paste. Das gilt für sämtliche Texte
und die bestehenden berechtigten Absender, ohne Sonderersetzung für `/resume`.

Der Pfad verwendet die vorhandene Auswahl, Eingabepolitik, Berechtigungen,
Reservierungsprüfung sowie nativen Identitäts-, Fokus- und Screenprüfungen.
Vor Return muss der Composer dem autorisierten Text und dem zuvor beobachteten
Rahmen entsprechen; zusätzlich eingefügte Fortsetzungszeilen werden auch dann
abgelehnt, wenn sie wie Modell-, Shortcut- oder Navigationszeilen aussehen.
Codex darf die Zahl abschließender ASCII-Leerzeilen zur Fensterfüllung ändern;
diese Normalisierung beginnt erst nach dem exakt erkannten Payload. Nichtleere
Footerzeilen und deren Trennung bleiben gebunden. Zusätzlich darf ausschließlich
das exakte optionale F2-Warnbadge am Ende derselben GPT-Modellzeile erscheinen
oder verschwinden. Modell-/Pfadtext und Zeilenfolge bleiben dabei identisch.
NBSP-/EM-Space-Fortsetzungen zählen weiterhin als Inhalt.
Unklare Paste-/Return-Ausgänge bleiben `unknown` und werden auch nach Neustart
nicht automatisch wiederholt. Der Task bestätigt Terminalzustellung, ohne
Agenten-ACK oder fachlichen Ausführungserfolg zu behaupten.

`agent.execute` und `message_send(kind="work")` behalten ihr bisheriges
Auftrags-, Empfangs- und Ergebnisprotokoll. MCP-Hinweise und README erläutern
die Wahl des Eingabewegs. Ein erneut als `work` gesendetes `/resume` bleibt
eine adressierte Nachricht; für das interaktive Menü wird `session.input`
verwendet.

Die Bereitschaftserkennung akzeptiert ausschließlich die bekannten vollständigen
Codex-Navigationszeilen neben einem nachgewiesenen leeren Composer mit erkanntem
Footer. Allgemeine Scrollhinweise, unbekannte Dialoge, vorhandene Eingaben,
laufende Arbeit, Queue-Composer und widersprechende/unklare gebundene Turnzustände
bleiben geschützt. Der Terminal-Lesepfad und die nativen Fokus-/Identitätsguards
sind unverändert.

## Nachweise

Die gezielten neuen Parserfälle reproduzierten vor der Reparatur sechs Fehler
bei Live-Composer plus Navigationshinweisen. Nach der Korrektur bestanden die
65 Parserfälle. Die Prüfung mit konkreter Terminalbindung bestätigte außerdem
den positiven Fall und fünf negative Fälle. Ein zunächst falsch erwarteter
Fehlername im neuen Dialogtest wurde auf den bestehenden Vertrag
`visible_target_unknown` korrigiert und ausschließlich dieser Fall nachgeprüft.

Der direkte `/resume`-Regressionstest scheiterte vor der Routingkorrektur:
Der alte Pfad fügte eine Auftragshülle ein und wartete beim simulierten Menü
auf einen nicht vorgesehenen ACK. Während der Testentwicklung wurden sieben
Fixturefehler nach vorzeitigem Datenbankschluss und sechs alte Erwartungen
an den Raw-zu-Handoff-Vertrag korrigiert; sie sind keine bestandenen Läufe.

Ein einmaliger breiter Lauf über 34 unmittelbar betroffene Testmodule ergab
**607 bestanden, 6 fehlgeschlagen** (52,02 s). Vier Fehler betrafen den
zusätzlichen Vorabread beim Paste ohne Return; dieser unnötige Read wurde
entfernt. Zwei Reservierungstests erwarteten weiterhin das Handoff-Ergebnis.
Sie prüfen jetzt die tatsächliche dauerhafte Task-Idempotenz und weiterhin den
unveränderten Schutz alter Reservierungen, Nachrichten und Bindungen.

Nach diesen Änderungen und der Absicherung der nativen Leerzeilen-Darstellung
bestand ausschließlich die nötige erneute Prüfung der fünf betroffenen Module:
**174 bestanden** (12,54 s), darunter alle **33 neuen Literaltests**.
Die übrigen **442 bestandenen Fälle** des breiten Laufs blieben unverändert.
Das validierte zu diesem Zeitpunkt **616 unterschiedliche Fälle**.

Zwei echte native Proben mit Codex `0.166.0` machten danach unterstützte
Rendereränderungen sichtbar: wechselnde abschließende Leerzeilen und das
Ausblenden des F2-Warnbadges beim Anzeigen von Slash-Vorschlägen. Die Tasks
blieben dabei `unknown`, ohne Return oder automatisches Wiederholen. Ihre
privaten Stores und Belege bleiben erhalten; jeder neue Test begann nach
identitätsgeprüftem Beenden des eigenen Testprozesses mit einer frischen
Testinstanz im selben eigenen Fenster.

Die dazu erfassten Framepaare reproduzierten zunächst einen Paddingfehler und
vier Warnbadgefehler. Nach den eng begrenzten Rendereranpassungen bestanden
**44 Literaltests** (0,89 s), einschließlich Zusatzzeilen, manipulierten
Footerzeilen, doppelten Warnbadges und Unicode-Gegenproben. Zwei weitere
Singularfälle (`1 warning`) reproduzierten den Scrollfehler; danach bestanden
**73 Parser-/Bindungstests** (0,37 s). Diese letzten Prüfungen ersetzen die
entsprechenden älteren Teilergebnisse. Zusammen sind **629 unterschiedliche
Fälle** validiert. Es gab keinen zweiten Gesamtsuitenlauf und keinen behaupteten
fehlerfreien ersten breiten Lauf. Ruff und Formatprüfung der zwölf geänderten
Pythondateien sowie `git diff --check` bestanden.

Enthalten sind Berechtigungen, manuelle/automatische Freigaben, aktuelle
Terminalauswahl, bestehende Eingabe, Busy-/Queue-Zustände, native Guards,
einmaliger Return, Idempotenz/Neustart/Unsicherheit, Nachrichtenzustellung,
Receiver, ACK/Antworten, MCP und bestehende Steuerkonsole.

Die unabhängige native Code-Review fand eine zunächst zu großzügige
Footererkennung. Die korrigierte Prüfung mit gebundenem Vorzustand und
Angriffsregressionen wurde erneut geprüft; es bleiben keine blockierenden
Codebefunde. Die UI-Erkennung ist eine Prüfung unterstützter Darstellungsformen
und OS-Prozessbeobachtungen, keine kryptografische Identitätsbestätigung.

Die native Menüprüfung und genaue Befehle/Hashes stehen im Prüfbeleg:
[rc20-terminal-input-20261030.json](evidence/rc20-terminal-input-20261030.json).

**Finale native Abnahme bestanden:** Auf Intel-macOS 15.7.4 mit echtem Codex
0.166.0 endete `native-resume-03` als `completed`. Der neue Quellcode fügte
genau einmal `/resume` ein und sendete genau einmal Return. Ein separates
Rücklesen bestätigte das echte Menü „Resume a previous session“ samt
`enter resume / esc exit`. Nachrichten und Handoffs im isolierten Store: jeweils
null. `agent_confirmed` und `execution_confirmed` bleiben zutreffend `false`.
Die Quellhashes waren vor und nach dieser Probe identisch.

Das Menü wurde kontrolliert verlassen, der eigene Codex per separater wörtlicher
`/quit`-Eingabe beendet und das einzige zusätzliche Testfenster geschlossen.
Unabhängig bestätigt: eigenes Fenster und sämtliche fünf erfassten Test-PIDs
abwesend, ursprüngliche Nutzerfenster erhalten. Ein zwischenzeitlich entstandenes
fremdes Fenster blieb unberührt. Frühere Harnessfehler bei Shellstart/Prompt und
die konservative Schließverweigerung vor einem geprüften Ctrl-L-Redraw sind in
den privaten Originalbelegen erhalten.

Der produktive RC20-Daemon blieb bei PID 47085 und derselben Instanz/Quelle.
Konfigurationshash, Dateimodus und Rechterevision blieben zwischen dem eigenen
Lesevergleich nach der ersten Probe/vor der zweiten und dem Abschluss identisch.
Die produktiven Pfade wurden nicht installiert oder umgeschaltet. Der native
Menütest prüft die reale Eingabe; die Navigationsregressionen verwenden simulierte
Terminalframes mit tatsächlicher Bridge-Vorprüfung. GitHub-CI, ARM- und
Release-/Installationsabnahmen sind für diesen lokalen Quellcodeauftrag nicht
als ausgeführt oder bestanden behauptet.

## Verwendung nach gesonderter Aktivierung

Nach `session_catalog` und `session_read` den aktuellen, bereiten Handle benutzen:

```json
{
  "task_id": "resume-menu-unique-request",
  "idempotency_key": "resume-menu-unique-request",
  "operation": "session.input",
  "arguments": {
    "pane_id": "terminal:123:ttys004",
    "expected_pid": 456,
    "text": "/resume",
    "submit": true
  }
}
```

Die Handlewerte sind Beispiele und müssen aus der aktuellen Sitzung stammen.
Bei unbestätigtem Ausgang denselben Task lesen und abgleichen; keinen neuen
Task als blinden Zustellversuch erzeugen. `completed` mit `return_sent=true`
bestätigt die Terminalaktion. Ob ein Menü oder eine fachliche Antwort erschienen
ist, zeigt das anschließende unabhängige Lesen der Sitzung.
