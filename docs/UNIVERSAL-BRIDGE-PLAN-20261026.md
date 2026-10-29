# Universelle Brücke: Bestandsaufnahme und Umsetzung / Universal bridge plan

Auftrag vom26.10.2026. Ausgangspunkt: main0866c00364994577581e56f5eee18538941a9315,
RC17 auf dem Intel-Mac installiert. Die ursprüngliche Installation ist von dieser
neuen Entwicklung getrennt. Keine erneute Bibliotheksauftragsausführung.

## Zuständigkeit und Leitplanken

KiraBridge transportiert autorisierte Daten und Aufrufe. Explizite Rechte,
Authentifizierung, Verschlüsselung und notwendige Identitäts-/Pfad-/Integritätsprüfungen
bleiben bestehen. Ressourcen begrenzen einzelne Seiten und Aufbewahrung, nicht den
berechtigten Gesamtzugriff durch stille Abschneidung. Jede Begrenzung braucht eine
sichtbare Fortsetzung oder eine genaue Aussage über tatsächlich nicht erhaltene Daten.

Vorhandene Module erweitern, keine zweite Berechtigungsengine oder parallelen
Dispatcher bauen. 4AllPass besitzt hier noch keinen Runtimeadapter. AgentAuthority
ist derzeit ein Beobachtungsexport, kein implementierter Berechtigungsissuer.
TollGate ist optionaler gepinnter stop_only-Workflowcontrol, keine universelle
Budgetgarantie. Erweiterungen benötigen echte belegte Verträge statt erfundener APIs.
ThreadDesk und Codex2/3 bleiben eigenständige Projekte/Arbeitsbereiche.

[Vollständiges statisches Modulinventar](UNIVERSAL-MODULE-INVENTORY-20261026.md).
Die manuelle Verhaltensprüfung der kritischen Pfade ist getrennt ausgewiesen.

## Team und bereits belegte Befunde

- Root: Integration, echtes Mac-Installationsfenster, Schnittstellenentscheidungen,
  kleine PRs und dauerhaftes Arbeitsgedächtnis. Kein paralleles produktives Update.
- TeamA/terminal_repair: Datei-/Logquellen und Range-/Streaming-/Listinggrenzen.
  read_query.py149–166 und filesystem_manager75–91 können UTF-8-Seiten an Bytegrenzen
  mit Ersatzzeichen beschädigen. Ein verlustfreier Bytesmodus fehlt. Listen werden
  bei100 bzw1000 Einträgen ohne Fortsetzung abgeschnitten.
- TeamB/whiteboard_repair: Authority-/Credential-/Ressourcenverträge und Modulgrenzen.
  readiness.py113–131 prüft nur Basiscapability, permissions.py68–125 enthält bereits
  zusätzliche Rechte; kein vollständiges Authorization-ready aus Teilprüfung ableiten.
  Bridge-Komposition103–152 und verzögerte Importzyklen sind konkret inventarisiert,
  begründen aber keine ungezielte Komplettneuschreibung.
- TeamC/receiver_contract_audit: MCP, Rückweg, Prozessausgabe, Plattform/Provider.
  read_query.py94–109 verliert source.truncated; terminal_manager verwirft Ausgabe
  über dem Capturebudget. terminal_app.py366 schneidet UTF-16 und kann Surrogate
  trennen. Live-Terminalausschnitt ist kein vollständiges Logarchiv.
- Produktiver gezielter Nachtest: neuer Dienst0866 und sichere No-op-Eingabe im eigenen
  Fenster belegt. Plain-Terminal submit=false wird vor Transport mit
  session_submit_required verweigert, dennoch wird der Task unknown. Diese konkrete
  Funktions-/Zustandslücke getrennt reparieren, bestehende History nicht umschreiben.

PR38 wurde zuerst geprüft: Draft d2edeb6, bereits DirectDispatcher/SessionResolution/
WindowLifecycle/Sourceactivation. Keine parallele Neuimplementierung. Vor Übernahme
müssen alte queued-Migrationen auch strukturierte Evidence/Ereignisse beachten;
accepted/started/receipt/lease_owner allein sind kein Beweis fehlender Ausführung.
PR38 behebt keine allgemeine Log-/Dateipagination; read_query ist dort unverändert.

## Reihenfolge und Abnahme

1. Vollständiges statisches Modulinventar und gezielte manuelle Pfadprüfung fortführen;
   konkrete Dateien/Abhängigkeiten/Zyklen und vorhandene Tests festhalten. Keine Behauptung,
   das Lesen einzelner Pfade sei bereits eine komplette semantische Codeprüfung.
2. Kleine Rückwegkorrekturen zuerst: ursprüngliches truncated erhalten; Unicode-sicherer
   sichtbarer Ausschnitt; bekannte Vorabverweigerung von ungewisser Ausführung trennen.
   Plain-native paste-only mit vorhandenem bestätigtem Einfügepfad ermöglichen, falls
   Identität/Fokus/Leerlauf/Autorisierung unverändert nachgewiesen werden können.
