# KiraBridge

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/design/icons/dark/KiraBridge-dark-128.png">
  <img src="assets/design/icons/light/KiraBridge-light-128.png" alt="KiraBridge" width="96" height="96">
</picture>

**Turn your ideas into work on your computer.**  
**Aus deinen Ideen werden Aufgaben auf deinem Rechner.**

[English](#english) · [Deutsch](#deutsch) · [Download RC12](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc12)

## English

### Start here: live voice and terminal connection

KiraBridge's intended conversational workflow starts with **ChatGPT Live voice mode**: you speak naturally with the assistant in a real-time voice conversation, agree on a task, and explicitly authorize its handoff. This is **not the same as tapping the microphone icon to dictate text** into a message field. Dictation converts speech into text; it is not, by itself, a continuous live voice conversation. Live voice availability and limits depend on the user's ChatGPT setup.

For implementation, KiraBridge uses **terminal interfaces** to hand work to configured coding agents, notably **Codex CLI and Grok Build**. The terminal connection is a separate technical step from the live voice conversation; successful voice input alone does not prove that a terminal command was delivered or executed.

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

The current setup uses a terminal and requires **Python 3.11+, Git and uv**.
Technical setup is still necessary; help from someone familiar with these tools
may be useful. The source supports macOS and Linux. The fresh RC12 package was
tested on Linux; a fresh macOS package installation still needs validation.

### Download and get started

**[Download 0.8.0rc12](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc12)**
— a private prerelease published on 20 October 2026. Access to this repository is
required. This is a release candidate, not the final stable 0.8.0 version.

Choose **`KiraBridge-0.8.0rc12-runtime.tar.gz`**. It includes the installer and
the matching source. Follow the
[RC12 installation guide](https://github.com/landjunge/KiraBridge/blob/v0.8.0rc12/docs/RELEASE-0.8.0rc12.md),
then [connect ChatGPT](docs/CHATGPT.md) and configure the assistants you use.
The first dependency installation needs Internet access. Accounts and credentials
are not included.

This download does not include a newly built native macOS companion app.
Mobile and live voice use still require a separate end-to-end check.

### Control and optional tools

You configure access to files, commands and assistants. New connections use
individual approvals by default; an operator can explicitly allow selected
actions without repeated approval. Assistants cannot grant themselves more rights.

KiraBridge works independently. An optional ThreadDesk connection can keep project
information and threads together. Creating a thread does not itself start a coding
task. Further assistant adapters and their limits are described in the
[provider guide](docs/providers/README.md).

### What has been checked?

RC12 packages fixes for blocked handoffs, missing error feedback and replies
blocked by a full conversation. Its installer also restores the exact bundled
source correctly.

The final Linux test run passed **940 tests**, with **2 skipped**. A fresh package
installation, startup and authenticated connection check passed. These checks do
not replace the pending fresh macOS installation or physical mobile/voice checks.
The release includes the detailed test report.

---

## Deutsch

### Zuerst das Wichtigste: Live-Sprache und Terminal-Schnittstellen

Unser gewünschter Arbeitsweg beginnt mit dem **Live-Sprachmodus von ChatGPT**: Wir besprechen eine Idee in einem laufenden, natürlichen Sprachgespräch, legen den Auftrag fest und geben die Übergabe ausdrücklich frei. Das ist **nicht dasselbe wie das Mikrofon-Symbol zur Spracheingabe** in einem Textfeld. Dort wird Gesprochenes lediglich als Text diktiert; daraus entsteht noch kein fortlaufendes Live-Sprachgespräch. Verfügbarkeit und Nutzungslimits des Live-Modus hängen von der ChatGPT-Konfiguration ab.

Für die eigentliche Umsetzung nutzt KiraBridge **Terminal-Schnittstellen** zu den eingerichteten Coding-Agenten, insbesondere **Codex CLI und Grok Build**. Das Sprachgespräch und die Terminal-Übergabe sind zwei getrennte Schritte. Eine verstandene Spracheingabe beweist noch nicht, dass ein Auftrag im Terminal angekommen oder ausgeführt worden ist.

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

Die Einrichtung erfolgt derzeit über das Terminal und benötigt **Python 3.11+,
Git und uv**. Technische Einrichtung ist also weiterhin nötig; dabei kann dir
jemand helfen, der diese Werkzeuge kennt. Der Quellcode unterstützt macOS und
Linux. Das frische RC12-Paket wurde unter Linux geprüft; eine neue Paketinstallation
unter macOS muss noch geprüft werden.

### Herunterladen und starten

**[0.8.0rc12 herunterladen](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc12)**
— ein privates Vorabrelease vom 20. Oktober 2026. Der Download erfordert Zugriff auf
dieses Repository. Es ist ein Veröffentlichungskandidat, noch keine endgültige
stabile Version 0.8.0.

Wähle **`KiraBridge-0.8.0rc12-runtime.tar.gz`**. Darin sind der Installer und der
passende Quellstand enthalten. Folge der
[RC12-Installationsanleitung](https://github.com/landjunge/KiraBridge/blob/v0.8.0rc12/docs/RELEASE-0.8.0rc12.md),
[verbinde ChatGPT](docs/CHATGPT.md) und richte die gewünschten Assistenten ein.
Für die erste Installation der Abhängigkeiten wird Internet benötigt. Konten und
Zugangsdaten sind nicht enthalten.

Eine neu gebaute native macOS-Begleitapp gehört nicht zu diesem Download.
Die Nutzung am Handy und im Live-Sprachgespräch braucht weiterhin eine gesonderte
Prüfung des gesamten Ablaufs.

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

RC12 enthält Korrekturen für blockierte Übergaben, fehlende Fehlerrückmeldungen und
Antworten, die durch einen vollen Gesprächsverlauf aufgehalten wurden. Außerdem
stellt der Installer den mitgelieferten Quellstand korrekt wieder her.

Beim abschließenden Linux-Testlauf bestanden **940 Tests**, **2 wurden
übersprungen**. Eine frische Paketinstallation, der Start und eine angemeldete
Verbindungsprüfung waren erfolgreich. Das ersetzt nicht die noch offenen Prüfungen
einer neuen macOS-Installation sowie des Ablaufs am Handy mit Sprache. Der
ausführliche Prüfbericht liegt beim Release.

---

## Further reading / Weiterführende Dokumentation

- [RC12 installation and release notes / Installation und Releasehinweise](https://github.com/landjunge/KiraBridge/blob/v0.8.0rc12/docs/RELEASE-0.8.0rc12.md)
- [Control center / Steuerfenster](https://github.com/landjunge/KiraBridge/blob/v0.8.0rc12/docs/CONTROL-CENTER-0.8.0rc1.md)
- [ChatGPT connection / ChatGPT-Verbindung](docs/CHATGPT.md)
- [Team coordination / Zusammenarbeit im Team](docs/TEAM-ORCHESTRATION.md)
- [ThreadDesk connection / ThreadDesk-Anbindung](docs/THREADDESK-ADAPTER-20261018.md)
- [Permissions and security / Berechtigungen und Sicherheit](docs/SECURITY.md)
- [Operations and recovery / Betrieb und Wiederherstellung](docs/OPERATIONS.md)
- [Architecture and modules / Architektur und Module](docs/ARCHITECTURE.md)

The download is pinned to tag `v0.8.0rc12`. The `main` branch may contain a
different development state. / Der Download gehört zum Tag `v0.8.0rc12`; der
Hauptzweig `main` kann einen anderen Entwicklungsstand enthalten.

KiraBridge is an independent project and is not an official product of the
connected AI providers. / KiraBridge ist ein eigenständiges Projekt und kein
offizielles Produkt der angebundenen KI-Anbieter.

## Lizenz / License

**Deutsch:** Es gilt die **Netzwerkpunkt Personal Use License 1.0**, eine individuelle Source-available-Lizenz. Private, nicht geschäftliche Nutzung ist kostenlos erlaubt, einschließlich privater Anpassungen und privatem Self-Hosting. Interner Firmeneinsatz, berufliche Nutzung, Weiterverkauf und kostenpflichtige Dienste benötigen eine vorherige schriftliche Erlaubnis beziehungsweise gesonderte Lizenz. Es gibt keine allgemeine Weiterverteilungserlaubnis. Historische Rechte und gesonderte Drittanbieter-Lizenzen bleiben erhalten. [Vollständige Bedingungen](LICENSE).

**English:** The **Netzwerkpunkt Personal Use License 1.0** provides custom source-available terms. Private, non-business use is free, including private modifications and private self-hosting. Internal business or professional use, resale and paid services require prior written permission or a separate license. No general redistribution permission is granted. Historical rights and separate third-party licenses remain intact. [Full terms](LICENSE); the German text governs.

Dies ist keine Open-Source-Standardlizenz; eine anwaltliche Prüfung wurde nicht durchgeführt. / This is not a standard open-source license and has not undergone legal review.

Die Projektseite `kirabridge.netzwerkpunkt.de` bleibt geplant. Noch kein öffentlicher Download und keine Sichtbarkeitsänderung. / The project site remains planned; there is no public download or visibility change.

