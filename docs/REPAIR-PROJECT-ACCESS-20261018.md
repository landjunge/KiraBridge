# Lokale Reparatur · Projektdateien und MCP-Lebenszyklus · 18.10.2026

**Aktiv:0.5.1**, Anwendungscode `eddb0b80cf8792bc495dbe16274350f39e38618b`
mit Basisreparatur `1e498f7`. Privater Quellcheckout `~/KiraBridge`;
`~/workspace/KiraBridge` ist der bestehende Austauschordner, kein Git-Checkout.
Kein Hilfezentrum-Feature, Providerkontakt, Grok-Auftrag oder Rückkanalausbau.

## Tatsächliche Ursachen und Änderungen

Der launchd-Dienst `com.kirabridge.bridge` startet die bearbeitbar installierte
`~/KiraBridge/.venv/bin/python3`-Installation mit explizitem
`~/.config/kirabridge/config.toml`. Vorher war bei `chatgpt` ausschließlich der
Austauschordner erlaubt. Auch alle drei vorhandenen historischen Policy-Backups
enthielten nur diesen Pfad: keine belegte Pfadprüfungsregression, sondern
unvollständige Einrichtung für die später benötigten Projekte.

Nun ergänzt **nur `chatgpt.read_roots`** die Bäume `~/Projects` und `~/KiraBridge`.
Ersterer enthält Hilfezentrum, dessen Worktrees und weitere bestehende Projekte.
Eine zunächst engere Freigabe nur des Hilfezentrum-Unterordners wurde nach
zusätzlich beobachteten berechtigten Projektübersichtsanfragen auf diesen
beauftragten Projektbaum erweitert. Das ganze Home und `/` bleiben gesperrt.
Schreiben, Verschieben, Löschen, Terminal-CWD und andere Principals behalten ihre
bisherigen Grenzen. Symlinks/Traversal/Bridge-Daten bleiben geschützt.

`automatic` ist nur der Freigabemodus. `/bin/cat` und `/usr/bin/python3` waren
nicht in der Programmliste; beide Fehlversuche hatten `started=null`.
Das war beabsichtigte Ablehnung. Für den Auftrag sind sie unnötig: vorgesehen ist
`file.read`. Keine neuen Interpreter/Programme freigegeben; bestehende
Shell-/Interpreterrechte nicht als OS-Sandbox ausgegeben. `osascript` war zuvor
gesondert autorisiert und bleibt eine andere Fähigkeit.

Der sporadische Initialisierungsfehler wurde über die App erneut beobachtet.
Der installierte offizielle `tunnel-client`v0.0.16 enthält exakt diesen Text und
Code im Stdio-Guard: Legacy-Aufrufe ohne abgeschlossene Initialisierung samt
`notifications/initialized` werden mit409/-32002 abgefangen, nicht an das Kind
geschrieben. Die alte Konfiguration enthielt den dokumentierten optionalen
Benachrichtigungsadapter nicht. Er ist jetzt bewusst aktiviert: Nach erfolgreichem
Initialize ergänzt er die Abschlussbenachrichtigung, unterdrückt deren Dublette
und führt keine Tools erneut aus. Der eigene Setupweg erhält dies sowohl für den
aktuellen Start als auch im privaten Profil. Tatsächlich beobachtet: natives
`runtimes connect` lässt dieses optionale Feld beim Neuerzeugen sonst weg.

Zusätzlich korrigiert: Der eigene Stdio-Proxy konnte eine nachweislich verlorene
lokale Sitzung bislang nicht wieder öffnen; `list_tools` griff direkt auf die
entfernte Sitzung zu. Jetzt erfolgt bei fehlender Sitzung ein gesperrter neuer
Handshake **vor** dem Aufruf. Bereits gesendete Aufrufe werden nie automatisch
wiederholt. Eine historische Kausalität dieses eigenen Fehlers für jeden409 ist
nicht bewiesen. Die früheren Tunnel-Metriken enthalten keinen genauen
Timing-/Sitzungsbezug; einmal trat bei der ersten kontrollierten Wiederverbindung
auch ein Ergebnisabruf-Timeout auf. Diese Zwischenbefunde werden nicht verschwiegen.

