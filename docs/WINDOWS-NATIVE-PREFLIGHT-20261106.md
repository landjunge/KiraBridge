# Windows: tatsächlicher Gast-Preflight, 06.11.2026

Auftrag `BIGPLAN-WINDOWS-NATIVE-20261106-V1`, Codex/root, einzige schreibende
Instanz. Fortsetzung des [Berichtsproduzenten](WINDOWS-CANDIDATE-PRODUCER-20261105.md),
kein neuer Produktauftrag. Die sechs nativen Kandidatenphasen sind noch **nicht
gestartet**. Kein neues abgenommenes Kit, keine produktive Installation.

## Unveränderter Kandidat und Vorbereitung

| Bindung | Geprüfter Stand |
| --- | --- |
| Quellcommit des Testpayloads | `179bb6f8a66311d0c6117c560b0e5f54eb7db0b2` |
| Version | `0.8.0rc39` |
| Manifest-SHA256 | `9489bc9defb18672831de688cbec546469abb9f440720eed59c5e06d54cfa2c0` |
| Inventar-SHA256 | `d127d98abb53f388627df6d2c2e64a9c9ff0f193c79d79e13a719785de1ce657` |
| Umfang | 192 Runtime-Module, neun Harness-/Producerdateien, 38 Wheels, 41 Payloaddateien |
| Vorgesehener neuer Gastordner | `KiraBridgeNative179bb6f20261106V1` unter `LOCALAPPDATA` |

Der universelle KiraBridge-Wheel wurde lokal und offline gebaut. Die übrigen
Wheels und der gepinnte AMD64-Pythoninstaller stammen bytegleich aus dem vorhandenen
RC33-Kit; das historische Archiv wurde frisch gehasht und nicht verändert.
`frozen_payload`, das gemeinsame Inventar und der Vergleich der tatsächlichen
Wheel-/Archiv-/Gitbytes bestanden. Das ist eine Paketvorbereitung auf macOS,
kein nativer Windows-Testpass. Die bisherigen 103 gezielten portablen und
PowerShell-7-Prüfungen sowie der unabhängige read-only Quellreview werden gezielt
wiederverwendet. Der frühere unbestätigte Grok-Review bleibt UNKNOWN.

## Echte Gastbeobachtungen

Fix1 war bereits gestartet: UUID `2B6EE828-02F0-42AE-B4FE-BE57C448F65E`,
x86_64, zwei CPUs, 8 GiB. Kein Boot/Stop/Restart, keine Betriebssysteminstallation,
kein Guest-Agent-/Sharing-/Rechtewechsel. Der ursprüngliche andere Gast blieb
gestoppt und unverändert. Der UTM-Prozessfilter muss auch QEMULauncher/XPC erfassen;
eine Suche allein nach `qemu-system` hatte den laufenden Backendprozess übersehen.

`utmctl exec` lieferte trotz Exitcode 0 einen Guest-Agent-Fehler. Kein Gastbefehl
wurde deshalb als ausgeführt gezählt. Ein KiraBridge-Fensterraise und ein
Tastaturversuch endeten UNKNOWN; Originaltasks/Events bleiben erhalten, keine
Wiederholung dieser Tasks und keine Abschwächung ihrer Guards.

Die bereits installierte offizielle UTM-Scripting-Schnittstelle wurde separat
auf die genaue VM-UUID, `qemu` und `started` gebunden. Ihre JavaScript-Komponente
war nutzbar; die AppleScript-Komponente wurde nicht gefunden. Ein VM-gebundenes
Shift-Paar weckte das schwarze Display. Das ist keine bestandene KiraBridge-
Tastaturprüfung. Danach wurde genau eine eigene Gastkonsole geöffnet.

Zwei konkrete Zuführungsfehler wurden vor einem Teststart aufgeklärt:

1. UTM erwartet erweiterte PC-Scancodes als zusammenhängende Werte, beispielsweise
   `0xE05B`, statt einer Folge einzelner E0-Bytes. Der erste Windows+R-Versuch
   öffnete laut frischem Bild keinen Dialog.
2. UTM bildet Text hier über US-Tasten ab; der Gast verwendet Deutsch. Minuszeichen
   erschienen zunächst als `ß`. Außerdem enthielt die gespeicherte Run-Zeile
   exakt nur die ersten 259 der beabsichtigten 1382 Zeichen. Beide ungültigen
   Startzeilen wurden nicht als erfolgreiche Shell-/Preflight-Ausführung gezählt
   und nicht erneut ausgeführt. Der korrigierte kurze Start wurde vor Return
   vollständig im Bild geprüft; ein alter Autocomplete-Vorschlag wurde nicht bestätigt.

