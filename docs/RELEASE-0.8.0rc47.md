# KiraBridge 0.8.0 RC47

macOS-Kandidat nach RC46 (`f0068fb`).

Neu gegenüber RC46:

- [PR #130](https://github.com/landjunge/KiraBridge/pull/130): Schreib- und Quittungslatenz zu
  ThreadDesk; Schreibquittungen warten nicht mehr hinter großen Lesevorgängen.
- [PR #131](https://github.com/landjunge/KiraBridge/pull/131): Design BP-DESIGN-01
  (ThreadDesk-Optik mit KiraBridge-Konturen im Fünf-Produkte-Kopf).
- ThreadDesk-Pin von `aa940db` auf `869a389` (`main` mit
  [ThreadDesk PR #115](https://github.com/landjunge/threaddesk/pull/115): Index-Neuaufbau
  verzögert, Papierkorb wird nur einmal gelesen). Das Paket bringt diese Bibliothek mit;
  `install` legt sie unter `install/shared/threaddesk-869a389` ab.

---

# KiraBridge 0.8.0 RC47 (EN)

macOS candidate after RC46 (`f0068fb`).

Changes since RC46:

- PR #130: write and receipt latency towards ThreadDesk; write receipts no longer block behind large reads.
- PR #131: BP-DESIGN-01 (ThreadDesk look with KiraBridge brand contours on the five-product header).
- ThreadDesk pin moved from `aa940db` to `869a389` (`main` with ThreadDesk PR #115: deferred index
  rebuild, trash read once). The package bundles this library; `install` places it under
  `install/shared/threaddesk-869a389`.
