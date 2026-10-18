# Dauerhafte Betreiberrechte / Persistent operator access · 18.10.2026

## Deutsch: Ursache und tatsächlich geladener Stand

Der Dienst war nicht insgesamt schreibgeschützt. Seine alte Programmliste erlaubte
unter anderem Git und zsh, aber kein direktes ps. Die früher eingetragenen
Projektwurzeln deckten spätere externe Worktrees und BlockDesigner nicht ab.
Automatische Genehmigung umgeht diese beiden Prüfungen nicht. Codex hatte bereits
den ausdrücklich eingestellten Modus workspace-write. Keine belegte Regression
dieses Modus; die neue Betreiberentscheidung erweitert die vorher engere Policy.

Die zweite Ursache wiederholter `forbidden`-Antworten ist die Identität: Der
Codex-MCP-Kanal authentifiziert sich als codex; die verbundene ChatGPT-App als
chatgpt. Betreiberrechte wurden gezielt chatgpt/local eingeräumt. Ein fremdes
Task-Ergebnis oder eine Sitzung wird dadurch nicht zu eigenem Arbeitsstand.

Nach erster Aktivierung scheiterte die harmlose Administratorprobe vor einer
Root-Ausführung: `osascript: can't open default scripting component`.
Die direkte lokale Gegenprobe bestätigt: AppleScript-Komponente nicht verfügbar;
explizites JavaScript Automation und Standard Additions funktionieren. Der
Administratoradapter verwendet nun transparent `osascript -l JavaScript` und
`doShellScript(..., {administratorPrivileges:true})`, ohne Passwortparameter.
Das ist derselbe lokale macOS-Autorisierungsweg; kein Abschalten seiner Prüfung.

Geladen: lokale0.5.2 mit Quellcommit
`c6f1eab91f4102fcfaa3d8503141fd18274bb45d`, Runtime
`3cd8af3837174d70a19b1b87281695a1`, Konfig-SHA256
`a5faefcf23380718c4093c5bf48955dc928a2d3b2bc9961d61cb7f5b3005031f`.
Python-Quellfingerabdruck
`deadc7ba4ae21292dd01ae2430bdfe6aa45acdd4bce76dda5a41e45864dc7381`.
Versionsnummer allein unterscheidet diese Backports nicht.
Die neuen Einstellungen sind nicht mit dem unveränderten eingefrorenen privaten
RC2-Paket kompatibel; dessen Installation wurde nicht ersetzt.

## Einrichtung und Bedienung

`~/.config/kirabridge/config.toml` bleibt0600. Unveränderte Originalpolicy liegt
privat unter `~/.local/share/kirabridge/development-permissions-20261018/`, Datei
`config.before-16b425b6d645499a84a760f2baa6d2ec.toml`. Keine Geheimnisse sind in
diesem Repository abgelegt. Betreiberänderung und Laden sind über getrennte
Fingerabdrücke und vorhandene Runtime-/Audit-Belege nachvollziehbar.

| Grenze | Tatsächliche Einstellung |
|---|---|
| ChatGPT/local | automatic; allow_any_executable=true; terminal_roots=["/"] |
| Reguläre Programme | Absoluter Pfad oder Programmname aus festem Betreiber-PATH; Existenz und Ausführbarkeit werden geprüft |
| Entwicklungsumgebung | HOME plus expliziter PATH für lokale CLI-/Brew-/Rust-Werkzeuge; keine Übernahme der gesamten Dienstumgebung oder ihrer Tokens |
| Dateiwerkzeuge | Bestehende Projektwurzeln plus Projects, ThreadDesk-Worktrees, BlockDesigner und beim Abgleich tatsächlich registrierte Worktrees; Symlink- und Bridge-State-Sperren bleiben |
| Andere Principals | Vorhandene getrennte Wurzeln, Programmlisten und Capabilities erhalten; keine globale Freigabe |
| Netzwerk | Loopback, vorhandene Authentifizierung, Origin-/Host-Prüfungen und Tunnel-Zugangsdaten erhalten |
| Codex | Strukturierter Adapter mit workspace-write, approval_policy=never, Projektregeln aktiv, keine rekursive MCP-Anbindung |
| Grok | ACP-Adapter; lokale Werkzeuge nur bei drei ausdrücklichen Freigaben: Konfiguration allow_local_tools, Principal agent.local_tools und Auftrag local_tools=true |
| Grok-Empfänger | Nachrichten setzen local_tools nicht; Text wird nicht zu einer Rechteentscheidung. Kein neuer Grok-Auftrag durch diese Abnahme |
| Administrator | Eigene Operation admin.execute; sichtbare lokale macOS-Autorisierung, keine gespeicherten Passwörter, keine sudoers-/SIP-/TCC-Änderungen |

