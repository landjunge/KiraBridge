# Zweistufiger Versand von `session.input`

**Abgelöst für Daniels Installation:** siehe [Voice-Policy](VOICE-POLICY.md).
Eves sichtbare Terminaleingaben haben eine dauerhafte Operationsfreigabe ohne
Marker und Einzelbestätigung. Das Voice-Gate gilt für Bridge-Nachrichten.
Der nachfolgende Ablauf beschreibt ausschließlich die optionale Altregel;
sie muss zusätzlich mit `principals = ["EXPLIZITER-PRINCIPAL"]` eingeschränkt werden.

```toml
[session_input_policy]
enabled = true
principals = ["EXPLIZITER-PRINCIPAL"]
timeout_seconds = 60
```

Der Timeout ist konfigurierbar (größer als null, maximal 86400 Sekunden).
Bestehende Konfigurationen ohne diesen Abschnitt behalten ihr bisheriges Verhalten;
Daniels Installation wird ausdrücklich mit `enabled = true` aktiviert.
Die drei Rechtestufen bleiben erhalten. Diese optionale Versandregel gilt nur
für explizit ausgewählte Principals ohne dauerhafte `session.input`-Freigabe.

Jeder neue Auftrag wird mit unverändertem Inhalt und Ziel in SQLite gepuffert.
Endet der Text mit dem exakten, kleingeschriebenen `go-go-go`, wird der Puffer
sofort freigegeben. Abschließende Leerzeichen/Zeilenumbrüche sind erlaubt.
Der Marker und der direkt vor ihm liegende Leerraum werden nicht ins Terminal
geschrieben. Ein Text, der nur aus dem Marker besteht, wird zurückgewiesen.
Die normale Berechtigungsprüfung bleibt bestehen.

Ohne Marker bleibt der Auftrag `created`, der Puffer `waiting`. Er wird weder
als zugestellt noch als verarbeitet gemeldet. Daniel kann ihn separat im lokalen
Steuerfenster unter **Rechte → Jetzt senden** freigeben. Der authentifizierte lokale
Bedienweg erstellt und verbraucht dafür atomar einen an diesen Auftrag und Inhalt
gebundenen Einmal-Token. Alternativ erstellt Daniel lokal mit
`kirabridge --principal PRINCIPAL grant request.json` einen Token; der Client sendet
anschließend denselben, unveränderten Auftrag mit `task_submit`/`action_submit`
und diesem `approval`-Token erneut. Die CLI-Optionen stehen in `kirabridge --help`.
`kirabridge approve TASK_ID` ist ebenfalls eine ausdrückliche lokale Freigabe.
Die Freigabe vertraut dem authentifizierten lokalen Bedienzugang. Über MCP gibt es keinen Token-Aussteller.

Die Frist beginnt beim ersten Puffern und wird durch Wiederholungen nicht verlängert.
Ein abgelaufener Puffer wird `expired`, der Auftrag `cancelled` mit
`reason=input_buffer_expired`. Ein späterer Token oder Neustart reaktiviert ihn
nicht. Die Ablaufmeldung wird auch im Rückkanal gespeichert.
Eine rechtzeitige Freigabe beendet das Warten; die anschließende Ausführung darf
in der normalen Warteschlange stehen.

Vor dem Schreiben prüft die Bridge erneut Auftrag, Inhalt und aktuellen Terminal-PID.
Nur ein freigegebener Puffer darf einmal `dispatching` werden. Erst nach der
Transportbestätigung wird er `sent`. Das bestätigt die Terminal-Eingabe,
noch keine Verarbeitung durch den Agenten und keine gesprochene Antwort.
Unklare Transportausgänge werden nicht automatisch erneut gesendet.
Wartende Puffer und ihre ursprünglichen Fristen überleben Neustarts; das spätere
Abschalten der Policy gibt solche Puffer nicht automatisch frei.

`bridge_health`, `policy_inspect` und `operation_catalog` zeigen die geladene Policy.
Aufträge enthalten `input_buffer` mit Zustand, Frist und Freigabequelle.
Das Protokoll führt `session.input.buffered`, `.released`, `.dispatching`, `.sent`
und `.expired` auf. Marker-Freigaben stehen als `release_source=suffix` im Puffer.

Tests decken die beiden Versandwege einschließlich eines echten privaten tmux-Terminals,
falsche Tokens, geänderten Inhalt, doppelte Aufrufe, Ablehnung, Ablauf nach Neustart,
manuelle Rechte und die direkte Transport-Sperre ab. Die Tests greifen keine
bestehenden Benutzersitzungen an. Sie bestätigen keine Grok-Audiowiedergabe.
