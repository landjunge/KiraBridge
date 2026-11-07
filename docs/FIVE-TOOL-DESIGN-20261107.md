# KiraBridge — gemeinsamer Produktheader / shared product header

Aufträge `FIVE-TOOL-DESIGN-CODEX-20261107` und Fortsetzung
`KB-DESIGN-ADAPT-KIRABRIDGE-20261107`, 07.11.2026. Fortschreibung des bestehenden
E05/UI-01 im ThreadDesk-Teamplan; keine neue Roadmap.

## Deutsch

Der bestehende Designcommit `d9b433d922258b7ace610d809776dfa47cb317fa` wurde
wiederverwendet und auf KiraBridge-Main `8b338b66752fb9d65a4c05959c04cf2505412ed2`
in einen regulär registrierten lokalen Git-Worktree übernommen. Der erste
Integrationscommit ist `2c191e95ee3c2f1d8884de45585375b96f552d20`; der aktuelle
Implementierungspin steht im [Fortsetzungsnachweis](evidence/kb-design-adapt-kirabridge-20261107.json).
Die README-Dateien der ersten Lieferung blieben bytegleich zum damaligen Main. Debian-/Installer-,
Server- und Auditbereiche wurden nicht angefasst.

Alle fünf Produkte bleiben eigenständig. KiraBridge, ThreadDesk, 4AllPass,
TollGate und Agent Authority stehen dauerhaft in dieser Reihenfolge im oberen
Header der vier vorhandenen Bedienansichten: `/`, `/protocol`, `/team` und
`/grok-connector`. Schmale Ansichten umbrechen den Header; die Icons bleiben
sichtbar und bedienbar. Gemeinsame Regeln: schwarzer Grund, zurückhaltende
Produktfarben, 44×56px Bedienflächen, 36×36px quadratische Rahmen und höchstens
28×28px sichtbare Originalmotive mit proportionalen optischen Ausschnitten.
Die fünf PNGs sind bytegleich zu den bereits vorhandenen Originalassets.
`src/kirabridge/console_assets/networkpunkt-appbar-assets.json` dokumentiert
Originalpfade, Quellpins, SHA-256, Farben und Ausschnitte. Es wurden keine
Ersatzlogos oder neuen Bilder erzeugt.

Status und Version stammen aus dem vorhandenen authentisierten
`/api/control/status`. Die Hauptansicht nutzt deren bestehende Kontrollsnapshots
über lokale Ereignisse; die übrigen Ansichten lesen dieselbe Schnittstelle mit
der vorhandenen Sitzung. Aktiver Dispatcher bedeutet bestätigt, gestoppter
Dispatcher getrennt, gemeldete Wartung beschäftigt und Transportfehler Fehler.
Ohne Sitzung, bei verweigerter Authentisierung oder ohne belegte Daten bleibt
der Status unbekannt; fehlende Version ist `v?`. Die angezeigte Laufzeitversion
kommt aus `bridge.runtime.version`, nicht aus einer UI-Konstante oder PID-Karte.
Ein authentisierter lokaler Bridge-Snapshot bestätigt keine externe
ChatGPT-/Grok- oder Fremdproduktverbindung. Die vier Fremdprodukte bleiben ohne
bestätigte Bindung unbekannt. Die Snapshot-Frische ist begrenzt; die Hauptansicht
verwirft ihren lokalen Snapshot nach acht Sekunden.

Ein Klick auf KiraBridge fokussiert die vorhandene Hauptansicht oder navigiert
von einer Unteransicht dorthin. Fehlende Fremdziele öffnen einen beschrifteten
Dialog mit ausdrücklicher Erklärung statt einer erfundenen Route. Tab, Enter,
Leertaste, Escape und die Fokusrückgabe funktionieren. Die Headerbeschriftung
folgt DE/EN einschließlich der vorhandenen kosmetischen Sprachpräferenz; Team
und Grok-Connector nutzen ihre vorhandenen Sprachschalter. Hauptansicht und
Protokoll haben keinen neuen Sprachschalter erhalten.

