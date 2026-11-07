# RC17: Pager, Rückmeldungen und Diagnosebudget – 26.10.2026

## Tatsächlich geändert

Die vier bestehenden Fenster `terminal:47570:ttys000`, `terminal:50666:ttys003`,
`terminal:51079:ttys005` und `terminal:51447:ttys006` wurden frisch katalogisiert
und über KiraBridge gelesen. Jeweils genau ein `q` beendete ausschließlich den
bestätigten `less`-Pager. Vor jeder Eingabe wurden das genaue Fenster/Tab/TTY,
Shell-, Git- und Pager-PID einschließlich OS-Startidentität sowie die
Vordergrund-Prozessgruppe geprüft. Die native Terminalsteuerung prüfte den Fokus
erneut unmittelbar vor dem Zeichen. Kein Return, kein Signal, kein Git-Abbruch.
Alle vier Pager verschwanden; alle vier Shells blieben erhalten. Der anschließende
Bridge-Katalog meldete diese vier Fenster `busy=false`. Die vorhandenen drei
Codex-Prozesse 12657, 60136 und 45831 blieben erhalten; keine Sitzung wurde beendet.

Produktiv läuft weiterhin RC17 aus Quelle `012b592`; dieser Auftrag hat den Dienst
nicht ersetzt oder neu gestartet. Konfigurationshash blieb unverändert. Keine
Datei, Historie, Berechtigung oder Queue wurde gelöscht.

## Rückkanal: belegter Ablauf und Grenze

Native `action_request`/`task_request` benötigen kein Ereignisabo. Der tatsächlich
geladene ältere ChatGPT-Connector verlangt im Schema dagegen noch das Rootfeld
`completion_subscription`. Die Bridge akzeptiert dafür ausdrücklich `""` als
„kein Abo“. Der Live-Test über **diesen Connector als Identität chatgpt** bestand:

1. Eindeutiges `completion_target`, schreibfreier Testauftrag `agent.status`.
2. `task_request` mit `completion_subscription: ""`: angenommen/queued.
3. Tatsächliche Ausführung `completed`, separate Task-Rücklesung.
4. `completion_receive` lieferte die passende dauerhafte Notice.
5. Erst nach Verarbeitung `completion_ack` mit passender Quittung.

Auch der native Codex-Zugang bestand. Ein zusätzlicher tatsächlicher Loopback-MCP-
Test über dieselbe Client-Verbindung mit parallelem wartendem Consumer lieferte
Submission nach 0,281 s und die vollständige Rückmeldung nach 3,766 s. Nach Lesen
und Quittieren war dieser eigene Posteingang leer. Kein allgemeiner Bridge-Lock
für Longpolls ist damit nachgewiesen. Beim ersten Versuch über den Host-Tooltransport
kam die 20-s-Abfrage leer zurück, danach konnte die Notice gelesen werden; das
lokale Starten eines Promise beweist keine vorherige Registrierung beim Server.
Host-/Connector-Serialisierung bleibt eine mögliche, nicht bestätigte Ursache.

`subscription_states: {}` / `delivery_states: {}` beschreiben den **optionalen
Webhook-Kanal**, nicht die Funktionsfähigkeit des Completion-Posteingangs. Für ein
echtes `kirabridge.task.completed`-Hostabo sind eine vom aktuellen ChatGPT-Host
bereitgestellte Registrierung und ein verifizierter Callback notwendig. Diese
Werkzeuge/Callbackdaten sind dieser Codex-Sitzung nicht verfügbar; keine URL,
Subscription oder UI-Quittung wurde erfunden. `chat_ui_receipt_independently_verified`
bleibt **false**. Ein Toolresultat/Consumer-Ack beweist kein spontanes Aufwecken
eines inaktiven Chats. Für die aktuelle Sitzung einen eigenen stabilen Completion-
Target und einen Consumer verwenden; historische Default-Notices nicht pauschal
quittieren. Connector-Metadaten müssen im tatsächlichen ChatGPT-Client aktualisiert
werden; eine Serveränderung allein bestätigt keinen Client-Refresh.