3. Ein gemeinsamer autorisierter Range-Reader: additive Offset-/Tail-/Bytes/Base64-
   Schnittstelle, Bytezahl, nächste Position, EOF, Identität/Änderungserkennung, SHA-256.
   Kein Größenlimit für die gesamte reguläre Datei; kontrollierte Seitenbudgets.
   Direkter MCP- und Legacy-Dateipfad verwenden denselben Reader. Keine stillen UTF-8-Verluste.
4. Stabile vollständige Verzeichnisfortsetzung über100/1000 Einträge, reproduzierbare
   Reihenfolge, sichtbare Änderungserkennung, bestehende Defaultantworten kompatibel.
5. Vollständige neu erzeugte Programmausgabe über eigentümergebundenen Spool/Snapshot
   mit Seiten, stdout/stderr, Integrität, Ressourcen-/Aufbewahrungsvertrag und Neustart.
   Bereits verworfene alte Bytes sind nicht rekonstruierbar; niemals Erfolg erfinden.
   Bildschirmansicht und ausdrücklich autorisierte Codex-Logdatei getrennt behandeln.
6. Readiness und effektive bestehende Rechteentscheidung vereinheitlichen; konfigurierte,
   autorisierte, freizugebende, verfügbare und tatsächlich ausgeführte Zustände trennen.
   ID, Adaptertyp und Prozessimage getrennt zuordnen, Mehrdeutigkeit sicher melden.
7. Konkrete 4AllPass/AgentAuthority/TollGate-Ports dokumentieren; nur gegen verifizierte
   Verträge anbinden. Windows-/weitere Terminaladapter nur mit echter Plattformabnahme
   als verfügbar ausweisen. Das universelle Interface darf fehlende Adapter nicht vortäuschen.
8. Kontrollierter Gesamt-Nachweis: große isolierte Text-/Binärdaten vollständig ab
   Anfang über Mitte bis EOF rekonstruieren, SHA-256 vergleichen; Unterbrechung,
   Wiederaufnahme, Änderung, fehlende Rechte und Ressourcenende sichtbar testen.
   Tatsächlicher ChatGPT-End-to-End-Nachweis verlangt tatsächlichen ChatGPT-Aufruf,
   aktuelle Werkzeugerkennung, autorisierte Quelle, vollständige Folgepositionen,
   echtes Ergebnis und Empfangs-/Quittierungsbelege. Operator-MCP ist kein ChatGPT-Host.

## Notwendige Tests und Integrationsweg

Pro Änderung nur betroffene Regression und direkt zugehörige Sicherheits-/Kompatibilitätsfälle.
Keine vorsorglichen wiederholten Gesamtsuiten. Pflichtprüfungen bleiben bestehen.
Dateifälle: Byte-/SHA-Roundtrip, UTF-8-Grenze/ungültige Bytes, Anfang/Mitte/Ende/EOF,
append/truncate/replace, FIFO/Symlink/Root-/Credentialausschluss. Listing: >100/>1000,
Unicode, Reihenfolge, Änderungen zwischen Seiten. Ausgabe: ursprüngliche Kürzung,
stdout/stderr/Quota/Owner/Restart. Eingabe: paste-only ohne Return, echte Aktivität
und stale PID/Fokus verweigern; niemals bestehende Codex-/Grok-Sitzungen testen.
Readiness: fehlende Sekundärrechte/Widerruf/zwei Identitäten.

Jeder abgeschlossene sinnvolle Teilschritt: prüfen, committen, pushen, PR und Review,
normal mergen nach den vereinbarten tatsächlichen Gates. Keine Admin-/Billing-/OS-Rechte-
Umgehung. GitHub- und lokale Intel-Ergebnisse getrennt dokumentieren; ARM bleibt ungeprüft.
Release aus eindeutig integriertem Stand bauen und prüfen; produktives Update sichtbar,
mit Backup/Rollback und Rücklesen der tatsächlichen Version/Quelle. Kein ungeprüftes
Arbeitspaket als Release oder vollständige ChatGPT-Abnahme bezeichnen.

Gemeinsames Arbeitsgedächtnis bleibt ausschließlich Whiteboard188ce4729a62.
Aktueller Plan, Fortschritt, konkrete Blocker und nächster Schritt werden dort mit
frischer Revision, stabiler Operation-ID und unabhängigem Readback fortgeschrieben.

## Vorschlag: quellenneutraler Modulvertrag V1 · 29. Oktober 2026

