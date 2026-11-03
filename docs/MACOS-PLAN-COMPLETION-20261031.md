# Abschluss des bestehenden macOS-Adapterplans

31.10.2026 · Arbeitswhiteboard `0ab8b95a7369` · Fortsetzung auf ausdrücklichen
Nutzerauftrag „bis fertig im Team und Kira-Skill“. Push und produktive Installation
sind freigegeben. Grundlage ist der bestehende Branch
`docs/macos-adapter-phases1-3-20261031`, Ausgang `480e3c9`.
Die bisherigen Prompt-Reparaturen und ihre Fehlerhistorie bleiben erhalten.
[Strukturierte Prüfbelege](evidence/macos-plan-completion-20261031.json).

## Mussumfang und Team

Der ursprüngliche Plan verlangt Bestandsaufnahme, Apple-Recherche, modularen
Adapter auf dem vorhandenen Ausführungsweg, gezielte gemeinsame Prüfungen und
nach Freigabe Paket/Installation. Allgemeine Fenster-, Capture-, Notifications-
und Preferencesprovider sind im Entwurf spätere optionale Erweiterungen.
Sie sind keine noch fehlende zweite Implementierung des bestehenden Auftrags.

Root koordiniert Integration, echte Abnahme und sichtbare Installation.
`helper_permission_impl` implementierte ausschließlich Helperdiagnostik und ihre
isolierten Tests; `independent_macos_review` prüfte Code und native API-Bindungen;
`plan_completion_audit` prüfte Mussumfang, fehlende Quellen und übernimmt den
unabhängigen Paket-/Installationsabgleich. Keine konkurrierenden Dateiedits.

## Ergänzte Funktion

Der bisherige Status erhob nur Coreberechtigungen. Ein Aufrufer kann nun
ausdrücklich `macos_status(check_helpers=true)` oder über den vorhandenen
generischen bzw. gecachten Aufrufweg
`platform.status` mit `{"check_helpers": true}` wählen. Ohne diesen Schalter
bleibt der Status unverändert; Tooldiscovery und Health starten keinen Helper.
Der bestehende zentrale Berechtigungscheck läuft vor jeder Diagnose.

Ein fester, begrenzter `/usr/bin/osascript`-JXA-Prozess erhebt seine eigenen
öffentlichen AX-/CG-Preflightwerte. Apple-Events-Prüfungen beziehen sich nur
auf jeweils genau ein bereits laufendes festes Ziel Terminal.app bzw.
System Events; PID-Descriptor und Vorher-/Nachherprüfung binden das Ziel.
`askUserIfNeeded=false`, keine Eventsendung, kein Zielstart, kein Clipboardinhalt.

Der Elternprozess vergleicht die ausgegebene Helper-PID mit dem tatsächlich
gestarteten Kind, prüft Zeilen/Typen/Ziele, begrenzt Ausgabe auf 16 KiB und
Laufzeit standardmäßig auf fünf Sekunden und reapet genau diesen Prozess.
Timeout, ungültige Beobachtung, fehlendes Symbol, geändertes Ziel und unklare
Bereinigung bleiben ausdrücklich erkennbar. Cancellation wird auch bei
Bereinigungsfehlern erhalten.

`helper_diagnostics` gehört ausschließlich zum expliziten Ergebnis. Die Werte
werden weder in `PermissionProbe` noch in `actor_identities` übernommen und
ändern keine Discoveryrevision. `authorizes_future_helpers=false` und
`updates_provider_permissions=false` verhindern eine irreführende Übertragung
auf einen späteren Worker oder auf pbcopy/pbpaste bzw. die Desktop-App.
Das ist eine echte prozessgebundene Diagnose, keine neue Rechtevergabe.

## Native API-Anbindung und Fehlerbelege

Die erste reale Probe lieferte AX korrekt, aber zwei öffentliche C-Aufrufe
waren nicht brauchbar angebunden: CGPreflightScreenCaptureAccess fehlte in den
JXA-Metadaten trotz Frameworkimport; AEDesc scheiterte an inkompatiblen
Structreferenzen. Beide Fehlbelege sind privat erhalten.