## Warteschlangen: Fehler repariert, Unknown nicht umgedeutet

Der produktive Aufruf `queue_catalog` scheiterte tatsächlich mit `internal_error`.
Gezielte lesende Eingrenzung fand `team-work`: Dessen `result` ist laut Schema
nativer Text. Die allgemeine Queue-Ansicht versuchte ihn als JSON zu lesen. Das
blockierte bei Klartext sogar den Katalog anderer Queues und wandelte JSON-ähnlichen
Text unzulässig um. Der Patch in `queue_management/views.py` dekodiert nur die echten
JSON-Spalten und erhält Ergebnistext exakt. Fünf neue isolierte Fälle (Unicode,
leer, JSON-/zahlähnlich, abgeschlossene Historie) belegen Katalog, Paging/SHA,
Eigentumsprüfung und unveränderte Datenbank/Auditdaten. Alle fünf schlugen vor dem
Patch fehl und bestanden danach. **Noch nicht produktiv aktiviert.**

Die zugänglichen ChatGPT-Task-/Handoff-/Nachrichten-Queues wurden über ihre eigenen
APIs ausgelesen. Der konkrete Alttask `codex_threaddesk_sync_20261021_01` gehört zu
`chatgpt`; unter `codex` war er korrekt nicht sichtbar. Der authentifizierte
ChatGPT-Zugang zeigt RC11-Ursprung, `unknown`/`visible_reply_unknown` und bereits
`agent_confirmed=true`, letzte Beobachtung `confirmed`, aber keinen abschließenden
Ausführungsbeleg. Sein altes Fenster 22104/PID94023 ist nicht aktuell. Das beweist
keine unterbliebene Ausführung: **nicht erneut senden, löschen oder als beendet
markieren**. Auch der alte aktive Unknown-Handoff und wartende Nachrichten wurden
erhalten; eindeutige Verwaisung ist nicht belegt. Neue Diagnoseaufträge konnten
trotz dieser Historie tatsächlich ausgeführt werden. Keine pauschale Aussage,
dass alle historischen Agent-Zustellungen dadurch frei wären.

Aktuelle Codex-Fenster sind lesbar; die persistent konfigurierten Codex-/Grok-
Zielbindungen verweisen auf alte Fenster/PIDs. Im Katalog und OS-Prozessbild war
kein aktuelles sichtbares Grok-Terminal nachweisbar. „Executable vorhanden“ und
„Receiver konfiguriert“ sind kein erfolgreicher Agent-Handshake. Keine fremde
Codex-Sitzung wurde stellvertretend als Grok ausgewählt. Für neue Agent-Handoffs
sind tatsächlich gestartete, vom Operator zugeordnete aktuelle Fenster nötig.

## Auditlimit und notwendige Tests

Die 2.000/Tag betreffen optionale `diagnostic.*`-Traces; Kern-Audit und Task-/
Completion-Ereignisse bleiben getrennt erhalten. Allerdings kann fehlende Diagnose-
Aufzeichnung die entsprechende Readiness-Auskunft verschlechtern. Sekündliche
interne Proxy-Healthpolls erzeugten je zwei Diagnoseereignisse: ungefähr 2.000 in
16 Minuten 40 Sekunden je Proxy. Der begrenzte Patch in `mcp_gateway/client.py`
und `proxy.py` fasst nur unverändert erfolgreiche **interne** Polls zusammen.
Erster Erfolg, Verbindungs-/Versions-/Revisionswechsel, Fehler und explizite
Aufrufe bleiben erhalten. Kein Retry, kein Budgetanstieg, keine Historylöschung.
Details und die bewusst nachträgliche Klassifizierung solcher Routinepaare:
[Auditbericht](AUDIT-HEALTH-NOISE-20261026.md).

