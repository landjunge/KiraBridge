# KiraBridge 0.8.0rc27 — weniger Tastatur-Werkzeugübergaben

Kurze `keyboard.control`-Tasks liefern ihren Abschluss jetzt bis zu zwei Sekunden
im ursprünglichen Aufruf. Längere Tasks bleiben unter derselben ID abfragbar;
das Wartebudget beendet und wiederholt keine Eingabe. Der Stdio-Proxy verwendet
Werkzeugschemas höchstens eine Sekunde wieder, mit Invalidierung bei Änderungen
und Verbindungswechsel. Ausführung, Antworten, Berechtigungen und Tastaturziele
werden weiterhin frisch geprüft. Werkzeughinweise empfehlen ganzen Text mit
Zeilenumbrüchen in einem Aufruf ohne Zwischenablage.

Historisch lagen 96,361 % der beobachteten Gedichtzeit außerhalb der internen
Taskausführung. Die genaue ChatGPT-Callquote und Cloud-Teillatenzen sind nicht
öffentlich bzw. lokal messbar. Der Cache beseitigt kein Plattformlimit.
[Untersuchung und Grenzen](RC26-KEYBOARD-LATENCY-20261102.md).

Gezielte lokale Prüfungen: 101 Tests bestanden; native Empfängerprüfung mit
41 Zeichen und einem Textcall in rund 0,42 Sekunden einschließlich Readback.
Hash, Cursor und unveränderte Clipboardgeneration bestätigt. Ein früherer
Durchlauf traf eine weiterhin ungeklärte native Zielprüfungsverweigerung;
unsichere Eingaben wurden nicht wiederholt. Keine allgemeine Zuverlässigkeitsquote.

Dieses Intel-macOS-Paket wird lokal gebaut und getrennt geprüft. Die produktive
RC26-Installation und laufende Sitzungen bleiben durch diese Veröffentlichung
erhalten. Kein neuer ChatGPT-Cloud-Abnahmelauf und keine ARM-/Linux-/Windows-Abnahme.
