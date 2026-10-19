# Gemini CLI in KiraBridge

Stand: 19. Oktober 2026. Lokal vorhanden: Gemini CLI **0.37.2**, ausführbare
Datei `/usr/local/bin/gemini`. Der Adapter verwendet das echte native
Headless-Protokoll `--output-format stream-json` über den vorhandenen
TerminalManager. Er startet eine eigene begrenzte Sitzung; eine bereits offene
interaktive Gemini-Sitzung wird weder übernommen noch beendet.

**Tatsächlicher Live-Stand: mit dem vorhandenen persönlichen Google-Login
providerseitig gesperrt.** Google hat diesen Zugang für Gemini CLI beendet.
Der Adapter ist integriert und getestet; ein erfolgreicher Modellturn auf
diesem Mac ist damit nicht belegt. Details und Quellen stehen unten.

## Einrichtung und Bedienung

In der tatsächlich geladenen privaten KiraBridge-Konfiguration:

```toml
[agents.gemini]
kind = "gemini_cli"
executable = "/usr/local/bin/gemini"
api_key_env = "GEMINI_API_KEY"
allow_local_tools = false
sandbox_mode = "read-only"
```

Der berechtigte Zugang braucht weiterhin `agent.execute`, den Agenteneintrag
`gemini` und ein erlaubtes Arbeitsverzeichnis. Der bereits eingerichtete
automatische Freigabemodus bleibt erhalten. Der Adapter erweitert keine
Zugangsrechte und startet keinen dauerhaften Hintergrundagenten.

Ein gewöhnlicher MCP-Auftrag über `task_request`:

```json
{
  "request": {
    "api_version": "1",
    "task_id": "gemini-text-check-001",
    "idempotency_key": "gemini-text-check-001",
    "operation": "agent.execute",
    "arguments": {
      "agent": "gemini",
      "prompt": "Antworte mit genau: KiraBridge Gemini bereit",
      "cwd": "/Users/landjunge/KiraBridge",
      "timeout": 45,
      "local_tools": false
    }
  }
}
```

Das Arbeitsverzeichnis muss zur Berechtigung des aufrufenden Zugangs passen.
Die tatsächliche Modellausführung arbeitet in einem leeren privaten temporären
Verzeichnis. Projektdateien werden nicht automatisch gelesen. Für Fragen über
ein Projekt muss der Aufrufer zulässige Ausschnitte ausdrücklich im Prompt
übergeben. `task_get` und `task_events` liefern Ergebnis und Ausführungsbelege.

## Anmeldung und Kosten

Der Adapter kann einen vorhandenen, für Gemini CLI berechtigten Google-Login
im Headless-Modus übernehmen. **Persönliche Konten sind dafür inzwischen
nicht mehr berechtigt.** KiraBridge übernimmt technisch ausschließlich die nativen Dateien
`oauth_creds.json` und gegebenenfalls `google_accounts.json` in ein privates
temporäres Gemini-HOME. Das originale Login-Verzeichnis und seine Einstellungen
bleiben erhalten. Aktualisierte temporäre Tokens werden nicht zurückkopiert.
Ein fehlender Login führt vor dem Prozessstart zu `agent_auth_required`.
Eine neue Browseranmeldung findet nicht aus einem Bridge-Auftrag heraus statt.

Alternativ kann der Betreiber genau eine eigene API-Key-Umgebungsvariable mit
`api_key_env` benennen. Ein vorhandener Wert wird für Gemini als
`GEMINI_API_KEY` bereitgestellt; sonstige Provider-Schlüssel werden nicht
übernommen. Ein Google-Login erfolgt separat im eigenen Terminal mit `gemini`.
Der Nutzer erledigt dabei selbst die Browseranmeldung; Passwörter und Tokens
gehören weder in einen Prompt noch in ein Repository.

