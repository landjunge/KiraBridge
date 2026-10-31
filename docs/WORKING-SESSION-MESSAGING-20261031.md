# Nachrichten an eine arbeitende Codex-Sitzung

Stand 31.10.2026, Arbeitswhiteboard `0ab8b95a7369`. Meilenstein in Revision 9
gespeichert und unabhängig zurückgelesen. Kira-Skill verwendet.
[Strukturierte Belege](evidence/working-session-messaging-20261031.json).

## Konkrete Ursache

Nachricht `dc4d2181-2b44-4ee7-892e-385dc7f8c521`, Kanal
`kb-macos-whiteboard-updates-20261031`, Absender `chatgpt`, Empfänger `codex`,
Typ `work`: dauerhaft gespeichert, aber vor Terminalinput abgewiesen.
Persistierter Job: `failed`, `run_id/claimed/started=null`,
`phase=direct_admission`, `reason=visible_target_working`,
`terminal_input_attempted=false`, `automatic_retry=false`.
Beobachtung: `state=working`, `reason=current_progress_row`, `ready=false`,
`input_empty=true`. `delivered/receipt/acknowledged` sind null.

Queue-Hold `direct_admission_rejected` verhindert späteren Inboxabruf.
Der exakte Abruf als Codex lieferte leer; der Verlauf bleibt lesbar.
Das ist keine wartende automatische Nachlieferung. Derselbe Sendeschlüssel
liest nur den gespeicherten Ausgang, ohne erneut zuzustellen.

Der sichtbare Übergabepfad verlangt ein bestätigtes bereites Ziel.
Aktuell sind sichtbare Handoffs aktiviert und `separate_managed_after` ist
nicht gesetzt; es gilt dieser sichtbare Standardweg.
`work/question` erzwingen ihn auch bei `dispatch=false`.
`MessageReceiver.send` beobachtet nur die erstmalige Zulassung;
`DirectDelivery._settle` hält nachweislich vor Eingabe abgewiesene Datensätze.
So werden historische Aufträge nicht später unerwartet ausgeführt.
Die Arbeitsanzeige verursachte hier die Ablehnung; kein Return-Transportfehler.

Der ursprüngliche Datensatz wurde nicht freigegeben, wiederholt oder
nachträglich quittiert. Die Whiteboardpflege beruht auf dem aktuellen
Nutzerauftrag; Revisionen 8 und 9 belegen sie separat.

## Echter laufender Kommunikationsweg

Eine **neue** `note` mit `dispatch=false`, `request_reply=false` nutzt das
vorhandene Postfach. Der arbeitende Codex liest es selbst über MCP an
Arbeitsschritten. Kein nativer Return und kein zweiter Agent erforderlich.
Vertrag, Beispiel und Wiederaufnahme stehen im [Agentenkanal](AGENT_CHANNEL.md).

Produktiver Test auf Core `7dff6f2`, PID 25826, während diese Sitzung arbeitete:
Über den externen ChatGPT-App-Connector wurde
`kb-working-inbox-live-20261031-01` gesendet. Zwei lokale Codex-Abrufe lieferten
seq 374 und Receipt `62b3d519-7460-454d-a15f-ec51bd5ab588` identisch.
Nach Lesen quittierte Codex; danach war der Kanal leer. Exakt wiederholtes
externes Senden lieferte dieselbe ID, seq und ACK zurück. `processing=null`.
Die Notiz verlangte nur Lesen/Quittieren, keine fachliche Zusatzausführung.

Das beweist echten Connector-/MCP-Empfang während eines laufenden Turns.
Es beweist kein automatisches Aufwecken ohne Leser und keine dauerhafte
Deduplizierung externer Aktionen nach Absturz. Dafür braucht der Consumer einen
dauerhaften, mit der Aktion abgeglichenen Nachweis. Receipt/ACK sind keine
allgemeine Exactly-once-Garantie.

## Native Codex-Steuerung separat halten

Die offizielle OpenAI-Dokumentation beschreibt `turn/steer` am App Server:
Input ergänzt den aktiven Turn mit `threadId` und passendem `expectedTurnId`;
ohne aktiven Turn schlägt der Aufruf fehl. Quelle:
[Codex App Server](https://learn.chatgpt.com/docs/app-server#steer-an-active-turn).
Die [offizielle Remote-Beschreibung](https://developers.openai.com/blog/mastering-codex-remote-for-engineering)
unterscheidet Queue für einen späteren Turn von Steer für laufende Arbeit.

Diese APIs belegen keinen Zugriff der aktuellen KiraBridge-Terminalbindung
auf den App-Server-Verbindungskontext desselben laufenden CLI-Prozesses.
In den geprüften Bridgepfaden besteht keine solche Bindung. Ein neuer App
Server oder verwalteter Empfänger wäre kein Nachweis einer Zustellung in
diesen Turn. Kein Ersatzprozess, blindes Enter oder Interrupt eingeführt.

## Korrektur und gezielte Tests

`MessageManager.get` bezeichnete Jobs ohne verknüpfte sichtbare Run-ID als
`managed_receiver`, auch direkte Ablehnungen. Für persistierte `failed/blocked`
mit `phase=direct_admission` ohne verknüpften sichtbaren Handoff lautet die
lesende Kennzeichnung jetzt `failed_visible_admission`. Explizite bestehende
sichtbare Scopes behalten Vorrang. Jobs, Holds und Routing bleiben erhalten.

**88 passed in 5.86s** über `test_working_session_delivery.py`,
`test_messages.py`, `test_direct_delivery.py`, `test_visible_message_evidence.py`.
Zehn neue Fälle: echte authentifizierte HTTP-Aufrufe für Busy-`work/question`
und Inboxnotiz sowie lesende Statusgrenzen. Das native Busy-Terminal ist in
diesen HTTP-Tests ausdrücklich simuliert. Null Terminalinput, Hold, kein Replay,
stabile ID/Receipt, exakter Kanal, idempotentes ACK, fremder Principal und falsche
Receipt sowie keine Agentenausführung geprüft. Ruff/Format bestanden.
Die Simulation ergänzt den echten Postfachtest und originalen gespeicherten
Busy-Nachweis; kein zusätzlicher nativer Busy-Sendeversuch behauptet.

Private Rohbelege:
`~/.local/share/kirabridge/backups/macos-implementation-20261031T121031Z/working-session-live-20261031.private.json`.
Weitere Laufzeitbelege im [Installationsbericht](MACOS-ADAPTER-INSTALLATION-20261031.md).

## Produktive Bestätigung der Korrektur

Codecommit `c573709df91544f4094265e61d351ad00827cfbf` auf dem bestehenden
Entwicklungsbranch gepusht und remote exakt bestätigt, anschließend geprüft
gebaut und sichtbar unterstützt installiert. Neuer Core PID 29698,
Start `2026-10-31T13:41:11.017772+00:00`, Quellhash
`c95246efe9d208bb0ec7141a35fa31e39aaad433e9965babd77b3987feb02fc4`.

Der echte externe ChatGPT-App-Readback des ursprünglichen Datensatzes liefert
jetzt `failed_visible_admission`; Job und Nichtzustellungsbelege sind erhalten.
Dieselbe bereits quittierte Testnotiz liefert auch nach dem Core-Neustart
unverändert ID/seq/Receipt/ACK zurück; das Empfängerpostfach ist leer.
Frisches authentifiziertes HTTP-`tools/list` enthält die neue Anleitung zu
kooperierenden laufenden Empfängern. Whiteboard-Meilenstein Revision 12
gespeichert und zurückgelesen. Kein Replay und kein neuer Agentenauftrag.
