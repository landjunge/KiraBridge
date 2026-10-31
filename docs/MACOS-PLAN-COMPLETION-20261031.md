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

Paket und produktive Installation werden erst nach ihren konkreten Ergebnissen
als bestanden eingetragen. Bis dahin läuft unverändert Core `acc1c85`, PID 35746, Start
`2026-10-31T14:30:28.259044+00:00`, Quellhash
`aef9319b72cce81a4b5d8702a7eccb69984bba43077c21bca881cd879a87c848`.
Für Test und Installation wird genau ein eigenes kontrolliertes Terminal
wiederverwendet; fremde Codexsitzungen bleiben erhalten.

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
Vor Installation folgt eine frische vollständige private Sicherung; der
bisherige Rückweg `install/backups/20261031-153021-014baa7c` bleibt erhalten.
