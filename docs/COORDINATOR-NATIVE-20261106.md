# Native Koordination über Core und MCP

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

Der neue lesende MCP-Aufruf `coordinator_status` benötigt `team.read` und den
konfigurierten Eigentümer. Er liefert höchstens die 16 Aufgaben des aktuellen
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
