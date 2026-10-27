# KiraBridge: Drittkomponenten und erforderliche Hinweise

Prüfstand: 27.10.2026, Quellcommit
`1cc3d2470d246713fb5f5cef96beb54fbddd8296`.
Die eigene [LICENSE](../LICENSE) ersetzt keine Lizenzen von Drittbestandteilen.
Dieses Verzeichnis dokumentiert deklarierte Paketlizenzen und offene
Distributionspflichten. Es ist keine vollständige SBOM und kein vollständiges
Notice-Paket für ein ausgeliefertes Binary, Image oder eine Plattform.

## Umfang und Nachweise

Der Root-`uv.lock` enthält 39 Drittpaketversionen sowie KiraBridge selbst.
Die Lizenzdeklarationen wurden versionsgenau anhand von 29 vorhandenen
`dist-info/METADATA`-Datensätzen und für zehn weitere Versionen anhand von
PyPI-Metadaten geprüft. Die Root-Lockbytes stimmen mit der installierten
RC17-Quelle am angegebenen Quellpin überein. Vorhandene originale Lizenzdateien
wurden lesend geprüft; ihre Copyrighttexte sind zu erhalten. Versionsmetadaten
beweisen nicht die Lizenz jeder nativen oder eingebetteten Einzeldatei.

Die folgende Tabelle enthält auch Entwicklungswerkzeuge und andere
Plattformpfade. Ihre Aufnahme bedeutet nicht, dass jedes Paket in jeder
Kundendistribution enthalten ist. `OR` kennzeichnet eine zu dokumentierende
Lizenzwahl; ungenaue Klassifikatoren werden nicht in präzisere Lizenzfassungen
umgedeutet.

