# KiraBridge 0.8.0rc23 · managed process lifecycle

Managed background execution acknowledges its own recorded process start without
mistaking it for terminal input or process completion. Its requested execution
timeout continues to apply after admission; historical uncertain jobs are never
replayed.

The release also addresses cleanup of process groups created inside an explicitly
owned managed session. In particular, macOS `system_profiler` may start a reporter
in another process group while retaining the created session. Cleanup must verify
that ownership, terminate only those groups and observe actual stream EOF.
Incomplete identity or cleanup remains an explicit unknown outcome.

Deutsch: Die beiden gemeldeten P0-Pfade werden getrennt abgesichert: eigener
Prozessstart beendet die Admission-Wartezeit, und bekannte Gruppen der eigenen
Prozesssitzung werden bei Timeout vollständig bereinigt. Ein Timeout ist kein
erfolgreicher Bericht; unbekannte alte Tasks bleiben erhalten. Die bestehende
macOS-Mitteilungsfreigabe wird nicht erneut angefordert.

See [the scoped repair evidence and verification status](RC23-RUNTIME-P0-20261101.md).
Actual package and running acceptance are recorded there separately. This does
not certify the remaining calculator focus, dynamic pagination or Brave cases.
