# Konfigurierter eigener Stopp / Configured owned stop

Tatsächlich auf dem Betreiber-Mac geladen und aus ChatGPT geprüft:
[Fortsetzungsbericht](SEVEN-TOOLS-FORTSETZUNG-20261019.md) und
[minimierte Belege](evidence/workflow-stop-chatgpt-20261019.json). Das ist kein
neuer RC2-Download und keine automatische Nutzer-/Gesamtprojektabnahme.

## Konkreter Vertrag

Dieses additive Wiring ergänzt den [Hostadapter](WORKFLOW-STOP-ADAPTER.md).
Standard: deaktiviert. Kein Task kann den Modus, Projektpfade, Actor, Consumer,
Kontrollspeicher oder importierten Quellstand auswählen. Aktuelle Quelle:
TollGate `53fc57cc2e082d022e65e5929cb2a1e186fba852`, PR37; getrennt vom
historischen Adapterbeleg auf PR35. Runtime-Aktivierung/ChatGPT-Abnahme wird erst
mit tatsächlichem gesondertem Beleg behauptet.

```toml
[workflow_control]
enabled = true
mode = "stop_only"
state_root = "/absolute/private/bridge-state/workflow-control"
actor_id = "kirabridge-cli"
consumer_id = "kirabridge-cli"
source_commit = "53fc57cc2e082d022e65e5929cb2a1e186fba852"
source_package_sha256 = "REPLACE_WITH_ACTUALLY_INSPECTED_PACKAGE_SHA256"

[workflow_control.projects]
example = ["/absolute/authorized/example-project"]
```

Die Vorlage ist ohne echten SHA256 absichtlich nicht gültig. Den SHA256 mit
`kirabridge.configured_workflow.package_fingerprint(Path(tollgate.__file__).parent)`
an der geprüften, installierten Quelle bestimmen. Der begrenzte Manifesthash aller
Pythondateien wird vor dem optionalen Import und erneut bei Voraussetzungenprüfungen
verglichen. Der Gitpin ist gesonderte Betreiberangabe, keine Remoteattestierung.
Root-/Home-Pauschalzuordnung und widersprüchliche identische Projektwurzeln werden
abgewiesen. Bei verschachtelten Projekten gilt der längste konfigurierte Root.

`workflow.stop` benötigt eigene Operationserlaubnis, `task.cancel` und
`process.terminate`. Input: `handoff_id`, positive `revision`, begrenzte technische
`stop_id`. Der aktuelle eigene Stop-Task muss genau diese Argumente enthalten.
Nur local/chatgpt erhalten im autorisierten Betreiberprofil die neue Capability;
andere Principals bleiben unverändert. Health ersetzt keine Readiness.

## Nachweis und Wiederanlauf

- Projekt, kanonisches CWD/Root samt beobachtetem dev/inode, Actor/Consumer,
  Paketfingerprint und tatsächliche Journal-UUID werden dauerhaft zugeordnet.
  Konfigurationsdrift oder ein ausgetauschtes Verzeichnis sperren die Fortsetzung.
- Dieselbe echte Journal-UUID wird **unter der tatsächlichen TG-Sperre** vor
  DISPATCH_ATTEMPTED und vor STOP-Commit erneut geprüft. Wechsel/Verlust erlaubt
  weder neuen Start noch eine falsche EFFECTIVE-Quittung. Unbekannte Versuche
  werden nicht wiederholt. Warten auf diese Sperre blockiert nicht den Eventloop.
- Vor asynchronem Kontrollwarten wird ein eigener Stopwunsch im **vorhandenen**
  Audit vermerkt: UNKNOWN/abort_only, kein behaupteter TG-Effekt. Er sperrt weitere
  Turns auch nach Wiederanlauf oder späterer Aktivierung einer Assembly. Es gibt
  keinen automatischen Wiederfreigabevertrag; neue Arbeit benötigt einen neuen
  tatsächlich ausgestellten Handoff. Audit/Journale nicht löschen oder resetten.
- Auch ein erster, noch nicht gebundener queued/accepted Start kann über seinen
  vorhandenen eigenen Taskeintrag abgebrochen werden. Dabei werden keine fehlenden
  ThreadDesk-/Run-/Quellkennungen erfunden und kein Binding nachträglich eingesetzt.
  Reine Warteschlangenstornierung behauptet keine TG-Barriere.
