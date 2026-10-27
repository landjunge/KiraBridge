# KiraBridge: Lizenzhistorie und bestehende Rechte

Prüfstand: 27.10.2026, Ausgangscommit
`1cc3d2470d246713fb5f5cef96beb54fbddd8296`, Paketversion `0.8.0rc17`.
Dieses Dokument erläutert belegte Repositoryzustände; die jeweiligen Lizenztexte
und tatsächlich wirksam erteilten Erlaubnisse bleiben maßgeblich.

## Gegenwärtige Lizenz

Die [LICENSE](../LICENSE) enthält die individuelle **Netzwerkpunkt Personal Use
License 1.0**. Die aktuelle Datei enthält ausschließlich die bereits zuvor
maßgebliche deutsche Fassung.
Die Lizenz erlaubt private, nicht geschäftliche Nutzung und die dort genannten
Bearbeitungen. Geschäftliche Nutzung, Weiterverkauf und entgeltliche Dienste
benötigen eine gesonderte schriftliche Erlaubnis. Eine allgemeine
Weiterverteilungs- oder Unterlizenzierungserlaubnis wird nicht erteilt.

`pyproject.toml` verweist mit
`LicenseRef-Netzwerkpunkt-Personal-Use-1.0` und `license-files = ["LICENSE"]`
auf diesen Text. Der LicenseRef ist ein projektspezifischer Verweis auf den
mitgelieferten Text, keine OSI-Zertifizierung. Gesondert lizenzierte
Drittbestandteile und Marken-, Namens- und Logorechte sind getrennt zu behandeln.

## Nachgewiesener Gitverlauf

Die Prüfung umfasst alle **274 durch den Ausgangscommit erreichbaren Commits**
und die jeweilige Rootdatei `LICENSE`. Der Verlauf verzweigt; ein Datum allein
grenzt deshalb nicht alle historischen Fassungen ab.

