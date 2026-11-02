# Automatische Tastatursteuerung – Untersuchung und Umsetzung

Ausgang: Code `f58ed2f`, installiertes RC24-Modul `73d4ea0`. Auftrag: direkte
Tastatursteuerung ohne Profilpflicht, automatische Programmerkennung, einfache
Oberfläche, Funktions- und ChatGPT-Nachweis. Bestehende Clipboard-, Terminal-,
Profil-, Shortcut- und Freigabefunktionen bleiben erhalten. Keine großen CI-Läufe.

## Gesicherte Probleme

1. Der alte Inspectpfad verlangte selbst für Escape oder Command+A ein vollständig
   lesbares Textfeld. Buttons, Listen und andere fokussierte Elemente wurden dadurch
   unnötig ausgeschlossen (`SystemKeyboard.observeField/snapshot`).
2. Die öffentlich verfügbaren einzelnen Tastaturoperationen benötigten native
   Zielhandles. Ein direkter Auftrag musste Programmauflösung, Fokus und Inspect
   selbst zusammensetzen; ein einfaches profilfreies ChatGPT-Werkzeug fehlte.
3. Die Konsole begann mit einem JSON-Profilmanager statt einer direkten Eingabe.
4. Eine ältere ausdrücklich umfassende Full-Freigabe erhielt neue Keyboardrechte
   nicht beim Laden. Die vorherige Installation brauchte dadurch einmal „Übernehmen“.
5. Eine fehlende AXSubrole war generell eine Verweigerung, obwohl Apple diese
   Eigenschaft nur bedingt verlangt. Für normale TextAreas ist das unnötig streng.

## Recherche und technische Folgerungen

Primärquellen und lokales Apple-SDK wurden gemeinsam ausgewertet:

- [NSWorkspace.frontmostApplication](https://developer.apple.com/documentation/appkit/nsworkspace/frontmostapplication)
  und [runningApplications](https://developer.apple.com/documentation/appkit/nsworkspace/runningapplications):
  laufende Programme und tatsächlicher Vordergrund sind beobachtbar. Programmnamen
  sind keine eindeutige Prozessgeneration. Deshalb genaue Auswahl, PID/Startzeit
  und anschließende native Bindung; keine unscharfe Zielvermutung.
- [AXUIElementCopyAttributeValue](https://developer.apple.com/documentation/applicationservices/1462085-axuielementcopyattributevalue),
  SDK `AXAttributeConstants.h:214–243` und `NSAccessibilityProtocols.h:278`:
  AX-Attribute/Subroles können fehlen. Eine fehlende TextArea-Subrole wird nur bei
  belegtem unsupported/noValue/success-nil akzeptiert; Kommunikationsfehler nicht.
  Textwert, UTF16-Auswahl, Fokus und Eigentum bleiben für Text zwingend.
- [CGEvent.postToPid](https://developer.apple.com/documentation/coregraphics/cgevent/posttopid(_:)):
  prozessbezogenes Posting hat keinen Anwendungs-Acknowledgement-Rückgabewert.
  Ein Beleg über zurückgekehrte Postcalls darf keine ausgeführte Programmaktion behaupten.
- [Unicode-CGEvents](https://developer.apple.com/documentation/coregraphics/cgevent/keyboardsetunicodestring(stringlength:unicodestring:))
  und lokaler `CGEvent.h:195–204`: Frameworks können Unicode-Eventtexte ignorieren.
  Deshalb kein behaupteter universeller Blindtext-Fallback; vorhandene exakte
  Feldverifikation und atomarer Text/Return-Weg bleiben erhalten.
- [Apple TN2150](https://developer.apple.com/library/archive/technotes/tn2150/_index.html):
  Secure Event Input behandelt Interceptionsschutz. Daraus folgt kein allgemeiner
  Sendebeleg und keine Erlaubnis, sichere Eingabefelder zu umgehen.
- [OpenAI MCP-Serverkonzept](https://developers.openai.com/plugins/concepts/mcp-server),
  [Custom MCP Server](https://developers.openai.com/api/docs/guides/custom-mcp-server)
  und [MCP Events](https://developers.openai.com/plugins/build/mcp-events):
  Werkzeuge besitzen strukturierte Schemas; Toolaufrufe und Eventbeobachtung sind
  getrennte Wege. Ein normales Eingabewerkzeug benötigt kein Events-Abo. Ein Client
  kann eine ältere Werkzeugliste behalten; der vorhandene allgemeine `action_request`
  bleibt deshalb ein kompatibler Weg zur neuen Operation.

„In jedem Programm“ ist kein belastbares universelles Versprechen: sichere Felder,
fehlende AX-Unterstützung, eigene Textengines, IMEs und geschützte laufende
Terminal-/Agentkontexte haben konkrete Grenzen. Die neue Grundsteuerung ist
programmübergreifend und profilfrei; unsichere oder unbestätigte Ziele verweigern.
Terminal-/Agentenschutz wird nicht durch globale Events oder Clipboard ersetzt.

## Schritt 1 – Gemeinsamer profilfreier Eingabeweg und Zugang

`keyboard.control` nimmt wahlweise `app` (genauer Programmname oder Bundle-ID),
ein beobachtetes PID-/Startzeitpaar oder den frisch beobachteten Vordergrund.
Daneben genau Text mit optionalem `submit` oder eine Taste mit expliziten Modifiern.
Beispiele: `{"app":"TextEdit","text":"Hallo","submit":false}` und
`{"app":"TextEdit","key":{"character":"a"},"modifiers":["command"]}`.
Profile, Menüs und zusätzliche Einstellungen werden dabei nicht benötigt.

Eine vorhandene Desktoptransaktion umfasst Auflösung, höchstens eine explizite
Programmaktivierung, frischen Inspect und den vorhandenen nativen Schreibweg.
Mehrdeutigkeit, alte Generation und Identitätswechsel verweigern; es gibt keine
Wiederholungs- oder Neuzielschleife. Der Textweg verwendet weiterhin denselben
verlustfreien Staging-/Hash-/Caret-/Return-Vertrag bis1MiB ohne Clipboardpflicht.
Autorisierung wird bis zum tatsächlichen Keysend/Textcommit erneut geprüft.
Ergebnisbelege enthalten das tatsächlich aufgelöste Programm und den nativen
Unterauftrag. Ein unvollständiger Postbeleg bleibt Unknown.

Das neue typisierte MCP-Werkzeug `keyboard_control` benutzt die vorhandene
Aufgabenannahme, Idempotenz und Completionkanäle. Discovery erklärt ausdrücklich
profilfreie Nutzung und automatische Zielbeobachtung. Nur ausdrücklich umfassende
Full-Policies (`permission_level=full`, beliebige Executables, Root `/`) erhalten
beim Validieren die festen sieben Keyboard-/Auflösungsfähigkeiten. Keine Datei
wird dafür umgeschrieben; Medium/Ask/Legacy/begrenzt konfigurierte Full-Policies
und alle OS-Rechte bleiben unverändert.

16 neue gezielte Corefälle bestanden in0,92s, darunter mehrteiliger Unicode-Text
mit/ohne Return, einzelne Fokusakquisition, eine Lease, unklare/geänderte Ziele,
Widerruf vor Commit und Antwortverlust ohne Replay. 43 gezielte Rechte-/MCP-Fälle
bestanden in3,43s. Eine unabhängige Review fand und schloss einen rekursiv benannten
Autorisierungscallback; die Textintegration prüft ausdrücklich den korrigierten
Pfad. Native-Transport dieser Fälle ist synthetisch, keine Liveeingabe behauptet.

## Schritt 2 – Allgemeine native Tasten ohne Textfeldpflicht

Der native Snapshot bindet nun einen allgemeinen fokussierten AX-Kontext. Für
Tasten und Kombinationen werden keine Textwerte gelesen. Fehlende optionale
Fokus-/Enabled-/Subroleattribute bleiben ausdrücklich unbekannt; widersprüchliche
Werte, sichere/protected Elemente, App-/Fenster-/Fokus-/Layoutänderungen verweigern.
App-, Prozess-, Principal-, Worker- und Zielrevision bleiben gebunden.

Text und optionales Return verlangen weiterhin den vollständigen strengen
Textvertrag. Für echte AXTextAreas darf die Subrole fehlen, wenn der AX-Status
dies belegt; bei TextFields wird daraus keine Freigabe abgeleitet. Kommunikations-
fehler werden nicht als optional fehlender Wert umgedeutet. Nach wie vor kein
blindes Unicode-/Clipboard-Fallback und keine behauptete Programmbestätigung.

Der neue isolierte Nativeharness bestand zunächst40, nach dem gezielten
TextArea-Delta54 Fallgruppen (letzter Lauf17,70s). Ausschließlich injizierte
AX-Daten/Closures, keine UI-, TCC- oder echten Postaufrufe. Alte174 Nativefälle
wurden nicht wiederholt. Eine kleine ergänzte App-Metadatenangabe kennzeichnet
normale GUI-Programme; die Konsole kann damit Hintergrundhelfer ausblenden,
während die allgemeine App-API diese unverändert zugänglich hält.

## Schritt 3 – Einfache Oberfläche, vorhandene Funktionen erhalten

Der Tastaturbereich lädt beim Öffnen automatisch die laufenden Programme.
Normale GUI-Programme erscheinen namentlich, explizite Hintergrundhelfer nicht;
alte Server ohne dieses Metadatum bleiben kompatibel. Es wird kein Browser oder
anderes Ziel geraten. Der Nutzer wählt ein Programm, Text oder Taste/Kombination
und „Senden“. Return ist bei Text ein ausdrückliches Häkchen. Der Backendweg ist
derselbe einzelne `keyboard.control`-Auftrag wie beim MCP-Werkzeug.

Profilverwaltung mit CAS, Vorschau, Profilaktionen und Menübeobachtung bleibt
vollständig unter „Erweitert“ verfügbar. Die bisherige Intent-/Unknown-/GET-only-
Behandlung wird wiederverwendet. IME-Komposition, Enter im Textfeld und Doppelklick
senden nicht versehentlich mehrfach. UTF8-/Unicode- und32-KiB-HTTP-Grenzen werden
vor Persistierung/POST geprüft; die Core-Textgrenze bleibt1MiB.

Ein neuer Backendfall bestand in0,35s, fünf neue isolierte Browserfälle bestanden
im ersten Lauf. Nur der anschließende GUI-Programmfilter erhielt einen weiteren
gezielten Browserfall. Alte Browsermatrizen wurden nicht wiederholt. Geprüft sind
direkter Text/Return, Taste/Modifier, Antwortverlust/Neuladen/GET-only, fehlende
Belege, Draft-/Größenschutz und weiterhin vorhandene erweiterte Funktionen.
Screenshot visuell geprüft; keine personenbezogenen Browserprofile verwendet.

Für die reale Prüfung erhält die vorhandene eigene Fixture zusätzlich einen
fokussierbaren Button mit unabhängigen Down-/Up-Zählern. Die TextArea benutzt
nun ihre normale Framework-Subrole; der alte erzwungene Leerstring ist optional.
Ein kleiner separater Sessionhelfer verwaltet ausschließlich eine neue UUID-App,
ihre Prozessgeneration und Receiverdateien; er sendet keine Tastatureingaben und
startet keinen alternativen MCP-Server. Code-/Offlineprüfungen und ein einzelner
Fixturecompile sind belegt. Erst Root sendet die tatsächlichen Eingaben über den
vorhandenen authentifizierten ChatGPT-Connector. Die vorbereitete Fixture ist
noch kein Liveeingabenachweis.

## Paket, Installation und tatsächliche ChatGPT-Prüfung

Noch ausstehend. Die bisherigen isolierten Belege werden wiederverwendet;
keine wiederholte Vollsuite, kein neuer Codex-Agentlauf und keine großen CI-Läufe.
Bis zur Paket-/Laufzeitabnahme bleibt der installierte Stand unverändert.

Die vorhandene öffentliche MCP-Abnahme erhielt dafür ausschließlich das neue
Szenario `direct-control`: kurzer BOM-/Unicode-Text, Appauswahl nur durch UUID-
Bundle-ID, kein übergebenes natives Target, exakt bestätigter Text/Return und
automatisch ermittelte Appgeneration. Die bisherigen Default-/Profilfälle werden
nicht erneut ausgeführt. Syntax-/Ruff-/Deltareview sind grün; ein Lauf wurde bis
zu diesem Sourcecheckpoint noch nicht behauptet. Danach folgt getrennt der
tatsächliche Apps-Connector mit authentifiziertem Principal `chatgpt`.

### Reale Abnahme fand einen Übergabefehler

Das erste saubere Paket `b1853e0` bestand offiziellen Build, isolierten Smoke und
unabhängigen Manifest-/Wheel-/Nativevergleich. Der anschließende einzelne reale
`direct-control`-MCP-Auftrag scheiterte jedoch vor Eingabe mit `state_conflict`:
Facade und delegierter Schreibmanager riefen beide den zustandsändernden
`running`-Callback auf. Die isolierten Adaptertests hatten einen permissiven
Callback und konnten diesen Dispatcher-Vertrag nicht belegen.

Die produktive Installation wurde deshalb nicht umgeschaltet. Fixture, eigener
Worker und privater Endpunkt wurden nachweislich bereinigt; der fehlgeschlagene
Originalbeleg bleibt unter `direct-control-live-01` erhalten. Die Facade setzt
jetzt nur einmal `running`; weitere native Phasen benutzen den vorhandenen
`progress`-Callback. Ein neuer gezielter Regressionstest verwendet den echten
Aufgabenstore und TaskManager von prepare/approve/claim bis completed und genau
einem Commit. Er bestand in0,31s. Eine anfängliche Testzählung verwechselte
Fortschrittszeilen mit Zustandsübergängen; nur die Zählung nach Evidence-Typ
wurde korrigiert, der Beleg bleibt erhalten. Unabhängiger Deltareview grün.
Nur wegen dieses tatsächlichen Corefixes ist ein neues exaktes Paket nötig;
Native-, Rechte- und Browsermatrizen werden nicht erneut ausgeführt.


### Hintergrundaktivierung: zweiter realer Fehler vor Installation

Das korrigierte exakte Paket `65c85b4` bestand Build, offiziellen Smoke,
unabhängigen Paketvergleich und die reale profilfreie MCP-Texteingabe mit Return
(`direct-control-live-fixed-01`, alle Abnahme-/Bereinigungsflags wahr). Ein
zusätzlicher, gezielt begründeter Hintergrundtest deckte danach eine noch offene
Synchronitätsannahme auf: Die eigene Fixture wurde nachweislich inaktiv; die
anschließende automatische Eingabe stoppte mit `keyboard_focus_unconfirmed`.
MacOS bestätigt `activate()` als Anfrage und aktualisiert `isActive` über die
Main-Runloop. Der sofortige Statuscheck war deshalb kein ausreichender Wartevertrag.

Der erste Hintergrundtest fand keinen laufenden Finder und stoppte bereits im
Testaufbau; er wird nicht als Produktfehler gezählt. Der korrigierte Aufbau
aktivierte ausschließlich das vorhandene Terminal ohne Eingabe und belegte den
Fehler (`background-control-live-02`). Beide Originalbelege und Logs bleiben
erhalten. Fixture, eigener Worker und privater Endpunkt sind jeweils bereinigt;
kein produktiver Dienst wurde umgeschaltet und keine Texteingabe wiederholt.

Die kleine Corekorrektur wartet nach höchstens einer Aktivierungsanfrage lesend
auf das exakt gleiche Programm. Sie verwendet die ohnehin autorisierte App-Liste,
eine kurze feste Deadline und unveränderte Prozess-/Bundle-/Pfadidentität. Erst
danach folgt frischer Inspect. Kein Aktivierungsretry, keine Texteingabewiederholung
und kein zusätzlicher Zugriff oder Clipboard-Fallback. Nur das betroffene Delta
wird geprüft; die vorhandenen Native-, Rechte- und Browserbelege bleiben gültig.

Zehn neue gezielte Fokusbeobachtungsfälle bestanden in0,80s;17 bestehende Fälle
wurden ausgelassen. Darunter verzögerte Aktivierung, alle festen Identitätswechsel,
unvollständiger Katalog, Berechtigungswiderruf und ein hängender Leseaufruf mit
strikter Gesamtdeadline vor jeglicher Texteingabe. Ruff-/Diffprüfung und
unabhängiger enger Core-Review sind grün.