Das ist umfassende Autorität des authentifizierten Betreibers, keine
OS-Sandbox für beliebige Terminalprogramme. Diese laufen mit den Dateirechten des
Mac-Kontos und können außerhalb der Dateiwerkzeug-Wurzeln wirken. Bestehende
Secrets werden nicht automatisch ins Prozessumfeld oder Audit kopiert; ein vom
Betreiber ausdrücklich gestarteter Befehl kann jedoch auf kontolesbare Daten
zugreifen. Terminal-Vollzugriff ist kein Tresor-Isolationsnachweis für4AllPass.
Absolute Symlink-CWDs wie /tmp können die Descriptor-Prüfung ablehnen; den
tatsächlichen Pfad /private/tmp verwenden. Kein versteckter Interpreterersatz.

Für sichere Abfragen bevorzugen:

```json
{"operation":"policy.inspect","arguments":{}}
{"operation":"agent.status","arguments":{}}
```

Diese Operationen benötigen wie bisher `task_id` und `idempotency_key` in
task_request; danach task_get/task_events lesen. Zusätzlich existieren die reinen
MCP-Lesewerkzeuge policy_inspect und agent_status. Veraltete Werkzeugkataloge
können weiterhin die Taskoperationen verwenden. Policy-Ausgabe nennt die geladene
Konfiguration und Drift, keine Rohkonfiguration mit möglichen Zugangsdaten.
bridge_readiness prüft nun auch working_directories und die tatsächlich verwendete
Programmsuche. Ein grüner Health-Status bleibt kein Arbeitsfähigkeitsnachweis.

Administratorbeispiel, nur mit lokal anwesendem Betreiber auslösen:

```json
{"operation":"admin.execute","arguments":{"argv":["/usr/bin/id","-u"],"cwd":"/Users/landjunge","timeout":60,"max_output":1024}}
```

Den macOS-Dialog lokal bestätigen; Passwort ausschließlich im Systemdialog.
`sudo -n` meldet derzeit korrekt `a password is required`. Nach einem Timeout oder
Abbruch ist das Ergebnis ausdrücklich unknown: zuerst ursprünglichen Task und
Prozesszustand lesen, keine automatische Wiederholung eines Schreibauftrags.
Die echte JXA-Probe `permissions-20261018-admin-jxa` wurde nicht rechtzeitig lokal
bestätigt und steht unknown/admin_timeout, Versuch1. Root-Ausführung bleibt
unbestätigt; eine Kontozugehörigkeit zur Gruppe admin ersetzt diesen Nachweis nicht.

Der lokale Operatorhelfer `scripts/configure_development_access.py` erweitert nur
bestehende local/chatgpt-Profile, prüft den zuvor gelesenen Config-Hash, legt ein
dauerhaft synchronisiertes Originalbackup mit erhaltenen Rechten an und ersetzt
atomar. Er übernimmt keine unbekannte Tabellenform stillschweigend, validiert die
echten Terminalvoraussetzungen vor Änderung und bewahrt andere Principals,
Zugänge, Netzwerk und Messaginglimits. Er startet den Dienst nicht selbst neu.
Für spätere Worktrees vorhandene freigegebene Projektunterordner verwenden;
neue externe Projektwurzeln benötigen eine explizite lokale Ergänzung.

## Tatsächliche Abnahme und Rückweg

Alle folgenden Abläufe liefen über die verbundene ChatGPT-App als chatgpt, nicht
nur als lokale Python-Direktprobe:

- Datei geschrieben und vollständig gelesen; Codex separat beauftragt, neuen
  Testinhalt erzeugt und über file.read unabhängig36Bytes zurückgelesen.
  Task `permissions-20261018-codex`, Sitzung
  `01a15004-3482-7593-85f6-6baf60c23f3d`, turn.completed, exit0, Versuch1.
  Das ist ein Turnnachweis, keine Abnahme aller Projekte oder Übernahme einer
  bereits offenen interaktiven Sitzung.
- ps direkt und als normaler Programmname; Git im neu freigegebenen BlockDesigner.
  GitHub-CLI mit vorhandener Anmeldung bestätigt isPrivate=true, ohne Zugangsdaten
  auszugeben. Groks echter ACP-Initialize antwortet mit Protokoll1 und cached_token;
  kein authenticate, session/new oder Modellprompt gesendet. Dies ist ein
  Schnittstellen-, kein aktueller Kontingent-/Modellzugangsnachweis.
  Agentstatus unterscheidet verwaltete Arbeit von lediglich beobachteten Prozessen.
  Kurze Darwin-Prozessnamen beheben die tatsächlich beobachtete Abschneidung durch
  lange fremde Programmpfade; zweiter Lauf observed/truncated=false.
