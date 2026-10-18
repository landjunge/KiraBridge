# Sechs eigenständige Tools · Integrationsanalyse18.10.2026

Nur Analyse und späterer Zuschnitt, **kein Bau der Gesamtintegration**. Die
separat beauftragte lokale KiraBridge-Rechtekorrektur ist umgesetzt; sie ist
keine Kopplung der sechs Produkte. Keine Grok-Aufträge, neuen Gegenstellen,
Zugänge oder Secrets verwendet. Brainstorming ist kein Ausführungsauftrag.

## Tatsächliche Quellen

Nach Fetch geprüfte Hauptstände: KiraBridge71ab97b (gezielter Adapterpatch auf
main8e33311), ThreadDeskf67fb59,4AllPass83d111d (gebauter Quellpin60eef0a),
TollGate114cdae, Gnom-Hub-v18108c64, Agent Authority **master**edd40b9.
[Quellpins, Dateihashes und Zeilenanker](evidence/integration-source-pins-20261018.json)
ermöglichen die Wiederprüfung. Keine fremden Arbeitsstände zusammengeführt.

Die aktiven lokalen Checkouts sind teils älter und enthalten fremde Änderungen:
ThreadDesk65aafdf, TollGateaead5d0, Gnom6d2e596, AA09cbf15. Insbesondere ist
AA09cbf15 der alte Lab-/G3-Stand, nicht der heutige Beobachter auf master.
Gnom-Hub-v1 ist das aktuelle Produkt; das separate Repo gnom-hub ist Legacy.
Daher Code vorhanden ≠ lokal geladen ≠ miteinander abgenommen.

Vor dem Planungsteil wurde die vorhandene lebende ThreadDesk-Referenz
`~/.threaddesk/Workflow/Workflow-Planerstellung-fuer-andere-KIs.md` gelesen.
Keine neue Delegation/Whiteboard-Auftragsverteilung dadurch gestartet.

## Verbindungen: vorhanden, fehlend und nötige Abnahme

