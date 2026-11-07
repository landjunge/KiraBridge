# Vertrag für reguläre Dateiverschiebungen

`FilesystemManager.move` verschiebt eine reguläre Datei innerhalb eines Dateisystems,
ohne ein vorhandenes Ziel zu ersetzen. Der normale Erfolg bleibt `{"moved": true}`.
Ein Zielkonflikt vor Beginn und Quelle/Ziel als derselbe Pfad werden ohne Capture
abgewiesen. Unterschiedliche `st_dev` der Eltern werden vor Capture abgewiesen;
es gibt keinen Copy/Delete-Fallback.

## Effektgrenzen

Der Quellparent und Zielparent werden wie bisher über `PathScope` ohne Verfolgen
von Verzeichnissymlinks geöffnet. Ein privates, zufällig benanntes Unterverzeichnis
`.kirabridge-move-<32hex>` im Quellparent enthält ausschließlich Daten dieses Versuchs.
Der Stage hat Modus 0700; Journal und unabhängiger Sentinel werden mit 0600 angelegt.
Gewöhnliche Dateitools verweigern diesen reservierten Pfadbestandteil. Das ist keine
Isolation gegen einen böswilligen Prozess desselben OS-Users, der private Bridge-Daten
gezielt manipuliert. Solche Prozesse können auch andere private Bridge-Daten verändern.

1. Eine `lstat`-Beobachtung verlangt eine reguläre Quelle. Ein No-Follow-Hardlink nach
   `pin` hält deren Inode fest, ohne Dateiinhalte zu öffnen oder Leserechte zu verlangen.
   Der Pin muss regulär sein und dieselbe dev/ino/Typ-Identität wie die Beobachtung haben.
   Der gehaltene Pin verhindert Inode-Wiederverwendung zwischen Pin und Capture.
2. Der zweite Name `captured` wird als **unabhängige reguläre Sentineldatei** exklusiv
   angelegt. Das begrenzte Journal mit UUID, Eltern-/Dateiidentitäten, Namen und Phase
   wird geschrieben, datei-fsync'ed und atomar ersetzt. Stage und Quellparent werden
   vor jedem öffentlichen Capture dauerhaft synchronisiert.
3. Ein gewöhnliches descriptor-relatives `rename` ersetzt diesen eigenen Sentinel
   durch die Quelle. Directory→bestehende Non-Directory-Datei ist im Kernel verboten:
   Ein inzwischen eingesetzter Ordner bleibt deshalb an der Quelle. Quelle und Stage
   werden anschließend synchronisiert. Dies ist gerade **kein** No-Replace-Rename in
   einen freien Namen: dieser würde auch einen Ordner verschieben.
4. Nur ein reguläres Capture mit derselben dev/ino/Typ-Identität wie der Pin darf per
   No-Follow-`link` am Ziel veröffentlicht werden. Link ersetzt dort keinen Eintrag.
   Danach wird der Zielparent synchronisiert und `committed` im Journal persistiert.
5. Aufgeräumt werden ausschließlich eigene Stage-Aliase und Journal. Der öffentliche
   Quellpfad wird nach Capture **niemals entlinkt**. Eine dort inzwischen neu angelegte
   Datei bleibt unangetastet. Pin und Capture werden niemals chmod/chown/truncate'ed,
   da Hardlinks denselben Nutzerdaten-Inode referenzieren.

Der Gesamtvorgang ist keine einzelne atomare Umbenennung: Zwischen Capture und
Publish kann die Datei ausschließlich über die privaten Aliase erreichbar sein.
Die Garantie betrifft erhaltene Objekte und No-Clobber-Grenzen, nicht eine über
mehrere Syscalls eingefrorene öffentliche Dateinamenansicht.

Identität ist kein eingefrorener Dateinhalt: externe In-place-Schreibzugriffe auf
denselben Inode bleiben möglich. Es gibt keinen vom Nutzer vorgegebenen älteren
Inode-/Approval-Token. Gegenüber der anfänglichen Beobachtung ist der Pin die konkrete
gehaltene Identität; ein stat-Vergleich allein wäre kein Inode-Lock.

## Konflikte und erhaltene Daten

Ein zwischen Pin und Capture eingesetzter anderer regulärer Eintrag, Symlink oder
FIFO kann vorübergehend in den privaten Stage geraten. Er wird **nicht** am Ziel
veröffentlicht. Ein No-Follow-Link versucht genau einmal, den erfassten Eintrag wieder
am freien Quellnamen anzulegen; dabei wird nichts ersetzt. Bei Source-Mismatch bleiben
Originalpin und unerwartetes Capture für explizite Recovery erhalten, auch wenn die
Wiederherstellung gelang. Ein eingesetztes Verzeichnis wird bereits vom Capture-Rename
verweigert. Die Garantie lautet deshalb nicht, dass jeder Non-Directory-Sondereintrag
zu jedem Zeitpunkt unberührt bleibt.

Bei einem erst nach Capture auftretenden Zielkonflikt wird die korrekte Quelle ebenso
ohne Überschreiben zurückgelinkt. Nur bei bestätigter Wiederherstellung und Cleanup
wird der Zielkonflikt als normaler Fehler zurückgegeben. Ist die Quelle inzwischen
belegt, bleiben neue Quelle, bestehendes Ziel und private Original-Aliase erhalten.
Weitere `stat`-Prüfungen und advisory Locks ersetzen keine dieser Kernelgrenzen.