- Eigenes vorhandenes RC2-Wheel ohne Netzwerk/Abhängigkeiten ausschließlich in ein
  synthetisches target-Verzeichnis installiert und wieder deinstalliert. Leeres
  Paketverzeichnis über Dateiwerkzeug bestätigt; echte Installation unverändert.
- Ein synthetischer pytest-Fall und Make-Build über terminal.execute bestanden.
- Eigenen sleep-Prozess gestartet, über process.list als laufend erkannt und
  ausschließlich diesen Prozess mit process.terminate beendet, exit-15.
- Status blieb trotz belegtem regulärem Slot erreichbar. Zweiter kontrollierter
  Dienststart lädt denselben Config- und effektiven Policyhash. Kein kompletter
  Mac-Neustart durchgeführt; RunAtLoad-/KeepAlive-LaunchAgent ist unverändert.
- Alle299 vorherigen Taskzeilen, fünf Nachrichten und vier Empfängerjobs sind
  inhaltlich unverändert. Zugangsdateien, Runtime-Key und LaunchAgent hash-/modusgleich.
  Historische unbekannte Jobs wurden nicht neu gestartet.

Gezielte Codeprüfungen umfassen fehlende und fremde Rechte, echte Initialisierung/
Wiederverbindung ohne Auftragsduplikat, private Konfigbackups und Drift,
Commandauflösung, begrenzte Prozesssicht, Status-Queue, Quoting, Admin-Abbruch und
Grok-Permission mit fremder Session/falscher Werkzeugart. Kein kostenpflichtiger
Grok-/Provideraufruf, kein Systemsoftware-Update und kein fremder Prozessabbruch.

Die kompakten Daten sind aus bestehenden Tasks/Audit abgeleitet:
[Abnahmebeleg](evidence/development-permissions-20261018.json).
Eigene synthetische Dateien werden nach Rücklesen entfernt. Historische Belege
bleiben erhalten. Rückweg: bei ruhender Queue nur passendes Configbackup und
vorherigen Quellpin cb390ba laden; keine Datenbank, Queue oder Zugangsdaten
zurücksetzen. Originalbackup ist0600; dessen Hash steht im Abnahmebeleg.

## English: operation and limits

The owner explicitly enabled full regular terminal access for chatgpt/local.
Unknown commands are resolved through the fixed operator PATH; normal POSIX access
checks still apply. Other principals retain their policies. File tools remain
scoped, with no-follow traversal and private Bridge-state protection. Arbitrary
authorized terminal commands have the user's OS authority; this is not secret
isolation or a filesystem sandbox.

Use policy.inspect for loaded permission/config/source metadata, agent.status for
owned managed work and bounded observations, then task_request/task_get with stable
identifiers. Status operations use the existing reserved control capacity.
Observed interactive processes are not attached sessions; their actual turn state
remains unknown. Configured executables alone do not prove authentication.

The Codex write/readback turn, regular ps/Git commands, synthetic pytest/Make,
isolated offline package installation/removal and owned-process termination passed
through the connected ChatGPT app. The same policy survived a controlled service
restart; a complete Mac reboot was not performed. All299 historical tasks, five
messages, four receiver jobs and authentication/service files were preserved.
The existing GitHub CLI authentication also works. A real, bounded Grok ACP
initialize returned protocol1/cached_token without authentication or a model
prompt. This proves protocol reachability, not current model/account availability.

Administrator execution uses explicit JavaScript Automation and the standard local
macOS authorization dialog. The default AppleScript component is unavailable on
this Mac. No password, sudoers modification or system-integrity bypass is used.
Unattended sudo currently requires authorization. The actual JXA administrator
test timed out without confirmed local approval; it remains unknown, attempt1,
and was not repeated. Root execution still requires a successful local acceptance
test. Interrupted commands are never automatically replayed.

Grok local tools require configuration, principal capability and per-task opt-in;
permissions are bound to the actual ACP session and one local operation. Existing
message receivers remain text-only. No real Grok/model-provider test was started,
and no control of an already-open interactive session is claimed. macOS TCC and
other OS controls remain authoritative. The frozen private RC2 artifact was not
rebuilt or relabeled; public release and Discussion remain pending separately.

## Private Quellsicherung und CI

Der vollständige Integrationsstand1591f735dab35ef0f096308a2e65e4c2fbbc98d8
besteht die vorhandene [Verify-CI](https://github.com/landjunge/KiraBridge/actions/runs/39150150992)
auf macOS15/Python3.11 sowie Ubuntu24.04/Python3.11 und3.13 einschließlich
Prüfungen, Format/Lint und Paketbau. Keine Veröffentlichung oder Aktualisierung
des eingefrorenen RC2-Downloads. Der lokale0.5.2-Backport ist oben getrennt gepinnt.
