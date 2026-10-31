# Agentenkanal

Stand 31.10.2026. SQLite und authentifizierte MCP-Werkzeuge transportieren
adressierte Nachrichten. Absender, Rechte und gegenseitige `message_peers`
stammen aus dem aktuellen Zugang und der lokalen Konfiguration.

## Sichtbarer Auftrag und Postfach

Im sichtbaren Standardweg erzwingen `kind="work"` und
`kind="question"` an konfigurierte CLI-Agenten eine geschützte sichtbare
Übergabe. **Auch `dispatch=false` schaltet diese Prüfung nicht aus.**
Ein arbeitendes Codex-Ziel kann `visible_target_working` ergeben, bevor
irgendeine Terminaleingabe versucht wurde. Ein gespeicherter Fehler ist
keine wartende Zustellung und wird nicht automatisch erneut versucht.

Zusätzliche Hinweise an einen bereits arbeitenden, kooperierenden Empfänger
verwenden das bestehende Postfach:

```json
{
  "message": {
    "recipient": "codex",
    "conversation_id": "bekannter-arbeitskanal",
    "idempotency_key": "eindeutige-stabile-anweisung-001",
    "kind": "note",
    "body": "Aktualisiere das vereinbarte Whiteboard am nächsten Meilenstein.",
    "dispatch": false,
    "request_reply": false
  }
}
```

Diese Kombination speichert ohne Empfängerjob und Terminalinput
(`processing=null`, `processing_route=external_client_inbox`). Sie startet
keinen Agenten und weckt einen inaktiven Chat nicht auf. `conversation_id`
adressiert einen Nachrichtenkanal, keine TTY oder Codex-Thread-ID. Genau ein
vereinbarter Empfänger muss diesen Kanal unter seinem Principal aktiv lesen.

Der Empfänger ruft an vereinbarten Arbeitsschritten
`message_receive(conversation_id="bekannter-arbeitskanal", after=0)` auf,
prüft und dedupliziert IDs, übernimmt die Anweisung und quittiert danach
mit `message_ack(message_id, receipt)`. Der Sender prüft `message_get`.
Ohne aktiven Leser bleibt die Notiz gespeichert und unquittiert. Es gibt
keinen automatisch injizierten Modellkontext und keine garantierte sofortige
Unterbrechung.

## Zustände und Wiederaufnahme

| Beleg | Bedeutung |
|---|---|
| ID/`seq`, `created` | Dauerhaft gespeichert |
| `terminal_input_attempted=false` | Kein Terminalinput versucht |
| `failed`, `phase=direct_admission` | Direkte Übergabe abgewiesen |
| `processing_route=failed_visible_admission` | Präzise lesende Kennzeichnung dieser Ablehnung ohne verknüpften sichtbaren Handoff |
| `delivered`, `receipt` | Adressierter Client hat über `message_receive` empfangen |
| `acknowledged` | Berechtigter Empfänger quittierte die Receipt; keine allgemeine fachliche Abschlussgarantie |
| Return-/Rollout-/Antwortbeleg | Separater Nachweis nativer Übergabe und Agentenverarbeitung |

Ältere Installationen nennen direkte Ablehnungen ohne sichtbare Run-ID
irreführend `managed_receiver`; gespeicherte `processing.evidence` bleiben
maßgeblich. Die Statuskorrektur ändert weder Routing noch Holds.

Unquittierte, nicht gehaltene Nachrichten bleiben mit derselben ID und Receipt
abrufbar. `after=0` berücksichtigt ältere offene Nachrichten; ein höherer Cursor
überspringt sie bewusst. Identischer Absender, Schlüssel und vollständiger
Inhalt liefern beim erneuten Senden denselben Datensatz. Inhaltliche Änderung
unter demselben Schlüssel wird abgewiesen.

Das garantiert keine einmalige Ausführung beliebiger externer Aktionen.
Ein robuster Consumer braucht einen dauerhaften Verarbeitungsnachweis nach
Nachrichten-ID und idempotente fachliche Operationen. Nach einem Absturz zwischen
Aktion und ACK zuerst den Aktionsbeleg abgleichen. Ohne atomare Kopplung bleibt
ein unklarer Zustand möglich; nicht blind wiederholen. Ein flüchtiges Set genügt
nur für einen ununterbrochenen Testlauf.

Gehaltene historische Fehler/Unknowns werden weder durch `receive` noch
erneutes `send` automatisch freigegeben. Der konkrete aktuelle Fehler ist im
[Nachrichtenbericht](WORKING-SESSION-MESSAGING-20261031.md) dokumentiert.

## Werkzeuge und Grenzen

| Werkzeug | Funktion |
|---|---|
| `message_send(message)` | Adressiert und idempotent speichern; nach Typ zulassen |
| `message_receive(after=0, conversation_id=...)` | Eigene offene, nicht gehaltene Nachrichten lesen; optional begrenzt warten |
| `message_ack(message_id, receipt)` | Nur als adressierter Empfänger mit passender Receipt quittieren |
| `message_get(message_id)` | Berechtigte Nachricht und Verarbeitungsbelege lesen |
| `conversation_get(conversation_id)` | Berechtigten Verlauf einschließlich gehaltener Fehler lesen |
| `message_events(message_id)` | Zustellungs-, Verarbeitungs- und ACK-Ereignisse lesen |
| `message_channel_status()` | Konfigurierte Gegenstellen und Empfängerzustände prüfen |

Konfigurationsabhängige Sender wie `chatgpt` sind möglich. Fremde ACKs oder
Receipts werden abgewiesen. `request_reply=false` verhindert eine automatische
Antwortanforderung, ändert aber nicht allein den Zustellungsweg. Optional
konfigurierte getrennte verwaltete Empfänger sind eigene Sitzungen und kein
Nachweis einer Zustellung in eine bestehende Terminal-Sitzung.

Die [Prüfung vom 17.10.](evidence/agent-channel-2026-10-17.json) und
[Empfängerprüfung vom 19.10.](../examples/message-receiver/README.md) bleiben
historische Belege für ihre damalige Konfiguration.