Die begrenzte Tastenzuführung verwendet die vorhandene UTM-Funktion, keine zweite
Produkt-Tastaturimplementierung. Für den lesenden Preflight wird ausschließlich
der bekannte Base64-Zeichensatz entsprechend abgebildet. Lange Zeilen gehen in
die eigene Konsole, in bestätigten Textblöcken mit exklusiven lokalen Receipts;
ein unklarer Block wird nicht erneut gesendet. Windows-Belegung und Richtlinien
wurden nicht verändert. Formatgrundlage ist die
[offizielle UTM-5.0.8-Implementierung](https://github.com/utmapp/UTM/blob/v5.0.8/Scripting/UTMScriptingInputImpl.swift)
und deren [Textabbildung](https://github.com/utmapp/UTM/blob/v5.0.8/Platform/Shared/VMKeyboardMap.m).

Der tatsächlich ausgeführte lesende Befehl bestätigte PowerShell
`5.1.26100.9711` und `Restricted`. Ein weiterer vollständiger Preflight wurde
nach genau einem Return empfangen und ausgelesen: `x64=true`, vorhandener
vorbereiteter Pythonpfad, neuer WorkName noch nicht vorhanden. Im abgefragten
Bestand `python,powershell,cmd` erschienen nur die eigene Eltern-PowerShell und
ihr lesendes Kind. Das beweist keine allgemeine Abwesenheit sämtlicher Dienste.
Die komplette Raw-Quittung hat SHA256
`b6a9e540aa5b2da28c4c37fcc00972f9ff5f4e9d68103fa9fb931ac9ce839b02`.

Eine zweite rein lesende Quittung bestätigt Windows 11 Enterprise Evaluation
`10.0.26300`, CIM-Build `26300`, 64 Bit; die angezeigte PowerShell-Assemblyversion
und das Desktopwasserzeichen sind keine gleichwertige OS-Buildabfrage.
Der vorhandene Interpreter meldet Python `3.14.10`, `AMD64`, Exitcode 0.
Alle **37** benötigten Dependencyversionen stimmen exakt mit dem neuen Manifest
überein; keine Paketinstallation oder Bytecode-Schreibzugriffe. Die separate
Umfeldquittung hat SHA256
`646914b4558cf5ab6b0937e2a203a7bd42fa8afab787256858bdb7f6ba46e4fd`.
Der Basisinterpreter enthält weiterhin KiraBridge `0.8.0rc31.dev2`; das belegt
keine derzeit laufende Bridge. Andere vorhandene Previewvenvs wurden nicht ersetzt.

## Startgate und nächste Abnahme

Die Nutzervorgabe verbietet das Abschalten von Sicherheitsprüfungen. Der vorhandene
reguläre Gastbootstrap sieht einen prozessgebundenen PowerShell-Override vor;
die frische eigene Konsole meldet jedoch `Restricted`. Dafür wurde konkret die
einmalige Freigabe für den eigenen hashgeprüften Testlauf angefragt. Bis zu einer
expliziten Antwort kein Override, keine Skriptausführung über Ersatzwege und keine
Kandidatenphase. Das ist keine fehlgeschlagene Windows-Kandidatenprüfung.

Nach passender Freigabe: Gast/Prozesse/WorkName frisch abgleichen, den eingefrorenen
Runner mit Manifestpin, `-CandidateVersion 0.8.0rc39` und `-ReusePreparedPython`
regulär starten. Core, Keyboard, MCP, Preview, Shortcuts und Windows genau einmal
im neuen Lauf ausführen; bei Fehler/UNKNOWN stoppen und Originalbelege prüfen.
Bestehende Interpreterpakete, Desktopstarter, Altberichte und Konfiguration erhalten.
Nur die sechs passenden unveränderten Raw-Phasenberichte in ein eigenes
Validierungsverzeichnis übernehmen; lesende Preflightberichte nicht als native
Phasen umbenennen oder in den Kandidatenvalidator einspeisen.

Native Win32-/PowerShell-5.1-Producerabnahme, neues Kit, Upgrade/Rollback,
Terminal-/CLI-Parität und Dirks konkrete Umgebung bleiben offen. Ein lokaler
Gastlauf wäre auch kein Browserchat-/Handy-Remote-End-to-End-Nachweis.

Private Rohbelege/Receipts und Übergabe liegen unter
`~/.local/share/kirabridge/backups/bigplan-windows-native-20261106-v1/`.
`REGULAR-START.txt` beschreibt den noch nicht ausgeführten Start einschließlich
Manifest-/Runnerpin. Die eigene idle Gastkonsole wurde per `exit` geschlossen;
eine unabhängige Fensteraufnahme zeigt wieder den Desktop. Der eigene temporäre
Hostreceiver wurde erst nach Prüfung von PID, Startzeit und vollständiger
Aufrufidentität beendet; unabhängige Prozess- und Listenerprüfung bestätigt seine
Abwesenheit. VM und bestehende Mac-/Koordinatorprozesse laufen weiter. Bei
Wiederaufnahme alle Bindungen frisch erheben und einen neuen eigenen Receiver
verwenden; die alte Capability-URL ist außer Betrieb.
ThreadDesk-Projektboard `188ce4729a62`, Claim206 und zurückgelesener Checkpoint207
(`c79a9ca1766f`); laufende Kurzberichte in Instanzboard `36722a01a76d`.
Keine Bootstrap-Capability-URL, Zugangsdaten oder vollständigen Terminaltranskripte
in die Repositorydokumentation oder das Board kopieren.