| Beleg | Festgestellter Zustand |
| --- | --- |
| [Erster erreichbarer Commit `5038f52`](https://github.com/landjunge/KiraBridge/commit/5038f52e33ec5ada1895443d65d5f05bdf7aa4e6), 17.10.2026, 15:30:04 UTC | Keine Rootdatei `LICENSE`. Daraus folgt keine freie Nutzungserlaubnis. |
| [Einführung `a2a21e7`](https://github.com/landjunge/KiraBridge/commit/a2a21e771b09f3235a95ac96118aa7ee889eec22), 18.10.2026, 12:12:40 UTC | Personal-Use-Lizenz erstmals im geprüften Graphen hinzugefügt; bereits mit dem unzutreffenden §5-Verweis auf 4AllPass/PolyForm. Parent `598bc1b15f8e84fd8551b5205d9af26f19c834a7` hat keine Root-LICENSE. |
| [Paketstand `57bee99`](https://github.com/landjunge/KiraBridge/commit/57bee99df829398102f8ab57c6dd845e3c8cf3aa), 18.10.2026 | RC2 integriert die Lizenz in Paketmetadaten und neue Pakete; [damalige Releasehinweise](RELEASE-NOTES-0.6.0rc2.md) lassen ältere RC1-Artefakte ausdrücklich unverändert. |
| [Weiterer Pfad `d5e19ae`](https://github.com/landjunge/KiraBridge/commit/d5e19ae23683215863480d485941e3591de40edf), 19.10.2026, 17:43:12 UTC | Derselbe Lizenztext wird auf einem Entwicklungszweig erneut hinzugefügt. Parent `cc33ea55fab80eeb45fd29a8c5f3e7faeaa6348b` hat keine Root-LICENSE. Kein zusätzlicher Lizenzwechsel. |
| Ausgangscommit `1cc3d2470d246713fb5f5cef96beb54fbddd8296` | 223 erreichbare Commitbäume enthalten denselben LICENSE-Blob `c5020fe627e99069d5be723e6857538e69d3d511`; 51 haben keine Root-LICENSE. Keine andere Root-LICENSE-Fassung in diesem Graphen gefunden. |

Der ursprüngliche Lizenztext hat SHA-256
`3316d5eda60ac1fea355aa43d196feea3567384179b55ca88c8636c0322021ec`.
Die GitHub-Releaseinformationen vom Prüfdatum nennen denselben Digest für die
separaten LICENSE-Assets von `v0.7.0rc1`, `v0.7.0rc2` und den Entwürfen
`v0.6.0rc2`/`v0.8.0rc17`. Ein Assetdigest ersetzt keine Prüfung sämtlicher
Dateien eines früheren Pakets. Ein veröffentlichtes Prerelease in einem privaten
Repository belegt auch keine frühere weltweite öffentliche Bereitstellung.

## Redaktionelle Korrektur des §5

§5 und seine englische Übersetzung verwiesen seit ihrer Einführung auf
historische **4AllPass**-Fassungen unter **PolyForm Noncommercial** sowie auf einen
angeblichen späteren All-rights-reserved-Hinweis. Dieser Fremdproduktverweis
belegt keine entsprechende KiraBridge-Lizenzhistorie. Der geprüfte
Root-LICENSE-Verlauf weist keinen solchen KiraBridge-Lizenzwechsel nach.

Die Korrektur benennt KiraBridge und erhält den allgemeinen Bestandsschutz:
bereits wirksam eingeräumte Rechte werden nicht rückwirkend entzogen;
früher bezogene Fassungen und gesonderte Erlaubnisse behalten ihre jeweils
geltenden Bedingungen. Sie erteilt keine neue PolyForm-, MIT- oder andere
historische Lizenz und ändert keine Rechte an 4AllPass. Historische Dateien,
Tags und Release-Assets werden nicht umgeschrieben oder ersetzt.

Bei der §5-Korrektur in `683e342` blieben Copyrightvermerk und §§1–4/6
beider damaliger Sprachfassungen unverändert. Die anschließende sprachliche
Vereinheitlichung entfernt die nicht maßgebliche englische Übersetzung aus
der aktuellen Datei; sämtliche deutschen Bedingungen bleiben bytegleich
zum Stand `21b6b97008c692a4bfd8f02e2d05a31686460cb0`. Das proprietäre
Lizenzmodell und bestehende Nutzungsrechte bleiben erhalten. Die frühere
Übersetzung bleibt im unveränderten Gitverlauf und im externen Belegarchiv
mit ihrer Herkunft erhalten; siehe [Sprachprüfung](LICENSE-LANGUAGE-CHECK.md).

## Grenzen und Verkaufsunterlagen

Nicht abschließend durch diese Prüfung erfasst sind nicht erreichbare
Entwicklungszweige oder frühere Repositorykopien, individuell erteilte
Erlaubnisse, tatsächlich versandte Pakete und deren Empfänger sowie Verträge
mit Mitarbeitern oder Auftragnehmern. Der fehlende Fund einer früheren
MIT-/PolyForm-Lizenz ist kein Nachweis, dass außerhalb dieses Graphen nie
weitere Rechte eingeräumt wurden. Bestehende private Nutzungsrechte aus
dieser Personal-Use-Lizenz sind ebenfalls zu berücksichtigen.

Ein Verkauf oder eine exklusive kommerzielle Lizenz kann nur die tatsächlich
vorhandenen eigenen Rechte umfassen. Git-Autorenangaben und Copyrightvermerke
beweisen keine vollständige Rechtekette. Vor Abschluss sind insbesondere
Arbeits-/Auftragsverträge, Bearbeitung, Weiterübertragung und Unterlizenzierung,
frühere private/kommerzielle Erlaubnisse, Design-/Markenrechte sowie die
[Drittbestandteile](THIRD-PARTY-LICENSES.md) gesondert zu prüfen. Dieses Dokument
verspricht weder vollständige Rechteinhaberschaft noch uneingeschränkte
Exklusivität und ersetzt keine anwaltliche Prüfung.
