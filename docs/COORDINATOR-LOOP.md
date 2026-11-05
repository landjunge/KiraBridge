# Big Plan · Codex-Koordinatorloop

Nutzerauftrag vom 05.11.2026. Der lokale Codex-Koordinator nimmt nacheinander ausdrücklich freigegebene ThreadDesk-Karten an. Er nutzt vorhandenes AutoNext, TeamWork, versiegelte Core-Tasks, Claims, Worktree-Leases und Outbox. Die bisherige Codex/Grok-Übergabe bleibt erhalten. Es entsteht keine zweite Aufgabenqueue.

Die neue Route ist ein eigenes KiraBridge-Profil mit privatem Zustand, eigenem Arbeitsbereich und eigener Loopback-Verbindung für den bestehenden TeamDispatcher. Der produktive Bridge-Dienst und dessen sichtbare Codex-/Grok-Bindungen werden weder verändert noch neu gestartet. `TeamWorker.execution_scope=separate_managed_session` ist ausdrücklich konfiguriert. Der Standard bleibt `existing_visible_terminal`; direkte Aufträge können keine andere Route über Eingabefelder wählen. Das globale Visible-Flag bleibt eingeschaltet. Nur ein versiegelter Teamauftrag kann den separaten Workerpfad nutzen.

## Ablauf

1. Eine `READY`-Karte enthält feste Aufgaben-ID, Produkt, Arbeitsbereich, Sandbox und `acceptance.kind=coordinator_checks`. Ein lokaler Freigabepin bindet exakte Eintrags-ID und Inhalts-SHA256. Andere Notizen und historische Aufgaben sind keine Aufträge.
2. AutoNext prüft Freigabe, Kontingentbeleg, Quellenbytes und Arbeitsbereich, claimt atomar und veröffentlicht die Übernahme.
3. Codex bearbeitet die Aufgabe im festgelegten Arbeitsbereich. Modellaktionen bleiben leer und können weder weitere Aufträge noch neue Prüfkommandos autorisieren.
4. Bei `acceptance.review_with_grok=true` prüft Grok unabhängig und schreibgeschützt. `acceptance.review_files` benennt dafür ausdrücklich freigegebene relative Textdateien: beide Prüfer erhalten denselben begrenzten Snapshot samt Hashes. Andere Dateien und gesamte Repositories werden nicht automatisch kopiert. Vor Annahme muss der Snapshot weiterhin zum Arbeitsstand passen. Anschließend prüft immer ein eigener `codex_verify` mit technisch schreibgeschütztem Codex-Profil.
5. Nur ein gültiges, positives und an den exakten Quellergebnishash gebundenes Urteil lässt die vorab gepinnten Prüfbefehle zu. Diese laufen ohne Shellinterpretation und mit begrenzter Zeit über die vorhandene Prozessverwaltung. Unterbrochene oder unklar bereinigte Prüfungen werden nicht automatisch wiederholt.
6. Erst erfolgreiche Prüfungen und echte native Corebelege erzeugen eine Annahmequittung. Danach wird die nächste gepinnte Aufgabe übernommen. Ein fertiger Modellturn allein bedeutet keinen fachlichen Abschluss.

Ein Task bleibt bei UNKNOWN, geändertem Inhalt, fremdem Scope, negativem Urteil, Checkfehler, Budget-/Loginfehler oder abgelaufener Lease gestoppt. Es gibt keine automatische Neuausführung desselben Modellturns. Ein Neustart liest bestehende Work-/Core-IDs und Ergebnisse. Quittungen bleiben an Grant und Task gebunden; Codex kann keine Operatorquittung simulieren.

## Benutzung

Das eingerichtete Profil und der aktuelle installierte Stand werden in den gemeinsamen Big-Plan-REFERENCES angegeben.

```sh
~/.local/bin/bigplan-loop status
~/.local/bin/bigplan-loop approve --entry-id EXAKTE_FREIGEGEBENE_KARTE
```

