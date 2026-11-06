# Originale Host-UNKNOWNs: Diagnose und begrenzter Belegfix

Auftrag: `BP-HOST-ORIGINAL-UNKNOWN-DIAGNOSIS-20261106`, 6. November 2026.
Board: `188ce4729a62/d94395dfccfd` (#271), Claim `e1791c086a4c` (#273).
Eigener Branch `fix/host-original-unknown-20261106`, Ausgangspunkt
`cb87a9ef97f2d2b46a1c0bf89a50127a266361ac`. Ausschließlich Diagnosemetadaten;
keine neue Fokus-, Tastatur-, Terminal- oder VM-Aktion und keine Installation.

## Was die Originalbelege zeigen

Die beiden Fehler stammen vom Mac-Host, nicht von einem Windows-Testlauf.
Ausführende Python-Runtime: `0.8.0rc39`, Quelle
`8d331314b608d247ba160e04a898f9498cbb22d3`, Instanz
`b988e7acdc284bbfb7da161a18585c46`, PID 40336. Startbeobachteter
Paketbaum-SHA256: `255f70f411b06d6f1aa7bab3f0c6953bf1b779da365ac01b90e8559ade0d8da0`.

| Originaltask | Gespeichertes Ergebnis | Beleg |
| --- | --- | --- |
| `win-native-20261106-focus-vm-01` | `unknown`, `macos_focus_unknown`, `finished=null` | Receipt `c9ccc108-4a8a-49a4-a254-e48aea9e65d0`, Events 40782–40786 |
| `win-native-20261106-wake-display-01` | `unknown`, `keyboard_unsupported`, `finished=null` | Receipt `360755a0-6257-4eb4-a622-ea8f2d811b15`, Events 40797–40803 |

Beide ursprünglichen Preflights waren autorisiert/automatisch; es fehlte keine
KiraBridge-Nutzerfreigabe. Das beweist keine macOS-Rechte und keine erfolgreiche
Wirkung. Windows-Ausführungsrichtlinien sind ein eigener, unveränderter Gate.

Der Fokusauftrag enthielt AXIdentifier `_NS:11`, PID 41465 und Startidentität
`1793727720.753100`. In der damaligen Swift-Quelle bezeichnet derselbe Fehlercode
drei verschiedene Stufen: AX-Raise fehlgeschlagen, App-Aktivierung fehlgeschlagen
oder Zielidentität nach dem Raise nicht mehr bestätigt. Die fehlende statische
Fehlermeldung verhindert eine eindeutige rückwirkende Zuordnung. Ein unbekannter
Fensterbezeichner oder eine vor dem Raise fehlende AX-Berechtigung hätten dort
andere Fehlercodes; zusätzliche Vermutungen über Fokus, Sperrbildschirm oder
Fensterbesitzer sind damit nicht bewiesen.

Der Wake-Auftrag wurde von `keyboard.control` auf `keyboard.key` gebunden:
`key_code=56`, Wiederholung 1, Ziel UTM/PID 41465 mit Startbindung. Code 56 ist
eine physische Modifierposition, die `SystemKeyboard.physicalKeys` im normalen
Key-Pfad absichtlich ausschließt. Er ist dort kein unterstützter Wake-Befehl.
`currentLayout()` läuft vor `resolve()`; auch die Layoutbeobachtung kann
`keyboard_unsupported` liefern. Bei gültiger Layoutbeobachtung lehnt der Resolver
56 vor dem Aufbau/Posting eines Tastenpaars ab. Die verlorene Backendmeldung
belegt jedoch nicht, welche dieser Stufen damals den Fehler lieferte. Der
historische UNKNOWN wird daraus ausdrücklich nicht zu einem No-effect-Ergebnis.

Zeitnahe erfolgreiche native Lesebelege in `native-observations.json` benennen
ebenfalls Helperquelle `8d331314…`. Die Fehlertasks selbst bewahren keine exakte
Helpergeneration/Binärhashbindung. Benachbarte Erfolge sind keine nachträgliche
Attestation des fehlerhaften Requests.

## Reproduzierter Informationsverlust und Änderung

Der ursprüngliche `NativeSystemTransport` prüfte Antwort-, Request- und
Helperidentität einschließlich PID, Generation, Quellcommit, Bundle und Pfad.
Beim Weiterreichen eines gültigen Backendfehlers behielt er nur Code und
`effect_unknown`; die statische Meldung und Helperbindung gingen verloren.
Der TaskManager speicherte folglich nur die generische Fehlerklasse und den
letzten Wirkungsversuchsmarker. Transport und die beiden Swift-Dateien sind
zwischen `8d331314…` und `cb87a9e…` identisch; der betreffende TaskManager-
Exceptionhandler ist trotz anderer Änderungen der Datei AST-identisch.

Der Fix erhält nach genau diesen bestehenden Prüfungen einen kleinen typisierten
`native_failure`-Beleg bis zum regulären Task-Readback:

- Operation und feste Stufe: `window_raise`, `application_activation`,
  `target_revalidation`, `physical_key_validation`, `keyboard_layout_validation`
  oder `unspecified`.
- Backendflag `backend_effect_unknown`, Helper-PID/-Generation/-Quellcommit,
  Request-ID und `contract_binary_sha256`.

Stufen werden nur aus exakten bekannten statischen Meldungen für das passende
Operations-/Fehlercodepaar abgeleitet. Andere/fehlende/nichttextuelle Meldungen
bleiben `unspecified`. Rohe Meldungen, Eingabetext, Pfade und Credentials werden
nicht in diesen Beleg übernommen. Das Modell verbietet zusätzliche Felder und
begrenzt die Formate. Der Hash bezeichnet den vom Launcher geprüften
Dateisnapshot im Transportvertrag, keine neue Attestation des geladenen Binaries.
Bei fehlerhafter Antwortidentität entsteht kein solcher vertrauenswürdiger Beleg.

Keine Änderung an Swift/Protokoll, akzeptierten Tasten, OS-Rechten, Zielgates,
Locks, Wirkungsversuchsmarkern, Exceptionklassenwahl, Taskzuständen oder Retries.
Insbesondere bleibt ein Backendflag `false` nach einem beobachteten
Wirkungsversuch im TaskManager UNKNOWN. Es ist keine No-effect-Quittung.
Historische Datensätze werden nicht ergänzt, bereinigt oder wiederholt.

## Prüfung und verbleibende Grenze

Vor dem Fix scheiterten sieben neue Belegprüfungen am unveränderten cb87-Code;
die negative Helper-PID-Kontrolle bestand. Danach bestanden zunächst zehn Tests
einschließlich zweier echter TaskManager/Store/Task-Readbacks mit synthetischem
Executor. Die erweiterte gezielte Auswahl besteht mit **123 Tests**: 13 neue
Fehlerbelegfälle, vorhandener Transport, Keyboard-Dispatcher, NativeAdmission
und zwei vorhandene UNKNOWN-/Reconciliation-Tests. Keine reale native Eingabe:
Der Nativeworker ist ein In-Memory-Fake, Taskdatenbanken liegen im Testverzeichnis.
Rohe Meldungen bleiben redigiert; fremde Helperbindung bleibt abgelehnt;
idempotenter Readback sendet nicht erneut, Retry bleibt verboten.

Private Originaldaten, Vorher-/Nachherlogs und Quellabgleich liegen unter
`~/.local/share/kirabridge/backups/bigplan-host-original-unknown-20261106/`.
Keine Geheimnisse oder Rohcaptures im Board. Unabhängiger Review und exakter
Lieferpin werden dort/auf dem bestehenden Board separat quittiert.

Der Fix ist ein nicht installierter Kandidat für bessere zukünftige Diagnosen.
Die genaue historische Fokusstufe und eine tatsächliche Wirkung bleiben offen.
Der übernommene W1-Freeze bleibt Restricted mit 0 gestarteten/0 bestandenen
nativen Phasen; dieser Auftrag startet keine davon. Eine Policy-Ausnahme wird
nicht aus diesem Auftrag abgeleitet.
Nächster begrenzter Schritt: unabhängige Quell-/Belegprüfung; erst bei gesonderter
Freigabe einen neuen nativen Diagnoseauftrag planen, keine Originaltask wiederholen.