| Root-Paket | Version | Deklarierte Lizenz |
| --- | --- | --- |
| [annotated-types](https://pypi.org/pypi/annotated-types/0.8.0/json) | 0.8.0 | MIT |
| [anyio](https://pypi.org/pypi/anyio/4.15.1/json) | 4.15.1 | MIT |
| [attrs](https://pypi.org/pypi/attrs/26.1.0/json) | 26.1.0 | MIT |
| [certifi](https://pypi.org/pypi/certifi/2026.7.22/json) | 2026.7.22 | MPL-2.0 |
| [cffi](https://pypi.org/pypi/cffi/2.1.1/json) | 2.1.1 | MIT-0 |
| [click](https://pypi.org/pypi/click/8.5.0/json) | 8.5.0 | BSD-3-Clause |
| [colorama](https://pypi.org/pypi/colorama/0.4.6/json) | 0.4.6 | License :: OSI Approved :: BSD License |
| [cryptography](https://pypi.org/pypi/cryptography/48.0.1/json) | 48.0.1 | Apache-2.0 OR BSD-3-Clause |
| [cryptography](https://pypi.org/pypi/cryptography/50.0.2/json) | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| [h11](https://pypi.org/pypi/h11/0.16.0/json) | 0.16.0 | MIT |
| [httpcore](https://pypi.org/pypi/httpcore/1.0.9/json) | 1.0.9 | BSD-3-Clause |
| [httpx](https://pypi.org/pypi/httpx/0.28.1/json) | 0.28.1 | BSD-3-Clause |
| [httpx-sse](https://pypi.org/pypi/httpx-sse/0.4.3/json) | 0.4.3 | MIT |
| [idna](https://pypi.org/pypi/idna/3.20/json) | 3.20 | BSD-3-Clause |
| [iniconfig](https://pypi.org/pypi/iniconfig/2.3.1/json) | 2.3.1 | MIT |
| [jsonschema](https://pypi.org/pypi/jsonschema/4.26.0/json) | 4.26.0 | MIT |
| [jsonschema-specifications](https://pypi.org/pypi/jsonschema-specifications/2025.9.1/json) | 2025.9.1 | MIT |
| [mcp](https://pypi.org/pypi/mcp/1.30.0/json) | 1.30.0 | MIT |
| [packaging](https://pypi.org/pypi/packaging/26.3/json) | 26.3 | Apache-2.0 OR BSD-2-Clause |
| [pluggy](https://pypi.org/pypi/pluggy/1.7.0/json) | 1.7.0 | MIT |
| [pycparser](https://pypi.org/pypi/pycparser/3.11/json) | 3.11 | BSD-3-Clause |
| [pydantic](https://pypi.org/pypi/pydantic/2.14.1/json) | 2.14.1 | MIT |
| [pydantic-core](https://pypi.org/pypi/pydantic-core/2.50.1/json) | 2.50.1 | MIT |
| [pydantic-settings](https://pypi.org/pypi/pydantic-settings/2.16.0/json) | 2.16.0 | MIT |
| [pygments](https://pypi.org/pypi/pygments/2.21.0/json) | 2.21.0 | BSD-2-Clause |
| [pyjwt](https://pypi.org/pypi/pyjwt/2.15.1/json) | 2.15.1 | MIT |
| [pytest](https://pypi.org/pypi/pytest/9.1.1/json) | 9.1.1 | MIT |
| [pytest-asyncio](https://pypi.org/pypi/pytest-asyncio/1.4.0/json) | 1.4.0 | Apache-2.0 |
| [python-dotenv](https://pypi.org/pypi/python-dotenv/1.2.4/json) | 1.2.4 | BSD-3-Clause |
| [python-multipart](https://pypi.org/pypi/python-multipart/0.0.32/json) | 0.0.32 | Apache-2.0 |
| [pywin32](https://pypi.org/pypi/pywin32/312/json) | 312 | PSF |
| [referencing](https://pypi.org/pypi/referencing/0.37.0/json) | 0.37.0 | MIT |
| [rpds-py](https://pypi.org/pypi/rpds-py/2026.9.1/json) | 2026.9.1 | MIT |
| [ruff](https://pypi.org/pypi/ruff/0.17.1/json) | 0.17.1 | MIT |
| [sse-starlette](https://pypi.org/pypi/sse-starlette/3.5.0/json) | 3.5.0 | BSD-3-Clause |
| [starlette](https://pypi.org/pypi/starlette/1.8.0/json) | 1.8.0 | BSD-3-Clause |
| [typing-extensions](https://pypi.org/pypi/typing-extensions/4.16.0/json) | 4.16.0 | PSF-2.0 |
| [typing-inspection](https://pypi.org/pypi/typing-inspection/0.4.4/json) | 0.4.4 | MIT |
| [uvicorn](https://pypi.org/pypi/uvicorn/0.54.0/json) | 0.54.0 | BSD-3-Clause |

## Gesonderter Chat-events-Adapter

`integrations/chat-events/pyproject.toml` und sein eigener Lock sind ein
zusätzlicher Scope. Er enthält 33 Drittpaketversionen und den eigenen Adapter.
24 Paarungen aus Name/Version sind bereits in der Root-Tabelle enthalten;
folgende neun unterscheiden sich. Ihre Lizenzangaben wurden anhand der
verlinkten exakten PyPI-Versionen geprüft; die vollständigen Wheel-/nativen
Inhalte und alle Pflichtnotices dieses Scopes sind noch gesondert zu prüfen.
Die Adaptermetadaten nennen keine eigene License-Expression; daraus wird
keine eigenständige Open-Source-Freigabe abgeleitet.

| Zusätzliches/abweichendes Adapterpaket | Version | Deklarierte Lizenz |
| --- | --- | --- |
| [certifi](https://pypi.org/pypi/certifi/2026.10.18/json) | 2026.10.18 | MPL-2.0 |
| [httpcore2](https://pypi.org/pypi/httpcore2/2.14.0/json) | 2.14.0 | BSD-3-Clause |
| [httpx2](https://pypi.org/pypi/httpx2/2.14.0/json) | 2.14.0 | BSD-3-Clause |
| [httpx2-jsfetch](https://pypi.org/pypi/httpx2-jsfetch/1.0/json) | 1.0 | BSD-3-Clause |
| [mcp](https://pypi.org/pypi/mcp/2.3.0/json) | 2.3.0 | MIT |
| [mcp-types](https://pypi.org/pypi/mcp-types/2.3.0/json) | 2.3.0 | MIT |
| [opentelemetry-api](https://pypi.org/pypi/opentelemetry-api/1.45.1/json) | 1.45.1 | Apache-2.0 |
| [starlette](https://pypi.org/pypi/starlette/1.9.0/json) | 1.9.0 | BSD-3-Clause |
| [truststore](https://pypi.org/pypi/truststore/0.10.5/json) | 0.10.5 | MIT |


## Vor einer konkreten Weitergabe

- **MIT/BSD:** Originale Copyright-, Lizenz- und Haftungshinweise entsprechend
  dem jeweiligen Text erhalten; BSD-Werbe-/Namensbedingungen beachten. Eine
  reine Liste der Lizenznamen genügt nicht. Siehe beispielsweise
  [MIT-Text](https://opensource.org/license/mit).
- **Apache-2.0:** Den [Lizenztext](https://www.apache.org/licenses/LICENSE-2.0)
  sowie anwendbare Urheber-/Attributionshinweise
  und vorhandene NOTICE-Inhalte erhalten; Änderungen bei betroffenen
  weitergegebenen Dateien nach Maßgabe des Texts kennzeichnen. Für
  `cryptography` und `packaging` eine zulässige Lizenzalternative mit ihrem
  tatsächlichen Text und allen weiteren enthaltenen Komponenten dokumentieren.
- **Certifi / MPL-2.0:** Bei Weitergabe die tatsächlichen MPL-gedeckten Dateien,
  zugehörigen Quellen und Änderungen bestimmen, vorgeschriebene Hinweise
  erhalten und den Zugang zum gedeckten Quellcode sicherstellen. Das ist kein
  pauschaler Lizenzwechsel des eigenen KiraBridge-Codes. Siehe
  [MPL 2.0](https://www.mozilla.org/en-US/MPL/2.0/) und
  [Mozilla-FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/).
- **MIT-0, PSF und sonstige Texte:** Jeweils den konkreten Pakettext prüfen.
  `typing-extensions` enthält einen mehrteiligen Lizenztext; der ungenaue
  Pywin32-Eintrag `PSF` und der Colorama-BSD-Klassifikator sind vor Weitergabe
  anhand des tatsächlich verwendeten Distributionspakets zu präzisieren.
- **Native Bestandteile und Betriebsumgebung:** Kryptografie-Wheels können
  zusätzliche OpenSSL-/Rustbestandteile enthalten. Pythonruntime,
  Betriebssystempakete, Systemframeworks und separat genutzte Agenten/Provider
  sind abhängig vom tatsächlichen Lieferumfang separat zu inventarisieren.
  Providerkonten und persönliche Abonnements sind keine durch KiraBridge
  automatisch übertragbaren Rechte.

Vor einem Verkaufs- oder Distributionsabschluss sind je tatsächlichem Artefakt
Quellpin, Plattform, Features und Hashes festzuhalten. Dann sind alle enthaltenen
Drittdateien mit ihren originalen Copyright-/Lizenz-/NOTICE-Texten und etwaigen
Quellbereitstellungspflichten abzugleichen. Die vorhandene Paketierung führt
Root-LICENSE und ihre Prüfsumme mit; sie erzeugt damit noch keinen Nachweis
vollständiger Drittanbieter-Compliance. Diese Dokumentation verändert weder
Buildlogik noch historische Release-Assets oder Rechte von Dritten.
