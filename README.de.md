[English](README.md)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/design/icons/dark/KiraBridge-dark-256.png">
  <img src="assets/design/icons/light/KiraBridge-light-256.png" alt="KiraBridge" width="160" height="160">
</picture>

# KiraBridge

**Du redest mit der KI. Die Arbeit landet auf deinem Rechner.**

KiraBridge verbindet ChatGPT mit **Grok Build und Codex, die in Terminalfenstern
auf deinem Computer laufen**. Besprich im Chat, was du erledigen möchtest, gib die
Arbeit an diese Terminalagenten weiter und verfolge ihre Antworten — mit den von dir erlaubten Zugriffen.

**macOS · Intel — [0.8.0rc20](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc20) · 30. Oktober 2026 · Vorabversion**

### [KiraBridge herunterladen — App und Installer](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc20/KiraBridge-0.8.0rc20-Intel-macOS.zip)

[Nur die App, wenn der Dienst bereits installiert ist](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc20/KiraBridge-App-0.8.0rc20-Intel.zip)
· [Prüfsummen](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc20/SHA256SUMS-INTEL)
· [Alle Versionen](https://github.com/landjunge/KiraBridge/releases)

Für die Downloads brauchst du ein GitHub-Konto mit Zugriff auf dieses private Repository.
Dies ist eine Vorabversion; eine stabile Version gibt es noch nicht. RC20 ist für Intel-Macs verfügbar.

## Wobei KiraBridge dir hilft

- **An lokalen Projekten arbeiten:** Lass deine verbundene KI Projektdateien und
  Protokolle lesen, Dateien bearbeiten oder Befehle ausführen — im erlaubten Rahmen.
- **Mit Terminalagenten arbeiten:** Schicke Aufträge an Grok Build und Codex
  in ihren eingerichteten Terminalsitzungen auf deinem Computer.
- **Die Arbeit verfolgen:** Sieh Anfragen, Nachrichten und Ergebnisse im lokalen Steuerfenster.
- **Den Zugriff bestimmen:** Lege fest, welche Ordner und Aktionen erlaubt sind
  und wann ein Auftrag deine Freigabe braucht.

ThreadDesk und andere Integrationen sind optional. Der Kern von KiraBridge funktioniert eigenständig.

## Loslegen

1. **Dienst installieren.** Lade das ZIP mit App und Installer herunter und
   entpacke es vollständig. Öffne `KiraBridge-Installieren.command` und folge dem Installer im Terminal.
2. **App öffnen.** Kopiere `KiraBridge.app` in den Ordner `Applications` in deinem
   Benutzerordner (`~/Applications`; bei Bedarf anlegen) und öffne sie. Die App
   verwendet den Dienst aus Schritt 1.
3. **Chat verbinden.** Folge der [ChatGPT-Verbindungsanleitung](docs/CHATGPT.md).
   Bitte ihn zum Einstieg, eine kleine Datei aus einem erlaubten Ordner zu lesen.
   Gib die Anfrage bei Bedarf frei und prüfe das Ergebnis in deinem Chat.

**Voraussetzungen:** Intel-Mac, geprüft mit macOS 15.7.4; Python 3.11 und uv 0.11.6
bereits im Terminal verfügbar; Internet zum Laden von Abhängigkeiten.
Installiere mit deinem normalen Benutzerkonto. KI-Konten und mögliche Anbieterkosten
bleiben getrennt; die Chatverbindung braucht die passenden Kontoberechtigungen.
Für Terminalaufträge müssen Grok Build oder Codex installiert und angemeldet sein.
Richte ihre Terminalsitzung in KiraBridge als Ziel ein.

Diese Vorabversion hat bekannte Einschränkungen bei der Terminalbedienung; die App
ist nicht von Apple notarisiert. Unter [Installation und Hilfe](docs/INSTALL-DE.md)
findest du Einrichtung, Updates und bekannte Probleme.

## Lizenz

Private, nicht geschäftliche Nutzung ist unter der
[Netzwerkpunkt Personal Use License 1.0](LICENSE) kostenlos. Geschäftliche Nutzung
benötigt eine gesonderte schriftliche Erlaubnis. Der deutsche Lizenztext ist maßgeblich.

[Entwicklerdokumentation](docs/DEVELOPERS.de.md)