- Fehlende/geänderte optionale Assembly lässt den Dienst und historische Leser
  weiterlaufen. Eigene Wartetasks/registrierte Prozesse bleiben abbrechbar;
  durable Barriere bleibt UNKNOWN, sofern nicht tatsächlich bestätigt.
- Ein umbenanntes/entferntes CWD verhindert den Stopp eines bereits gebundenen
  Scopes nicht. Abbruch nur über vorhandene eigene Terminalregistrierungen;
  fremde/interaktive Sitzungen werden nicht angefasst.

Readiness trennt `owned_abort_available` von
`durable_barrier_prerequisites`; `barrier_confirmed=false` bleibt eine Vorabprüfung.
Sie schreibt kein Journal. Projektzuordnung und tatsächlicher Stopausgang werden
erst am konkreten Auftrag geprüft. Statezugang ist eine momentane lokale
Berechtigungsprobe, keine garantierte künftige Schreibbarkeit.

Das vorhandene Beobachtungsexportformat projiziert Stopwunsch/PENDING/EFFECTIVE
getrennt. Epochenreferenz ist bei echter Assembly deren gespeicherter Hash;
reine Hostadapter-Scopehashes sind ausdrücklich keine Journalepochen. Runtime
stammt nur aus dem tatsächlichen Stop-Task-Preflight, nicht vom alten Codex-Turn.
Kosten bleiben unbekannt, `hard_cost_cap=false`, externe Restwirkung unbekannt.
Direkte Standalone-Terminal-/Agentenaufrufe werden dadurch nicht global kontrolliert.

## Rückweg

Vor Konfigänderung private Kopie mit denselben Dateirechten und Hash sichern.
Eigene laufende/wartende Tasks berücksichtigen; nur die betroffenen Bridge-Dienste
kontrolliert laden. Bei Rücknahme Queue, Zugangsdaten, Audit und TG-Journale
erhalten. Bereits kontrollierte oder
gestoppte Historie darf nicht automatisch als Standalone fortgesetzt werden.

Für den aktuellen Betreiberstand ist der sichere Funktionsrückweg:
`workflow_control.enabled=false` setzen und die geprüfte neue Guard-Quelle geladen
lassen. Allgemeiner Dienst und historische Leser bleiben verfügbar, kontrollierte
Fortsetzungen gesperrt. Nicht auf alte Builds ohne Stopwunsch-/Historienguard
zurückstufen und damit gestoppte Handoffs ausführen. Ein vollständiger Quelldowngrade
benötigt eine gesondert geprüfte Ausführungssperre; bloßes Erhalten der Journaldatei
gibt alter Software dieses Wissen nicht.

## English

This disabled-by-default operator configuration maps fixed project roots to the
existing owned CLI stop adapter. Tasks cannot choose control identity, paths or
source. The inspected Python package fingerprint is enforced before import and
at prerequisite checks; the separately configured Git pin is an operator claim.
Canonical source-directory identity and real journal UUID bind subsequent turns.
The UUID is rechecked under the actual dispatch/stop lock, including journal
replacement races. Lock waits run outside the event loop.

An owned stop intent is recorded in the existing audit before asynchronous waits.
It blocks new turns across restart and later assembly activation. Queued first
starts without a run binding can be cancelled using their actual owned task,
without inventing source/run identities. Missing control assembly still permits
owned abort; it never establishes a durable TG barrier. A removed CWD does not
prevent stopping a previously bound scope. No foreign session is terminated.

Readiness distinguishes abort availability from barrier prerequisites and never
certifies a committed barrier. Observation export preserves actual stop-task
runtime and separates requested/pending/effective. Cost and external effects stay
unknown; no hard money cap or global control of standalone tools is claimed.
Preserve configuration permissions, queue, credentials, audit and journals on
reload/rollback. Stopped work cannot silently resume; no automatic unlock exists.
Disable the optional assembly while retaining the checked history/stop guards for
feature rollback. Older builds without these guards must not execute stopped
history; preserving a journal alone cannot teach older software to enforce it.
