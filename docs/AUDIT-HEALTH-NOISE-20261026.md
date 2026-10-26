# Passive health diagnostics / Passive Health-Diagnostik

The stdio proxy checks daemon health every second. Previously each successful
poll recorded two diagnostic audit entries, exhausting the default daily budget
after about 1,000 polls per proxy. Multiple proxies share that database budget.

Only the internal `bridge_health({})` monitor is now marked `routine_health`.
The first healthy response and changes to connection generation, version,
instance or discovery revision retain their diagnostic pair. Identical healthy
polls are coalesced. Explicit health requests, terminal observation requests,
task/result/receipt calls, failures, cancellations and recovery remain recorded.
No tool invocation is skipped or repeated by this change. Internal poll pairs
are recorded after classification; their audit timestamps are recording times,
not a measurement of request duration. Connection lifecycle events remain intact.

The 2,000/day default limits **optional `diagnostic.*` entries**, globally by UTC
day. There is also a 20,000-record total diagnostic limit. Core task, completion
and audit-chain records are not deleted or disabled. Diagnostic exhaustion can
still make readiness report `diagnostic_recording_unavailable`; this repair does
not increase limits or erase existing history, and cannot retroactively recover
already dropped diagnostics.

Verification used isolated data only: the old behavior exhausted a ten-entry
test budget after eight polls. Fifteen new focused cases and four directly
affected existing regressions passed across the scoped runs, including real HTTP
handshake/reconnection, lost-write reconciliation and audit-chain/budget checks.
One extra recovery case first exposed, then verified the correction of, an
explicit health failure followed by background recovery. No whole suite ran.

**Deutsch:** Nur gleichbleibende erfolgreiche interne Health-Polls werden
zusammengefasst. Versions-/Instanz-/Rechtewechsel, Fehler und belegrelevante
Aufrufe bleiben sichtbar. Die Tagesgrenze betrifft Diagnosetraces, nicht pauschal
die Ausführungserlaubnis. Bestehende Limits und Historie bleiben unverändert.
Events-Abonnements sind weiterhin optional; dieses Logging-Fix registriert weder
Abonnements noch einen Chat-Aufweckkanal. Eine lokal gestartete Consumer-Promise
beweist noch keinen serverseitigen Eingang oder eine spontane Chat-Zustellung.
