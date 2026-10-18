# Zugeordneter Arbeitsablauf / correlated workflow · M2

Privater Quellstand `583c000` ist integriert. Der lokale0.5.2-Backport `c7a00e0`
ist kontrolliert geladen und über die tatsächlich verbundene ChatGPT-App geprüft.
Dies ist keine neue Downloadversion. ThreadDesk-Quellpin für die Rundreise:
`16b2ccb2da8fc1a6953fd830970bbb19139b0635` (M2 plus exakter get_return-Leseweg).
Das getrennte Betreiberprofil bleibt erhalten; M2 ergänzt dessen vorhandenen
Arbeitsablauf und setzt weder Daten noch Queue zurück.

## Tatsächliche Rundreise und Betriebsnachweis

Elf tatsächliche App-Tasks als chatgpt, jeweils Versuch1, dokumentieren Anlegen,
Ausstellen, Start, Rückfrage, ausdrückliche Antwort, Lieferung, unabhängiges
Dateilesen, Inbox, getrennte Entscheidung, Wiederholschutz und Status nach Neustart.
Der echte Codex-Durchgang fragte zunächst nach einer Farbe. Die synthetische
Betreiberantwort blue setzte ausschließlich dieselbe aufgezeichnete Sitzung fort.
Die neue eigene Datei m2-proof.txt wurde danach unabhängig über file.read mit
exakt5Bytes vollständig gelesen. Vor der Antwort enthielt das Testverzeichnis
noch keine Ergebnisdatei. Der Agent behauptete ausdrücklich keinen separaten Test.

Die Lieferung ging zunächst delivered/unverified in ThreadDesk ein. Erst danach
wurde dieser eng begrenzte synthetische Techniktest explizit accepted entschieden;
project_completion_verified bleibt false. Eine neue Bridge-Taskkennung für denselben
Start gab duplicate=true und denselben Lauf zurück. Nach kontrolliertem Neustart
blieben Lauf, Sitzung und Entscheidung unverändert; kein dritter Turn startete.
Der klar synthetische Thread und die eigene Ergebnisdatei bleiben privat zur
Nachprüfung erhalten. Kein fremder Thread und keine offene Sitzung wurden verändert.