| Verbindung | Vorhandener Code | Fehlende Kopplung / begrenzter Umbau | Abnahme und Wiederanlauf |
|---|---|---|---|
| ChatGPT ↔ ThreadDesk | `services/mcp.py` bietet list/get/switch, Notizen, Snapshots, lokale Exporte, Import und ausdrückliche Rückgabeprüfung; `api/service.py:create` existiert. MCP ist datenorientiert, führt keine Agenten aus. | `create` fehlt weiterhin im tatsächlich gelesenen MCP-Katalog. Eine entfernte ChatGPT-Anbindung samt Identität/Transport ist damit nicht automatisch eingerichtet. Bei späterem Auftrag schmalen Create-Vertrag und explizite Konto-/Threadrechte ergänzen; keinen allgemeinen Runner daraus machen. | Temporärer Thread mit bestehender autorisierter Identität, genau einmalige Erstellung, untrusted Kontext, Ownergrenzen. Nach Abbruch dieselbe Erstellungskennung abfragen. Keine automatische Veröffentlichung von Kontext. |
| ThreadDesk → KiraBridge → Codex/Grok | `handoff_contract.py` enthält `threaddesk.handoff.v1`, Rechtebedarf, Akzeptanzkriterien, ran=false/sent=false. KiraBridge hat authentifizierte Tasks, persistente Idempotenz/Ownergrenze, strukturierte Adapter und jetzt ausdrücklich wählbares workspace-write. | Kein Adapter konsumiert bereits automatisch dieses Handoff. ThreadDesk-Default `thread-id:task` ist mit KiraBridge `^[a-zA-Z0-9_-]+$` inkompatibel. Dauerhafte Zuordnung von Projekt/Thread/handoff_id/revision/original-task_id zu Bridge-task_id, idempotency_key und Requesthash nötig; keine bloße Doppelpunkt-Ersetzung. Handoff-Rechte sind Bedarf, keine Autorisierung. Vor Übergabe konkrete Pfade/Funktionen vorprüfen. | Eine synthetische freigegebene Änderung mit Quellpin/Dateidiff; Handoff zweimal zustellen und nach Neustart fortsetzen: gleicher Task, ein Versuch. Revisionskonflikt, fremder Owner, unerlaubter Pfad und geänderter Inhalt müssen abgelehnt werden. Bereits offene interaktive Sitzungen sind keine verwalteten Adapterläufe. |
| KiraBridge → ThreadDesk-Rückgabe | Bridge liefert receipt/accepted/started/completed, Agent-/Sessionbeleg, getrennt `project_completion_verified=false`; ThreadDesk hat `return_contract.py`, `ReturnInbox`, Konflikt-/Duplikat-/Stale-Prüfungen und explizite accepted/rejected/rework-Entscheidung. | Übersetzer vom konkreten Task-/Run-Ergebnis in `threaddesk.return.v1` fehlt. Aus der zuvor gespeicherten Zuordnung zurückübersetzen, kleine Belegreferenzen/Quellpin/Testumfang statt Rohprompts oder Terminaldump übernehmen. Bestehende Task-/Inboxspeicher wiederverwenden, keine zweite Taskqueue. | Gleicher return_id und gleicher Inhalt idempotent; anderer Inhalt Konflikt; alte Revision ablehnen. Inbox bleibt unverified bis zur dokumentierten Prüfung. Turnabschluss ist kein vollständiger Projektabschluss; Empfang und Verarbeitung getrennt. |
| ThreadDesk ↔ optional Gnom-Hub | ThreadDesk besitzt `gnom_bridge.py`, persistente `gnom_jobs.py`-Bindung und strengen `gnom_callback.py`-Empfänger mit Revision/Event-ID; ein delivered-Callback wird in return.v1/unverified umgewandelt. Gnom besitzt Jobs, Status-/Cancel-HTTP und `threaddesk_ops.py` zum Lesen/Schreiben eines lokalen Erinnerungspakets. | Gnom sendet nicht bereits den benötigten `threaddesk.gnom-callback.v1`-Vertrag. Sein aktuelles Erinnerungspaket hat purpose/data_refs/result und ist weder dieser Callback noch return.v1. Konkreter erlaubter Send-/Execute-Adapter, Job/Handoff-Bindung und Rückübersetzer fehlen. Gnom bleibt optional, kein zweiter automatischer Starter neben KiraBridge. | Genau ein bestätigter Job, started/question/blocked/error/delivered/cancelled richtig abbilden. Kooperatives Cancel wartet auf tatsächliches Ende; ein Timeout/Cancel-Signal beweist keine Rücknahme bereits ausgeführter Wirkung. Gnom-Jobregistry ist In-Memory/Ringpuffer: nach Prozessneustart fehlende Jobauskunft unbekannt lassen und nicht einfach neu ausführen. |
| Gnom-Hub → TollGate | `llm/manager.py:_chat_via_tollgate` nutzt `TollgateClient.chat` bei URL, sonst `routed_chat`; gezwungener TollGate-Weg scheitert geschlossen statt bezahltem Ausweichen. TollGate enthält /v1-Client, Gateway Protect→Execute→Feedback, Budgetreservierung/Usage-Ledger und Fehlerredaktion. | Bereits eine echte Codekopplung, keine Neuerfindung nötig. Für Gesamtworkflow fehlen gemeinsame beständige IDs/Consumer-Zuordnung und belegter Betrieb mit der konkret verwendeten Auth-Konfiguration. Die aktuelle Clientvoreinstellung consumer=gnom ist kein erfundener gültiger Consumer-Key. | Kleiner autorisierter/synthetischer Gateway-Aufruf und Denial ohne Providerwirkung; unbekannten Streamingabbruch nicht als kostenlos/ungezählt oder beliebig wiederholbar behandeln. Schutz gilt nur für tatsächlich durch diesen Pfad laufende Aufrufe. |
| KiraBridge/CLI → TollGate | KiraBridge `GrokAPIAdapter` ruft derzeit direkt api.x.ai per httpx auf; Codex-/Grok-CLI haben eigene Laufzeit-/Kontokontexte. | **Keine** bestehende TollGate-Abdeckung dieser direkten Aufrufe. Später nur ausdrücklich unterstützte Kostenaktionen über vorhandenes TollGate-Gateway führen und Consumer-/Request-ID zuordnen; CLI-Kontingente und beliebige vom Kind gestartete Aktionen werden dadurch nicht pauschal kontrolliert. Kein Recht, Modellaufrufe heute umzuleiten. | Ablehnung vor kostenpflichtigem Start und Zuordnung von Reservierung/Ergebnis belegen. Bei unklarem Providerergebnis kein blinder zweiter API-Aufruf; Budgetstand und Taskausgang getrennt behandeln. ThreadDesks `services/tollgate.py:LocalGate` ist ein eigener lokaler Aktionszähler, nicht das TollGate-Produkt. |
| 4AllPass → konkret berechtigter Verbraucher | `packages/access/src/client.ts` spricht Loopback-Relay, prüft Schema/Timeout und gibt approved/denied zurück; `packages/core/src/access/handoff.ts` unterstützt ausschließlich raw_secret, mediated wird ehrlich abgelehnt. Relay/Pairing und entsperrte App bleiben eigene Vertrauensgrenze. | Kein bestehender automatischer Secret-Provider im Python-KiraBridge-Adapter. Später enger Verbraucheradapter mit Provider/Capability/TTL, konkreter Betreiberfreigabe und Minimalübergabe direkt in benötigten Prozesskontext; kein Schlüssel im Chat, Prompt, Audit oder Return. SDK-/Relay-Portvoreinstellungen unterscheiden sich in eigenständigem Broker8787 und Access-Client8788: tatsächlichen App-Bindepunkt prüfen, nicht Ports pauschal ändern. | Synthetischer Zugang: erlauben/ablehnen/ablaufen/Abbruch und Geheimnisfreiheit der Belege. Ein einmal ausgegebenes Roh-Secret wird durch Grantablauf nicht vergessen oder automatisch beim Originalanbieter widerrufen. Kein behaupteter mediated-Proxy. Keine persönlichen Tresore für diese Analyse geöffnet. |
| Alle → Agent Authority | Aktueller `agent_authority/json_source.py` liest begrenzte `agent-authority-observation-v1`-Dateien; `whiteboard.py` ist optionaler ThreadDesk-Lesekanal. `report.py` nennt berichtete Zuordnung, Quellenhashes, Inkonsistenzen und unbekannte Identität/Wirkung. Gnom, TollGate und4AllPass enthalten bereits eigene `authority_emit.py`-Producer. | Authority-Event-Envelope-JSONL ist nicht automatisch das neutralisierte Beobachtungsformat. Schmaler minimierender, quellenbezogener Reader/Export nötig; vorhandene Bridge-Audit-/Task-/Runtimebelege projizieren statt neuen Voll-Log anzulegen. Keine Rohprompts/Secrets; Pfade nur wenn erforderlich, sonst Referenz/Hash. Gnom-Producer nimmt freie Extrafelder an: PUBLIC-Label allein beweist keine Datensparsamkeit, Schemafilter nötig. Hashkette ist keine authentifizierte Zustellung. | Korrekte Begrenzung, Rotation/Segmentherkunft, doppelte/falsche/fehlende/reihenfolgewidersprüchliche Einträge darstellen. Bericht entscheidet keine Rechte, Budgets oder Secrets und stoppt keine Arbeit. Historische Lab-ALLOW/DENY-Experimente begründen keinerlei Produktionsvollmacht. |