Das Gemini-CLI-Team hat den Zugang für freie Individualkonten sowie
Google-AI-Pro-/Ultra-Konten zum **18. Juni 2026 eingestellt**. Die frühere
Angabe eines kostenlosen persönlichen Gemini-CLI-Kontingents ist hier deshalb
keine nutzbare Zusage. Enterprise-Zugänge mit passender Code-Assist-Lizenz und
API-Key-Authentifizierung sind laut Team nicht von dieser Abkündigung betroffen.
Siehe die maßgebliche
[offizielle Abkündigung des Gemini-CLI-Teams](https://github.com/google-gemini/gemini-cli/discussions/28017).

API-Key- und Vertex-Tarife können kostenpflichtig sein. Ein solcher Schlüssel
wurde nicht als Ausweichweg eingerichtet oder verwendet. Der Adapter bucht
nichts, wechselt keine Tarife und setzt
`billing.overageStrategy = "never"`. Diese Einstellung macht einen bereits
kostenpflichtigen API-Key nicht kostenlos und ist kein allgemeines Geldlimit.
Siehe [Anmeldung](https://geminicli.com/docs/get-started/authentication/) und
[Kontingente und Preise](https://geminicli.com/docs/resources/quota-and-pricing/).

## Tatsächliche Sicherheitsgrenzen

Der Adapter bietet derzeit **ausschließlich Textaufträge**. Lokale Werkzeuge
werden auch bei `allow_local_tools = true` nicht freigeschaltet; ein Auftrag
mit `local_tools = true` scheitert vor dem Start mit
`agent_tools_unsupported`. `sandbox_mode` ist keine Behauptung, Gemini werde in
einer Betriebssystem-Sandbox gestartet. Ergebnisbelege melden ausdrücklich
`text_only = true`, `isolated_cwd = true` und `os_sandbox_enforced = false`.
Für echtes Lesen/Schreiben im Projekt muss ein späterer Adaptervertrag mit
nachgewiesener nativer Eingrenzung ergänzt werden.

Die Prozesssteuerung verwendet explizites Executable, Zeitlimit,
Ausgabelimit, minimale Umgebung und den vorhandenen Stop-/Reap-Pfad. Native
Einstellungen liegen nur in einem privaten temporären HOME und Arbeitsordner.
Die angefragte Projekt-CWD wird vorher trotzdem mit PathScope geprüft. Ein
leeres eigenes `.env` stoppt die automatische Suche nach fremden `.env`-Dateien.
Die CLI erhält keine vorhandenen Hooks, Extensions, MCP-Konfigurationen,
Skills, Unteragenten oder IDE-Verbindungen. Automatische Updates und
Telemetrie sind ausgeschaltet. Der native Turn ist auf einen Modellturn begrenzt.
Die tatsächlich geladenen Einstellungen setzen außerdem `general.maxAttempts = 1`
und `general.retryFetchErrors = false`. Das begrenzt den allgemeinen nativen
Requestpfad. Provider-SDKs und native Availability-/Fallback-Regeln können eigene
Transportwiederholungen besitzen; eine vollständige Transportretryfreiheit wird
nicht zugesichert. KiraBridge selbst reicht denselben Turn nicht erneut ein.

Zusätzliche technische Sperren:

- Native `tools.core = []` und eine native `deny`-Policy für `*`.
- `hooksConfig.enabled = false` und `experimental.enableAgents = false`.
- `--extensions none`, mit der nativen Enablement-Klasse geprüft.
- Eine nichtleere zufällige MCP-Allowlist und dieselbe Excludelist. Jeder
  andere Server scheitert an der Allowlist; der eine Listenname scheitert an
  der Excludelist. Das verhindert auch eine Verbindung zu eventuell zentral
  injizierten MCP-Servern.
- Ein fester Textpräfix verhindert Slash-Befehle. Jedes `@` wird vor stdin zu
  `\@` maskiert; der native Parser expandiert damit auch absolute Dateipfade
  nicht. Der Modellprompt kann dadurch die sichtbare Maskierung enthalten.

Die Version 0.37.2 ersetzt lokale `settings.admin.*` durch Remote-Admin-Defaults.
Zudem bedeutet eine leere MCP-Allowlist dort keine Sperre. Die Implementierung
stützt sich deshalb auf die genannten wirksamen Sperren, nicht auf ein lokal
gesetztes `admin.mcp.enabled = false`.

## Statusnachweise und Wiederholung

`init.session_id` belegt nur die Sitzung. Erst eine native Assistant-Antwort
oder ein natives finales Ergebnis belegt die Bearbeitung. Erfolg verlangt
`result.status = "success"`, dieselbe Sitzungsidentität, keinen beobachteten
fatalen Fehler und Exit-Code 0. Ein Timeout, Identitätswechsel, Werkzeugereignis
im Textmodus oder fehlendes Endereignis wird als unbekannter Ausgang behandelt.
Solche Aufträge werden nicht automatisch neu gestartet.

Eine eindeutig erkannte native Authentifizierungsablehnung vor jeder Sitzung
wird als gesicherter Startfehler gemeldet: `agent_auth_unsupported_client` für
den belegten Wegfall der Individualkonten, sonst `agent_auth_failed`. Dafür
müssen die bekannte native Startdiagnose, ein Fehlerexit und das Fehlen jeglicher
Session-/Ausführungsbelege zusammenpassen. Ein Exit-Code allein reicht nicht.

Native Fehlermeldungen und Toolparameter werden nicht in Ergebnis-/Auditbelege
übernommen. Ergebnistexte sind auf 65.536 UTF-8-Bytes begrenzt. Ein beendeter
Modellturn bedeutet nicht, dass eine ganze Projektaufgabe abgeschlossen ist;
`project_completion_verified` bleibt `false`.

## Prüfung dieses Adapterstands

25 gezielte Tests prüfen den tatsächlichen lokalen Prozesspfad mit synthetischen
CLIs: Completion/Exit-Code, Sessionwechsel, reine Empfangsereignisse, fehlendes
Ende, Timeouts mit Prozessbereinigung, unerlaubte Toolereignisse, Fehlerredaktion,
Unicode-/Textgrenzen mit sichtbarer Kürzungsangabe, private Konfiguration,
Umgebungsfilter, Authdateien und sanitisierte native Startdiagnosen.

```sh
PYTHONPATH=src python -m pytest tests/test_gemini_adapter.py -q
ruff check src/kirabridge/agent_manager/gemini.py tests/test_gemini_adapter.py
```

Zusätzlich wurden die installierten nativen Module offline geprüft. Dabei
wurden die echten Einstellungen geladen, die native Policy erzeugt und der
native `handleAtCommand`-/Slash-Parser mit maskierten absoluten Pfaden und
Adresszeichen ausgeführt.

## Echter Liveversuch und gesicherte Grenze

Genau ein Auftrag lief über eine eigene Bridge-/TaskManager-Datenbank:
`gemini-oauth-proof-20261019-01`, Prompt `Antworte exakt KIRABRIDGE_GEMINI_OK`,
Timeout 120 Sekunden. Eine garantiert ungesetzte Credential-Umgebungsvariable
verhinderte API-Key-Nutzung. Der Dispatcher quittierte den Auftrag, der native
Prozess startete, aber keine Session-/Abschlussereignisse wurden empfangen.
Der historische Auftrag bleibt nach 12,781 Sekunden ehrlich als `unknown`
mit `agent_unconfirmed` dokumentiert; er wurde nicht wiederholt.

Ein anschließender gezielter Start-/Authcheck erlaubte in temporären Einstellungen
**null Modellturns**. Die CLI beendete die Anmeldung mit Exit 1 und
`IneligibleTierError`: Der persönliche Code-Assist-Client werde nicht mehr
unterstützt; Google verweist auf Antigravity. Die Diagnose entstand vor einer
nativen Session. Die vorstehende offizielle Abkündigung bestätigt diese
Ursache. Ein Rechte-Bypass oder CLI-Upgrade stellt diesen Zugang nicht wieder her.
Ein neuer authentifizierter Modellturn wurde nicht versucht. Das originale
OAuthcache-Verzeichnis blieb unverändert.

Der minimale Livebeleg liegt privat unter
`~/.local/share/kirabridge/cli-providers-20261019/gemini-live-proof.json`
(Modus 0600). Rohe Authdiagnosen gehören nicht ins Repository oder Audit.
Die aktualisierte Fehlerkategorie wurde mit synthetischen Prozessen getestet.

Die nur lesend abgefragten npm-Metadaten melden aktuell **0.64.0** als neueste
stabile Version. Eine zusätzliche Installation wurde nicht vorgenommen, da
die Abkündigung den Anmeldeweg und nicht bloß die installierte Version betrifft.
Der von Google genannte Nachfolger Antigravity CLI wurde nicht automatisch
installiert oder zur Übernahme bestehender Konfigurationen verwendet. Dessen
eigene Anmelde-, Werkzeug- und Isolationsgrenzen brauchen eine separate Integration.

Weitere offizielle Quellen:
[Headless-Protokoll](https://geminicli.com/docs/cli/headless/),
[Konfiguration](https://geminicli.com/docs/reference/configuration/),
[Policy Engine](https://geminicli.com/docs/reference/policy-engine/).
Die lokal installierte 0.37.2 wurde zusätzlich untersucht, weil aktuelle
Onlinedokumentation nicht jede Eigenheit dieser Version abbildet.