15 neue gezielte Fälle und vier direkt betroffene bestehende Regressionen bestanden;
hinzu kommen die fünf Queuefälle. Root prüfte beide Patches vor Integration und
Ruff/Format der fünf betroffenen Python-Dateien. Keine vorsorgliche lokale
Gesamtsuite, kein neues Installationspaket: getestet wurden die tatsächlichen
Änderungen und ihre Sicherheits-/Rückmeldeeffekte. Pflicht-CI bleibt bestehen.
Die Limits 2.000/Tag und 20.000 gesamt bleiben; bereits verlorene optionale Traces
werden nicht rekonstruiert. Dauerhafte Kapazitätsplanung braucht zusätzlich
autorisierten Export/Archivierung ohne Löschen der vorhandenen Historie.

## Offen und nächster Schritt

Quellcodefixes separat committen/pushen und PR-Prüfungen auswerten; kein Merge oder
Release ohne vereinbarte Gates. Danach geprüften integrierten Paketstand freigeben,
erst dann produktiv aktivieren. Intel-Runner-Konto und ARM-/GitHub-Billing-Hürden
aus PR39 bleiben eigenständig offen. Für vollständige Agent-Kommunikation zusätzlich
ein tatsächliches Grok-Fenster zuordnen und den ChatGPT-Hosttransport aktualisieren.

[Maschinenlesbare Live-Nachweise](evidence/rc17-live-diagnostics-20261026.json)
enthalten nur nötige Metadaten, keine Credentials, Originalauftragsinhalte oder
Rückmelde-Receipt-Tokens.

## Übernahme und sichere Etappen · 29. Oktober 2026

Auftrag `codex_grok_handoff_20261029_01` wurde über die zugehörige
KiraBridge-Konversation gelesen und mit deren Receipt quittiert. Initialer
Arbeitsbaum sauber, Branch `feat/managed-message-route-20261028`, lokaler und
tatsächlicher GitHub-Head `89b88f8`. Beide Vorgängercommits `4f87340` und `89b88f8`
wurden gelesen. Groks Tab `terminal:2767:ttys000`, Shell-PID 45159/Grok 45186,
wurde ausschließlich gelesen; der ursprüngliche Plan wurde zusätzlich aus seiner
gespeicherten Sitzung rekonstruiert. Die dortigen 14 bestandenen Receiver-Tests
sind historische Belege, kein neuer Testlauf dieser Übernahme.

Vier abgeschlossene Etappen sind jeweils separat committed und gepusht:

- `8d5774e`: Restartabschluss verlangt die echte Quittierung der Originalnachricht
  zusätzlich zur passenden finalen Antwort. Acht Zustands-/Ack-Kombinationen grün;
  vorher vier erwartete Fehler und vier Erfolge.
- `291d128`: ThreadDesk-Leseproxy prüft lokalen Rechte-/Opt-in-Widerruf nach
  Lock-Wartezeit und asynchroner Discovery erneut. 20 betroffene Fälle grün;
  die neue Matrix hatte vorher neun Fehler und drei Erfolge.
- `10e337d`: Nur beim Start übernommene zugestellte `running`-Jobs werden weiter
  anhand gespeicherter Belege beobachtet. Spätes Result oder Ack kann Job und
  Handoff ohne Eingabe abschließen. Beteiligte und aktueller Zustand werden neu
  geprüft; neue aktive Jobs sowie `unknown`/`blocked` bleiben unberührt. 31
  Receiver-/HTTP-Fälle bestanden nach drei erwarteten Late-Reply-Fehlern. Der
  unabhängige Review fand anschließend einen Startblocker bei entzogenen Rechten
  des historischen Absenders. Beide betroffenen Fälle wurden rot belegt und
  bestanden nach enger Isolation von `forbidden`; nur diese zwei wurden erneut
  ausgeführt. Andere Fehler propagieren weiter, Rechte werden nicht erweitert.
- `76427f9`: [Modulvertrag V1](UNIVERSAL-BRIDGE-PLAN-20261026.md) und
  [Discovery-Schema](contracts/module-descriptor.v1.schema.json) vorbereitet;
  keine neue Runtimeintegration. Sechs gültige und 18 ungültige Beispiele geprüft.
  Der erste Schema-Lauf scheiterte, weil der vorhandene Validator keinen wirksamen
  `date-time`-Checker registriert hatte. Der gezielte Folgelauf mit explizitem
  Standardbibliothek-Checker bestand, ohne Installation einer Abhängigkeit.