## Tatsächlich geprüft

-15 unterschiedliche passende lokale Prüfungen: neue Lesebäume, weiterhin
  gesperrtes Schreiben/Terminal-CWD, fremder Principal, Pfad/Symlink,
  fehlendes Programm, Operationsrecht, gespeicherter Konfigurationsfingerabdruck,
  echtes MCP-HTTP/stdio, verlorene Antwort nach dauerhafter Annahme und neue
  Verbindung ohne zweite Ausführung, Setup-Persistenz/Key-Geheimhaltung und
  Abbruch bei unbereitem Dienst. Neue Zwischenfehler wurden korrigiert und nur
  betroffene Prüfungen wiederholt. Ruff/Format bestanden.
- Die vorhandene CI lief einmal auf dem fertigen Code `eddb0b8`:
  [Run39122131826](https://github.com/landjunge/KiraBridge/actions/runs/39122131826),
  macOS/Python3.11 und Ubuntu/Python3.11/3.13 jeweils erfolgreich, inklusive Build.
- Tatsächliche **verbundene App-Werkzeuge** dieser Codex-Sitzung:
  `task_request`→`task_get`→`task_events` für `project-handoff-repair-20261018`,
  Principal `chatgpt`, vollständig9117Bytes, `truncated=false`.
  Empfang `8a0fc58b-80da-43ce-97de-87f8e8542c07`.
  Ergebnis bytegleich zur vorhandenen Hilfezentrum-Datei, SHA-256
  `186f0ca668081c763ae063436dacabd384ece27d439d95dc47814fae423341cf`.
  Nach Tunnel-Wiederverbindung und Benachrichtigungsadapter dieselbe ID/Quittung;
  erneute identische Einreichung liefert denselben Abschluss, `attempt=1`,
  genau ein accepted/running/completed-Ereignis.
- `/etc/hosts` über dieselben App-Werkzeuge weiterhin `path_denied`,
  `started=null`, kein Inhalt. `~/Projects` über App vollständig gelistet,
 17Einträge. Keine Dateiänderung/Installation/Agentenausführung durch diese Proben.
- Eine weitere, nicht von dieser Codex-Sitzung erzeugte Anfrage
  `chatgpt-file-verification-20261018-1311` las dieselbe Hilfezentrum-Datei
  erfolgreich. Herkunft der konkreten Benutzeroberfläche ist allein aus dem
  Principal/der Task-ID nicht beweisbar.
- Bereitschaft prüft auf dem **laufenden** Dienst benötigte Pfade/Programme,
  eigenen Principal und beim lokalen CLI-Abgleich Konfiguration/Quellstand.
  Geladene30Python-Dateien entsprechen Fingerabdruck
  `86f0474f3804a83e5a8241e81dad6f010ccdbe80baa0bf6532a724c5e65267a2`.
  Der Wert beschreibt den Quellbaum bei Dienstkonstruktion, keine Fernbeglaubigung.
  Health enthält jetzt ausdrücklich seine begrenzte Aussage.

Bei allen kontrollierten Neustarts vorab keine aktiven/wartenden Tasks oder
Empfängerjobs; Tasks-Annahme und Idle-Prüfung beim Dienstreload kurz mit SQLite-
Schreibsperre gegeneinander abgegrenzt. Alle199 anfänglichen Taskzeilen blieben
hashgleich, alte `unknown` unverändert. Weitere fremde Anfragen während der
Prüfung wurden nicht verändert oder erneut eingereicht. Datenbank integer,
Zugangsdaten hashgleich, Konfiguration/Profil/Backup0600. Nur der beauftragte
Bridge-Dienst und dessen eigener Tunnel neu geladen; fremde CLI-Sitzungen nicht
gestoppt. Keine Datenbankrücksicherung oder Quoten-/Queuebereinigung.

## Bedienweg und abschließender Zielchat-Nachweis

Die [Bereitschaft und Fehlercodes](OPERATIONS.md#bereitschaft-und-projektdateien)
beschreiben den lokalen lesenden Abgleich und das neue MCP-Tool
`bridge_readiness`. Keine Anforderungen bedeutet `ready=null`; erlaubte Programme
werden nur geprüft, nicht gestartet. Health allein belegt weder Datei- noch
vollständige Arbeitsfähigkeit. Rechte und zukünftige Laufzeit bleiben begrenzt.

**ChatGPT-Abnahme bestanden:** Im Folgeauftrag vom18.10.2026 bestätigt der Nutzer
den echten Abruf `chatgpt-file-verification-20261018-1311`: completed,9117Bytes
vollständig gelesen. Dies stimmt mit dem bereits vorhandenen Datensatz im obigen
Beleg überein. Kein neuer Lauf und keine erneute Dateiausführung. Die Herkunft
dieses Zielchat-Nachweises ist damit Nutzerbestätigung plus bestehender Taskbeleg;
die eigenen Codex-App-Aufrufe bleiben davon getrennt. Der weiterhin vorbereitete
Abruf des schon abgeschlossenen eigenen Vergleichsauftrags lautet:

```json
{"task_id":"project-handoff-repair-20261018"}
```

an **`task_get`**. Erwartet: `principal=chatgpt`, `state=completed`,9117Bytes,
oben genannte Quittung, vollständiger Beginn „# Morgenübergabe …“.
Für `task_request` steht die exakte unveränderte Anfrage in
[project-handoff-read.json](../examples/project-handoff-read.json); sie verwendet
denselben Idempotenzschlüssel, erzeugt keinen zweiten Auftrag und benötigt im
tatsächlich eingerichteten automatischen Modus keinen Browserklick.
Bei Initialisierungsfehler zuerst den Client-Lifecycle wiederherstellen und nur
dieses Ergebnis lesen; keine neuen Aufgaben-IDs als blinder Wiederholungsweg.

Die begrenzten Aufrufe nach Adapteraktivierung waren erfolgreich. Offen bleibt
eine vollständige Erklärung des früheren sporadischen Timings und die Beobachtung
unter künftigen Unterbrechungen. Keine Garantie dauerhafter Fehlerfreiheit.
Die [offizielle OpenAI-Tunneldokumentation](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
trennt lokale Health/Readiness/Metriken vom Produktaufruf; die genaue Guard-
Semantik stammt aus der Referenz des tatsächlich installierten Clients.

## Belege und Rückweg

Reduzierte [Ergebnisbelege](evidence/project-access-2026-10-18.json) im privaten
Repository. Lokale erhaltene Einzelbelege und originale Konfigurations-/Profil-
Sicherungen: `~/.local/share/kirabridge/project-access-repair-20261018/`(0700),
`~/.config/kirabridge/backups/config-before-project-read-roots-20261018.toml`(0600).
Keine Credentialwerte im Repository/Browser/Terminal.

Rückweg nur bei leerer aktiver/wartender Task-/Empfängerqueue: zuerst die
gesicherte ursprüngliche Konfiguration und das ursprüngliche Tunnelprofil mit
ihren0600-Rechten wiederherstellen, dann die beiden Codekorrekturen auf dem
privaten Zweig zurücknehmen und Dienst/Tunnel kontrolliert laden. Vorheriger
Quellstand `62ca3bb`. Alte Software akzeptiert `read_roots` nicht; deshalb diese
Reihenfolge. Der ursprüngliche Profilstand lässt die optionale
Abschlussbenachrichtigung weg; dieser Rückweg nimmt die Reparatur bewusst zurück.
Tokens und Datenbank **niemals** aus einer alten Sicherung ersetzen. Keine
fremden Sitzungen stoppen. Anwendung/Queue nach dem Rückweg anhand desselben
geladenen Stands und ursprünglicher Task-IDs prüfen.
