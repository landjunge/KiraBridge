# Optionaler ChatGPT-Events-Anschluss

Status, private Vorbereitung, Grenzen und Abnahme:
[CHATGPT-EVENTS-20261019.md](../../docs/CHATGPT-EVENTS-20261019.md).
**Echter Chatempfang ist noch nicht nachgewiesen.**

Separates Abhängigkeitsprojekt; verändert die laufende SDK-1-Bridge nicht:

```sh
uv sync --project integrations/chat-events --locked
integrations/chat-events/.venv/bin/python integrations/chat-events/serve.py --help
```

Produktiv: `serve.py --external-sender` hinter dem vorhandenen privaten Tunnel,
zusätzlich derselbe Einstieg mit `--sender-only` als dauerhafter lokaler Dienst.
Beide benötigen dieselbe private `--state`-Datei und die tatsächlich geprüften
`--allow-callback-host`-Werte. `--config` verweist auf die bestehende TOML-Policy;
keine neuen Tokens/Rechte. Die Standard-Allowlist ist leer.

`prepare.py` schreibt nur neue private Kandidaten, installiert oder startet nichts.
`check_protocol.py` ist ausschließlich ein simulierter Host für isolierte Tests.
Niemals diesen Testadapter mit der echten App verbinden.

Normale Task-Schemas bleiben unverändert. Push ist optional über das bestehende
`completion_target=push:<echte bestätigte Subscription-ID>`; kein neues Pflichtfeld.
[Aktueller Betrieb und Abnahmegrenze](../../docs/MCP-SCHEMA-CACHE-20261019.md).
