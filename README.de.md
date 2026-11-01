[English](README.md) · **Deutsch**

<p align="center">
  <img src="assets/readme/normalized/KiraBridge-large.svg" alt="KiraBridge" width="256" height="256">
</p>

<p align="center">
  <a href="https://github.com/landjunge/threaddesk/blob/docs/product-family-readme-20261031/README.de.md" title="ThreadDesk"><img src="assets/readme/normalized/ThreadDesk-small.svg" alt="ThreadDesk" width="48" height="48"></a>
  &nbsp;
  <a href="https://github.com/landjunge/4AllPass/blob/docs/product-family-readme-20261031/README.de.md" title="4AllPass"><img src="assets/readme/normalized/4AllPass-small.svg" alt="4AllPass" width="48" height="48"></a>
  &nbsp;
  <a href="https://github.com/landjunge/tollgate/blob/docs/product-family-readme-20261031/README.de.md" title="TollGate"><img src="assets/readme/normalized/TollGate-small.svg" alt="TollGate" width="48" height="48"></a>
  &nbsp;
  <a href="https://github.com/landjunge/agent-authority-lab/blob/docs/product-family-readme-20261031/README.de.md" title="Agent Authority"><img src="assets/readme/normalized/Agent-Authority-small.svg" alt="Agent Authority" width="48" height="48"></a>
</p>

<h1 align="center">KiraBridge</h1>

<p align="center"><strong>Du redest mit der KI. Die Arbeit landet auf deinem Rechner.</strong></p>

KiraBridge verbindet ChatGPT mit **Grok Build und Codex, die in Terminalfenstern
auf deinem Computer laufen**. Besprich im Chat, was du erledigen möchtest, gib die
Arbeit an diese Terminalagenten weiter und verfolge ihre Antworten — mit den von dir erlaubten Zugriffen.

**macOS · Intel — [0.8.0rc21](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc21) · 31. Oktober 2026 · Vorabversion**

### [KiraBridge herunterladen — App und Installer](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc21/KiraBridge-0.8.0rc21-Intel-macOS.zip)

[Nur die App, wenn der Dienst bereits installiert ist](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc21/KiraBridge-App-0.8.0rc21-Intel.zip)
· [Prüfsummen](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc21/SHA256SUMS-INTEL)
· [Alle Versionen](https://github.com/landjunge/KiraBridge/releases)

Für die Downloads brauchst du ein GitHub-Konto mit Zugriff auf dieses private Repository.
Dies ist eine Vorabversion; eine stabile Version gibt es noch nicht. RC21 ist für Intel-Macs verfügbar.

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
ist nicht von Apple notarisiert. Unter [Installation und Hilfe](docs/INSTALL-RC21.de.md)
findest du Einrichtung, Updates und bekannte Probleme.

Sichtbare Übergaben an Terminalagenten senden deinen Text unverändert. Die bestätigte Zustellung ist noch keine Antwort oder abgeschlossene Arbeit.

## Geplante Zusammenarbeit

Die fünf Produkte bleiben eigenständig. Geplant ist ein gemeinsamer Ablauf mit **KiraBridge als Kommunikationszentrale**:

| Produkt | Aufgabe im gemeinsamen Ablauf |
| --- | --- |
| [ThreadDesk](https://github.com/landjunge/threaddesk/blob/docs/product-family-readme-20261031/README.de.md) | Bewahrt Projektstand, Wissen und Ergebnisse. |
| [KiraBridge](https://github.com/landjunge/KiraBridge/blob/docs/product-family-readme-20261031/README.de.md) | Vermittelt Aufträge, Rückfragen und Antworten zwischen Chat, lokalen Agenten und Werkzeugen. |
| [4AllPass](https://github.com/landjunge/4AllPass/blob/docs/product-family-readme-20261031/README.de.md) | Verwaltet Zugangsdaten; soll gezielt erlaubte Zugriffe ermöglichen. |
| [TollGate](https://github.com/landjunge/tollgate/blob/docs/product-family-readme-20261031/README.de.md) | Prüft angeschlossene Aufrufe und setzt Verbrauchsgrenzen und Stopps durch. |
| [Agent Authority](https://github.com/landjunge/agent-authority-lab/blob/docs/product-family-readme-20261031/README.de.md) | Zeigt Beobachtungen, Widersprüche und fehlende Belege; erteilt keine Freigaben. |

Einzelne Schnittstellen sind vorhanden. Ein vollständig eingerichteter und geprüfter Ablauf aller fünf Produkte ist noch geplant. Freigaben bleiben beim zuständigen Werkzeug und beim Menschen. KiraBridge und Agent Authority benötigen Zugriff auf ihre privaten Repositorys.

## Lizenz

Private, nicht geschäftliche Nutzung ist unter der
[Netzwerkpunkt Personal Use License 1.0](LICENSE) kostenlos. Geschäftliche Nutzung
benötigt eine gesonderte schriftliche Erlaubnis. Der deutsche Lizenztext ist maßgeblich.

[Entwicklerdokumentation](docs/DEVELOPERS.de.md)
