# KiraBridge RC21: Installation und Hilfe

[English](INSTALL-RC21.md) · [README](../README.de.md)

Diese Anleitung folgt der [veröffentlichten RC21-Paketanleitung](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc21/INSTALLIEREN-RC21-INTEL.txt). Quellstand des Downloads: `7ea0f24ae6c36f689d0889d41071fa8bca8aaf65`.

## Voraussetzungen

Intel-Mac, geprüft auf macOS 15.7.4; Python 3.11 und uv 0.11.6 im Terminal verfügbar. Für den Download ist ein GitHub-Konto mit Zugriff auf das private Repository nötig. Abhängigkeiten werden bei Bedarf aus dem Internet geladen. Ein Swift-Compiler ist nicht nötig. Die App ist ad-hoc signiert und nicht Apple-notarisiert. Apple Silicon und andere macOS-Versionen sind mit diesem Paket nicht abgenommen.

## Installieren oder aktualisieren

1. Lade das [ZIP mit App und Dienst-Installer](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc21/KiraBridge-0.8.0rc21-Intel-macOS.zip) herunter und entpacke es vollständig. Vergleiche die Prüfsumme mit [SHA256SUMS-INTEL](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc21/SHA256SUMS-INTEL).
2. Öffne `KiraBridge-Installieren.command`. Der Installer läuft in einem sichtbaren Terminalfenster. Verwende dein normales Benutzerkonto ohne sudo und keine laufende Codex-/Grok-Sitzung als Installationsfenster.
3. Kopiere `KiraBridge.app` nach `~/Applications` und öffne sie. Schließe eine bereits laufende App vor dem Ersetzen. Die App benötigt den Dienst aus Schritt 2.
4. Folge der [ChatGPT-Verbindungsanleitung](CHATGPT.md). Grok Build oder Codex benötigen eigene Installation, Anmeldung und eine eingerichtete Terminalsitzung als Ziel.

Der Installer erhält vorhandene Konfiguration und Zugangsdaten, prüft laufende Arbeit und legt einen Rückweg an. Eine bereits laufende Installation desselben Quellstands muss nicht erneut installiert werden.

## Bekannte Grenzen und Hilfe

Die [RC21-Releasehinweise](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc21) dokumentieren den geprüften Umfang und die Einschränkungen. Kurze umgebrochene Eingaben können vor Return mit `visible_paste_unconfirmed` abgewiesen werden. Alte unklare Übergaben werden nicht automatisch wiederholt. Zustellung, Agentenantwort und fachlicher Abschluss bleiben getrennt. Eine Freigabe im Chat ersetzt keine fehlenden Betriebssystemrechte. Nicht alle Live-/Voice-Abläufe sind abgenommen.

Die [ausführliche Vorgängeranleitung](INSTALL-DE.md) bewahrt Diagnose und Wiederherstellung für RC20. Verwende deren ältere Downloadbefehle nur bewusst für diese frühere Version. [Entwicklerdokumentation](DEVELOPERS.de.md).