Auftrag `codex_grok_handoff_20261029_01`, ursprünglicher Stabilitätsplan Schritt5.
Dieser Anhang und das [Discovery-Schema](contracts/module-descriptor.v1.schema.json)
bereiten einen Vertrag vor. Kein vorhandener Adapter implementiert durch diesen
Text einen neuen Discovery-Endpunkt; keine Runtimefähigkeit oder Produktivabnahme
wird daraus abgeleitet. Bestehende Protokolle, Autorisierung und Dispatcher bleiben
die jeweiligen Eigentümer. Ein Deskriptor enthält keine Ausführungsanfrage.

### Discovery und sichere Auswahl

Ein künftiger Adapter liest den Deskriptor ausschließlich über einen konfigurierten,
authentifizierten bestehenden Transport. `module.id`, `instance_ref`, `revision`,
Capabilities und `required_permissions` sind fremde Aussagen, keine Identitäts- oder
Rechtebelege. Authentifizierte Gegenstelle und lokales Ziel werden separat geprüft.
Keine Zugangsdaten, Hostpfade, Shellbefehle oder ausführbaren Schemaimporte gehören
in den Deskriptor. Schema-IDs sind opake Referenzen auf lokal geprüfte Definitionen;
sie veranlassen keinen Datei-, Netzwerk- oder Codeabruf.

Der vorgeschlagene Auswahlablauf ist verbindlich für eine spätere Implementierung:

1. Nur die ausdrücklich lokal unterstützte `descriptor_version="1"` mit dem lokalen
   Schema validieren, einschließlich `date-time`-Formatprüfung. Unbekannte Version,
   unbekanntes Pflichtfeld oder fehlerhafte Form sperrt die Verwendung; kein
   automatischer Rückfall auf einen älteren Vertrag.
2. `protocols` und `schemas` nennen exakte unterstützte Versionen, keine Bereiche.
   Jede Capability referenziert genau eine Protokoll-, Anfrage- und Ergebnisversion.
   Diese müssen sowohl im Deskriptor als auch in der lokalen Adapterunterstützung
   enthalten sein. Doppelte IDs innerhalb einer Liste, widersprüchliche Deklarationen
   und nicht auflösbare Referenzen sperren die Auswahl. Diese Beziehungen benötigen
   zusätzliche semantische Prüfung; JSON-Schema allein beweist sie nicht.
3. Die tatsächlich benötigte Capability frisch erkennen und die vorhandene lokale
   Rechteentscheidung für Principal, Operation und Ressource neu auswerten. Fremde
   `required_permissions`, `effect` oder Healthwerte können Rechte nur zusätzlich
   einschränken. Sie ersetzen keine lokale Klassifizierung, Freigabe oder Prüfung
   weiterer benötigter Rechte. Ablehnung und ausstehende Freigabe bleiben getrennte
   Zustände; Discovery erteilt keine Ausführungsvollmacht.
4. `health.state=unknown`, `degraded`, `unavailable` oder veraltete Beobachtung
   begründet keine Ausführungsbereitschaft. `available` benötigt `observed_at` und
   `valid_for_seconds` von 1 bis 300. Der Consumer prüft Zeitsinn und maximal erlaubte
   Uhrabweichung, begrenzt die Gültigkeit zusätzlich mit seiner lokalen TTL und
   misst seit eigenem Empfang monoton. Fremde Zukunftszeit verlängert keine Frist.
   Health bleibt eine Beobachtung und ersetzt keine aktionsbezogene Readiness.
5. `binding.state=claimed` nennt nur `target_ref` und Bindungsrevision. Der Consumer
   muss diese Referenzen an seine aktuelle authentifizierte Transport-/Instanzbindung
   koppeln und unmittelbar vor der Operation erneut prüfen. `unbound`, unbekannte
   Identität, Zielwechsel, Reconnect oder Revisionswechsel sperrt die Fortsetzung
   bis zur neuen Discovery und lokalen Prüfung. Terminal-Pane/TTY/PID oder konkrete
   Ressourcen bleiben im bestehenden lokalen Adapter und werden nicht zu allgemeinen
   Modulidentitäten umgedeutet.

Deskriptoren werden anhand lokaler Byte-/Tiefe-/Zeitbudgets gelesen; eine
unvollständige Antwort ist ungültig und wird nicht still gekürzt verwendet.
Ein leeres Capability-/Protokoll-/Schemaverzeichnis ist gültige Discovery, erlaubt
jedoch keine Operation. Neue Fähigkeiten werden weder aus Produktnamen noch aus
unbekannten Feldern erraten. Optionale `extensions` dürfen nur benannte Metadaten
unter einem Namensraum wie `org.example` ergänzen. Unbekannte Erweiterungen bleiben
inert und dürfen ignoriert werden. Sicherheitsrelevante oder erforderliche neue
Semantik benötigt eine ausdrücklich unterstützte neue Vertragsversion.

### Operations-ID, Abschluss und Unknown