## Dauerhafte Identität und Fehlersemantik

Bei einem späteren ausdrücklich freigegebenen dünnen Integrationsschritt wird
zuerst genau eine dauerhafte Zuordnung in den vorhandenen Speichern benötigt:
Ursprungsprojekt/Thread, Handoff-ID+Revision+Inhaltshash, Bridge-Task-/Idempotenz-ID,
Agent-Run-/Session-ID, optional Gnom-Job-ID, Return-ID und ausdrücklich getrennte
Prüfentscheidung. Kollisionen und Änderungen bei derselben Revision ablehnen.
Eine Verbindung darf neu initialisiert werden; ein unklar angenommener Auftrag
wird danach **gelesen**, nicht neu gestartet. Unbekannt bleibt unbekannt.

Statusfolge nicht vermischen: Transport verbunden → Initialize/initialized →
Anfrage angenommen → Agent tatsächlich gestartet → Durchgang beendet → Ergebnis
zugestellt → Inhalt verarbeitet → Projektkriterien unabhängig geprüft. Vorhandene
KiraBridge-Diagnostik beobachtet nur eigene Komponenten; externe Tunnelereignisse
bleiben ausdrücklich unbekannt. Rückgabe mit Fehler oder Teilresultat ist möglich,
kein künstlicher Erfolg wegen HTTP200 oder turn.completed.

