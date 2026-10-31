# macOS-Kompatibilität: ergänzte API- und Identitätsbelege

Revision 1 · 31.10.2026 · Fortsetzung auf Nutzerwahl „Kompatibilitätslücken
abschließen“. Arbeitswhiteboard `0ab8b95a7369`, Ausgangsrevision 17.
Kira-Skill verwendet; bestehende Implementierung und Prompt-Reparatur beibehalten.
[Maschinenlesbare Belege](evidence/macos-compatibility-followup-20261031.json).

## Ergebnis und Umfang

Die offene Einführungsversion der neuen Clipboard-APIs ist geklärt: **macOS
15.4**, nicht erst 26. Die vier betreffenden Objective-C-Methoden sind auf dem
vorhandenen Intel-Mac mit 15.7.4 in der Laufzeitklasse vorhanden. Das ist ein
Symbolnachweis ohne Clipboardzugriff und keine Erhebung eines Zugriffsrechts.
Die Dokumentation trennt jetzt außerdem die öffentliche Console-Keydefinition
von der weiter undokumentierten Sperrstatusheuristik und beschreibt die
tatsächlichen ausführenden Prozesse jedes bestehenden Blatts.

Dieser Schritt ändert nur Dokumentation. Kein neuer Provider, kein neuer
Ausführungsweg und keine Lockerung bestehender Eingabe- oder Berechtigungschecks.
Der Nutzer hat anschließend Push und Installation freigegeben. Für unveränderten
Laufzeitcode ist kein neues Paket und kein erneuter Corestart erforderlich.

Ausgangspunkt: sauberer Branch `docs/macos-adapter-phases1-3-20261031`,
HEAD `388e5c9e2655e43a36ea8de11e38d3e18bf859d2`. Installierter und live
antwortender Core `acc1c850ba3d2ff384e02da78e489b48ebbbf27a`, PID 35746,
Start `2026-10-31T14:30:28.259044+00:00`, Paketquellhash
`aef9319b72cce81a4b5d8702a7eccb69984bba43077c21bca881cd879a87c848`.
Die bestehende [produktive Prompt-/Return-Abnahme](WRAPPED-PROMPT-REPAIR-20261031.md)
bleibt für diesen unveränderten Code maßgeblich; sie wurde hier nicht wiederholt.

## OS-Vertrag und tatsächlicher Nachweis

| Ebene | Vertrag / Befund | Grenze |
| --- | --- | --- |
| Bestehender Provider | `CapabilityProbe` modelliert macOS ab 12.0 und prüft Transportpfade | kein Nachweis lauffähiger Paketabhängigkeiten oder vollständiger Funktionen auf jeder Version |
| Generiertes Bundle-`install.sh` | `scripts/build_release.py` lässt 15.* und 26.* sowie x86_64/arm64 zu | Zulassung im Skript ist keine native Abnahme; andere Versionen werden dort abgewiesen |
| Direkter Pythoninstaller | separate Python-3.11+- und Installationsprüfungen; nicht identisch mit dem Versionsfilter des Bundle-Wrappers | kein neuer vollständiger Mindest-OS-/Abhängigkeitsnachweis durch diesen Bericht |
| Tatsächlich geprüftes System | macOS 15.7.4, Build 24G517, x86_64 | keine native Abnahme von 12/13/14/26/27 oder arm64 |
| Neue Clipboard-Symbole | SDK-Vertrag ab 15.4; Methoden auf diesem 15.7.4-Mac vorhanden | keine neue aktivierte Funktion und keine Zugriffsfreigabe |
| Optionale Provider | windows/capture/notifications/preferences weiter `provider_not_implemented` | keine Fähigkeiten allein aufgrund einer neuen OS-Version aktivieren |

Die Angabe 12.0 im Provider ist somit eine technische Modellgrenze, keine neue
Installationszusage. Der bestehende Paketfilter und die Plattformfreigaben werden
nicht erweitert. Ebenso ersetzt eine lokale Funktionsprobe nicht Apples
Hardwarefreigabe; die im ursprünglichen Entwurf dokumentierte Abweichung des
iMac17,1 bleibt bestehen.

## Clipboard: SDK und Laufzeit ohne Inhaltszugriff

Apples lokale `NSPasteboard.h` aus SDK 15.4 und 26.2 deklarieren die folgende
Availability; im geprüften SDK 12.1 fehlen diese Deklarationen:

