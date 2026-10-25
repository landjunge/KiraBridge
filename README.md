# KiraBridge

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/design/icons/dark/KiraBridge-dark-128.png">
  <img src="assets/design/icons/light/KiraBridge-light-128.png" alt="KiraBridge" width="96" height="96">
</picture>

**Turn your ideas into work on your computer.**  
**Aus deinen Ideen werden Aufgaben auf deinem Rechner.**

[English](#english) · [Deutsch](#deutsch) · [Published / Veröffentlicht RC14](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc14)

## RC17 status / RC17-Stand

Published: **RC14**. Installed and verified on the operator Mac: **RC17/012b592**.
This integration combines current main/PR33, runtime repairs PR32, cleanup PR36
and legacy checkpoint compatibility PR35; it is not yet a newly accepted package.
Design PR34 remains separate and uninstalled.

Veröffentlicht bleibt **RC14**, produktiv läuft geprüftes **RC17/012b592**.
Dieser Integrationsbranch führt main/PR33, Laufzeitreparaturen PR32,
Abnahme-Cleanup PR36 und Checkpoint-Kompatibilität PR35 zusammen. Die
Designvorschau PR34 bleibt separat. Bestehende Paketnachweise gehören zu ihren
exakten Quellpins und gelten nicht automatisch für diesen integrierten Stand.

The existing Debian vServer runners execute Linux CI. A concrete Python3.13
rewrite/idle safety regression and the build/smoke contract are repaired locally;
Linux3.13 and final package checks remain separate gates.
Hosted macOS jobs remain billing-blocked; no skipped or failed gate is a pass.
Die vorhandenen Debian-Runner führen Linux-CI aus. Ein konkreter Python3.13-
Rewrite/Idle-Fehler und der Build/Smoke-Vertrag sind lokal gezielt repariert;
Linux3.13 und finale Paketabnahme stehen noch aus;
gehostete macOS-Jobs bleiben abrechnungsbedingt blockiert. Kein Pflichtcheck
wird umgangen. [Latest installed proof](docs/RC17-RESUME-20261025.md) ·
[Library contract and compatibility](docs/LIBRARY-COMPAT-20261025.md).

## English

**Current source: RC17 consolidation candidate**, combining main, RC15/RC16 and subsequent repairs. Existing RC15/RC16 draft assets contain historical source pins, not this combined code. [Consolidation and acceptance gates](docs/CONSOLIDATION-20261024.md). The RC17 review command was tested with isolated paths; the operator subsequently authorized an RC17 upgrade. Source, draft assets and installed service must be distinguished.

### Current repair status (unreleased)

The development branch fixes stale explicit visible-agent selection and permits
authorized `session.input(submit=false)` paste without Return. Process identity,
current focus, readiness and unchanged-input guards remain mandatory. Positive
Intel-macOS Kira paste-only input and independent Kira readback passed on installed
`7725bc6`; an earlier transient read timeout remains documented. CI has not run.
[Terminal evidence and limits](docs/VISIBLE-SELECTION-20261024.md).

Whiteboard mutations now preflight fresh peer schemas and report safe character/
byte diagnostics. An isolated real ThreadDesk MCP run verified 10,000 description
characters and 100,000 emoji note characters (400,000 UTF-8 bytes), with independent
readback. Larger content needs an agreed lossless receiver contract, not truncation.
[Whiteboard evidence](docs/WHITEBOARD-BOUNDARIES-20261024.md) ·
[Current integration report](docs/REPAIR-SEQUENCE-20261024.md).
Published RC14 remains unchanged. The authorized operator RC17 installation and
remaining native-input acceptance are documented separately above.

### Start here: live voice and terminal connection

KiraBridge's intended conversational workflow starts with **ChatGPT Live voice mode**: you speak naturally with the assistant in a real-time voice conversation, agree on a task, and explicitly authorize its handoff. This is **not the same as tapping the microphone icon to dictate text** into a message field. Dictation converts speech into text; it is not, by itself, a continuous live voice conversation. Live voice availability and limits depend on the user's ChatGPT setup.

For implementation, KiraBridge uses **terminal interfaces** to hand work to configured coding agents, notably **Codex CLI and Grok Build CLI**. Where configured and permitted, the two CLI agents can exchange tasks, findings and reviews through explicit handoffs; each CLI may also coordinate its own subagents. Parallel work can greatly accelerate complex projects, but the speedup depends on task independence, available resources and usage limits. Agent-to-agent communication and subagents are capabilities to configure and verify, not proof that every installation supports them automatically. The terminal connection is a separate technical step from the live voice conversation; successful voice input alone does not prove that a terminal command was delivered or executed.

### What is KiraBridge?

KiraBridge connects your AI conversation with coding assistants such as Codex and
Grok on your own computer. You describe what you want to build or change. The
bridge passes an explicit task to the configured assistant and makes its replies
and results available through the connection.

It is useful for **software projects of many kinds**: building an application,
adding a feature to an existing program, fixing a bug, running tests or creating
a website. A website is just one example.

### Why use it?

You can discuss an idea, send the agreed work to your coding assistant and follow
the result without repeatedly copying text between a chat and a terminal.
A second configured assistant can review the work. You choose which projects and
actions the connection may access.

For example:

> “Add a search function to my project, test it, and have another assistant review
> the changes.”

### How does it work?

1. **Describe the task.** Discuss the result you want in your connected chat.
2. **Give the instruction.** KiraBridge passes the task to the configured assistant.
   For visible terminal delivery, it uses the explicitly assigned window.
3. **Follow the result.** Questions and results return through the configured
   connection. You can discuss changes and give the next instruction.

A task waiting in a queue has not necessarily reached the terminal. KiraBridge
tracks delivery, acknowledgement and completion separately.

### What do I need?

- A computer with KiraBridge installed and a configured connection to your chat.
- Access to the coding assistants you want to use, including their accounts,
  subscriptions or API access. KiraBridge does not provide these or remove their
  usage limits.
- Permissions for the project folders and actions you want to allow.

For the macOS candidate you need **Python 3.11, uv 0.11.6 and GitHub CLI (`gh`)**,
signed in with access to this private repository. Draft downloads require permission
to view the release draft. The package was tested on **macOS 15.7.4, Intel x86_64**.
Apple Silicon, macOS 26 and older macOS versions remain unverified. A 2015 iMac's
hardware model alone does not establish OS compatibility. See the
[bilingual prerequisites and installation guide](docs/INSTALL-MACOS.md).

### Download and get started

**Latest published release: [v0.8.0rc14](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc14)**
(private prerelease, 22 October 2026; wheel only).

**RC17 is the combined unpublished candidate.** Its wheel, macOS bundle, bootstrap and
SHA-256 checksums are available to authorized reviewers in the
[RC17 release draft](https://github.com/landjunge/KiraBridge/releases).
The installation command is [below](#install--update--installieren--aktualisieren).

[PR #28](https://github.com/landjunge/KiraBridge/pull/28) merged the consolidation into main.
The subsequent ChatGPT repair is in open [PR #32](https://github.com/landjunge/KiraBridge/pull/32).
The separately named candidate below pins `012b592`, actually installed and tested on Intel macOS. Native paste/readback proof remains pinned to its byte-identical native modules from7725bc6.
Standard RC17 draft assets still represent main/b54f462; RC15/RC16 are historical drafts.
**Merged into main; publication remains gated:** GitHub Actions cannot start because of account
billing/spending limits. Additional review was waived by the owner. Native paste-only
input passed; actual ThreadDesk file receiver acceptance remains outstanding. Draft creation is not publication.

For a **first installation**, this explicitly authorized `--full-access` command
grants automatic full filesystem/command access to ChatGPT. Agent/provider accounts
and optional receivers still require real setup. For an **update**, run the same command; existing
configuration, credentials, databases, permissions and user files are preserved.
Active tasks and unfamiliar launchers/services cause an explicit error.
The **launchd service continues running when Terminal or browser windows close**.

Check the running version and status with `~/.local/bin/kirabridge status`.
After tasks finish, restart with
`launchctl kickstart -k gui/$(id -u)/com.kirabridge.bridge` and check status again.
If installation fails, inspect the error and
`~/.local/share/kirabridge/install/logs/`; retry network failures and reject checksum
mismatches. Keep existing permissions unchanged. For rollback, obtain and extract
the candidate bundle and follow the [recovery guide](docs/INSTALL-MACOS.md).

### File transfer and direct terminal control

RC16 adds opt-in transfer of **real unchanged file bytes** from officially supplied
ChatGPT file parameters or explicitly authorized local exports. No Library-wide API,
Drive permission or successful import is inferred. ThreadDesk must implement the
[proposed v1 receipt contract](docs/THREADDESK-FILE-TRANSFER-V1.md); only a verified
persistent-storage receipt counts. See [setup and limits](docs/FILE-TRANSFER.md).

ChatGPT direct terminal commands use a freshly confirmed idle **visible** Terminal.app
shell, or a new separate visible window. Busy/unconfirmed windows are preserved;
there is no hidden replacement session. This rule does not prescribe internal
Codex/Grok execution. ThreadDesk is a separate route. `operation_catalog`,
`bridge_health` and `agent_inventory` distinguish grants, observation and execution.
See [discovery and terminal behavior](docs/DISCOVERY-VISIBLE-TERMINAL.md).

### Control and optional tools

You configure access to files, commands and assistants. New connections use
individual approvals unless the operator explicitly grants full access; selected
actions without repeated approval. Assistants cannot grant themselves more rights.

KiraBridge works independently. An optional ThreadDesk connection can keep project
information and threads together. Creating a thread does not itself start a coding
task. Further assistant adapters and their limits are described in the
[provider guide](docs/providers/README.md).

### What was checked?

RC17: two exact-source builds match; the authenticated draft command passed isolated Intel-macOS fresh install, RC14 upgrade, status/version, data preservation, idempotence, restart, KeepAlive and rollback. [RC17 proof](docs/ACCEPTANCE-MACOS-RC17.md). Native paste-only input passed on7725bc6; successful CI remains open. The owner waived additional review.

RC16's [acceptance record](docs/ACCEPTANCE-MACOS-RC16.md) distinguishes actual Intel
macOS tests, isolated byte/MCP contract fixtures and unverified product integration.
The RC15 [historical installer proof](docs/ACCEPTANCE-MACOS-RC15.md) remains available.
Those historical RC16 checks modified no production installation/configuration. Apple Silicon, live ChatGPT
file selection and actual ThreadDesk durable imports must not be inferred from fixtures.

---

## Deutsch

**Aktueller Quellstand: RC17-Konsolidierungskandidat**, aus main, RC15/RC16 und nachfolgenden Reparaturen. Vorhandene RC15/RC16-Draft-Assets enthalten historische Quellstände, nicht diesen zusammengeführten Code. [Zusammenführung und offene Abnahmen](docs/CONSOLIDATION-20261024.md). Der RC17-Reviewbefehl wurde mit isolierten Pfaden geprüft; der Betreiber hat danach sein RC17-Upgrade freigegeben. Quellstand, Draft-Assets und installierter Dienst sind getrennt nachzuweisen.

### Aktueller Reparaturstand (unveröffentlicht)

Der Entwicklungsbranch behebt veraltete explizite Agenten-Zuordnungen und erlaubt
autorisierte reine Paste mit `session.input(submit=false)` ohne Return. Prozess-,
Fokus-, Bereitschafts- und Eingabeprüfungen bleiben verpflichtend. Die positive
Intel-macOS-Eingabe über Kira und ein unabhängiges Kira-Readback sind auf installiertem
`7725bc6` bestanden. Ein vorübergehender Lese-Timeout ist dokumentiert; CI lief nicht.
[Terminalbelege und Grenzen](docs/VISIBLE-SELECTION-20261024.md).

Whiteboard-Mutationen prüfen frische Peer-Schemas und melden sichere Zeichen-/
Byte-Diagnosen. Ein isolierter echter ThreadDesk-MCP-Lauf bestätigte 10.000 Zeichen
Beschreibung und 100.000 Emoji Notiz (400.000 UTF-8-Bytes) mit separatem Readback.
Größere Inhalte benötigen einen verlustfreien Empfängervertrag statt Abschneiden.
[Whiteboardbelege](docs/WHITEBOARD-BOUNDARIES-20261024.md) ·
[Integrationsstand](docs/REPAIR-SEQUENCE-20261024.md).
Veröffentlicht bleibt RC14. Der Betreiber-Mac wurde auf RC17/012b592 aktualisiert;
Quellstand, private Kandidaten-Assets und tatsächlicher Dienst sind getrennt belegt.

### Zuerst das Wichtigste: Live-Sprache und Terminal-Schnittstellen

Unser gewünschter Arbeitsweg beginnt mit dem **Live-Sprachmodus von ChatGPT**: Wir besprechen eine Idee in einem laufenden, natürlichen Sprachgespräch, legen den Auftrag fest und geben die Übergabe ausdrücklich frei. Das ist **nicht dasselbe wie das Mikrofon-Symbol zur Spracheingabe** in einem Textfeld. Dort wird Gesprochenes lediglich als Text diktiert; daraus entsteht noch kein fortlaufendes Live-Sprachgespräch. Verfügbarkeit und Nutzungslimits des Live-Modus hängen von der ChatGPT-Konfiguration ab.

Für die eigentliche Umsetzung nutzt KiraBridge **Terminal-Schnittstellen** zu den eingerichteten Coding-Agenten, insbesondere **Codex CLI und Grok Build CLI**. Bei entsprechender Einrichtung und Freigabe können beide CLI-Agenten über ausdrücklich geregelte Übergaben Aufgaben, Erkenntnisse und Prüfergebnisse miteinander austauschen. Jede CLI kann außerdem eigene Unteragenten koordinieren. Durch parallele Arbeit lässt sich die Umsetzung komplexer Projekte erheblich beschleunigen. Der tatsächliche Geschwindigkeitsgewinn hängt jedoch von der Aufgabenteilung, den verfügbaren Ressourcen und den Nutzungslimits ab. Diese Zusammenarbeit muss jeweils eingerichtet und geprüft werden; sie ist nicht automatisch in jeder Installation aktiv. Das Sprachgespräch und die Terminal-Übergabe sind zwei getrennte Schritte. Eine verstandene Spracheingabe beweist noch nicht, dass ein Auftrag im Terminal angekommen oder ausgeführt worden ist.

### Was ist KiraBridge?

KiraBridge verbindet dein KI-Gespräch mit Programmierassistenten wie Codex und Grok
auf deinem eigenen Rechner. Du beschreibst, was du entwickeln oder ändern möchtest.
Die Bridge übergibt einen konkreten Auftrag an den eingerichteten Assistenten und
macht seine Rückmeldungen und Ergebnisse über die Verbindung zugänglich.

Das hilft bei **unterschiedlichen Softwareprojekten**: eine Anwendung entwickeln,
eine Funktion in ein bestehendes Programm einbauen, einen Fehler beheben, Tests
ausführen oder eine Webseite erstellen. Eine Webseite ist dabei nur ein Beispiel.

### Wozu brauche ich das?

Du kannst eine Idee besprechen, die vereinbarte Arbeit an deinen
Programmierassistenten geben und das Ergebnis verfolgen. Das wiederholte Kopieren
zwischen Chat und Terminal entfällt. Ein zweiter eingerichteter Assistent kann die
Arbeit prüfen. Du bestimmst, auf welche Projekte und Aktionen die Verbindung
zugreifen darf.

Zum Beispiel:

> „Ergänze eine Suchfunktion in meinem Projekt, teste sie und lass die Änderungen
> von einem zweiten Assistenten prüfen.“

### Wie funktioniert es?

1. **Aufgabe besprechen.** Du erklärst im verbundenen Chat, welches Ergebnis du
   möchtest.
2. **Auftrag geben.** KiraBridge übergibt die Aufgabe an den eingerichteten
   Assistenten. Bei sichtbarer Terminalübergabe verwendet sie das ausdrücklich
   zugeordnete Fenster.
3. **Ergebnis verfolgen.** Rückfragen und Ergebnisse kommen über die eingerichtete
   Verbindung zurück. Du kannst Änderungen besprechen und den nächsten Auftrag geben.

Ein Auftrag in der Warteschlange ist noch nicht unbedingt im Terminal angekommen.
KiraBridge unterscheidet deshalb Übergabe, Empfangsbestätigung und Abschluss.

### Was brauche ich dafür?

- Einen Rechner mit installierter KiraBridge und einer eingerichteten Verbindung
  zu deinem Chat.
- Zugang zu den gewünschten Programmierassistenten einschließlich ihrer Konten,
  Abonnements oder API-Zugänge. KiraBridge stellt diese nicht bereit und hebt deren
  Nutzungslimits nicht auf.
- Freigaben für die Projektordner und Aktionen, die du erlauben möchtest.

Für den macOS-Kandidaten brauchst du **Python 3.11, uv 0.11.6 und GitHub CLI
(`gh`)**, angemeldet mit Zugriff auf dieses private Repository. Für den Entwurf ist
zusätzlich die Berechtigung zum Anzeigen von Release-Entwürfen nötig. Geprüft wurde
auf **macOS 15.7.4 mit Intel x86_64**. Apple Silicon, macOS 26 und ältere
macOS-Versionen sind noch ungeprüft. Das Hardwaremodell iMac 2015 allein belegt
keine Betriebssystem-Kompatibilität.
[Voraussetzungen und Anleitung auf Deutsch/Englisch](docs/INSTALL-MACOS.md).

### Herunterladen und starten

**Zuletzt veröffentlicht: [v0.8.0rc14](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc14)**
(privates Vorabrelease vom 22.10.2026; bisher nur ein Wheel).

**RC17 ist der zusammengeführte unveröffentlichte Kandidat.** Wheel, macOS-Paket, Bootstrap und
SHA-256-Prüfsummen liegen für berechtigte Reviewer im
[RC17-Release-Entwurf](https://github.com/landjunge/KiraBridge/releases).
Der Installationsbefehl steht [unten](#install--update--installieren--aktualisieren).

[PR #28](https://github.com/landjunge/KiraBridge/pull/28) hat die Zusammenführung nach main gemergt.
Die folgende ChatGPT-Reparatur liegt in offenem [PR #32](https://github.com/landjunge/KiraBridge/pull/32).
Der separat benannte Kandidat unten ist Quelle `012b592`, tatsächlich auf Intel-macOS installiert und geprüft. Native Paste/Readback ist für seine unveränderten Module aus7725bc6 belegt.
Die Standard-RC17-Draft-Assets stehen noch auf main/b54f462; RC15/RC16 sind historische Entwürfe.
**Nach main gemergt; Veröffentlichung bleibt gesperrt:** GitHub Actions startet wegen
Kontoabrechnung/Ausgabenlimit nicht. Zusätzliche Review auf Nutzeranweisung entfallen;
reine native Eingabe ist bestanden, tatsächliche ThreadDesk-Dateiempfänger-Abnahme bleibt offen. Ein Entwurf ist keine Veröffentlichung.

Bei der **Erstinstallation** fordert dieser ausdrücklich freigegebene Befehl mit
`--full-access` automatischen vollständigen Datei-/Befehlszugriff für ChatGPT an.
Agenten-/Providerkonten und optionale Empfänger benötigen ihre tatsächliche Einrichtung. Für ein **Update** denselben Befehl wiederholen;
Konfiguration, Zugangsdaten, Datenbanken, Berechtigungen und Nutzerdateien bleiben
erhalten. Aktive Aufträge sowie unbekannte Launcher oder Dienste führen zu einer
klaren Fehlermeldung. Der **launchd-Dienst läuft nach Schließen von Terminal oder
Browser weiter**.

Version und Zustand des laufenden Dienstes: `~/.local/bin/kirabridge status`.
Nach Abschluss aktiver Aufträge neu starten:
`launchctl kickstart -k gui/$(id -u)/com.kirabridge.bridge`; danach Status erneut prüfen.
Bei Fehlern die Meldung und `~/.local/share/kirabridge/install/logs/` prüfen.
Netzwerkfehler können erneut versucht werden; bei falschen Prüfsummen abbrechen.
Vorhandene Berechtigungen unverändert lassen. Für einen Rückfall das Kandidatenpaket
beziehen und entpacken; Schritte siehe [Wiederherstellung](docs/INSTALL-MACOS.md).

### Kontrolle und optionale Werkzeuge

Du legst die Zugriffe auf Dateien, Befehle und Assistenten fest. Neue Zugänge
verwenden ohne ausdrückliche Vollfreigabe Einzelgenehmigungen. Der Betreiber kann ausgewählte
Aktionen ausdrücklich ohne wiederholte Bestätigung erlauben. Assistenten können
sich selbst keine zusätzlichen Rechte geben.

KiraBridge funktioniert eigenständig. Über eine optionale ThreadDesk-Anbindung
lassen sich Projektinformationen und Threads zusammenhalten. Einen Thread
anzulegen startet für sich noch keinen Programmierauftrag. Weitere
Assistenten-Anbindungen und ihre Grenzen stehen in der
[Anbieterübersicht](docs/providers/README.md).

### Dateiübertragung und direkte Terminalsteuerung

RC16 überträgt optional **echte unveränderte Datei-Bytes** aus offiziell bereitgestellten
ChatGPT-Dateiparametern oder ausdrücklich autorisierten lokalen Exporten. Kein
Bibliotheks-Vollzugriff, keine Drive-Freigabe und kein Importerfolg wird daraus
abgeleitet. ThreadDesk muss den [vorgeschlagenen v1-Vertrag](docs/THREADDESK-FILE-TRANSFER-V1.md)
umsetzen; erst die geprüfte dauerhafte Speicherbestätigung zählt. [Einrichtung und
Grenzen](docs/FILE-TRANSFER.md).

ChatGPT-Direktbefehle verwenden eine frisch bestätigte freie **sichtbare** Terminal.app-
Shell oder ein neues separates sichtbares Fenster. Beschäftigte/unbestätigte Fenster
bleiben unangetastet; es gibt keine unsichtbare Ersatzsitzung. Diese Regel schreibt
Codex/Grok keine interne Arbeitsweise vor. ThreadDesk ist ein getrennter Zugang.
Werkzeugkatalog, Health und Agenteninventar trennen Rechte, Beobachtung und Ausführung.
[Details](docs/DISCOVERY-VISIBLE-TERMINAL.md).

### Was wurde geprüft?

RC17: zwei identische Builds; authentifizierter Draft-Befehl auf Intel-macOS mit isolierter Erstinstallation, RC14-Upgrade, Status/Version, Datenerhalt, Idempotenz, Neustart, KeepAlive und Rollback bestanden. [RC17-Nachweis](docs/ACCEPTANCE-MACOS-RC17.md). Native reine Eingabe ist auf7725bc6 bestanden; erfolgreiche CI bleibt offen. Zusätzliche Review auf Nutzeranweisung entfallen.

Der [RC16-Prüfbericht](docs/ACCEPTANCE-MACOS-RC16.md) trennt echte Intel-macOS-Tests,
isolierte Byte-/MCP-Vertragstests und noch ungeprüfte Produktintegration. Der
[historische RC15-Installernachweis](docs/ACCEPTANCE-MACOS-RC15.md) bleibt erhalten.
Produktive Installation/Konfiguration blieb unverändert. Aus Testfixtures folgen keine
Apple-Silicon-Abnahme, echte ChatGPT-Dateiauswahl oder ThreadDesk-Produktimporte.

---

RC17 base was merged through [PR #28](https://github.com/landjunge/KiraBridge/pull/28), merge `a74fe613`. The installed012b592 repair remains in open PR32; native evidence is pinned to unchanged7725bc6 modules. Native paste/readback passed; CI did not start because of billing, so merge/release acceptance remains open. Additional review was waived. / RC17-Basis über PR #28 gemergt; die installierte012b592-Reparatur liegt noch in offenem PR32; native Belege beziehen sich auf unveränderte7725bc6-Module. Native Paste/Readback bestanden; CI wegen Abrechnung nicht gestartet, daher keine Merge-/Release-Abnahme. Zusätzliche Review entfallen.

## Install / update · Installieren / aktualisieren

**RC17-Kandidat: nur für berechtigte Reviewer des Release-Entwurfs; noch kein
freigegebener Endnutzer-Download. / RC17 candidate: draft reviewers only until CI
and release acceptance pass (additional review waived by owner).** Voraussetzung / prerequisite: Python 3.11, uv 0.11.6 und
angemeldete GitHub CLI mit Repository-Zugriff / authenticated GitHub CLI.
Der Befehl lädt authentifiziert, prüft SHA-256 und installiert oder aktualisiert /
authenticated download, checksum verification and install/update:

```sh
d=$(mktemp -d) && gh release download v0.8.0rc17 -R landjunge/KiraBridge -p 'KiraBridge-macos-chatgpt-20261024b.tar.gz*' -D "$d" && (cd "$d" && shasum -a 256 -c KiraBridge-macos-chatgpt-20261024b.tar.gz.sha256 && tar -xzf KiraBridge-macos-chatgpt-20261024b.tar.gz && sh KiraBridge/install.sh --full-access "$@")
```

**Für Erstinstallation und Update derselbe Befehl. RC17 bleibt bis zur Abnahme
unveröffentlicht. / Same command for install and update. RC17 remains unpublished.**

[Download-Voraussetzungen, Status, Neustart, Rollback und Fehlerbehebung /
prerequisites, status, restart, rollback and troubleshooting](docs/INSTALL-MACOS.md).
Keine Apple-Signierung/Notarisierung; kein sudo; vorhandene Konfiguration,
Zugangsdaten und Nutzerdateien bleiben erhalten. / No Apple signing/notarization,
no sudo; existing configuration, credentials and user files are preserved.

## Further reading / Weiterführende Dokumentation

- [RC17 candidate notes / Kandidatenhinweise](docs/RELEASE-0.8.0rc17.md)
- [Actual RC17 package acceptance / Echte RC17-Paketprüfung](docs/ACCEPTANCE-MACOS-RC17.md)
- [Control center / Steuerfenster](https://github.com/landjunge/KiraBridge/blob/89c2e4359090de53fb6c1da55b6146072443988d/docs/CONTROL-CENTER-0.8.0rc1.md)
- [ChatGPT connection / ChatGPT-Verbindung](docs/CHATGPT.md)
- [Team coordination / Zusammenarbeit im Team](docs/TEAM-ORCHESTRATION.md)
- [ThreadDesk connection / ThreadDesk-Anbindung](docs/THREADDESK-ADAPTER-20261018.md)
- [Permissions and security / Berechtigungen und Sicherheit](docs/SECURITY.md)
- [Operations and recovery / Betrieb und Wiederherstellung](docs/OPERATIONS.md)
- [Architecture and modules / Architektur und Module](docs/ARCHITECTURE.md)

The published release is RC14. The highlighted command selects the RC17 draft, tested with explicit isolated paths; RC17 is not published. Paste-only Kira input/readback passed on7725bc6, with a transient timeout recorded. / Veröffentlicht bleibt RC14. Der hervorgehobene Befehl wählt den RC17-Entwurf, mit ausdrücklich isolierten Pfaden geprüft; RC17 ist nicht veröffentlicht. Reine Kira-Eingabe/Readback ist auf7725bc6 bestanden, ein vorübergehender Timeout bleibt dokumentiert.

KiraBridge is an independent project and is not an official product of the
connected AI providers. / KiraBridge ist ein eigenständiges Projekt und kein
offizielles Produkt der angebundenen KI-Anbieter.

## Lizenz / License

**Deutsch:** Es gilt die **Netzwerkpunkt Personal Use License 1.0**, eine individuelle Source-available-Lizenz. Private, nicht geschäftliche Nutzung ist kostenlos erlaubt, einschließlich privater Anpassungen und privatem Self-Hosting. Interner Firmeneinsatz, berufliche Nutzung, Weiterverkauf und kostenpflichtige Dienste benötigen eine vorherige schriftliche Erlaubnis beziehungsweise gesonderte Lizenz. Es gibt keine allgemeine Weiterverteilungserlaubnis. Historische Rechte und gesonderte Drittanbieter-Lizenzen bleiben erhalten. [Vollständige Bedingungen](LICENSE).

**English:** The **Netzwerkpunkt Personal Use License 1.0** provides custom source-available terms. Private, non-business use is free, including private modifications and private self-hosting. Internal business or professional use, resale and paid services require prior written permission or a separate license. No general redistribution permission is granted. Historical rights and separate third-party licenses remain intact. [Full terms](LICENSE); the German text governs.

Dies ist keine Open-Source-Standardlizenz; eine anwaltliche Prüfung wurde nicht durchgeführt. / This is not a standard open-source license and has not undergone legal review.

Die Projektseite `kirabridge.netzwerkpunkt.de` bleibt geplant. Noch kein öffentlicher Download und keine Sichtbarkeitsänderung. / The project site remains planned; there is no public download or visibility change.



### RC17 interface note / Schnittstellenhinweis

Routine `bridge_health` no longer scans Terminal windows. Explicit
`observe_terminals=true`, `operation_catalog` or `agent_inventory` refreshes the
observation; cached health metadata is never input readiness. / Normale Health-Polls
belegen keine Terminal-Leseplätze. Frische Fenstererkennung ausdrücklich anfordern.

Events are optional. Cached Apps tools that still require `completion_subscription`
accept `""`; refresh the connector metadata when available. Kira's actual Whiteboard
write and independent readback passed. / Alte Apps-Schemas können das leere
Legacyfeld nutzen; keine zusätzliche Freigabe oder Events-Anmeldung erfinden.
[Interface behavior and limits / Verhalten und Grenzen](docs/DISCOVERY-VISIBLE-TERMINAL.md).


Current operator evidence / Aktueller Betreibernachweis:
[team audit and remaining limits](docs/CHATGPT-BLOCKER-AUDIT-20261024.md) ·
[live7725bc6 proof](docs/evidence/rc17-live-7725bc6-20261024.json).
All42 registered operations were independently read back as authorized and automatic
for Kira. / Alle42 registrierten Operationen wurden für Kira autorisiert und automatisch zurückgelesen.
The copy command was exercised with isolated install paths and service=none; actual
launchd upgrade/status/rollback were verified separately with these same package bytes.
/ Der Kopierbefehl wurde mit isolierten Pfaden und service=none ausgeführt;
echter launchd-Upgrade/Status/Rollback ist für dieselben Paketbytes separat belegt.

Current installed RC17 source / Aktuell installierte RC17-Quelle: **012b592**, with preserved data and42 automatic ChatGPT operations. [25 October build/install/command evidence](docs/RC17-RESUME-20261025.md). PR32 remains open, RC17 draft; latest published RC14. / PR32 offen, RC17 Entwurf, veröffentlicht RC14.

Separate terminal design preview / Separate Terminal-Designvorschau: [Draft PR34](https://github.com/landjunge/KiraBridge/pull/34), [pink Braille wordmark and bridge / pinker Braille-Schriftzug und Brücke](https://github.com/landjunge/KiraBridge/blob/ada6e37df1be607bfdc0dec8428e609c12d46ef8/docs/design-preview/terminal-braille-100.png). Not installed or merged; work stops after presenting this preview pending the next user instruction. / Nicht installiert oder gemergt; nach dieser Vorschau Halt bis zum nächsten Nutzerauftrag.

[Integrated source and vServer validation / Integrierter Quellstand und vServer-Prüfung](docs/VERIFIED-INTEGRATION-20261025.md). This is not a new release or productive deployment. / Kein neues Release und kein neuer Produktivwechsel.