`approve` ist der lokale Freigabeadapter für bereits ausdrücklich beauftragte Karten, kein Mechanismus zum Freigeben fremder Boardtexte. Er prüft Kartentyp, READY, Scope, Sandbox und Abnahmevertrag. Ein Batch enthält bis zu16 Karten und wird nacheinander abgearbeitet. Neue Batches ersetzen die Pin-Liste nach dem bisherigen Abschluss; laufende Batches dürfen nicht ausgetauscht werden. Frühere Aufgabenkennungen werden nicht erneut ausgeführt. Neue fachliche Aufträge außerhalb des festen Worktrees brauchen zunächst eine isolierte passende Profilzuordnung, keine still vergrößerten Rechte.

Das Profil ist strikt typisiert; `enabled` muss ein JSON-Boolean sein. `enabled=false` beendet die weitere Aufnahme/Beobachtung. Bereits gestartete eigene Prozesse werden nicht dadurch als beendet gewertet; Claims bleiben erhalten. Beim Wiederanschalten wird der gepinnte Grant erneut abgeglichen, kein UNKNOWN freigegeben. Zum Stoppen des gesamten eigenen Dienstes wird ausschließlich dessen launchd-Label verwendet. Fremde Prozess- und Terminalkennungen gehören nicht zu diesem Ablauf.

Der Loop fragt im Leerlauf alle5 Sekunden nur das lokale Freigabeprofil ab; es erfolgt kein Modellaufruf. Kontingent-/Abrechnungsbelege stammen vor einem neuen Grant aus Codex `account/rateLimits/read`, nicht aus geschätzten Prozentwerten. API-Schlüssel für OpenAI/Codex/xAI werden abgelehnt. Keine Guthabennachladung oder Abrechnungsumschaltung. Ein Grant ist zeitlich und auf höchstens16 Aufgaben begrenzt. Nach Budgetende ist eine neue belegte Freigabegeneration nötig.

## Berichte und Kira

Der Koordinator berichtet mindestens alle60 Sekunden seinen tatsächlich beobachteten Zustand und angenommene Aufgaben. Jede gestartete Work-ID erhält ein eigenes Berichtsboard für Codex, Grok oder Codex-Verifier. Die Workerberichte sind ausdrücklich Zustandsbeobachtungen des Koordinators; sie erfinden keine Eigenmeldung oder unabhängige Abnahme. Modelltexte und Rohtranskripte werden nicht automatisch in die zentrale Übersicht kopiert.

Kira liest `get_thread` für die bestehende Agentenübersicht `3e706958488c`: Notes enthalten den lesbaren Stand und JSON. Wie beim Berichtssystem gilt180 Sekunden als Veraltungsgrenze. Gesonderte Quellen-/Corebelege liegen in den bestehenden AutoNext-/Team-Receipts und im dedizierten Profil. Ein alter abgeschlossener Workerbericht bleibt abgeschlossen, ist aber keine aktuelle Liveness-Meldung.

## Implementierung und Nachweise

Der eigene Grok-Reviewadapter nutzt die unterstützte Headless-JSON-Schema-Ausgabe und ausschließlich `structuredOutput`; Gedanken-/Einleitungstext sind kein Urteil. Die bestehende ACP-Übergabe wird weiter unverändert angeboten. Eigene Codexturns haben ein striktes Team-Ausgabeschema. Die Managed-Lane wird nur für exakt versiegelte und ausdrücklich konfigurierte Teamaufträge ausgewählt, nicht durch Erhöhen des Native-Admission-Zeitlimits.

Neue Kernlogik: `autonext/coordinator.py`; neuer Runtime-/Freigabeadapter: `scripts/bigplan_loop.py`. Die Standardroute, Operatorbestätigung und bestehenden Aufgaben bleiben durch Opt-in getrennt. Gezielte Tests prüfen echte lokale HTTP-/MCP-/Dispatcherketten mit deterministischen CLI-Fixtures, Hash-/Scope-/Replaygrenzen, negative Urteile, strikte JSON-Verträge und Bereinigung eigener Check-Prozessgruppen. Native Providerabnahme und deren tatsächlicher Stand werden zusätzlich dokumentiert; Fixtures sind keine Liveabnahme. Nicht veröffentlichte Quelländerungen sind keine neue Desktop-Paketversion.

