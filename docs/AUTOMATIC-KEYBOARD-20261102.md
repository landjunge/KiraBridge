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

## Schritte 2 und 3

Native allgemeine Fokuskontexte, optionale TextArea-Subrole, einfache Konsole und
gezielte reale ChatGPT-Abnahme werden als weitere getrennte Schritte dokumentiert.
Bis zur Paket-/Laufzeitabnahme bleibt der installierte Stand unverändert.