| Symbol | Mindestversion laut Header | Laufzeit 15.7.4 |
| --- | --- | --- |
| `NSPasteboard.AccessBehavior` / `accessBehavior` | 15.4 | Methode vorhanden |
| `detectPatternsForPatterns:completionHandler:` | 15.4 | Methode vorhanden |
| `detectValuesForPatterns:completionHandler:` | 15.4 | Methode vorhanden |
| `detectMetadataForTypes:completionHandler:` | 15.4 | Methode vorhanden |

Apples [AccessBehavior-Dokumentation](https://developer.apple.com/documentation/appkit/nspasteboard/accessbehavior-swift.enum)
bestätigt die Einführung ab 15.4. Die Methode zur Werterkennung ist ein
Inhaltszugriff; sie ist keine passive Berechtigungsprobe. Auch eine deklarierte
Methode beweist weder einen erlaubten Aufruf noch ein bestimmtes Promptverhalten.
Eine künftige Nutzung müsste Version, tatsächliche Selectorverfügbarkeit,
aufrufende Identität und die konkrete autorisierte Operation getrennt prüfen.
Für ältere Systeme bleibt der vorhandene Transport maßgeblich; dieser Bericht
führt keine automatische Ausweichroute ein.

Native lesende Prüfung: AppKit geladen, Klasse über `objc_getClass`, Selektoren
über `sel_registerName` und Methodentabelle über `class_getInstanceMethod` gelesen.
Kein `objc_msgSend`, kein Pasteboardobjekt, kein Methodenaufruf am Pasteboard,
kein Clipboardinhalt und keine Rechteanforderung. Endbeleg aus separatem
Python-3.11-x86_64-Prüfprozess PID 37617; er ist nicht der produktive Core oder
einer seiner Clipboardhelper. SDK-Headerpfade/-Hashes und das private Prüfskript
sind in der JSON-Belegübersicht referenziert. Die vorgelagerte Erkundungsprobe
lief mit Python 3.8; sie ist kein Python-3.11-Paketnachweis.

## Blattprovider und ausführende Identität

| Bestehendes Blatt | Tatsächlicher Ausführungspfad | Berechtigungs- und Nachweisgrenze |
| --- | --- | --- |
| Dateien | Python-Core, `filesystem_manager`, vorhandener `PathScope` | Principal/Roots, POSIX/ACL und etwaige OS-Grenzen; kein universeller FDA-Preflight |
| Prozesse | Python-Core und eigene kontrollierte Kindprozesse | kein allgemeiner Rechtekatalog für fremde Systemprozesse; bestehende Ownership-/PID-Prüfungen |
| Terminal | separater `/usr/bin/osascript`-JXA-Aufruf für Terminal.app bzw. System Events | Apple Events zielbezogen, AX getrennt; Corefreigabe ist keine Helperfreigabe |
| Clipboard-Text | `ClipboardManager` startet `pbpaste` bzw. `pbcopy`; Schreibprüfung nutzt ebenfalls `pbpaste` | getrennte Prozesse; `clipboard.info` liest keinen Inhalt und bestätigt kein OS-Recht |
| Clipboard-Lease für native Eingabe | eigener langlebiger `osascript`-JXA-Helper mit NSPasteboard | eigene Lebensdauer/Generation/Restore; keine Übertragung von Core- oder `pbpaste`-Rechten |
| Desktopstatus | begrenzter `ioreg`-Kindprozess, Auswertung passender UID | Zustandsheuristik; weder TCC-Freigabe noch Agentbereitschaft |
| Expliziter Corestatus | AXIsProcessTrusted / CGPreflightScreenCaptureAccess im Coreprozess | nur dieser Prozess; negatives Bool bleibt ohne erfundene genaue Ablehnungsursache |
| Desktop-App | eigener Appprozess, bisheriger Bundlecommit `da1bdae` | eigenständige Identität; weder neuer Core noch Prüfprozess belegt ihre Rechte |

`Bridge` konstruiert `MacOSProvider` aktuell ohne `actor_identities`.
Der produktive Helper-Berechtigungsstatus bleibt deshalb bewusst `unknown`;
die vorhandenen nativen Zielprüfungen sind weiter erforderlich. Die bestehende
Injektionsschnittstelle der Tests ist keine produktive Helpererhebung. Ein
Pfad oder Binärhash allein würde keine OS-Zurechnung von TCC-Rechten beweisen.
Diese Grenze ist nun konkret dokumentiert, nicht durch eine Erlaubnisannahme
geschlossen. Eine neue helpergebundene Berechtigungserhebung wäre eine getrennte
Implementierung mit Prozess-/Zielbindung und Tests.

## Console- und Sperrstatus unterscheiden

Präzisierung des ursprünglichen Entwurfs: Der Makroname
`kCGSessionOnConsoleKey` ist öffentlich; sein Stringwert lautet
`kCGSSessionOnConsoleKey`. Auch der UID-Schlüssel ist öffentlich definiert.
Apple beschreibt [kCGSessionOnConsoleKey](https://developer.apple.com/documentation/coregraphics/kcgsessiononconsolekey)
und [CGSessionCopyCurrentDictionary](https://developer.apple.com/documentation/coregraphics/cgsessioncopycurrentdictionary()).
`CGSession.h` in den geprüften SDKs 12.1, 15.4 und 26.2 bestätigt die Definitionen;
die öffentliche Funktion ist dort ab 10.3 deklariert.

Dieser Vertrag betrifft das Dictionary der aufrufenden Window-Server-Sitzung.
Er belegt keine identische Semantik der heute ausgewerteten `ioreg`-Liste
`IOConsoleUsers`. `CGSSessionScreenIsLocked` ist in diesen geprüften Headern nicht
deklariert; ein stabiler öffentlicher Lockstatusvertrag wurde nicht gefunden.
Consolezugehörigkeit allein beweist keinen entsperrten Bildschirm. Deshalb
bleibt die komplette bestehende Lockprobe eine ausdrücklich bezeichnete
Kompatibilitätsheuristik. Eine Umstellung auf das öffentliche Sessiondictionary
würde weder den Lockstatus noch die gesamte Mehrbenutzerauswertung ersetzen.
Es wurde kein solcher Ersatz eingebaut und kein Mac gesperrt/entsperrt.

## Abschluss, Sicherung und verbleibende Grenzen

Geklärt sind API-Einführungsversionen, lokale Methodentabellenverfügbarkeit,
öffentliche Console-Keydefinition, Paketfilter gegenüber Providermodell und
die konkrete Trennung der Ausführungsidentitäten. Vorhandene Provider-/Status-
Schutztests wurden gelesen; für reine Dokumentationsänderungen wurden keine
Code-, Clipboard- oder Terminaltests neu gestartet. JSON, alle sechs
Headerhashes samt Symbolzeilen, Backup-/Prüfskripthash und zehn lokale Links
wurden geprüft; `git diff --check` bestand. Das unabhängige Dokumentationsreview
gegen Code, SDKs und privates Prüfskript ergab keine wesentlichen Befunde.

Die beiden Bibliothekspläne und die originale Desktop-Commander-Recherche
bleiben fehlende Quellen: erneute reine Indexabfrage in Arbeits- und
Koordinationsboard liefert jeweils `index.status=missing`, `documents=0`.
Kein Neuindex, Import oder Replay des alten Bibliotheksauftrags.
Weitere reale OS-/Architekturabnahmen, öffentliche Lockstatus-Erhebung und
produktive Helper-Berechtigungsbeobachtung bleiben getrennte offene Punkte.
Sie werden durch diesen Quellen- und Symbolabgleich nicht als bestanden ausgegeben.

Geprüfte Basissicherung außerhalb des Worktrees:
`~/.local/share/kirabridge/backups/macos-compatibility-20261031T145121Z/`.
`baseline-source.tar` SHA256
`e97b37e5ff9077b20e85ac0f8071f24b9a328b2c1bb906d3fe03170ba5cb1108`;
die drei relevanten bisherigen Dokumente wurden byteweise abgeglichen.
`baseline.json`, `RECOVERY.md`, `inspect-symbols.py` und
`runtime-symbols.json` erhalten die Ausgangs- und Prüfbelege. Bestehender
Installationsrückweg `install/backups/20261031-153021-014baa7c` bleibt erhalten.
Kein Rollback ausgeführt. Aktueller Abschlussstatus und Commit stehen zusätzlich
im bestehenden Arbeitswhiteboard; ein Push ist getrennt remote zu bestätigen.