Eine spätere Ausführungsanbindung verwendet die vorhandene stabile Operations-ID
mit dauerhaftem Bezug zu Principal, ausgewählter Capability-/Schemaversion,
ursprünglichem Ziel und Anfragefingerprint. Dieselbe ID mit anderem Inhalt wird
abgewiesen. Diese Pflicht ist Teil des Operationsvertrags, kein zusätzliches
Ausführungsfeld dieses Discovery-Schemas. Bestehende Idempotenz-/Receipt-Journale
werden weiterverwendet, keine zweite Ausführungsqueue aufgebaut.

Nach verlorenem Rückweg, Timeout, Reconnect oder Neustart wird unter der
ursprünglichen ID ausschließlich der vorhandene Zustand und authentifizierte
Abschlussbeleg gelesen. `unknown` ist weder fehlgeschlagene noch ungestartete
Ausführung und wird niemals automatisch wiederholt oder mit neuer ID umgangen.
Empfang, Quittierung, bestätigte Wirkung und fachlicher Erfolg bleiben getrennt.
Eine frische Discovery beweist keinen früheren Abschluss und entsperrt keinen
historischen Handoff. Widersprüchliche Belege oder nicht unterstützte Abfrageverträge
bleiben sichtbar ungeklärt; kein synthetischer Erfolgsbeleg.

### Vier Produktgrenzen und minimale Referenzdeskriptoren

| Produkt | Hier belegte bestehende Grenze | Keine Aussage dieses Vorschlags |
| --- | --- | --- |
| ThreadDesk | Vorhandene getrennte Read-/Manage-/Knowledge-Adapter; zusätzlich begrenzte dynamische Erkennung lesender Tools. Administration besitzt einen produktspezifischen Vertrag in `threaddesk_contract.py`. | Kein implementiertes Mapping auf diesen Moduldeskriptor, keine neue Import-/Indexabnahme oder erneute Library-Ausführung. |
| 4AllPass | In KiraBridge kein Runtimeadapter. Geschützte konkrete Zugangsnutzung braucht einen gesondert geprüften Vertrag; Rohgeheimnisse gehören nicht in Modell, Prompt, Log oder Deskriptor. | Keine allgemeine Tresorisolation und kein bereits vorhandener vermittelnder Secret-Executor. |
| TollGate | Optionaler gepinnter `stop_only`-Hostadapter mit begrenzter eigener Dispatch-/Stoppgrenze; [vorhandener Vertrag](WORKFLOW-CONTROL-CONFIGURATION.md). | Keine universelle Kosten-/Budgetkontrolle direkter APIs, CLI-Kontingente oder beliebiger Kindprozesse. |
| Agent Authority | Begrenzter Beobachtungsexport ausgewählter bestehender Belege; [vorhandener Vertrag](WORKFLOW-OBSERVATION-EXPORT.md). | Kein Rechteissuer, Budgetentscheider oder allgemeiner Stoppdienst. |

Die vier folgenden **synthetischen Referenzen** enthalten bewusst keine behauptete
Runtimefähigkeit. Sie sind kein Discovery-Ergebnis einer laufenden Installation.
Jedes einzelne Objekt validiert gegen das V1-Schema; alle bleiben ungebunden und
ohne beobachtete Health. Eine zukünftige echte Deklaration benötigt eigene Belege.

```json
[
  {
    "descriptor_version": "1",
    "revision": "example-only",
    "module": { "id": "threaddesk", "instance_ref": "example-only" },
    "protocols": [], "schemas": [], "capabilities": [],
    "binding": { "state": "unbound" }, "health": { "state": "unknown" }
  },
  {
    "descriptor_version": "1",
    "revision": "example-only",
    "module": { "id": "4allpass", "instance_ref": "example-only" },
    "protocols": [], "schemas": [], "capabilities": [],
    "binding": { "state": "unbound" }, "health": { "state": "unknown" }
  },
  {
    "descriptor_version": "1",
    "revision": "example-only",
    "module": { "id": "tollgate", "instance_ref": "example-only" },
    "protocols": [], "schemas": [], "capabilities": [],
    "binding": { "state": "unbound" }, "health": { "state": "unknown" }
  },
  {
    "descriptor_version": "1",
    "revision": "example-only",
    "module": { "id": "agent-authority", "instance_ref": "example-only" },
    "protocols": [], "schemas": [], "capabilities": [],
    "binding": { "state": "unbound" }, "health": { "state": "unknown" }
  }
]
```

Vor Runtimeanbindung bleiben die produktspezifischen Protokoll-/Schemaabgleiche,
authentifizierte Discovery, lokale Rechte-/Zielbindung, Drift-/Freshnessprüfung und
gezielte Unknown-/Idempotenzabnahme offen. Schema- und Beispielvalidierung dieses
Dokumentationsschritts ersetzt keinen dieser Nachweise.
