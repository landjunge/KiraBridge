# KiraBridge — gemeinsamer Produktheader / shared product header

Auftrag `FIVE-TOOL-DESIGN-CODEX-20261107`, 07.11.2026. Fortschreibung des
bestehenden E05/UI-01 im ThreadDesk-Teamplan, keine neue Roadmap.

Authentisierte Kontrollsnapshots aus `/api/control/status`; RPC-Laufzeitversion, wenn vorhanden. Kein Status aus PID-Karten. Die fünf Originalbilder sind explizite statische PNG-Routen innerhalb der bestehenden Self-CSP.

Gemeinsame Regeln: KiraBridge, ThreadDesk, 4AllPass, TollGate und Agent Authority
stehen in fester Reihenfolge dauerhaft im Header. Original-PNGs bleiben bytegleich;
44×56px Bedienfläche, 36×36px schwarzer quadratischer Rahmen, höchstens28×28px
sichtbares Motiv mit proportionalem CSS-/Nativeausschnitt. Produktfarben sind
kleine Akzente. Metadaten haben begrenzte Frische; fehlende Version heißt `v?`.
Fremdprodukte ohne bestätigte Bindung bleiben unbekannt. Klick fokussiert/navigiert
die eigene vorhandene Oberfläche; fehlende Fremdziele erhalten eine klare Meldung.
Fokus, Tastatur und DE/EN-Beschriftung sind Teil der Implementierung.

Das mitkopierte `networkpunkt-appbar-assets.json` nennt Originalpfade, Quellpins,
SHA-256 und sichtbare Ausschnitte; `networkpunkt-appbar-SHA256SUMS` hält die
portable Kopie fest. Gemeinsame Quelle ist ThreadDesk, Vertrag
`docs/contracts/appbar-v1.md`; lokale Synchronisierung mit dessen
`scripts/sync_product_header.py` plus `--check`. Kein zusätzlicher zentraler Dienst.

Quellimplementierung und gezielte Prüfungen/Builds sind getrennt von Browser-,
nativer Laufzeit-, Paket- und Produktivabnahme. Browser scheitern im Worker vor
DOM-Start; Screenshots, reale Tastatur/Klicks und schmale Hostansichten bleiben
unabgenommen. Keine neue Appinstallation, kein Push, Release oder Deployment.
Produktwebseiten und veröffentlichte Abbildungen bleiben bis zu belegter visueller
Abnahme beim bisherigen veröffentlichten Stand. Hauptnachweis im TD-Arbeitsstand:
`docs/evidence/five-tool-design-20261107.json`.

## English

Authenticated control snapshots from `/api/control/status`; dispatcher RPC runtime version when present. No status from PID cards. The five images are explicit static routes with `image/png`, enabled by the existing self-only CSP.

All five original product icons share fixed black frames, optical padding,
proportions, focus and keyboard semantics. Missing peers, versions and targets
remain explicit. A local navigation does not authenticate a product connection.
Original asset provenance, checksums and the pinned bundle are included locally;
products remain independent. Targeted source checks/builds are not browser/native
runtime acceptance. Browser startup is blocked before DOM, so screenshots and
real viewport/keyboard/click acceptance remain open. No installation, push,
release or deployment is claimed.
