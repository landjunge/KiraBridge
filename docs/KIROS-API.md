# KirOS-Fassade `kirabridge.kiros_api`

Zweck: einzige, schmale Importfläche für das Modul KirOS
(Spezifikation: KirOS `docs/SPEC.md`, Abschnitt 8, Punkt 1). Die Fassade enthält
keine eigene Logik, sondern re-exportiert nur die stabilen Bausteine:

- `OpenRouterAdapter` — OpenAI-kompatible Text-/Tool-Turns über OpenRouter
- `keychain_credential`, `credential_status` — lokaler Keychain-Zugriff
- `OPENROUTER_FREE_MODELS`, `OPENROUTER_PAID_MODELS` — verifizierte Modellsammenstellungen
- `OPENROUTER_DEEPSEEK_MAX_PRICE`, `OPENROUTER_DEFAULT_MODEL` — Preis-Obergrenze, Standardmodell
- `ACPClient` — ACP-v1-stdio-Client
- `record_completion` — Abschluss-Meldung mit Handoff

Stabilitätszusage: Nur die Namen in `__all__` sind die unterstützte Fläche.
**Aenderungen an diesen Namen brauchen einen Test aus KirOS-Sicht**
(`tests/test_kiros_api.py`); alles andere in KiraBridge ist intern.

Secret-Regel: `keychain_credential` liefert ein Secret nur im Speicher an den
Aufrufer. Nie Schluesselwerte loggen, ausgeben oder persistieren.
