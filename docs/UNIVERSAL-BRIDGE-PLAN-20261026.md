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
