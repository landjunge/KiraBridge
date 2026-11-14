# Native Koordination über Core und MCP

Aktueller zusammengeführter Stand: [Integrationsübersicht](BIGPLAN-INTEGRATION-STATUS-20261106.md).
Dieser Bericht dokumentiert den ursprünglichen C1-Checkpoint; das damals folgende
Routingpaket C2 ist inzwischen integriert und unabhängig angenommen.

Auftrag `BP-COORD-NATIVE-20261106-C1`, 6. November 2026. Basis des gesonderten
Quellkandidaten ist der geprüfte Koordinator `4bdf851`. Der laufende installierte
Koordinator und das veröffentlichte Desktop-Paket erhalten durch diesen
Quellschritt keine vorgetäuschte Aktualisierung.

## Ein vorhandener Ablauf

Der KiraBridge-Core wählt `CoordinatedAutoNext` bei
`autonext.coordinator_mode=true` bereits beim Aufbau der Bridge, auch wenn das
Profil zunächst deaktiviert ist. Andernfalls bleibt es beim bisherigen
`AutoNextManager`. Das bestehende Loop-Skript setzt diesen ausdrücklichen Modus
im eigenen Profil; sein manueller Austausch des Managers entfällt.

Die vorhandene TeamWork-Änderungsmeldung weckt weiterhin den einzigen
AutoNext-Manager. Claims, Worktree-Leases, Quellenpins, Budget-/Routenprüfung,
Grokreview, eigener Codex-Verifier und gepinnte Checks entscheiden über Annahme
und Folgeauftrag. Ein Abschluss oder Neustart erzeugt keinen zusätzlichen
Workerturn. Im Leerlauf wartet der vorhandene Core auf Änderungen und Fristen;
er befragt dafür kein Modell und lädt keinen Skill.

## Lesbarer Stand und dauerhafte Rückmeldungen

Der lesende MCP-Aufruf `coordinator_status` benötigt `team.read` und erlaubt den
konfigurierten Koordinatorakteur sowie den frisch über `Team.get` bestätigten
unveränderlichen Owner ausschließlich des konfigurierten Teams. Diese zusätzliche
Leseansicht bleibt auch nach einem Koordinatorrollenwechsel beim echten Owner;
sie erweitert keine Steuer-, ACK- oder privaten Core-/Prompt-/Ergebnisrechte.
Ein fremdes, fehlendes oder nicht mehr aktiv zugängliches Team ist keine
Ersatzbindung. Der Aufruf liefert höchstens die 16 Aufgaben des aktuellen
gepinnten Grants mit Claim-/Work-/Corekennungen, Zuständen, Checkphase und
vorhandener Annahmequittung. Prompts, Modellresultate, Prüfausgaben und alte
fremde Grants werden nicht ausgegeben. Mitgliedschaft und Berechtigungen werden
aktuell geprüft. Ein nur zur Laufzeit veränderter Modus tauscht keinen aktiven
Manager aus; der Status zeigt dafür `restart_required`.

Clients mit älterem Werkzeugkatalog können denselben Vertrag über
`read_query({"operation":"coordinator.status"})` lesen. Das ist eine direkte
lesende Anfrage ohne neue Task-/Completionanlage. Kleine Lesebudgets und fremde
Datei-/Taskselektoren werden ausdrücklich abgewiesen. Der Status ist auch im
vorhandenen read-only Werkzeugbatch zugelassen.

Im vertrauenswürdigen AutoNext-Profil kann eine stabile eigene Zielkennung
gesetzt werden, beispielsweise `completion_target: "coordinator-c1"`. Dieselbe
optionale Einstellung ist im lokalen Loop-Profil verfügbar. Der bestehende
Grantfingerprint bindet eine gesetzte Route; eine nicht gesetzte Route erhält
den bisherigen Fingerprint und erzeugt keine zusätzlichen Meldungen.

