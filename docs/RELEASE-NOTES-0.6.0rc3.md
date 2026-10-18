# KiraBridge 0.6.0rc3 · Private Release Candidate

## Deutsch

KiraBridge für Vibe Coding: Mit ChatGPT besprechen, über KiraBridge an Codex oder
Grok auf dem eigenen Rechner übergeben. Zusammenarbeit mit eingerichteten Rechten;
weitere CLI-Anbindungen geplant. Keine Übernahme fremder interaktiver Sitzungen.

Dieser neue Kandidat enthält die seit RC2 integrierten Projektfunktionen:
ThreadDesk-Verwaltung und revidierte Handoffs mit Frage-/Antwortfortsetzung,
expliziten Codex-Schreibmodus, begrenzten PNG-Bildabruf, ThreadDesk-Wissen,
beobachtenden Auditexport, konkrete Bereitschaftsprüfung und strukturierte
Diagnosen. Optionaler auftragseigener Stopp prüft Quell-/Konfigurations-/Journal-
identität; ein angenommener Stopp verhindert weitere Turns auch nach Wiederanlauf.
Stoppwunsch, dauerhafte Barriere und tatsächliches Prozessende bleiben getrennt.
Kosten unbekannt, kein harter Dollarcap und kein universeller Prozessstopp.

Der konfigurierte Stopp bleibt standardmäßig aus. TollGate und ThreadDesk sind
keine mitgelieferten Abhängigkeiten und werden nicht automatisch installiert.
Deren feste geprüfte lokale Peers/Quellpins und explizite Rechte müssen gesondert
konfiguriert werden. Ohne sie bleibt der eigenständige Bridgebetrieb verfügbar.
Die Konfiguration des Betreiber-Macs wird weder mitgeliefert noch übernommen.

Ein Startbefehl im geprüften entpackten Paket: `sh install.sh`, Englisch
`sh install.sh --language en`. Der vorhandene DE/EN-ASCII-Assistent führt durch
Voraussetzungen, lokale Einrichtung und den wiederverwendeten ChatGPT-Helfer.
Keine sudo-Abfrage; bestehende Konfiguration, Daten und Schlüssel bleiben erhalten.
Kontoberechtigung und verdeckte Eingabe eines eingeschränkten Tunnel-Runtime-
Schlüssels bleiben echte Nutzerschritte. Health/Tunnel sind keine Zielchat-Abnahme.

Enthalten: unveränderte Netzwerkpunkt Personal Use License1.0, DE maßgeblich,
EN Übersetzung; LICENSE im Bundle/Payload, Wheel, Quellpaket und als separates
Asset. Ausdruck `LicenseRef-Netzwerkpunkt-Personal-Use-1.0`. Private nicht
gewerbliche Nutzung kostenlos, geschäftliche Nutzung/Weiterverkauf/kostenpflichtige
Dienste nur mit gesonderter schriftlicher Erlaubnis. Individuell, kein OSI-Standard,
nicht anwaltlich geprüft; Fremdlizenzen und historische Rechte bleiben erhalten.

**Privater RC, keine stabile1.0 und keine öffentliche Veröffentlichung.**
Der genaue Quellpin steht in `release.json`; Plattformbelege und SHA256SUMS
gehören zum jeweiligen neuen Kandidaten. Historische RC1/RC2 bleiben unverändert.
macOS15 Intel/Apple Silicon und Ubuntu24.04 x86_64 sind die begrenzten Paketziele;
frische Benutzerdienst-/ChatGPT-Kontoabnahme, Drittanbieterbedingungen und die
Wartungsbewertung des Intel-only cryptography48.0.1-Pins bleiben separat offen.
Öffentliches Release, Discussion und geplante Subdomain benötigen Freigabe.

## English

Built for Vibe Coding: discuss with ChatGPT, pass tasks through KiraBridge to
Codex or Grok on your computer, with configured permissions. More CLI integrations
are planned. Existing interactive sessions are not taken over.

This new candidate packages the project controls added since RC2: ThreadDesk
management, revision-bound handoffs and question/answer continuation, explicit
Codex write mode, bounded PNG snapshots, ThreadDesk knowledge, observer-only
audit export, concrete readiness and structured diagnostics. Optional owned
workflow stop checks source/config/journal identity and prevents further turns
after an accepted stop, including after restart. Stop request, durable barrier
and actual process exit are separate. Costs unknown, no hard dollar cap and no
universal process termination.

Control is disabled by default. TollGate and ThreadDesk are not bundled or
automatically installed: reviewed fixed local peers/source pins and explicit
permissions require operator configuration. Standalone bridge use remains
available without them. The operator Mac's settings are not included or copied.

One start command from the verified extracted archive: `sh install.sh --language
en`. The existing DE/EN ASCII guide covers prerequisites, local setup and the
reused ChatGPT setup helper. No sudo prompts; existing settings/data/keys are
preserved. Account access and hidden entry of a restricted tunnel runtime key
remain real user steps. Health/tunnel readiness is not a target-chat acceptance.

Unchanged Netzwerkpunkt Personal Use License1.0: German governs, English is a
translation; LICENSE in bundle/payload, wheel, source archive and separate asset.
Expression `LicenseRef-Netzwerkpunkt-Personal-Use-1.0`. Free private non-business
use; business use/resale/paid services need separate written permission. Custom,
not an OSI standard or legal review. Third-party/historical rights remain.

**Private RC, not stable1.0 or a public release.** Exact pin in `release.json`;
new platform evidence and SHA256SUMS accompany this candidate. Historical RC1/RC2
remain unchanged. Targets: macOS15 Intel/Apple Silicon and Ubuntu24.04 x86_64.
Fresh user-service/ChatGPT account acceptance, third-party terms and maintenance
review of the Intel-only cryptography48.0.1 pin remain separate. Public release,
Discussion and the planned subdomain still require explicit publication approval.
