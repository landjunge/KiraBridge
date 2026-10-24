# KiraBridge

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/design/icons/dark/KiraBridge-dark-128.png">
  <img src="assets/design/icons/light/KiraBridge-light-128.png" alt="KiraBridge" width="96" height="96">
</picture>

**Turn your ideas into work on your computer.**  
**Aus deinen Ideen werden Aufgaben auf deinem Rechner.**

[English](#english) · [Deutsch](#deutsch) · [Published / Veröffentlicht RC14](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc14)

## English

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

**RC15 is an unpublished candidate.** Its wheel, macOS bundle, bootstrap and
SHA-256 checksums are available to authorized reviewers in the
[RC15 release draft](https://github.com/landjunge/KiraBridge/releases/tag/untagged-315af41126d778a271e1).
The installation command is [below](#install--update--installieren--aktualisieren).

The installer changes were merged through [PR #21](https://github.com/landjunge/KiraBridge/pull/21)
and the documentation through [PR #22](https://github.com/landjunge/KiraBridge/pull/22)
on the owner's explicit merge instruction. **Publication remains blocked:** GitHub
Actions does not start jobs because of account billing/spending limits. Successful
CI and release acceptance remain outstanding; a merge is not release approval.

For a **first installation**, the command creates a scoped project setup with
individual approvals. For an **update**, run the same command; existing
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

### Control and optional tools

You configure access to files, commands and assistants. New connections use
individual approvals by default; an operator can explicitly allow selected
actions without repeated approval. Assistants cannot grant themselves more rights.

KiraBridge works independently. An optional ThreadDesk connection can keep project
information and threads together. Creating a thread does not itself start a coding
task. Further assistant adapters and their limits are described in the
[provider guide](docs/providers/README.md).

### What has been checked?

On actual **macOS 15.7.4 / Intel x86_64**, **960 regression tests passed**.
Two builds produced identical checksums. The real authenticated draft-download
command, fresh installation, RC14-wheel upgrade, version/status, idempotence,
launchd restart, automatic crash recovery and rollback passed in isolated paths.
Configuration, credential hashes, a database row and a user file survived the update.
The production installation was not modified.

The [acceptance report](docs/ACCEPTANCE-MACOS-RC15.md) records the exact command,
artifact hashes and remaining gates. These local results do not establish a
successful GitHub CI or Apple Silicon run. Mobile, Live voice and end-to-end
ChatGPT remain separate unverified checks.

---

## Deutsch

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

**RC15 ist ein unveröffentlichter Kandidat.** Wheel, macOS-Paket, Bootstrap und
SHA-256-Prüfsummen liegen für berechtigte Reviewer im
[RC15-Release-Entwurf](https://github.com/landjunge/KiraBridge/releases/tag/untagged-315af41126d778a271e1).
Der Installationsbefehl steht [unten](#install--update--installieren--aktualisieren).

Die Installer-Änderungen wurden über [PR #21](https://github.com/landjunge/KiraBridge/pull/21)
und die Dokumentation über [PR #22](https://github.com/landjunge/KiraBridge/pull/22)
auf ausdrücklichen Merge-Auftrag des Eigentümers integriert.
**Die Veröffentlichung bleibt gesperrt:** GitHub Actions startet wegen eines
Zahlungs-/Ausgabenlimits des Kontos keine Jobs. Erfolgreiche CI und Release-Abnahme
stehen noch aus; ein Merge ist keine Release-Freigabe.

Bei der **Erstinstallation** legt der Befehl einen begrenzten Projektzugang mit
Einzelgenehmigungen an. Für ein **Update** denselben Befehl wiederholen;
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
verwenden standardmäßig Einzelgenehmigungen. Der Betreiber kann ausgewählte
Aktionen ausdrücklich ohne wiederholte Bestätigung erlauben. Assistenten können
sich selbst keine zusätzlichen Rechte geben.

KiraBridge funktioniert eigenständig. Über eine optionale ThreadDesk-Anbindung
lassen sich Projektinformationen und Threads zusammenhalten. Einen Thread
anzulegen startet für sich noch keinen Programmierauftrag. Weitere
Assistenten-Anbindungen und ihre Grenzen stehen in der
[Anbieterübersicht](docs/providers/README.md).

### Was wurde geprüft?

Auf echtem **macOS 15.7.4 / Intel x86_64** bestanden **960 Regressionstests**.
Zwei Builds lieferten identische Prüfsummen. Der tatsächliche authentifizierte
Downloadbefehl, Erstinstallation, Update vom RC14-Wheel, Version/Status, idempotente
Wiederholung, launchd-Neustart, automatische Erholung nach Prozessabbruch und
Rollback bestanden in isolierten Verzeichnissen. Konfiguration, Zugangsdaten-Hashes,
ein Datenbankeintrag und eine Nutzerdatei blieben erhalten. Die produktive
Installation wurde nicht verändert.

Der [Abnahmebericht](docs/ACCEPTANCE-MACOS-RC15.md) nennt den genauen Befehl,
Paket-Prüfsummen und offene Hürden. Diese lokalen Ergebnisse belegen keinen
erfolgreichen GitHub-CI- oder Apple-Silicon-Lauf. Handy, Live-Sprache und die gesamte
ChatGPT-Verbindung bleiben gesondert ungeprüft.

---

`main` is a separate development lineage (currently 0.7.0rc2); the latest
published code is the RC14 integration lineage. Use release assets for installation.
`main` ist eine getrennte Entwicklungslinie (derzeit 0.7.0rc2); der jüngste
veröffentlichte Stand liegt in der RC14-Integrationslinie. Zur Installation die
Release-Dateien verwenden. [Runtime/install PR #21](https://github.com/landjunge/KiraBridge/pull/21).

## Install / update · Installieren / aktualisieren

**RC15-Kandidat: nur für berechtigte Reviewer des Release-Entwurfs; noch kein
freigegebener Endnutzer-Download. / RC15 candidate: draft reviewers only until CI
and release acceptance pass.** Voraussetzung / prerequisite: Python 3.11, uv 0.11.6 und
angemeldete GitHub CLI mit Repository-Zugriff / authenticated GitHub CLI.
Der Befehl lädt authentifiziert, prüft SHA-256 und installiert oder aktualisiert /
authenticated download, checksum verification and install/update:

```sh
d=$(mktemp -d) && gh release download v0.8.0rc15 -R landjunge/KiraBridge -p 'install-macos.sh*' -D "$d" && (cd "$d" && shasum -a 256 -c install-macos.sh.sha256 && sh install-macos.sh "$@")
```

**Für Erstinstallation und Update derselbe Befehl. RC15 bleibt bis zur Abnahme
unveröffentlicht. / Same command for install and update. RC15 remains unpublished.**

[Download-Voraussetzungen, Status, Neustart, Rollback und Fehlerbehebung /
prerequisites, status, restart, rollback and troubleshooting](docs/INSTALL-MACOS.md).
Keine Apple-Signierung/Notarisierung; kein sudo; vorhandene Konfiguration,
Zugangsdaten und Nutzerdateien bleiben erhalten. / No Apple signing/notarization,
no sudo; existing configuration, credentials and user files are preserved.

## Further reading / Weiterführende Dokumentation

- [RC15 candidate notes / Kandidatenhinweise](docs/RELEASE-0.8.0rc15.md)
- [Control center / Steuerfenster](https://github.com/landjunge/KiraBridge/blob/89c2e4359090de53fb6c1da55b6146072443988d/docs/CONTROL-CENTER-0.8.0rc1.md)
- [ChatGPT connection / ChatGPT-Verbindung](docs/CHATGPT.md)
- [Team coordination / Zusammenarbeit im Team](docs/TEAM-ORCHESTRATION.md)
- [ThreadDesk connection / ThreadDesk-Anbindung](docs/THREADDESK-ADAPTER-20261018.md)
- [Permissions and security / Berechtigungen und Sicherheit](docs/SECURITY.md)
- [Operations and recovery / Betrieb und Wiederherstellung](docs/OPERATIONS.md)
- [Architecture and modules / Architektur und Module](docs/ARCHITECTURE.md)

The published download is pinned to `v0.8.0rc14`; the highlighted command selects
the unpublished `v0.8.0rc15` draft explicitly. `main` and the RC14/RC15 integration
lineage remain separate. / Der veröffentlichte Download gehört zu `v0.8.0rc14`;
der hervorgehobene Befehl wählt ausdrücklich den unveröffentlichten Entwurf
`v0.8.0rc15`. `main` und die RC14/RC15-Integrationslinie bleiben getrennt.

KiraBridge is an independent project and is not an official product of the
connected AI providers. / KiraBridge ist ein eigenständiges Projekt und kein
offizielles Produkt der angebundenen KI-Anbieter.

## Lizenz / License

**Deutsch:** Es gilt die **Netzwerkpunkt Personal Use License 1.0**, eine individuelle Source-available-Lizenz. Private, nicht geschäftliche Nutzung ist kostenlos erlaubt, einschließlich privater Anpassungen und privatem Self-Hosting. Interner Firmeneinsatz, berufliche Nutzung, Weiterverkauf und kostenpflichtige Dienste benötigen eine vorherige schriftliche Erlaubnis beziehungsweise gesonderte Lizenz. Es gibt keine allgemeine Weiterverteilungserlaubnis. Historische Rechte und gesonderte Drittanbieter-Lizenzen bleiben erhalten. [Vollständige Bedingungen](LICENSE).

**English:** The **Netzwerkpunkt Personal Use License 1.0** provides custom source-available terms. Private, non-business use is free, including private modifications and private self-hosting. Internal business or professional use, resale and paid services require prior written permission or a separate license. No general redistribution permission is granted. Historical rights and separate third-party licenses remain intact. [Full terms](LICENSE); the German text governs.

Dies ist keine Open-Source-Standardlizenz; eine anwaltliche Prüfung wurde nicht durchgeführt. / This is not a standard open-source license and has not undergone legal review.

Die Projektseite `kirabridge.netzwerkpunkt.de` bleibt geplant. Noch kein öffentlicher Download und keine Sichtbarkeitsänderung. / The project site remains planned; there is no public download or visibility change.

