# Wiederherstellung des bisherigen Bridge-Anschlusses

**Aktueller Stand:** [Korrigierte Events-Anbindung erneut aktiviert; echter Empfang im ursprünglichen Chat weiterhin offen](MCP-SCHEMA-CACHE-20261019.md). Die nachfolgenden Betriebsstände sind historische Nachweise.

**Zusätzlicher ausdrücklicher Betreiberauftrag zu ChatGPT-Rechten:** Die App-Freigabe
war bereits „Allow all actions“. Verbleibende lokale Policy-Lücken wurden gezielt
beseitigt: `file.delete` ergänzt, direkte Datei-/Lesewurzeln auf `/` gesetzt und
`chatgpt` als gegenseitiger Nachrichtenpartner von Codex/Grok ergänzt. Automatikmodus
und `allow_any_executable=true` gelten. Andere Konfiguration und OS-Rechte wurden
nicht verändert. Der Hauptdienst wurde nach atomarer Prüfung von 0 aktiven Tasks
und 0 Empfängerjobs neu geladen; privates Backup unter
`~/.config/kirabridge/rights-chatgpt-20261019-01/`.
Echte App-Aufträge legten eine neue eigene Testdatei außerhalb der früheren
Projektliste an und löschten sie wieder, beide completed. Kein Grok-Aufruf.
[Änderungsbeleg](../examples/chat-events/recovery-20261019-01/chatgpt-rights-change.json),
[App-Tests](../examples/chat-events/recovery-20261019-01/chatgpt-rights-app-tests.json).
Die Freigaben gelten innerhalb der Rechte des angemeldeten Betriebssystembenutzers;
Transport-/Authentifizierungsregeln und zuvor verlangte begrenzte Ausführungsrunden
werden damit nicht zu globalen OS-Administrationsrechten umgedeutet.

**Nach Nutzer-Refresh erneut geprüft:** Ein echter neuer Auftrag über die verbundene
App ist erfolgreich: `bridge-recovery-app-20261019-02`, completed, Exitcode 0,
`KIRABRIDGE_RECOVERY_APP_OK`.
[App-Auftragsbeleg](../examples/chat-events/recovery-20261019-01/post-refresh-app-task.json).
Die App verlangt trotz Refresh weiterhin das veraltete Pflichtfeld. Die
Kompatibilitätsangabe `completion_subscription=""` erlaubt normale Aufträge am
zurückgestellten Server. Ein leerer Wert ist keine Subscription-ID und erzeugt
keine Subscription; der Legacy-Server ignoriert diese zusätzliche Angabe.
Ohne diese Zusatzangabe weist der Connector die Anfrage weiterhin vor dem Server
ab. Der Schema-Cache ist deshalb **nicht dauerhaft bereinigt**; die praktische
Kompatibilitätslösung ist dagegen tatsächlich über die App nachgewiesen.
Keine weiteren Refresh-Wiederholungen wurden vom Nutzer verlangt.
Die folgenden Refresh-Angaben dokumentieren den vorausgehenden Stand.

Stand 19.10.2026: Die Events-Fassade wurde im erneut geprüften Leerlauf
zurückgerollt. Der bisherige Stdio-Proxy ist wieder aktiv. Der separate
Ereignissender ist aus launchd entladen; seine Definition liegt gesichert im
privaten Aktivierungsbackup und startet nicht erneut beim Login.

Die Umstellung hatte normale Aufträge fälschlich von einer verifizierten
`completion_subscription` abhängig gemacht. Da keine echte Host-Subscription
vorliegt, wurde ein Aufruf mit `explicit_verified_chat_subscription_required`
abgewiesen. Zusätzlich scheiterte der Sender nach dem gemeinsamen Neustart von
Hauptdienst und Sender an `httpx.ConnectError: All connection attempts failed`.
Seine Startbereitschaft war nicht zuverlässig an die Bereitschaft des Hauptdiensts
gekoppelt. Das waren Fehler der vorgenommenen Integration, keine belegten
Kontingent- oder Providerprobleme.

## Nachweise der Wiederherstellung

- Originales Tunnelprofil bytegleich wiederhergestellt; Hauptdienst, bestehende
  Aufgaben und Sitzungen nicht zurückgesetzt. Kein Datenbankbackup zurückgespielt.
- Direkter authentifizierter MCP-/Stdio-Status funktioniert. Nach einem zunächst
  aufgetretenen Timeout funktioniert auch der tatsächliche verbundene App-Status.
- Ein echter Terminalauftrag `bridge-recovery-20261019-01` unter `chatgpt` ohne
  Subscription endete completed, Exitcode 0, `KIRABRIDGE_RECOVERY_OK`.
- Die aktuelle Serverdefinition von `task_request` verlangt keine
  `completion_subscription`.
- Die App weist eine neue Einreichung jedoch noch vor dem Server mit
  `completion_subscription [required]: Missing required property` zurück.
  Ihre Werkzeugdefinition muss nach dem Rückrollen aktualisiert werden.
  Der abgewiesene App-Auftrag wurde nicht ausgeführt.

[Wiederherstellungsbeleg](../examples/chat-events/recovery-20261019-01/recovery.json),
[echter lokaler Terminalauftrag](../examples/chat-events/recovery-20261019-01/local-recovery-task.json),
[aktuelle Serverdefinition](../examples/chat-events/recovery-20261019-01/server-task-schema.json).

## Verbleibender Schritt

**https://chatgpt.com/plugins → bestehende KiraBridge-Verbindung → Refresh**,
beziehungsweise „Rescan MCP server“, wenn so beschriftet. Dadurch muss die private
App die wiederhergestellten Werkzeuge neu einlesen. Keine neue App, kein neuer
Tunnel und kein Schlüsseltausch. Danach eine gewöhnliche Einreichung über die App
prüfen; erst dann ist auch diese Stufe wieder abgenommen.

Die Events-Fassade nicht anhand der älteren Aktivierungsanleitung erneut laden,
bevor gewöhnliche Aufträge ohne Subscription kompatibel bleiben und der
Senderstart zuverlässig auf den Hauptdienst wartet. Autonomes Chat-Aufwecken
bleibt unbestätigt; der vorhandene aktive Completion-Consumer bleibt bestehen.