Belege: [minimierte Task-/Laufquittungen](evidence/handoff-m2-20261018.json),
[drei bestandene CI-Plattformen](https://github.com/landjunge/KiraBridge/actions/runs/39155285485).
Konfig-SHA256 e6dd7af8ded9f98098fe59e232a8fe5d0711189782a08c7790552efc266219a0;
Python-Quellfingerabdruck c034dc9eb7f02f1ac1ed2b90b3885ace27896de723ebb08fe5074f4f19394391.
Neustartinstanz f9cf3308086544079731f2aeb9daa2b2, lokaleVersion0.5.2.
Alle373 vorherigen Tasks, fünf Nachrichten und vier Empfängerjobs sowie Zugangs-
und Dienstdateien sind unverändert. Die unbekannte Adminprobe bleibt Versuch1.

Rückweg bei nachweislich ruhender Queue: vorherige M1-Konfiguration aus
~/.local/share/kirabridge/handoff-m2-20261018/config.before.toml mit0600 und
passenden vorherigen Quellstand85ac7da laden. Den alten unveränderten M1-Peerpin
a99afa8 erhalten; keine Datenbank oder Zugangsdaten zurücksetzen. Beide Dienste
kontrolliert neu laden. Bereits angenommene Aufträge niemals erneut ausstellen.

## Vertrag und Bedienweg

Alle Operationen verwenden vorhandene Bridge-Tasks, Idempotenz, Audit und MCP.
Die additive Tabelle handoff_bindings enthält nur Zuordnung und gespeicherte
Quittungsgrundlagen; sie ist keine Queue und startet nichts nach einem Neustart.
Originale ThreadDesk-task_id einschließlich Doppelpunkt bleibt unverändert.
Die technisch gültige Bridge-task_id wird separat gespeichert. run_id ist die
tatsächliche erste Bridge-Empfangsquittung; session_id ist die separat beobachtete
Codex-Sitzung. Handoff-Revision, Thread-Revision, Snapshot und Quellhash bleiben
unterschiedliche Felder. Ein Hash bestätigt keine externe Identität.

| Operation | Argumente | Wirkung |
|---|---|---|
| handoff.issue | operation_id, thread_id, expected_revision, target=codex/generic | Festen Peer um einmalige Übergabe bitten; kein Agentenstart |
| handoff.start | handoff_id, revision, cwd, agent=codex, timeout bis300s | Ausdrücklicher Ausführungsauftrag; einmalig an vorhandenen Codex-Adapter binden |
| handoff.status | handoff_id, revision | Eigene gespeicherte Zuordnung und beobachteten Ausgang lesen; kein Peer/Agent nötig |
| handoff.answer | handoff_id, revision, question_id, answer_id, text, timeout | Genau die eigene wartende Sitzung fortsetzen; keine fremde Sitzung oder --last |
| handoff.inbox | offset=0, limit=20 (max50) | Nur eigene Return-IDs exakt nachladen; next_offset fortsetzen |
| handoff.reconcile | handoff_id, revision | Ausschließlich vorhandene exakte Liefer-/Entscheidungsquittung lesen und zuordnen |
| handoff.decide | handoff_id, revision, return_id, choice, note | Explizite Betreiberentscheidung accepted/rejected/rework; kein Funktionstest |

Benötigte Capabilities werden nur dem ausdrücklich autorisierten Betreiber
zugeordnet. handoff.start/answer benötigen zusätzlich agent.execute, eine
erlaubte Codex-Identität, ein vorhandenes Programm und autorisierten Projekt-CWD.
Alle Fachoperationen benötigen threaddesk.read, Ausstellen einer Übergabe zusätzlich
threaddesk.manage. Normale Bot-Identitäten erben diese Rechte nicht.
Der feste lokale Peer und das gemeinsame Betreiberprofil sind kein öffentlicher
Mehrmandantendienst. Clientpayloads können keinen Peer, Speicher, Quellpfad,
Session oder Rückgabebeleg als vertrauenswürdig vorgeben.

## Ausführung und Rückfragen

Vor Modellstart werden tatsächlich ausgestellte Übergabe, Hash und Revision am
festen ThreadDesk-Peer gelesen und eine exakte Laufbindung quittiert.
Geänderte Grundlage blockiert den Start. Die vorhandenen read-only/workspace-write-
Profile, Projektregeln, deaktivierten MCP-Kindserver und Ressourcenlimits gelten
weiter. Ausgelieferter Kontext und angefragte Rechte erweitern keine Policy.
Referenzierte Repositories werden weder installiert noch automatisch ausgeführt.

Ein begrenztes JSON-Antwortschema unterscheidet question/result. Erst ein
beobachteter erfolgreicher Agententurn und passende Session-ID dürfen eine
Rückfrage oder Lieferung erzeugen. Eine Frage beendet den Prozessdurchgang;
der Workflow wartet mit persistierter eigener Codex-Sitzung. Nur handoff.answer
mit genau dieser Frage zeichnet die Antwort im Peer auf und startet anschließend
explizit exec resume für dieselbe UUID. Ein gespeicherter Antworttext allein
bestätigt keine Zustellung. Maximal acht ausdrücklich angestoßene Durchgänge;
kein automatischer Frage-/Ausführungsloop. Grok-Fortsetzung ist für diesen
begrenzten M2-Weg noch nicht implementiert und wird abgewiesen.

Die tatsächliche ThreadDesk-Rückgabe bleibt delivered/unverified. Dateien und
Tests sind zunächst Agentenangaben, keine ungeprüfte Verifikation. ThreadDesk
prüft den ersten Return bereits gegen ausgegebenen Auftrag, Run und aktuelle
Grundlage; ein erster veralteter oder fremder Return überschreibt nichts.
accepted ist eine getrennte dokumentierte Betreiberentscheidung. Das Feld
project_completion_verified bleibt durch einen Agententurn oder bloße
Entscheidungsquittung unverändert false.

## Verbindungsabbruch und Nachweise

Gleiche Übergabe mit anderem Inhalt/CWD/Agentenprofil kollidiert. Neue Bridge-ID
unter derselben gebundenen Übergabe startet keinen zweiten Lauf. Unklarer
Turn-, Frage- oder Antwortausgang bleibt unknown; kein automatisches Resume.
Status liest weiterhin die ursprüngliche Task und Quittung.

Bei unterbrochener import_return/review_return-Antwort bleibt der konkrete
Schreibversuch samt pending payload/Entscheidung referenziert. handoff.reconcile
holt ausschließlich die bereits vorhandene exakte Return-ID. Nur vollständig
passende Nutzlast, Run-, Principal- und Betreiberzuordnung dürfen den abgeleiteten
Workflowstand bestätigen. Die originale Task wird dabei nicht nachträglich als
erfolgreich umgeschrieben. Nicht beobachtete oder widersprüchliche Ausgänge
bleiben unbekannt. Es wird keine Schreiboperation wiederholt.

Bereits vorhandene Task-Events sind cursorfähig; ChatGPT fragt sie ausdrücklich
ab. Kein Push in aktive Sprachsitzungen zugesagt. Audit enthält minimale
Kennungen/Hash-/Statusreferenzen, keine Frage-/Antworttexte, Rohprompts oder
Ergebnisdateien. Diese bleiben im bestehenden privaten Task-/ThreadDesk-State.
Inbox-Auswahl und Antwortgröße sind begrenzt; alte öffentliche Desktoppakete
werden dadurch nicht verändert.

## English

This privately integrated, locally loaded M2 adapter reuses existing tasks, audit, MCP and ThreadDesk
contracts. Its additive binding table is not an execution queue. Preserve the
original task ID, including colons; Bridge task IDs, receipt-based run IDs,
observed session IDs, handoff revisions and source revisions remain separate.
Explicit start is required. Context does not grant rights or execute repositories.

An owned Codex turn can return a question or an unverified result. Questions end
the process turn and leave the workflow awaiting an explicit answer. Continuation
uses the exact recorded session UUID, never an unrelated interactive session or
--last. Stored answers are not delivery evidence. Unknown outcomes never resume
automatically. Only Codex continuation is supported in this bounded first path.

Returns enter the existing unverified inbox. Tests and artifact references remain
producer claims until actually checked. An explicit operator decision is separate
from agent-turn completion and does not automatically verify project completion.
Read-only reconciliation can recognize an exact already-stored return/decision
after a lost reply; it neither repeats writes nor rewrites the original unknown
task. The fixed local profile is not a multitenant service. Existing data,
credentials, release artifacts and foreign sessions remain unchanged.

The connected ChatGPT App completed eleven real synthetic acceptance tasks. An
actual Codex question was answered explicitly, resuming the exact same owned
session. The five-byte result was independently read through the Bridge. Delivery
was initially unverified; a later technical operator decision is not overall
project or user acceptance. A duplicate start did not execute again, and the same
binding survived a controlled service restart. The synthetic demo is retained
privately. The evidence file records source/config/runtime fingerprints and task
receipts without raw prompts or credentials. This is a local0.5.2 backport, not an
updated frozen RC2 download; no complete Mac reboot or Grok model test is claimed.
