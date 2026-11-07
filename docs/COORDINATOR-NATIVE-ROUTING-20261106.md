# C2: native Modellwahl für versiegelte Managed-Worker

Aktueller zusammengeführter Stand: [Integrationsübersicht](BIGPLAN-INTEGRATION-STATUS-20261106.md).
Der korrigierte Pin `843db415ad2fa7b619ae00d7fae2f973bdaaf7ee` ist unabhängig
angenommen. Die offenen Nachtestangaben unten gehören zum damaligen Quellabschluss;
der erste Freeze `6159640` und seine roten Belege bleiben unverändert erhalten.

`BP-COORD-NATIVE-ROUTING-20261106-C2`, Karte `188ce4729a62/d1e023e96e11`,
Claim `a1f44a24a2ab`. Ein KB-Schreiber01a1a7d1 im eigenen Worktree
`coordinator-native-routing-20261106`. Grundlage ist C1
`0e755e8bca668659d442dcb4b84fedbbccad429a`; der bestehende Router
`1605d9acce96906034c62a8abb71c8a3494b8822` wird mit vollständigem Elternstand
integriert. Kein neuer Dispatcher, Rechteaussteller oder Aufgabenledger.

## Begrenzter nativer Opt-in

Der Core wählt den Router beim normalen `Bridge`-Aufbau, wenn im vertrauenswürdigen
lokalen Profil `team.routing` gesetzt ist. Darin stehen ein vorhandener lokaler
ThreadDesk-Workspace, die feste Matrix-Thread-ID und das **bestehende**
`Runtime`-Format aus `capability_routing.router`: Zugangs-/Versionsbelege,
freigegebene Modelle und Roots, Ablaufzeit und privater Zustandsordner.
Ohne diese Einstellung bleibt es beim bisherigen AgentManager.

Ein einzelner Worker erklärt außerdem in `team.workers.<principal>.routing`
seine lokalen Anforderungen, zum Beispiel diesen Schemaausschnitt:

```json
{"workload":"review","effort":"xhigh","independent_of_provider":"openai"}
```

`workload` und `effort` sind ausdrücklich erforderlich. Optional sind `model`
und `min_effort`. Fehlt `model`, bleibt ein vorhandenes `AgentConfig.model` eine
explizite Anforderung; nur sonst entscheidet die Matrix innerhalb des festen
CLI-Providers. Auswahl, Effortunterstützung und Zugang müssen tatsächlich passen.
Diese Angaben kommen nicht aus einer Modellantwort, Planprosa oder READY-Zeichenkette.
Das installierte anfängliche Router-Leseprofil wird dadurch nicht erweitert.

Der Worker muss bereits `execution_scope=separate_managed_session` besitzen.
Vorhandene sichtbare Sitzungen bleiben im bisherigen Weg. Die vollständige
Legacy-Adaptermap bleibt erhalten; auch ein anderer konfigurierter sichtbarer
CLI-Adapter wird nicht durch eine pauschal verkleinerte Map unbenutzbar.
Nicht unterstützte geroutete Managed-Adapter werden abgewiesen. Codex,
GrokACP und **GrokStructured** bleiben eigene bestehende Adapter. Ein strikter
Grok-Review wird niemals still in ACP, Queue oder einen API-Weg umgewandelt.

## Ein Auftrag, vorhandene Autorität, erneuter Livecheck

`NativeRouting.profile(task, args)` baut einen Router-Task ausschließlich aus dem
tatsächlich gespeicherten, akzeptierten/running Coreauftrag, dessen versiegeltem
TeamWork und lokalem Workerprofil. Geprüft werden Principal, Claimzustand/-zeit,
Assignee, echte Core-ID, Operation, ursprüngliche Argumente, feste CWD-/Timeout-
Bindung und vorhandener Seal. Der konfigurierte Executablepfad muss derselbe sein
wie im Runtime-Zugangsbeleg; seine bestehende Dateiidentität fließt in die Bindung.

`Task.read_only` wird aus dem ursprünglichen Sandboxprofil abgeleitet.
`Runtime.allow_write` kann einen vorhandenen workspace-write-Codex zusätzlich
sperren, ihm aber keine Schreibrechte erteilen. `bridge_tools` und zusätzliche
lokale Tools werden nicht freigeschaltet. Grok-Routing bleibt in diesem Paket
read-only. Die bestehenden Core-/Team-/Worktree-/AutoNext-Budgetprüfungen tragen
weiterhin die Ausführungsautorität.