Nach Capture, nach möglicherweise wirksamen Syscalls oder bei fehlgeschlagenem Commit-
fsync werden private Daten nicht pauschal gelöscht. `UncertainExecution` besitzt eine
JSON-taugliche `.provider_error`-Receipt: `ref`, `phase`, `retained`, `retained_entries`,
`source_removed`, `dest_published`, `recovery_dir` und ausdrücklich keine automatischen
Retries/Recoveries. Ein unbestätigter Publikationsausgang kann `dest_published: null`
haben. `source_removed` bezeichnet den Capture dieses Versuchs ohne bestätigte
Wiederherstellung; es verspricht nicht, dass der Pfad gegenüber externen Neuanlagen
weiterhin leer ist. `TaskManager` speichert diese Receipt bereits in seiner Evidenz.
`dest_published: true` bestätigt den zurückgekehrten Link-Aufruf, nicht eine bei
späterem fsync-Fehler noch ungewisse Crash-Dauerhaftigkeit. Nach einem späten
Cleanup-fsync-Fehler kann `retained: false` sein oder der Stage bereits fehlen;
die Receipt ist deshalb kein Versprechen, dass jeder UNKNOWN noch Payload enthält.
Scheitern Metadatenbeobachtungen selbst, kann `retained: null` stehen. Solche
Beobachtungsfehler dürfen die Receipt nicht durch einen nackten OS-Fehler verdrängen.
Ist auch der Capture-Ausgang nicht mehr beobachtbar, ist `source_removed: null`
erforderlich; `false` würde fälschlich einen nachweislich ausgebliebenen Effekt melden.

## Abbruch und Recovery

`journal.json` ist auf 65.536 Bytes begrenzt. Vor Capture ist mindestens `prepared`
dauerhaft auffindbar, einschließlich ursprünglichem Pin und Sentinel-Identität.
Ein Prozessabbruch nach Capture oder Publish kann diese letzte Phase hinterlassen;
eine Phasenangabe allein ist kein Beweis, dass der folgende Syscall nicht stattfand.
Ein fehlgeschlagener späterer Journal-fsync darf den vorherigen Intent nicht zerstören.
Gehaltene Identitäten und tatsächlich vorhandene Stage-Einträge sind zusammen zu prüfen.
`recovery_dir` ist der ursprüngliche Locator. Wird der geöffnete Quellparent extern
verschoben, kann dieser Pfad veraltet sein; vor einer autorisierten Recovery sind
die gespeicherten Eltern-/Objektidentitäten zu prüfen. Ein Pfadstring allein ist
keine Berechtigung, einen inzwischen anderen Eintrag zu verändern.

Der Wiederanlauf führt **keinen** öffentlichen Pfadschreibzugriff und keine Wiederholung
des ursprünglichen Tasks aus. Der lokale, ausdrücklich autorisierte Operator prüft
Journal und retained Einträge lesend, ohne Symlinks zu verfolgen oder FIFO/Devices
zu öffnen. Eine Wiederherstellung ist eine neue autorisierte Aktion mit No-Clobber-
Konfliktbehandlung. Es gibt keinen automatischen Restore-Endpunkt; normale `file.read`
und andere Dateitools dürfen den reservierten Stage nicht öffnen. Journale und retained
Objekte dürfen bei Konflikten weder zeitgesteuert noch durch rekursive Cleanup-Routinen
entfernt werden. Ein bereits extern belegter Quellname kann ohne Überschreiben nicht
gleichzeitig in den alten Zustand zurückversetzt werden; `UNKNOWN` ist dann erforderlich.

Ein gültiges Journal schützt nicht vor einem vollständig verlorenen Datenträger oder
einem Dateisystem, das bestätigte fsync-Garantien verletzt. NFS/Remote-Dateisysteme
können sogar nach einem Syscall-Fehler einen Effekt behalten; dieser Fall ist kein
Anlass für automatisches Wiederholen oder Löschen des erhaltenen Pins.

## Nachweise und Abnahme

Gezielte Tempfile-Tests müssen den alten Nach-Link-Quelldatenverlust zuerst reproduzieren
und dann Source-Recreate nach Publish, Directory-/Regular-/Symlink-/FIFO-Austausch,
fehlende Quelle nach Pin, Ziel-/Restore-Konflikte, Source==Destination, Mode000 ohne
Content-Open, EXDEV vor Capture, Journal-/Capture-/Publish-fsync-Fehler und Fehler nach
bereits erfolgtem Capture prüfen. Recovery-Abnahme liest die erhaltenen Daten und das
Journal, ohne den fehlgeschlagenen Task wiederzuholen. Diese Tests benötigen keine UI,
Appstarts oder produktiven Daten. Ein Erfolg ist keine native Terminal-/Handoff-Abnahme.

Die Typgrenze des gewöhnlichen Rename und die No-Clobber-Eigenschaft von Link sind
öffentliche Primitive: [Apple rename(2)](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/rename.2.html),
[Linux rename(2)](https://man7.org/linux/man-pages/man2/rename.2.html),
[Linux link(2)](https://man7.org/linux/man-pages/man2/link.2.html).
Der lokale Darwin-SDK-Header erklärt keine atomare erwartete Inode-Bedingung für
`renameatx_np`; `unlinkat` besitzt ebenfalls keinen solchen Compare-and-Unlink-Vertrag.