Bei den ersten isolierten Liveversuchen wurden ein interner MCP-Timeout unterhalb des Serverantwortbudgets und eine fehlende Managed-Lane-Zuordnung erkannt. Beide Versuche bleiben mit ihren Originalkennungen erhalten; gestoppte UNKNOWN-Versuche werden nicht durch Löschung oder Zurücksetzen als bestanden ausgegeben. Die endgültige Abnahme erfolgt mit neuen expliziten Testkarten in einem disjunkten eigenen Arbeitsbereich.

# English

The dedicated local Codex coordinator reuses existing AutoNext claims, TeamWork, sealed Core tasks, leases and outbox. It accepts only explicitly approved ThreadDesk card IDs and content hashes. Codex performs the task, optionally delegates an independent read-only Grok review, then uses a separate read-only Codex verifier and predefined bounded checks. Only native evidence and successful acceptance produce a receipt and advance to the next pinned task.

The existing production daemon, visible terminal bindings and default route remain untouched. Dedicated workers explicitly select the managed route through sealed team assignments. No additional task queue or model-invented authorization is introduced. UNKNOWN, negative reviews, failed/interrupted checks, changed sources or missing subscription evidence stop advancement without replay. Idle monitoring makes no model requests.

Use `bigplan-loop status` and `bigplan-loop approve --entry-id EXACT_APPROVED_ENTRY`. Cards must match the fixed isolated profile. New approved batches are loaded after the previous batch completes. Each worker and the coordinator report through the existing central agent overview. Tests using deterministic native CLI fixtures are distinguished from actual provider acceptance. Installation details and evidence are recorded in shared Big Plan references.

## Lokale Abnahme und Betrieb am 05.11.2026

Die finale native Abnahme hat zwei ausdrücklich gepinnte `workspace-write`-Karten vollständig angenommen: Codex erzeugte `loop-result-1.txt`, Grok prüfte den gespeicherten Dateibeleg, ein eigener read-only Codex-Verifier prüfte zurück, und der unabhängige Check bestätigte den Inhalt. Erst nach dieser Annahme wurde `loop-result-2.txt` automatisch erzeugt und separat geprüft. Genau fünf native Coreturns (2 Hauptturns, 1 Grok-Review, 2 Codex-Verifier) und zwei Annahmequittungen; anschließend `complete/no_authorized_ready_card`.

Aktuelles lokales Profil: `~/.config/kirabridge-coordinator/bigplan.json`. Eigener Zustand: `~/.local/share/kirabridge-coordinator/bigplan/`. Konkrete Quittungen, Dateihashes und Reihenfolgeprüfung: `acceptance-evidence.json` dort. Das autonome Profil bleibt im Leerlauf für neue ausdrücklich freigegebene Pin-Batches aktiv. Der primäre Produktivdienst wurde nicht neu gestartet.

Eigener launchd-Dienst: `de.threaddesk.bigplan-coordinator`. Status: `launchctl print gui/$(id -u)/de.threaddesk.bigplan-coordinator`. Stoppen: `launchctl bootout gui/$(id -u)/de.threaddesk.bigplan-coordinator`; weder andere Bridge-Labels noch fremde Terminalprozesse verwenden. Logs: `~/.local/state/bigplan-coordinator/`. Rückbau betrifft nur den eigenen Launcher `~/.local/bin/bigplan-loop` und die gleichnamige eigene LaunchAgent-Plist; zuerst stoppen und diese Dateien sichern. Aufgaben-/Berichts-/Auditdaten bleiben erhalten. Der Quellworktree `KiraBridge-worktrees/coordinator-loop-20261105` ist ein aktiver Laufzeitpfad und darf nicht als temporärer Testordner entfernt werden.

Es wurden 29 Koordinatortests, 10 Grok-Structured-Tests, 5 Managed-Lane-Tests, 4 Runtimeprofiltests und 8 Schemafälle bestanden; zusätzliche betroffene Basis-/Native-/Adapterregressionen wurden während der Umsetzung geprüft. Der unabhängige Review meldete keine blockierenden Befunde. Die Website und veröffentlichten Pakete bleiben unverändert: es handelt sich um einen lokalen Opt-in-Adapter, keine neue öffentliche Desktopversion.