Der vorhandene `DelegationGuard.prepare` prüft Matrix, Accessalter, konkrete CLI-
Version und Subscriptionanmeldung. Langsame Probes laufen außerhalb des Core-
Eventloops. Der bestehende Effortshim und pro Aufruf kopierte AgentConfig setzen
echte Modell-/Effortparameter, ohne globale Defaults oder das Originalprofil zu ändern.

`NativeRouting.authorize(task, args, profile, decision)` vergleicht danach
Matrix-ID, Revision **und** Inhaltsdigest sowie Runtime-/Profilbindung erneut.
Derselbe synchrone Callback läuft im vorhandenen nativen Spawnpfad unmittelbar
vor dem Prozessstart, nach möglichen Warte-/Progressschritten. Dabei werden Team-
Autorisierung und der vorhandene Worktree-/Lease-/Budgetguard erneut aufgerufen.
Dateierzeugung und Inhaltsprüfung des Effortwrappers erfolgen vor diesem letzten
Livecheck; danach folgt der vorhandene Spawnaufruf.
Ein gekippter Claim, abgelaufener Lease/Budgetbeleg oder geänderte Matrix stoppt
ohne Modellstart. Kein unvermeidlicher Profilkonflikt führt zu einem anderen Provider.

Core-Requesthash und Router-Profilhash bleiben verschiedene Hashdomänen. Der
native Request wird nicht neu komponiert oder umetikettiert. Neue Routingfelder
werden bei Opt-out nicht serialisiert; bisherige Worker-/Grantfingerprints bleiben
erhalten. Bei Opt-in bindet der bestehende Grantfingerprint die Routingkonfiguration.
Profiländerungen erfordern einen passenden neuen isolierten Coreaufbau, keinen
heimlichen Austausch eines laufenden Managers.

## Rückmeldung, Resume und UNKNOWN

Vorhandene Progress-, Task- und Completionbelege enthalten `routing_decision`
beziehungsweise eine begrenzte `routing`-Projektion. `model`/`effort` bezeichnen
die Anforderung. Effektive Werte bleiben ohne Beleg `unverified`. Erkannte native
Grok-`modelUsage`-Metadaten werden ausdrücklich als `cli_reported` gespeichert;
eine abweichende ID wird nicht zu einer bewiesenen Aliasgleichheit. Modelltext
selbst kann diese Angaben nicht erzeugen. Completiondaten enthalten keine Prompts,
Runtime-Zugangsliste, Executablepfade oder Schlüssel.

Der vorhandene Core bleibt das einzige Idempotenz-/Wiederanlaufledger. Eine bereits
gespeicherte Routingentscheidung oder ein gerouteter owned-resume wird fail-closed
abgewiesen, bevor neu ausgewählt wird. UNKNOWN wird nicht unter einer Ersatz-ID
wiederholt. Die alten sichtbaren und nicht gerouteten Resumewege bleiben separat.

## Gezielte Nachweise

Alle CLIs, Loginantworten und Modelle sind deterministische lokale Fixtures.
Echte lokale MCP-/Core-/Team-/Processwege prüfen Codex → GrokStructured → Codex-
Verifier mit tatsächlicher Argv/Effortübertragung und striktem Verdict. Das ist
kein Liveprovider- oder Vierprovider-PASS. Zwei Codex plus zwei Grok bleiben ein
Erprobungsziel; C2 erfindet dafür keine weitere Rolle oder zusätzliche Realstarts.

- 71 bestehende gezielte Router-/ManagedLane-/GrokStructuredfälle bestanden.
- Erste neue Runde: 12 bestanden, Claim-Abbruchfall fehlgeschlagen. Die zusätzliche
  Claimzustandsprüfung und reguläre Abbruchmeldung korrigieren diesen konkreten
  Pfad; gezielte Claimregression danach 1 bestanden. Erstfehler bleibt erhalten.
- Zwischenlauf neuer Fälle plus zwei betroffene C1-Konstruktion/Completionwege:
  23 bestanden in31,95s.