Der echte Browserlauf entdeckte eine verzögerte native Dialog-Schließmeldung,
die den inzwischen weiterbewegten Tastaturfokus zurückholte. Der lokale
Komponentenpatch `1.1.1` verhindert dies. Die Kopie basiert auf ThreadDesk-Bundle
`1.1.0`; sie ist nicht als bereits synchron mit anderen Produkten ausgegeben.
`networkpunkt-appbar-SHA256SUMS` prüft die lokale Kopie. Der getrennte spätere
Rücktransfer dieses Fokuspatches in den gemeinsamen Ursprung ist offen; er ist
kein ungetesteter Bestandteil dieser KiraBridge-Lieferung.

Die frühere Browserblockade ist für diese Fortsetzung gelöst: Ein isolierter
Chrome-for-Testing Headless Shell 130.0.6723.31 rendert die echten HTML-/CSS-/JS-
Routen mit unveränderter Worker-Sandbox. Neuere vorhandene Browser scheiterten
an macOS-Appregistrierung bzw. einem verweigerten Kernel-VM-Query. Der getestete
kompatible Browser liegt nur im Aufgabenarbeitsstand; keine Systeminstallation,
keine Änderung von Systemrechten oder Browser-Sicherheitsregeln.

Die Abnahme verwendet echtes Loopback-HTTP, signierten Login, vorhandene
Kontrollhandler und einen tatsächlich gestarteten/gestoppten isolierten
Bridge-Dispatcher. OS-Prozessinventur und Host-Befehle sind im Prüfling gesperrt.
Wartung und Transportfehler werden ausdrücklich nur als Darstellungsfehler
injiziert. Es werden keine produktiven Aufgaben, Agenten oder Dienste bedient.
Vier Ansichten × drei Breiten (1280/390/320) × zwei Systemeinstellungen
(hell/dunkel), fünf Originalbilder, eigene echte Version/Status,
unbekannte Fremdprodukte, Tastatur/Fokus/Klicks und Zustandswechsel sind im
[Browsernachweis](evidence/kb-design-adapt-kirabridge-20261107/browser/browser-checks.json)
mit 29 gehashten Screenshots dokumentiert. Die gezielten 47 Python-Prüfungen
und zwei nach der MIME-Aufräumung wiederholte Asset-/Designprüfungen bestehen.
Die Screenshotprüfung umfasst Hauptansicht, Protokoll, Team und Connector.

Offene Grenzen: keine Prüfung einer installierten nativen Desktop-App oder
produktiver Fremdverbindungen. Die aktuelle Fortsetzung autorisiert normale
Push-/Mainintegration über PR73 nach Pflichtprüfungen. Release, Deployment und
produktiver Dienstwechsel sind kein Teil dieser Designlieferung. Browserbelege sind Quelllaufzeitbelege des lokalen
Kandidaten. Der bestehende Fünf-Tool-Gesamtnachweis im ThreadDesk-Arbeitsstand
`docs/evidence/five-tool-design-20261107.json` bleibt historisch erhalten.
Live-Board-Schreiben und Koordinatorzustellung werden getrennt mit tatsächlichem
Ergebnis im Fortsetzungsbericht ausgewiesen.

## PR73 · aktuelle Mainintegration

Nach bestätigtem Debian-Merge und unabhängig heruntergeladenem, hashgeprüftem
Linux-Download wurde Main `2bbf6d9` normal in den Designbranch übernommen.
Integrationspin `8812662`: eigene Installer-/Server-/Dependencydifferenz gegen
Main leer; sämtliche bisherigen UI-/Testquellen und Original-PNGs unverändert.
Die READMEs erhalten den vollständigen Maintext und ergänzen nur den bestehenden
Designabschnitt mit Browser-PASS und ausdrücklich ungeprüfter nativer App.

