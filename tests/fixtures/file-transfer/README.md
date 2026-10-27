# Synthetische Testdateien für isolierte Formatprüfungen

Keine Nutzerdateien. Enthalten sind eine einseitige PDF mit Querverweistabelle,
eine RGB-PNG mit 1×1 Pixel (zlib und PNG-CRC), eine Mono-PCM-WAV
(8 kHz, 0,1 s) und rote H.264-Einzelbilder in einer MP4, mit ffmpeg aus
`lavfi color` erzeugt.

Dies sind vollständige kleine Dateien, keine bloßen Dateiköpfe mit passender
Erweiterung. Die Übertragungstests prüfen identische Bytes und SHA-256 am
dauerhaften Speicherort der Testgegenstelle. Sie belegen weder Anzeige und
Indexierung durch ThreadDesk noch alle Varianten dieser Formate. Office- und
ZIP-Containerfälle sind getrennte Prüfungen der Übertragung und Archivvalidierung.
`Payload.bin` prüft die Übertragung von Bytes in mehreren Blöcken.