Native Unteragenten prüften Receiver, Terminal-/Workerinventur und Adapter getrennt.
Root prüfte ihre Ergebnisse vor Integration; Receiver und Modulvertrag erhielten
zusätzlich unabhängigen Gegenreview. Ruff/Format der geänderten Pythondateien und
Diffprüfung bestanden. Anfangs gefundene Formatabweichungen wurden korrigiert.
Keine zusätzliche lokale Gesamtsuite und kein vorsorgliches Wiederholungstesten.

| Planschritt | Belegter Stand | Offen |
| --- | --- | --- |
| 0 Inventur | Branch, Logs, Backups, Grok-Bericht und Live-Zustände gelesen | Kein Produktionsfreigabeschluss daraus |
| 1 Abschluss/Restart | Ack-/Late-Reply-/Idempotenzreparaturen gezielt geprüft | Kontrollierte produktive Restartabnahme |
| 2 Terminal/Bindings | Bestehende sichtbare und Hintergrundpfade statisch inventarisiert; Grok-Ziel aktuell | Konfiguriertes Codex-Ziel veraltet; keine automatische Umbindung oder neue Live-Abnahme |
| 3 Worker/Diagnose | Isolation/Timeout-/Diagnosemechanismen statisch geprüft | Live-Diagnosebudget erschöpft; keine neue Kapazitätsabnahme |
| 4 Adapter | Konkretes ThreadDesk-Widerrufsrennen repariert | Weitere Runtimeabnahmen und bekannte fehlende Verzeichnispagination |
| 5 Modulvertrag | Neutraler V1-Vorschlag mit Schema und Produktgrenzen vorbereitet | Consumer, semantische Versionsauflösung, echte Autorisierung und Freshnessprüfung |
| 6 Wiederherstellung | Quelldateien mit Hashreadback gesichert; isolierte Restartfälle und Test-Tab-Cleanup belegt | Produktiver Restore/Rollback, Paket-/Releaseabnahme |

Die neue Sicherung liegt unter
`~/.local/share/kirabridge/backups/codex-grok-stability-20261029-01`; die vorhandenen
Sicherungen `20261029-repair-visible-binding` und `20261029-restart-after-delivery`
blieben erhalten. Vollständige Testausgaben und das Schema-Prüfskript liegen
dauerhaft im Unterordner `evidence` der neuen Sicherung; Hashes und genaue Befehle
stehen im [maschinenlesbaren Nachweis](evidence/stability-handoff-20261029.json).

Ein über die Bridge angeforderter eigener Testfensterauftrag blieb ohne Annahme
oder Start in `queued`. Er wurde als eigener Auftrag abgebrochen, und der
Abbruch wurde unabhängig gelesen, bevor Codex intern genau einen eigenen sichtbaren
Test-Tab öffnete. Terminal.app gruppierte ihn in das bestehende physische Fenster;
es entstand kein separates Installationsfenster. Zwei Test-Sendeversuche wurden
vor Eingabe wegen eines falsch maskierten eigenen Shellprompts abgewiesen; eine
erste Promptkorrektur scheiterte vor Eingabe an der erwarteten Prozessidentität.
Keiner dieser Versuche zählt als Testlauf. Danach liefen die gezielten Prüfungen
sichtbar in demselben Tab 3051/ttys002. Vor dessen Schließen wurden Eigentümerschaft,
exakte Identität und Leerlauf erneut geprüft; ein unabhängiger Katalogread bestätigt
seine Abwesenheit und den Erhalt beider ursprünglichen Agent-Tabs.

Die drei Problemnachrichten sind am Ende unverändert: `61ccf5a9` bleibt
`unknown/receiver_restart` trotz gespeicherter Antwort `15445f23`; `ed182f06` und
`013a112e` bleiben `blocked/conversation_run_limit`, unzugestellt und unquittiert.
Kein erneutes Senden, kein `resume_unsent`, keine Zustandsumdeutung und kein Librarylauf.