Bei fachlicher Annahme oder Stopp wird eine Meldung mit `source="autonext"`
atomar im vorhandenen Completion-Postfach gespeichert. Ihr Ereignisbezug ist die
bereits vorhandene AutoNext-Outbox, keine zweite Aufgabenliste. Der Inhalt
beschränkt sich auf Kennungen, Phase und gebundene sichere Nachweise. Ein
beendeter Modellturn ist weiterhin keine Annahme; Stopp/UNKNOWN ist kein Erfolg.

Ein MCP-Consumer verwendet die bisherigen Werkzeuge:

```json
{"tool":"completion_receive","arguments":{"target":"coordinator-c1","wait_seconds":18}}
```

Nach Verarbeitung bestätigt er genau die zurückgegebenen Werte:

```json
{"tool":"completion_ack","arguments":{"notice_id":"EXAKTE_ID","receipt":"EXAKTE_QUITTUNG"}}
```

Empfang und Quittierung laufen unter demselben Eigentümer mit `team.read`.
Task-/Nachrichtenquellen behalten ihre bisherigen Rechte. Derselbe
Quellenvertrag gilt auch für die vorhandene Completion-Queueansicht und deren
Kontrollaktionen. Empfang, Ack, Netzwerkverlust und Wiederaufnahme erlauben
keine neue Ausführung. Bereits vor dem Consumer gespeicherte Meldungen bleiben
bis zur passenden Quittierung nachlesbar. Das setzt einen aktiven Consumer
voraus und weckt keine inaktive ChatGPT-Unterhaltung automatisch.

## Opt-in: autonome Verarbeitung vor Folgestart

Der Quellvertrag vom 14. November 2026 ergänzt den vorhandenen Manager um eine
ausdrücklich wählbare Verarbeitung im selben Daemon. Das bestehende,
vollständige und zunächst deaktivierte AutoNext-Profil erhält diese Einstellung:

```toml
[autonext]
enabled = false
principal = "codex"
coordinator_mode = true
completion_target = "kb-server-autonext-readonly-20261114-v1"
completion_mode = "verified_ack"
```

Der Ausschnitt ersetzt keinen Grant. Team und aktuelle Revision, Quellenboard,
vollständige Kartenpins, abgeschlossener Startanker mit Ergebnishash, feste
Executor-/Verifierprofile, Arbeitsbereich, Lease und aktuelle Budgetbeobachtung
bleiben erforderlich. Erst das vollständig gebundene Profil darf aktiviert
werden. Der Modus benötigt `coordinator_mode=true` und eine stabile eigene
Zielkennung. Ohne ausdrückliche Auswahl gilt `completion_mode="external"`:
bisheriger Ablauf, bisherige externe Consumer und bestehende Grantfingerprints
bleiben erhalten. Es gibt keine pauschale neue Sperre für andere Aufträge.

Nach fachlicher Annahme prüft der vorhandene Manager den ursprünglichen
versiegelten Coreauftrag, Principal, Requesthash, Versuch, Corequittung,
nativen Erfolg und Ergebnis, Quellenpin und Annahmequittung. Nur eine exakt
passende `completed`-Outbox mit bestätigtem Board-Readback und die dazugehörige
Completion für denselben Eigentümer, Zielkanal, Grant und Task werden verarbeitet.
Der Consumer nutzt die vorhandenen Receipt-/ACK-Operationen; fremde,
unbestätigte, gehaltene oder gestoppte Meldungen werden nicht automatisch
quittiert. ACK und typisierte Verarbeitungsquittung werden gemeinsam in der
bisherigen Datenbank gespeichert. Die additive Tabelle
`autonext_processed_completions` verändert keine historischen Zeilen und ist
keine zweite Aufgabenliste.