Der gemeinsame RC41-Quellstand besteht erneut 47 gezielte UI-Prüfungen und
28 echte Browserchecks mit 29 neuen Screenshots. Die tatsächlichen Importpfade,
Laufzeitversion, Testaufrufe und Quellpins sind im
[PR73-Integrationsnachweis](evidence/kb-design-pr73-integration-20261107.json)
festgehalten. Alte RC40-Belege bleiben historisch erhalten. Die normalen finalen
PR-Prüfungen und der tatsächliche Mainmerge werden am [PR73](https://github.com/landjunge/KiraBridge/pull/73)
und im Koordinatorbericht belegt; keine Erfolgsaussage vor deren Abschluss.

## English

The existing design commit `d9b433d922258b7ace610d809776dfa47cb317fa` was reused
and normally imported into a registered local Git worktree based on current
KiraBridge main `8b338b66752fb9d65a4c05959c04cf2505412ed2`. Initial integration
commit: `2c191e95ee3c2f1d8884de45585375b96f552d20`. The final implementation pin
is recorded in the [continuation evidence](evidence/kb-design-adapt-kirabridge-20261107.json).
The original delivery preserved both then-current main README files. Installer, server and audit code is outside
this delivery.

All five independent products keep their original identities and order in a
permanent top header on `/`, `/protocol`, `/team` and `/grok-connector`.
The layout wraps at narrow widths. Original PNG bytes, optical proportions,
44×56px controls, 36×36px black frames, up to 28×28px visible motifs and subtle
brand accents follow the existing ThreadDesk rules. The asset manifest records
original paths, source pins, SHA-256 hashes and proportional optical viewports;
no replacement logos were generated.

Authenticated existing control snapshots provide KiraBridge dispatcher status
and `bridge.runtime.version`. The home view reuses its control events and
expires its local snapshot after eight seconds; other views read the same
existing authenticated endpoint. Confirmed, disconnected, busy, error and
unknown states stay distinct. Missing sessions, rejected authentication or
missing evidence produce unknown status and `v?`. Local Bridge health does not
prove external ChatGPT/Grok connectivity. All four unbound products remain
unknown; no peer status or version is invented.

The own icon focuses the existing main view or navigates back to it. Missing
foreign targets show an explicit accessible dialog. Keyboard activation,
Escape and focus return are supported. Header labels follow DE/EN and the
existing cosmetic preference; existing Team/Connector language controls work.
Home/Protocol do not gain fictional locale controls. Browser testing found and
fixed a delayed native dialog close event stealing later keyboard focus. Local
bundle `1.1.1` records this patch over upstream `1.1.0`; its checksums are updated.
Backporting that patch to the shared ThreadDesk origin remains separate.

The earlier browser startup blocker is resolved for this task using isolated
official Chrome-for-Testing Headless Shell 130.0.6723.31. Its provenance and
hashes are included. The worker sandbox and system permissions are unchanged;
there is no installed app or binary modification. Real HTTP, signed login,
actual console handlers and an actually running/stopped isolated dispatcher
are used. Host inventory/commands are disabled in the test fixture. Maintenance
and transport-error states are explicitly injected presentation checks.

The [browser evidence](evidence/kb-design-adapt-kirabridge-20261107/browser/browser-checks.json)
covers four real views, three widths (1280/390/320), light/dark preference,
all five original icons, authenticated runtime version, unconfirmed peers,
keyboard, focus, pointer actions and state transitions, with 29 hashed screenshots.
The targeted 47 Python checks and two repeated asset/design checks pass.
Installed native runtime and productive peer connections are not claimed.
The current continuation authorizes normal PR73 push/main integration after
required checks. Release, deployment, app installation and production service
switch are outside this design delivery. Live board writing and
coordinator notification are reported with their actual outcomes separately.

## PR73 · current main integration

After the Debian merge and an independent actual download/hash verification,
accepted main `2bbf6d9` was normally merged into the design branch at `8812662`.
There are no own installer/server/dependency changes against main. All existing
UI/test hashes and original PNGs match the prior accepted implementation.
Both READMEs keep the complete accepted main text and add only the existing
design section, accurately separating passed browser checks from the unverified
installed native app.

The combined RC41 source passes 47 targeted UI checks and 28 real browser
checks with 29 new screenshots. Import paths, actual source version, commands and
pins are in the [PR73 integration evidence](evidence/kb-design-pr73-integration-20261107.json).
Earlier RC40 evidence remains historical. Final regular PR checks and the actual
merge are proved by [PR73](https://github.com/landjunge/KiraBridge/pull/73) and the
coordinator handoff; success is not asserted before those steps finish.
