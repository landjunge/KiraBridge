# Begrenzte Transportbelege bei Launcherfehlern

Paket `BP-GROK-TRANSPORT-DIAGNOSTICS-FIX-20261106`, Basis
`cb87a9ef97f2d2b46a1c0bf89a50127a266361ac`. Nur künftige Aufrufe des vorhandenen
Launchers betroffen; keine neue Queue, Providerroute oder automatische Wiederholung.
Die installierten Routerreleases und historischen Receipts werden nicht verändert.

Die Originalfälle `coord-native-c1-grok-review-20261106-v1` und
`windows-evidence-review-20261105-v1` bleiben UNKNOWN. Ihre Receiptzeitpunkte passen
stark zu den gesetzten 180-/600-Sekunden-Fristen, beweisen aber keine konkrete
Exception oder Grok-/Netz-/Quotaursache. Wrapperexit2 war kein beobachteter
Grokexit2. Originaldiagnose und private Belege liegen unter
`~/.local/state/bigplan-grok-original-transport-diagnosis-20261106/`.

## Erhaltene Beobachtungen

`run_bounded` erhält auf Spawn-, Wait-, Drain- und Streamfehlern eine strukturierte
`process_evidence` an der Exception. Dieselbe Struktur ergänzt normale Ergebnisse:

- Phase, beobachteter Spawn/PID und tatsächlich beobachteter `native_exit_code`;
- monotone vergangene Zeit und gesetztes Timeout;
- ob der Abbruch des eigenen direkten Kindes angefordert wurde und gegebenenfalls
  die Fehlerklasse dieser begrenzten Bereinigung;
- stdout-/stderr-Bytezähler, Truncation und begrenzte Teilpuffer;
- Exceptionklasse und gegebenenfalls errno, ohne argv, Prompt, Umgebung oder
  beliebigen Exceptiontext in die Diagnose zu kopieren.

Hauptprozess-Timeout (`wait_main`) und nach Kindende nicht rechtzeitig abgeschlossene
Streams (`drain_after_exit`) bleiben getrennt. Das bisherige Streaminglimit bleibt
1MiB stdout und64KiB stderr. `read1` erhält bereits verfügbare kleine Teilstücke,
ohne auf einen vollständigen großen Leseblock oder EOF warten zu müssen.
Die bestehende begrenzte Joinphase kann auch nach einem Haupttimeout anfallen.
Nach angefordertem Kill ist die eigene Waitbereinigung auf eine Sekunde begrenzt;
ein weiterhin unbekannter Status wird nicht erfunden. Es gibt keine erweiterten
Killrechte für andere Sitzungen oder Nachkommen. Ein Streamfehler kann weiterhin
unbekannte lebende eigene Ressourcen hinterlassen; die erfasste PID ist kein
Wiederverwendungsrecht oder Livenessbeweis.

Der Launcher erhält vorhandene Teilpuffer auch auf Exceptions. Ausgabedateien
werden exklusiv mit Modus0600 angelegt; vorhandene Dateien/Symlinks werden nicht
überschrieben. stdout und stderr werden unabhängig versucht. Ein Fehler einer
Datei verhindert nicht den Versuch der anderen. Bekannter Kindexit wird vor der
folgenden Dateiausgabe festgehalten. Ein sekundärer Capturefehler ersetzt weder
die primäre Fehlerklasse noch einen bereits bekannten Kindexit.

`transport_error` ergänzt Kategorie/Klasse um die Phase. `native_exit_code` ist
ausschließlich ein beobachteter Prozessstatus, einschließlich eines tatsächlich
beobachteten negativen Signalstatus nach eigenem Kill auf POSIX. Das ist keine
fachliche Providerantwort oder Modellattestierung. Ein nach Kindexit0 verlorener
Transport oder IO-Fehler bleibt `state=unknown`; vorhandene bekannte Beobachtungen
dürfen dabei erhalten bleiben. Der Wrapper kann weiterhin Exit2 liefern.

Exklusive Admission, ursprüngliche Task-ID, NoReplay, UNKNOWN-Schreiblease,
Matrix-/Rechteprüfung und fachliche Abnahme bleiben bestehen. Ein vorhandenes
Ausgabefile nach einem Kindstart ist ein Capturefehler, keine nachträglich
vorgetäuschte Workspace-Ablehnung. Rohausgaben bleiben private Dateien und können
sensible Arbeitsinhalte enthalten; Diagnosemetadaten und Boardberichte übernehmen
keine rohen Prompt-/Ausgabe-/Zugangsdaten. Die Korrektur liest keine Kontodateien.

## Gezielte Prüfung und Grenzen

Neue Regressionen nutzen vorhandene Fake-Matrix-/CLI-Fixtures und eigene lokale
Python-Stand-ins: echter eigener Waittimeout mit Teilstdout/stderr und NoReplay;
synthetischer Timeout ohne argv-Leak; bekannter Exit7 plus Capture-IO-Fehler;
Kindexit0 plus gestallte Fake-Streams; Spawnfehler ohne erfundenen Exit;
begrenzte/private Teilausgaben; vorhandener Capture-Symlink ohne fremdes
Überschreiben; normale Grok-Transportantwort mit ungültigem Metadaten-JSON.
Alte Erfolg-, Lease-, Rechte- und Admissionfälle werden im betroffenen Testmodul
mitgeprüft. Keine echten Providerstarts oder historische Replayversuche.

Die Änderung ist lokal implementiert/getestet. Rootreview, Merge, Push,
Installation und Provider-/Windows-Liveabnahmen bleiben getrennte Schritte.
Der neue Fehlerbeleg garantiert keine Diagnose bei einem abrupten Absturz vor
Receiptfinalisierung; dort bleibt die vorhandene Admission als UNKNOWN-Grenze.
Eine fehlgeschlagene finale Receiptspeicherung bleibt `OutcomeUncertain`.
README DE/EN und Webseite sind nicht betroffen: kein neuer Nutzerbefehl,
Installationsweg oder veröffentlichter Download.

## Enger IO-Nachtrag nach unabhängigem Review

Der erste Freeze280421a erhielt NEEDS_FIX: Ein stdin-write-EIO wurde verschluckt,
ein stdout-close-EIO entwich als Threadexception. Trotz Kindexit0 war dadurch ein
falsches `process_completed` mit freigegebener Schreiblease möglich.
Der Nachtrag erfasst auch stdin-write/flush und das Schließen jedes Streams als
`stream_io`. Die Fehlerkarte nennt `stream_name`, `operation`, Klasse und errno;
die bisherigen stdout-/stderr-Indizes0/1 bleiben bestehen, stdin erhält2.
Arbiträrer Fehlertext wird nicht übernommen. Eine tatsächlich beobachtete native0
bleibt erhalten; der Transport bleibt UNKNOWN und die Schreiblease bestehen.
Es gibt keine Parser-, Prozesskill- oder Wiederholungsänderung. Zusätzliche lokale
EIO-Injektionen prüfen echte Fehlereinwirkung, keine entwichenen Threadexceptions,
Teilpuffer, Lease und unveränderte NoReplay-Receipts. Alte Original- und
unabhängige280421a-Belege bleiben separat erhalten.
