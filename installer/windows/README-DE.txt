KiraBridge RC33 für Windows 11 x64

Setup installiert KiraBridge und eine eigene Python-Laufzeit vollständig offline
nur für Ihren Windows-Benutzer. Ein vorhandenes Python bleibt unabhängig.
Startmenü: KiraBridge starten, KiraBridge konfigurieren, KiraBridge deinstallieren.
Zum Beenden die KiraBridge-Konsole schließen; danach ist ein Upgrade möglich.

Der Konfigurationseintrag zeigt den lokalen MCP-Endpunkt und den Datenordner
und lässt Sie einen Port ab 1024 auswählen. Standardport: 8768.
Konfiguration, Zugangsdaten und Aufgabenverlauf liegen standardmäßig unter
%LOCALAPPDATA%\KiraBridge\Data. Sie bleiben bei Upgrade und Deinstallation
erhalten. Eine erneute Installation verwendet sie wieder. Ein vorheriges
Dev-Kit wird nicht automatisch übernommen oder beendet.

Bei Installationsfehlern wird die bisherige Laufzeit wieder ausgewählt. Nach
einem Stromausfall Setup im gleichen Ordner erneut starten. Beschädigte Pakete,
laufende KiraBridge-Sitzungen und Downgrades werden abgelehnt. Setup schreibt
einen Log im temporären Windows-Ordner. Keine automatische Wiederholung von
Tastatur- oder Fensteraktionen.

RC33 bleibt eine Entwicklungsvorschau: lokales authentifiziertes MCP, native
Tastatur, Tastenkombinationen und geschützte Fenstersteuerung. Allgemeine Datei-,
Prozess- und Terminalwerkzeuge sowie ein Windows-Dienst sind nicht enthalten.
Kein Autostart, keine Firewall- oder PATH-Änderungen. Nur im eigenen aktiven
Windows-Desktop benutzen. Nicht signierte Vorabpakete können eine Windows-
Herausgeberwarnung anzeigen; Prüfsummen sind keine Herausgebersignatur.

Lizenz: beiliegende LICENSE.txt. Drittanbieterlizenzen bleiben in der Laufzeit.