Datei-/Programmberechtigung des ChatGPT-Principals, terminal.execute, verwalteter
agent.execute und offene interaktive Sitzung bleiben vier verschiedene Grenzen.
Projektkontext oder ein fremder Handoff erteilt keine zusätzlichen Rechte. Die
sechs Tools behalten ihre selbstständigen Start-/Update-/Nutzungswege.

## Aufwand und begrenzte Reihenfolge für eine spätere Entscheidung

Grobe Entwicklungsarbeitstage eines Entwicklers bei vorhandenen Zugängen,
keine Zusage und keine bereits erteilte Bauvollmacht:

| Späterer Arbeitsschnitt | Aufwand | Warum / Abschlusskriterium |
|---|---:|---|
| ThreadDesk-MCP Create und konkrete Verbindung | 1–2 | Kleiner vorhandener Servicevertrag, aber Identität/Idempotenz und echte ChatGPT-Abnahme erforderlich. |
| ThreadDesk→Bridge→ein Codex-Run→unverified-Rückgabe | 3–5 | Dauerhafte ID-/Revisionszuordnung, Receipt-/Unklarheitsbehandlung und unabhängige Abnahme sind größer als bloßes Promptweiterreichen. |
| Optional Gnom-Adapter mit Callback/Restartgrenzen | 3–5 | Vorhandene Empfängerverträge nutzen, fehlender Sender und flüchtige Jobregistry berücksichtigen. |
| Genau definierter TollGate-API-Pfad | 2–4 | Vorhandenes Gateway, aber Consumer-/Abrechnungskorrelation und unklare Streamausgänge prüfen. Keine pauschale CLI-Kostenkontrolle versprechen. |
| 4AllPass-Verbraucher für einen Zugangstyp | 2–4 | Sichere Freigabe, begrenzte Lebensdauer und getrennte Secretübergabe; kein ungefragter mediated-Ausbau. |
| AA-Projektion vorhandener minimierter Belege | 2–3 | Bestehendes Eingangsformat statt Voll-Logs, klare Herkunfts-/Vollständigkeitsgrenzen. |

Ein dünner erster vertikaler Schnitt kann nach eigener Freigabe bei ThreadDesk→
KiraBridge→einem lokal begrenzten Codex-Auftrag→unverified-Rückgabe beginnen.
Gnom, Secretübergabe und Kostenintegration sind dafür keine automatisch
freigegebenen Nebenbaustellen. Parallelität und Abhängigkeiten verhindern eine
verlässliche einfache Summierung dieser Spannen. Es wurde kein solcher Schnitt
gebaut, kein E2E-Erfolg aller sechs Produkte behauptet und kein fremder
Arbeitsstand aktualisiert.
