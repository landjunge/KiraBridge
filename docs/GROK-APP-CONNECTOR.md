# Grok-App und Eve mit KiraBridge verbinden

Der Grok-App-Connector ergänzt den vorhandenen CLI-Arbeitsagenten. Die beiden
Zugänge besitzen unterschiedliche Identitäten:

| Zugang | Bedeutung |
| --- | --- |
| `grok` | Bestehender verwalteter Grok-CLI-/ACP-Arbeitsagent |
| `grok_app` | Externer Teilnehmer aus der Grok-Web-/Handy-App über OAuth und MCP |

Eine Verbindung zum CLI-Programm bestätigt keinen Zugriff aus der Handy-App.
Eve oder ein anderer Sprachmodus gilt erst dann als geprüft, wenn tatsächlich
aus diesem Modus ein authentifizierter Werkzeugaufruf nachgewiesen wurde. Die
lokale OAuth-Freigabe und ein erfolgreicher synthetischer MCP-Test reichen dafür
nicht aus. Eine zusätzliche kostenpflichtige Voice-API wird nicht verwendet.

## Einrichten

Die vorhandene KiraBridge-Installation und ihr authentifizierter lokaler Dienst
müssen bereits eingerichtet sein. Die folgenden Befehle erzeugen einen
getrennten App-Zugang; vorhandene ChatGPT-/Grok-Zugänge, Schlüssel und laufende
interaktive Sitzungen bleiben erhalten.

```sh
kirabridge grok-connector setup --access team
kirabridge grok-connector start
kirabridge grok-connector status
kirabridge approvals
```

`team` ist das Standardprofil für gemeinsame Teamfunktionen. Es übernimmt den
vorhandenen lokalen Freigabemodus. Ist dieser bereits automatisch, entstehen
durch die App-Verknüpfung keine neuen Freigabeklicks je Teamauftrag. Die eigenen
Fähigkeiten und Teamrollen begrenzen weiterhin jeden Aufruf.

Falls ausdrücklich der bereits eingerichtete Funktionsumfang von ChatGPT für
den neuen App-Zugang gewünscht ist, kann bei der Ersteinrichtung stattdessen
`setup --access same-as-chatgpt` gewählt werden. Das erstellt eine eigene Kopie
der Policy mit eigenen Zugangsdaten. Die ursprüngliche `chatgpt`-Policy und die
CLI-Identität `grok` werden dadurch nicht geändert. Ein bereits vorhandenes
anderes App-Profil wird nicht still überschrieben.

`start` startet ausschließlich den eigenen Connector. Es prüft den bereits
geladenen Bridge-Zugang authentifiziert und meldet `bridge_access_ready` sowie
`reload_required`. Ein alter Hauptdienst muss die neue Identität gegebenenfalls
erst bei einem geplanten Neustart laden. Dafür neue Aufträge vorübergehend
anhalten und vorhandene Arbeit geordnet abschließen lassen. Der Connector
signalisiert oder beendet keine Haupt- oder Freigabedienste: Eine vorherige
Leerlaufprüfung allein verhindert kein Rennen mit neu eintreffenden Aufträgen.
Eine gespeicherte Änderung belegt noch nicht, dass der laufende Dienst sie
geladen hat. Die hier dokumentierte Zielinstallation ist bereits aktiv geprüft.

## Adresse und einmalige Anmeldung

Im geöffneten lokalen Freigabebereich **Grok App** wählen. Die lokale Adresse ist
`http://127.0.0.1:8766/grok-connector`; der lokale Starter meldet den Browser an.
Der Bereich zeigt die aktuelle öffentliche MCP-Adresse, beispielsweise
`https://DEIN-TUNNEL.trycloudflare.com/mcp`. Dies ist die Adresse für den Grok-
Connector. Die lokale Freigabeseite bleibt ausschließlich auf dem Mac erreichbar.