Vor einem Folgeclaim prüft dieselbe Schreibtransaktion die Originalbindung und
den gespeicherten ACK erneut. Eine parallele oder verspätete Hintergrundprüfung
kann diese Grenze nicht umgehen. Die Claim-Outbox enthält den gebundenen
Vorgänger-ACK als Nachweis. Ein bereits passender ACK wird nach Neustart nur
erneut validiert, nicht durch einen neuen Modellturn ersetzt. Fehlende oder
abweichende Originalbelege lassen ausschließlich diese Folgearbeit ausstehen.
Bei einer verspäteten Completion beobachtet der Manager das bestehende lokale
Postfach; weder Modellpolling noch ein zusätzlicher HTTP-Endpunkt, Dienst oder
eine weitere Queue sind erforderlich. Nach der letzten Karte wird auch deren
Annahmemeldung verarbeitet, bevor der Grant als abgeschlossen gilt.

Der Startanker vor der ersten Karte behält den bisherigen Vertrag: abgeschlossene
Originalarbeit und expliziter Ergebnishash. Die neue ACK-Grenze betrifft die
innerhalb dieses Grants angenommenen Karten. Ein anderer Grant, Nutzerstopp,
historische UNKNOWNs und alte Leases werden dadurch nicht übernommen oder
freigegeben. Bestehende Daten vor dem regulären Update sichern; keine alten
Quittungen löschen, um einen fehlenden Nachweis zu umgehen.

English: select `completion_mode="verified_ack"` explicitly on a complete pinned
coordinator grant to process accepted-result notices inside the existing daemon.
The claim transaction requires a matching persisted processing receipt and
owner/target/grant/task-bound completion ACK. Acceptance, original Core request
and result hashes, and verified board outbox are rechecked; foreign or unverified
notices cannot unlock a successor. The additive processing ledger and idempotent
ACK survive restart without replay. The default `external` mode preserves legacy
behavior and grant fingerprints. This source contract does not claim live server,
desktop or other-platform acceptance.

## Prüfung und nächste Integration

Die gezielten Prüfungen verwenden ausschließlich temporäre Daten und echte
lokale MCP-/Core-/TeamDispatcher-Verbindungen mit deterministischen
Codex-/Grok-CLI-Fixtures. Geprüft werden native Opt-in-/Legacy-Auswahl, zwei
auf fachliche Annahme folgende Aufgaben, dauerhafte Rückmeldungen/Ack,
Wiederaufnahme ohne Replay, Rechte-/Owner-/Queuegrenzen, atomarer Rollback,
Konflikt-/Stoppverhalten und begrenzte Statusausgabe. Das sind keine neuen
Provider-, Desktop-, Windows- oder Handy-Abnahmen. Die finalen Ergebnisse und
Quellpins werden im ThreadDesk-Claim `188ce4729a62/7b7093bca508` ergänzt.

Die existierende CLI-Modellmatrix und ihr geprüfter Delegationshook bleiben
die Modellwahlgrundlage. In dieser Runde wurden die echten Plan-Hooks mit
Matrixrevision5 und dem vorhandenen ChatGPT-Zugang verwendet. Eine Planquittung
ist kein Providerstart und keine technische Modellattestierung. Die sichere
native Einbindung des bereits vorhandenen Routingadapters und mehrere
gleichzeitige Codex-/Grok-Workerprofile sind folgende gezielte Pakete; C1
erfindet dafür weder eine neue Rechtequelle noch eine weitere Queue.

README Deutsch/Englisch sind gezielt ergänzt. Website und Downloads brauchen
erst nach regulärer Integration, neuer Paketidentität und echter Auslieferung
eine Verfügbarkeitsänderung. Der C1-Quellkandidat ist kein öffentliches Release.

## English

The Core now selects the existing coordinator through explicit AutoNext
configuration, including initially disabled profiles. `coordinator_status`
provides bounded owner-only MCP state. An optional pinned completion target
delivers accepted/stopped events through the existing durable completion inbox,
with matching source permissions for receive, acknowledgement and queue access.
The existing claims, reviews, checks and event-driven continuation remain the
only execution authority; no skill or model request is needed for idle waiting
or advancing an already approved sequence. Local deterministic CLI tests are
distinct from provider, desktop, Windows and mobile deployment acceptance.