- Finaler betroffener Lauf: **48 bestanden in68,06s**, neue C2-Grenzfälle,
  bestehende Completionregression und der geänderte Routertimeoutfall. Kein Skip.
- Nach der zusätzlichen Erhaltung des ursprünglichen GrokStructured-Billinggates:
  Workerchain/Configimmuabilität 2 bestanden; die neue direkte Fixture hatte zuerst
  keinen PATH (gesonderter Umgebungsfehler). Korrigierte Billing-/UNKNOWNproben:
  2 bestanden in2,48s. Der alte Fehlversuch bleibt erhalten, kein Produkt-PASS daraus.
- Der unabhängige Review des ersten Freeze `6159640` fand Datei-I/O des
  Effortwrappers nach der letzten Autorisierung: Budgetentzug dabei erlaubte einen,
  Claimrücknahme drei synthetische Starts. Eigene zwei Negativregressionen gegen
  den unveränderten Produktcode scheiterten ebenso in9,88s. Die enge Korrektur
  prüft den Wrapper zuerst und autorisiert danach: beide Fälle bestanden in2,32s,
  jeweils ohne Start. Alte Belege bleiben erhalten; neuer exakter Reviewfreeze
  und dessen unabhängiger Nachtest werden getrennt im Board/Handoff dokumentiert.
- Nach der Korrektur bestanden 82 betroffene native und bisherige Routerfälle in
  37,04s. Die zusätzliche ausdrückliche Entzugsbestätigung verhindert einen
  scheinbaren Erfolg bei frühem Shimabbruch: beide verschärften Proben bestanden
  danach in2,62s. Diese Läufe überlappen und werden nicht addiert.
- Ruff, Format- und Diffprüfung bestanden. Unabhängige Abnahme bleibt bis zum
  Nachtest der Korrektur offen.

Einstieg: `tests/test_native_capability_routing.py`. `Bridge(..., routing_guard=...)`
ist eine explizite vertrauenswürdige Dependency-Injektion für vorhandene Reader/
isolierte Tests, kein MCP-Argument. Ohne sie wird der konfigurierte lokale
ThreadDesk-Service über `local_source` wiederverwendet. Es gibt keinen Cachefallback
bei fehlender Matrix oder Bibliothek. Native Routertimeouts verlangen hier dieselben
ganzen Sekunden wie der vorhandene Router-Taskvertrag.

## Separater historischer Grok-Transportbefund

Der Originaltask `coord-native-c1-grok-review-20261106-v1` wurde nicht neu gestartet.
Sein Receipt unter `~/.local/state/bigplan-coordination-20261106/native-c1/router/`
enthält `unknown`, keinen nativen Exitcode, keinen Ausgabepfad und keine effektive
Modell-/Effortattestierung. Die damalige **Wrapper**-Rückgabe2 ist durch dessen
`__main__` erklärt und kein belegter Grok-Exitcode2.

Der vorhandene Launcher fasste `OSError`/`SubprocessError` zusammen; der Runner
kann sowohl beim Prozesswarten als auch bei unvollständigem Readerabschluss einen
Timeout melden. Der Originalbeleg reicht nicht zur Unterscheidung. C2 bewahrt
Receipt/Lease unverändert und ergänzt für künftige kontrollierte Läufe nur eine
strukturierte Transportfehlerklasse ohne Rohfehler oder Retry. Die synthetische
Timeoutregression belegt diesen Metadatenpfad. Das behebt oder wiederholt keinen
unbekannten Grokturn und stellt keine nachträgliche Grokabnahme dar.

## Lieferung und Grenzen

Keine Installation, produktive Profile/Dienste/Terminals, VMänderung, Mainmerge,
Release, kostenpflichtige API oder Cloud-CI. Native Windows-/Linux-/Desktop-/
Handy-/Mehrbenutzerabnahme und reale Providerattestierung bleiben offen. Windows
für Dirk bleibt im Gesamtplan priorisiert; Restricted/0 von6 wird hier nicht verändert.
Webseite/Downloads erhalten keine neue Verfügbarkeitszusage aus diesem Quellpaket.

Private Logs, Code-/Reviewmanifest, Freeze und Übergabe:
`~/.local/share/kirabridge/backups/bigplan-coordinator-native-routing-20261106-c2/`.