Explizite `ObjC.bindFunction`-Signaturen beheben das: AX Boolean als unsigned
char, CG als C bool, AE als OSStatus/int mit zwei UInt32-Eventcodes,
Boolean/unsigned char und opakem `const AEDesc*`. Die Typen und Wildcardprüfung
stimmen mit Apples lokalen öffentlichen SDK-Headern überein; der Descriptor
bleibt während des Calls Eigentum von NSAppleEventDescriptor.
Quellen: [AXIsProcessTrusted](https://developer.apple.com/documentation/applicationservices/1460720-axisprocesstrusted),
[CGPreflightScreenCaptureAccess](https://developer.apple.com/documentation/coregraphics/cgpreflightscreencaptureaccess()),
[AEDeterminePermissionToAutomateTarget](https://developer.apple.com/documentation/coreservices/3025784-aedeterminepermissiontoautomatet).

Finale normalisierte native Probe auf macOS 15.7.4/Intel: Helper PID 38751,
AX und CG positiv, Terminal-Automation OSStatus 0 bei unveränderter Ziel-PID
36845; nicht laufende System Events korrekt `unknown/target_not_running`.
Helperbereinigung bestätigt. `helper-native-final.json` SHA256
`573bd6ba98cfa18381ec9199e5eade7103714efd761f2c8bddd5e9d8c97ba110`;
der gespeicherte Skripthash stimmt mit der endgültigen Implementierung überein.

## Prüfungen und Installationsgrenze

70 gemeinsame Provider-/Status-/Readquery-/Discoveryfälle bestanden. Diese
testen die drei autorisierten Statuswege einschließlich echter HTTP-Aufrufe
und persistiertem Task, unveränderte Discovery-/Providerrechte, verweigerte
Aufrufer und strikt begrenzte Eingaben. Im Helpermodul bestanden zunächst
37 Fälle; zwei nachträgliche Cancellationfälle und eine neue JXA-Regression
wurden gezielt ergänzt und geprüft. Der letzte dazugehörige Lauf hatte zwei
ausgewählte Erfolge und 38 abgewählte Fälle; überlappende Zahlen nicht addieren.
Ruff/Format sowie unabhängiger finaler Binding-/Sicherheitsreview sind positiv.

Die gemeinsame native HTTP-MCP-Abnahme bestand vollständig mit 16 Prüfungen:
authentifizierte Discovery und neue Helperdiagnose, generischer Statustask,
manuelle Approvalgrenzen, echte Busy-/Stale-/Schemasperren, kurzer umbrochener
Prompt mit einmaligem Paste/Return und genau einer Antwort im echten Rollout,
Text mit Leerzeile, expliziter Return ohne Paste, `/resume` und exakt eine
Bestätigung des eigenen Menüs. Kein zusätzlicher Eingabefallback oder Fenster.
Eigener Test-Codex beendet; die wiederverwendete kontrollierte Shell und die
ursprünglichen Fenster/Prozessidentitäten sind erhalten. Prüfquellhash:
`9244aa9fb6fa39e792e7439edab5895f0f031231b2b365f3f1c2cf82b4a01685`.

## Produktive Installation und Abschluss

Codecommit `831150a9b973410fd7eaca90dafd0996818234fc` auf dem bestehenden
Entwicklungsbranch gepusht und remote exakt bestätigt. Offline gebautes Bundle
SHA256 `d8ca6950fbada6d60b97aa26106df532ff7f231397559bc62b3ff44e2f451874`.
Unabhängig alle 427 Manifestdateien und 134 Pythondateien in Git/Wheel/Payload
bytegleich geprüft; isolierter Darwin-x86_64-Installationssmoke bestanden.
Das ist keine zusätzliche ARM-Abnahme oder öffentliche Veröffentlichung.

Vor Installation: vollständige vorige Installation mit 1348 Einträgen, acht
Konfigurationsdateien samt Credentials/Modi und konsistente SQLitekopie frisch
gesichert. Integrität `ok`; keine aktiven Bridge-Tasks oder Empfängerjobs.
Unterstützter Installer sichtbar im selben eigenen Terminal 8356/ttys001,
Shell 38838: 15:11:49–15:12:00 UTC, Exit 0. Neuer Core PID **40636**, Start
`2026-10-31T15:11:58.839455+00:00`, Instanz
`7d05de2ba3f04290981bee2d6290ee29`, Quellhash
`9244aa9fb6fa39e792e7439edab5895f0f031231b2b365f3f1c2cf82b4a01685`.
Versionlabel bleibt 0.8.0rc20; Commit und Hash identifizieren die Installation.

Der tatsächliche externe ChatGPT-App-Connector erreicht die neue Helperfunktion:
eigener Diagnoseprozess 40652, AX/CG und beide inzwischen laufenden AE-Ziele
positiv, weiterhin keine übertragbare Freigabe. Derselbe produktive Core stellte
den 886-Zeichen-Prompt `macos-plan-installed-prompt-20261031-v2` genau einmal zu:
`completed`, Attempt 1, Return=true, Completion empfangen/ACK. Sichtbare Antwort
und genau ein User-/Finalantwortitem im eigenen Rollout
`01a19285-4839-7581-a5c8-60b4fd0a973b` unabhängig geprüft.
Ein vorgelagerter eigener Testaufruf enthielt irrtümlich einen Return-only-Guard
im Textmodus und wurde `invalid_arguments/not_submitted` vor jeder Eingabe
abgewiesen. Er bleibt als Prüferfehler erhalten und wurde nicht als Unknown-
Übergabe wiederholt. Ein anfänglicher Cleanup-Modellfehler wurde ebenfalls vor
jeder Cleanup-Eingabe erkannt und dokumentiert. Die produktive Reparatur benötigte
keinen zusätzlichen Codefix oder manuellen Nach-Return.

Unabhängige Installationsprüfung bestätigt current/release/launchd und laufenden
Code, 149 originale Wheeldateien bytegleich sowie alle 155 Zeilen des vom
Installer erweiterten RECORDs. Konfiguration/Credentials/Modi, Berechtigungsrevision,
Dienstoptionen außer Interpreterpfad, alle 28 Holds, ursprüngliche dc4-Nachricht
mit Job, seq374-ACK und vier benannte historische Fehleraufträge sind unverändert.
Die volle frische Vorherdatenbank ist die Vergleichsbasis; kein historischer
Task wurde erneut ausgeführt. Alter Core 35746 abwesend; Nutzer-Codex 36878,
Tunnel 25909 und Konsole 15308 erhalten.

Eigenen Test-Codex 40722 erst nach leerem, bereitem und protokollgebundenem
Zustand beendet; danach nur das eigene leere Terminal 8356 samt Shell geschlossen.
Prozessidentitäten anderer Sitzungen erhalten; gesonderter produktiver Katalogabruf
bestätigt die Absenz des eigenen Panes. Ein währenddessen anderweitig entstandenes
Terminal 8382 blieb erhalten. Kein weiteres eigenes Testfenster geöffnet.
Rückweg `~/.local/share/kirabridge/install/backups/20261031-161152-1fdbd7a1`,
kein Rollback erforderlich. Abschlussbelege stehen im strukturierten Nachweis
und im vorhandenen Whiteboard; abschließender Dokumentationscommit separat.

## Externe Nachweisgrenzen

Die beiden im ursprünglichen Whiteboard genannten Planquellen und die originale
Desktop-Commander-Recherche wurden erneut gezielt in Downloads, Documents,
Desktop, ThreadDesk-Daten und Libraryindex gesucht und fehlen weiterhin.
Der lokale Libraryindex ist `ready` mit 16 anderen Dokumenten; die bloßen
historischen Desktop-Commander-Erwähnungen ersetzen keinen Forschungsbericht.
Kein Import, Neuindex oder Replay des ursprünglichen Bibliotheksauftrags.
Der ursprüngliche Quellenvergleich bleibt daher nicht nachweisbar.

Andere macOS-Versionen und ARM können auf diesem Intel-Mac nicht nativ
abgenommen werden. Die bekannte ioreg-Sperrstatusheuristik bleibt ausdrücklich
bezeichnet; die öffentliche Console-Keydefinition ersetzt keinen Lockstatus.
Optionale neue Provider bleiben deaktiviert. Diese Grenzen werden weder
verschwiegen noch durch eine fingierte lokale Abnahme als erledigt markiert.

Basissicherung und private Prüfbelege:
`~/.local/share/kirabridge/backups/macos-plan-completion-20261031T150132Z/`.
`baseline-source.tar` SHA256
`637aa3ec803d60d2aa413cc95a020d33397528c7ce11488d105573a2929a5da0`;
gegen Git abgeglichen, `BASELINE.json` und `RECOVERY.md` vorhanden.
Die frische vollständige private Sicherung liegt unter `productive/preinstall`;
auch der bisherige Rückweg `install/backups/20261031-153021-014baa7c` bleibt erhalten.