[Draft-PR 49](https://github.com/landjunge/KiraBridge/pull/49) enthält den bestehenden
Arbeitsbranch einschließlich früherer Managed-/Terminal-/Whiteboardänderungen.
Die hier dokumentierten lokalen Prüfungen sind keine neue Gesamtabnahme dieser
Vorgängerarbeit. Die einzeln gelesenen macOS-Verify- und Paketannotationen melden
erneut fehlgeschlagene Kontozahlung/Ausgabenlimit und **keinen gestarteten Job**.
Die frühere pauschale Aussage für sämtliche Verify-Jobs war zu weitgehend:
Beim späteren Abruf für `6980b39` waren Linux3.11/3.13 tatsächlich gestartet und
an elf Ruff-Befunden gescheitert; Tests und Build wurden danach übersprungen.
Dieser fehlgeschlagene Lauf und ältere abgebrochene Läufe bleiben als solche
erhalten. Pflichtchecks bleiben offen.

Kein Merge, Release oder Dienstneustart. Der Dienst meldet weiterhin PID 60636,
Instanz `31849a4ff7c346f396b99e31d6fd807d`, Start `2026-10-29T05:14:06Z` und
Startupquellhash `4bb8e3b9…` für 120 Dateien. Sein Quellpfad ist dieser inzwischen
geänderte Worktree; dessen Dateihash nach den funktionalen Fixes `d7cbae44…` ist
separat vom späteren Stand nach den Formatkorrekturen erfasst.
Keine Behauptung, dass neuer Code vollständig geladen oder als geprüftes Paket
installiert sei. Veröffentlicht bleibt `v0.8.0rc14`; RC17 bleibt Entwurf.

Work-memory-Whiteboard bleibt ausschließlich `188ce4729a62`. Inventur und
Codemeilenstein wurden als Einträge 49/50 mit beobachtetem Vorgängerstand und
stabilen Operations-IDs angehängt und vollständig separat gelesen. Der erste
Inventur-Schreibversuch wurde mit `invalid_arguments: Whiteboard actor type is
invalid` vor Mutation abgewiesen. Der unabhängige Katalogread bestätigte weiterhin
48 Einträge und keinen neuen Marker; derselbe Operationsschlüssel wurde nach
Korrektur auf `actor_type=codex` verwendet. Kein blinder Retry oder konkurrierendes
Whiteboard. Als Nächstes sind echte CI-/Paketprüfungen und die kontrollierte
Produktivabnahme nach erfüllten Gates erforderlich.

### Nachtrag: tatsächlich gestartete Linux-CI und eng begrenzte Korrektur

`c961d63` behebt ausschließlich die elf konkret gemeldeten Lintstellen und sieben
zusätzlich vom erforderlichen Formatcheck benannte Dateien des bestehenden Branches.
Originale wurden vor Änderung separat gesichert und zurückgelesen. Sieben reine
Formatänderungen sind zusätzlich durch Gleichheit ihrer Python-ASTs belegt.
Produktionscode erhielt nur Format-, Importreihenfolge- und Docstringkorrekturen.
Die zwei tatsächlichen Teständerungen ersetzen eine pauschale Exception-Erwartung
durch `ValidationError` und einen blockierenden Bystanderprozess durch den eigenen
asynchron gestarteten Kindprozess mit begrenztem Cleanup.

Die zwei betroffenen Prozessfälle und der eine Exceptiontypfall bestanden gezielt;
die restliche Testsuite wurde lokal nicht wiederholt. Diese zusätzlichen Fälle
liefen intern über Codex/native Unteragenten, ohne einen weiteren Terminal-Tab zu
öffnen. Erforderliches `ruff check .` und `ruff format --check .` bestanden für
alle 383 Pythondateien. Unabhängiger Gegenreview fand keinen Commitblocker.

Der konkrete Fehlerlauf ist Verify40903898329 auf `6980b39`; die Linuxjobs
123553371698/123553372604 scheiterten an Ruff. Die getrennt gelesenen
macOS-Verify-/Paketannotationen bestätigen weiterhin 0 ausgeführte Schritte wegen
Kontozahlung/Ausgabenlimit. Die Folge-CI nach dem gepushten `c961d63` wird anhand
ihrer tatsächlichen Jobschritte bewertet; kein früherer Start- oder Erfolgsschluss
wird übertragen. Whiteboardeintrag 51 korrigiert den früheren CI-Wortlaut und wurde
vollständig unabhängig zurückgelesen. Keine Gateumgehung, produktive Aktivierung
oder Wiederholung historischer Aufträge.

Tatsächlicher Folgestand auf `c961d63`: Linux3.11 in Verify40904756345 bestand
Lint, Format und beide gepinnten Peer-Checkouts, wurde aber während pytest durch
die bestehende Concurrency-Regel abgebrochen. Das ist kein Testsuite-Erfolg.
Linux3.13 wurde noch als `in_progress` ohne Jobschritte gemeldet; der zweite
Verify40904765133 wartete ohne Jobs. Beide Paketjobs in40904765086 scheiterten
ohne Schritte. Es liegt daher weiterhin keine vollständige CI-/Paketabnahme vor.
Der aktuelle Quell-Dateibaum nach den Formatkorrekturen hat Hash `f54098e1…`;
der unveränderte Dienst meldet weiterhin seinen Startuphash `4bb8e3b9…`.

### Nachtrag: einzelner Health-Read-Testfehler im abgeschlossenen Linux-Lauf

Verify40905449753 auf `852a016` beendete beide Linux-Suiten tatsächlich mit
jeweils **1 Fehler, 1766 bestanden, 17 übersprungen**; Build wurde übersprungen.
Betroffen war ausschließlich
`test_health_monitors_leave_terminal_read_capacity_available`. Sein Testdouble
für `read_observed` kannte den seit `def45ff` übergebenen Cursorparameter `since`
nicht. Die echte Methode unterstützt ihn bereits. Der Toolfehler lieferte kein
strukturiertes Ergebnis; erst der anschließende Zugriff erzeugte den sichtbaren
`NoneType`-Fehler. Die unabhängige Diagnose bestätigt eine Testvertragsabweichung,
keinen Nachweis erschöpfter Lesekapazität.

Nur dieses Testdouble wurde nach Backup an die reale Signatur angepasst.
Zusätzlich prüft der Test den leeren Standardcursor und den erfolgreichen
strukturierten Toolrückweg, bevor er dessen Inhalt liest. Alle sechs parallelen
Health-Aufrufe, das Verbot von Terminalkatalogproben und die Prüfung des freigegebenen
Leseslots bleiben erhalten. Der einzelne betroffene HTTP-Fall bestand danach;
Ruff/Format der Testdatei ebenfalls. Keine lokale Gesamtsuite, kein Produktionscode,
keine Kapazitäts-/Rechteänderung oder unsichtbare Ersatzroute aus diesem Fix.
Der Fehlerlauf bleibt als fehlgeschlagen erhalten; die nachfolgende Pflicht-CI
ist gesondert zu beurteilen.

## Lokale Intel-macOS-Abnahme für PR49 · 29. Oktober 2026

Auftrag `channel-042858aeda9a4799b45a547029d1424c` wurde im Gespräch
`kira-pr49-review-20261029` empfangen und mit Receipt quittiert. Geprüfte Quelle:
`71bfbb9316481996def5800390e0d8ebe63c3671`, sauberer separater Checkout unter
`/private/tmp/kb-pr49-review-20261029/source`; keine Änderung produktiver Quellen.

Die Codex-Bindung war bereits aktuell: `terminal:3033:ttys001`, Shell70676,
Codex71896. Frischer Katalog, UID/TTY/Prozessstart-/Elternidentitäten und sichtbarer
Auftragsmarker stimmen überein. Deshalb keine Bindungs-/Konfigurationskorrektur.
Dies ist eine OS-/Sitzungsbeobachtung, keine kryptografische Prozessattestation.

Auf Intel macOS15.7.4 mit Python3.11.15 und den exakt gepinnten TD-/TollGate-Exports
bestand ein lokaler isolierter Verify-Lauf: **1782 bestanden, 1 übersprungen,
1 ausdrücklich abgewählt**, 289,24 Sekunden. Der Skip betrifft den optionalen
tatsächlichen AA-Reader ohne Quelle; abgewählt wurde ausschließlich der Test gegen
das echte Operator-Whiteboard. Ruff und Format bestanden für383 Dateien.
Alle **32 Receiver-/Restart-/Late-Reply-Fälle** bestanden im selben Lauf; JUnit
belegt ihre IDs und Ergebnisse. Keine zusätzliche Suite-/Receiverwiederholung.

Zwei saubere Builds derselben Quelle lieferten identische Artefakthashes. Die
echte isolierte launchd-Paketabnahme bestand: Original-RC14-Wheelstart, Upgrade,
authentifizierter Status, Konfigurations-/Credential-/Daten-/Dateierhalt,
Idempotenz bei gleichem PID, eigener Testdienst-Neustart, Crash-Recovery,
Rollback und frische Installation. Alle Pfade und der freie Loopbackport gehören
zur Testinstanz `com.kirabridge.test.accept-pr49-042858ae`. **Keine** dieser
Serviceaktionen betraf den laufenden RC17-Dienst. Die Label-Abwesenheit wurde
vorher und nach dem Harness unabhängig mit `launchctl print`-Code113 bestätigt.
Der Harness verlangt zusätzlich selbst eine geprüfte Abwesenheit beim Cleanup.

Der Paketlauf war im einzigen eigenen Test-Tab3184/ttys002 sichtbar. Nach frischer
Identitäts-/Leerlaufprüfung wurde genau dieser Tab geschlossen; ein separater
Katalogread bestätigt seine Abwesenheit und beide ursprünglichen Agent-Tabs.
Der produktive Dienst behält PID60636, Instanz31849a4f…, Start05:14:06Z und den
unveränderten Startupquellhash. Die tatsächliche Konfigurationsdatei hat weiterhin
Hash52747b83…; die drei historischen Problemnachrichten sind exakt unverändert.
Kein produktiver Restore, kein Replay, Merge, Release oder Deployment.

[Maschinenlesbare Belege](evidence/pr49-local-macos-20261029.json) enthalten Pins,
Versions-/Hash-/Paket-/Erhaltungsnachweise. Vollständige Logs, JUnit und private
Artefakte liegen mit geprüftem Hashmanifest unter
`~/.local/share/kirabridge/backups/pr49-local-macos-20261029-042858ae`.
Ein anfänglicher Peer-Extraktionsversuch scheiterte vor Tests am älteren
Shell-Python; das leere Ziel wurde geprüft und die Extraktion mit dem dedizierten
Python3.11 ausgeführt. Dieser Setupfehler zählt nicht als Test.

Diese lokale Intel-Abnahme ersetzt keine erforderlichen GitHub-Checks. ARM,
Signierung/Notarisierung und GitHub-Reviewfreigabe bleiben offen; die bisherigen
macOS-Runner waren durch Billing gesperrt. Die hiesige Dokumentationsänderung
verändert keinen geprüften Pythonquellcode. Nächster sicherer Schritt: externe
GitHub-/ARM-/Reviewgates regulär ermöglichen und abschließen; Merge, Release und
produktive Änderungen benötigen danach eine erneute Freigabe.

# Priorität 1 · direkte Queue-/Terminalzulassung · 29. Oktober 2026

Neuer ausdrücklicher Nutzerauftrag vor Masterplan und ThreadDesk-Aufräumen.
[Vollständiger Befund und Reparaturvertrag](QUEUE-DIRECT-ADMISSION-20261029.md),
[minimierter Snapshot](evidence/queue-priority1-20261029.json).
Die früheren Berichte bleiben unverändert als datierte Belege erhalten.

Produktiv unverändert: RC17/PID60636, Instanz31849a4ff7c346f396b99e31d6fd807d.
Konfigurationshash52747b8353bef4cc162997c34c30d8e759ca0691725d902f313ce4653cf903c2
und beide Credentialdateien stimmen mit der Sicherung vor diesem Auftrag überein.
Beide ursprünglichen Agenten71896/45186 und weitere Codex-Sitzung90216 bestehen.
Keine produktive Terminaleingabe oder Dienständerung.

Bereinigt wurden **0 historische produktive Einträge**: kein queued Receiver-Job
im konsistenten Ausgangssnapshot; keine nachweislich nie gestartete aktive
Ausführungsblockade. Inbox-Ergebnisse und Completionhinweise werden nicht als
ungestartete Arbeit gelöscht. Historische unknown/blocked einschließlich
61ccf5a9/ed182f06/013a112e bleiben im erneuten Vergleich unverändert.

Reparatur auf isoliertem Branch `fix/queue-direct-admission-20261029`, Ausgang36a7c5c:
einmalige sichtbare Nachrichten-/native Taskzulassung, konkrete Fehler statt
endlosem Warten, unveränderliche Idempotenzbelege, Zielpinning und bestehende
Eingabe-/Berechtigungsprüfungen. Neue sicher vor Eingabe abgelehnte Nachrichten
werden über vorhandene Holds von späterer Zustellung ausgeschlossen; keine Holds
auf vermutete unbekannte Ausführungen. Native Antwortwartende blockieren keinen
normalen Worker. Frische CLI-Freigaben bleiben möglich; alte queued Historie
wird nicht automatisch aufgenommen. Shutdown-/Late-Reply- und Cleanup-Rennen
gezielt korrigiert; kein CWD als Ursache erfunden.

Lokale gezielte Prüfung in mehreren überlappenden Teil-/Korrekturläufen, keine
erneute Gesamtsuite:55 aktuelle Admission-/Mixed-/Shutdown-/HTTP-Fälle bestanden;
135 weitere Receiver-/MCP-/Handoffprüfungen bestanden, ein geänderter alter
Cancellationvertrag anschließend einzeln bestanden. Zuvor196 Bestandsfälle und
86 Task-/Approval-/Nachrichtenfälle bestanden; ihre Laufmengen überlappen und
werden nicht addiert. Fünf an den neuen Vertrag angepasste Faultboundary-Fälle
nach reproduzierten Fehlern gezielt4+1 bestanden. MCP-Rechteentzug nach der neuen
Wartephase2 Fälle bestanden. Unterbrochene/fehlgeschlagene erste Läufe bleiben
in den privaten JUnit-/Toolprotokollen sichtbar, kein Gesamtpass daraus behauptet.
Zusätzlich2 Runlimit-/Inbox-Holdfälle und ein vollständiges Receiver-Stop-/Start-
Interleaving ergänzt; zuletzt6 direkt betroffene Lifecyclefälle bestanden.
Ruff vollständig grün;390 Dateien formatiert; `git diff --check` und `uv build`
bestanden. Tests benutzen private Stores, fake Terminal-I/O und Loopback-MCP.

Backup vor Änderung verifiziert unter
`~/.local/share/kirabridge/backups/queue-priority1-20261029-201843`.
Nachsicherung mit isoliertem Quellrestore:
`~/.local/share/kirabridge/backups/queue-priority1-final-20261029-v2`.
Der erste Restoreversuch hatte bytegleiche Inhalte, aber durch die private Umask
0600 statt gespeicherter0644-Dateimodi; er wurde ausdrücklich nicht als bestanden
gezählt. Der korrigierte Ablauf stellt die im Manifest gespeicherten Modi nur im
privaten Restoreziel wieder her und vergleicht anschließend Bytes und Modi.
Commit/Push und neue Head-CI werden mit ihren tatsächlichen Ergebnissen festgehalten.
Merge, Release, Installation und
produktiver Neustart benötigen weiterhin neue ausdrückliche Freigabe.