1. Im Grok-Konto **Connectors** öffnen, je Oberfläche über die Einstellungen
   oder direkt [grok.com/connectors](https://grok.com/connectors).
2. **New Connector → Custom** wählen und die angezeigte vollständige MCP-Adresse
   eintragen. Die Anmeldung starten.
3. Auf dem Mac im Bereich **Grok App** die dadurch entstandene Anmeldeanfrage
   prüfen: vom Client selbst gemeldeter Name, registrierter Rücksprung zur Grok-
   Anmeldung und angefragter Umfang. Die hervorgehobene **Verbindungskennung**
   muss mit der Kennung im ursprünglichen Grok-Anmeldefenster übereinstimmen;
   sie besteht aus den letzten zwölf Zeichen der Anfrage-ID in Großbuchstaben.
   Nur die gerade selbst gestartete Anmeldung
   mit **Diese Verknüpfung erlauben** bestätigen oder gezielt ablehnen.
4. Im ursprünglichen Grok-Anmeldefenster fortfahren. Die Freigabe verknüpft den
   App-Zugang einmalig; sie ist keine zusätzliche Einzelauftragsfreigabe.

Grok beschreibt benutzerdefinierte MCP-Connectoren über seine Connectorseite
mit Serveradresse und anschließender Authentifizierung. Die konkrete Anordnung
der Einstellungen in einer Handy-App kann davon abweichen.
[Offizielle Grok-Anleitung](https://docs.x.ai/grok/connectors).

Es wird hier kein Grok-Passwort, kein xAI-API-Schlüssel und kein OAuth-Token
abgefragt oder in einen Link kopiert. Die App erhält über den OAuth-Ablauf eigene
kurzlebige Berechtigungen für `grok_app`. Die lokale Oberfläche zeigt keine
Authorization-Codes, Verifier oder Zugangstokens.

## Tatsächliche Verbindung prüfen

Im verbundenen Grok-Chat beispielsweise anweisen:

> Nutze den KiraBridge-Connector. Rufe `bridge_health` und anschließend
> `team_list` auf. Berichte das tatsächliche Ergebnis und deinen authentifizierten
> Zugang. Starte keinen weiteren Agenten und ändere keine Dateien.

Den Ergebnisbeleg mit `kirabridge grok-connector status` und dem Bereich
**Tatsächlichen Aufruf prüfen** abgleichen. Die Zustände haben unterschiedliche
Bedeutungen:

| Nachweis | Was er bestätigt |
| --- | --- |
| Connector konfiguriert | Eine öffentliche Adresse ist eingerichtet |
| Gateway lokal gesund | Der lokale OAuth-/MCP-Eingang antwortet |
| OAuth-Anmeldung bestätigt | Der geprüfte Client wurde lokal zugelassen |
| Authentifizierter MCP-Aufruf protokolliert | Ein Client hat über diesen Zugang tatsächlich ein MCP-Werkzeug aufgerufen |
| Tatsächlicher Aufruf aus der gewünschten Handy-/Eve-Sitzung | Erst die übereinstimmende Beobachtung in dieser Sitzung und der Bridge belegt diesen Bedienweg |

Clientnamen und User-Agent-Angaben allein beweisen weder ein bestimmtes Handy
noch Eve. Deshalb bleibt die Anzeige für Handy-/Sprachmodus ausdrücklich
**nicht verifiziert**, solange dessen echter Werkzeugaufruf nicht gesondert
belegt wurde. Falls Eve keine Connectorwerkzeuge anbietet oder verwendet, kann
KiraBridge diese Anbieterfunktion nicht durch eine lokale Freigabe erzwingen.
Dann zunächst den normalen Grok-Chat getrennt prüfen.

## Im Team zusammenarbeiten

`grok_app` im [Team-Bereich](TEAM-ORCHESTRATION.md) als aktives Mitglied
aufnehmen und eine gewünschte Rolle zuweisen. Der App-Zugang bleibt ein externer
Teilnehmer ohne automatisch gestarteten CLI-Empfänger. In einer aktiven Grok-
Sitzung kann er Nachrichten und gemeinsame Ergebnisse lesen, Aufgaben vergeben
oder eigene externe Aufgaben annehmen und Ergebnisse melden.

Ein Beispiel für einen eingerichteten Koordinator:

> Lies das Team und die offenen Aufträge. Beauftrage Codex über
> `team_work_create` mit der beschriebenen Teilaufgabe. Prüfe später den
> vorhandenen Auftrag und sein Ergebnis. Verwende einen stabilen
> Idempotenzschlüssel und wiederhole keinen unklar beendeten Auftrag.

Die Bridge setzt den Absender aus der authentifizierten OAuth-Identität
`grok_app`. Er lässt sich nicht als frei wählbares Feld auf `grok`, `codex` oder
`chatgpt` ändern. Teamrollen erweitern keine Datei-, Programm- oder Anbieterrechte.
Eine Rolle weckt keine inaktive Handy-App. Bestehende private Aufträge werden
nicht automatisch mit dem neuen App-Zugang geteilt.

## Tunnel, Neustart und Betrieb

Der verwaltete Eingang bindet lokal standardmäßig an Port 8767. Nur dieser
separate Gatewayport wird durch den eigenen ausgehenden Tunnel erreichbar;
der Hauptdienst und die lokale Freigabeseite werden nicht mit veröffentlicht.
Der Standard verwendet einen vorhandenen offiziellen `cloudflared`-Client.
Bei Bedarf dessen bestehenden Pfad mit `setup --cloudflared /ABSOLUTER/PFAD`
angeben.

Für den Standard-Quick-Tunnel ist kein zusätzliches Cloudflare-Konto nötig.
Die temporäre öffentliche URL kann sich beim Tunnelneustart ändern. Grok
benötigt dann die neue MCP-Adresse und eine neue OAuth-Verknüpfung. Die
gespeicherten Berechtigungen sind an die ursprüngliche öffentliche Origin
gebunden. Ein Tunnel ersetzt die OAuth-Authentifizierung nicht.
[Offizielle Grok-Tunnelanleitung](https://docs.x.ai/grok/connectors/custom-mcp-tunneling).

Die lokale Oberfläche liest das vom eigenen Supervisor privat gespeicherte
Laufzeitprofil. Nach einem erkannten Profilkonflikt wird die alte Adresse nicht
weiter als gültige Verbindungsadresse angeboten. Bei einer fehlenden
Entscheidungsantwort zuerst aktualisieren; die Oberfläche sendet keine Freigabe
automatisch erneut.

Eine bereits selbst bereitgestellte stabile HTTPS-Adresse kann bei der
Ersteinrichtung mit `setup --public-origin https://DEIN-EIGENER-HOST` gewählt
werden. DNS, Zertifikate und der vorgeschaltete HTTPS-Zugang werden dadurch
nicht eingerichtet. Nur den separaten Gatewayport weiterleiten. KiraBridge
verwendet Streamable HTTP mit JSON-Antworten und benötigt hierfür keinen alten
SSE-Transport.

```sh
kirabridge grok-connector status
kirabridge grok-connector stop
```

`stop` beendet den eigenen Connectorbetrieb; vorhandene Codex-/Grok-Arbeit und
andere Tunnel bleiben unberührt. Einzelne Connectorclients können gezielt mit
`kirabridge grok-connector revoke CLIENT_ID` widerrufen werden. Die lokale
Terminalalternative für eine gerade geprüfte Anfrage lautet
`kirabridge grok-connector approve REQUEST_ID`, zum Ablehnen zusätzlich `--deny`.
Diese Kennungen sind keine Zugangstokens; Geheimnisse gehören nicht in Chat,
Befehlsargumente oder Logs.

Die Einrichtung kauft kein Modell- oder Sprachpaket. Bestehende Grok-Nutzung,
Kontolimits und Anbieterbedingungen gelten unabhängig von diesem lokalen
Connector. Öffentlich erreichbar bedeutet nicht unbegrenzt oder kostenlos
nutzbar.

## English quick start

Keep `grok` (the managed CLI worker) separate from `grok_app` (the external
web/mobile participant). Run `kirabridge grok-connector setup --access team`,
then `start` and `status`. Open `kirabridge approvals` and choose **Grok App**.
Add its current public `/mcp` URL through Grok's **Connectors → New Connector →
Custom** flow. Compare the displayed connection reference with the original
Grok sign-in window; the client name alone does not identify your request.
Review that initial authorization once on the Mac and continue
in the Grok sign-in window. This adds no per-task approval and changes no
existing principal permissions.

For broader, already authorized capabilities, the explicit initial
`--access same-as-chatgpt` option copies the existing ChatGPT policy into the
separate app principal. It preserves the original policy and credentials.

OAuth approval, local gateway health and recorded authenticated tool calls are
different evidence. None alone establishes an actual Eve/mobile voice session.
Verify a harmless tool call from that specific session; the bridge does not
pretend to enable provider-side voice features. New temporary tunnel URLs need
a new connection. Existing CLI sessions are never attached or restarted.
