# Server-Inventar netcup · Kurzbericht

Stand: 08.11.2026, Beobachtung ab 16:59:45 UTC. Paket **BP-OPS-01** (nur lesend) und
Vorbereitung **BP-TRUTH-01**, Lane L1. Bezug: Big Plan im ThreadDesk-Master `6b5b73b9de36` (früherer GitHub-Bauplan, gelöscht 09.11.), Abschnitte 2, 3,
4.2 und 5 Stufe 0.

**Ablage: nur privat.** Der Bericht enthält Serveradressen und offene Sicherheitsbefunde.

- Inventar: `ops/netcup.json` (Format `kirabridge.ops-inventory.v1`, Feld `observed_at`)
- Prüfskript: `scripts/ops_inventory_check.py` (Exit 0 = deckungsgleich, 1 = Abweichung, 2 = Fehler)
- Test: `tests/test_ops_inventory_check.py` (Vergleichslogik ohne ssh, Nur-Lese-Prüfung des Remote-Skripts)

Auf dem Server liefen nur lesende Befehle: `systemctl list-units/list-unit-files/cat/show`,
`ss -tlnp`, `docker ps/inspect/images/system df`, `ls`, `stat`, `sha256sum`, `df`, `du`, `journalctl`
lesend, Caddyfile lesen. Nichts wurde neu gestartet, geschrieben, gelöscht oder gezogen. Die
Testordner wurden nur aufgelistet. Geheimnisse wurden weder ausgegeben noch abgelegt.
Umgebungsvariablen stehen nur mit Namen im Inventar.
Vom Mac aus gab es zusätzlich einzelne `GET`-Abrufe und Portprüfungen gegen die öffentlichen
Endpunkte.

Der Abgleich direkt nach dem Anlegen meldet `0 Abweichung(en)`. Eine Ausnahme ist konfiguriert:
Kurzlebige Loopback-Ports ab 32768 stammen von CI-Jobs der beiden Runner und werden
übersprungen.

---

## 1. Widersprüche W01–W04

| Nr. | Ergebnis | Belege |
|---|---|---|
| **W01** 4AllPass veraltet | **(a) bestätigt, mit Korrektur.** (b) nicht geprüft. | Siehe 1.1 |
| **W02** Servercode ohne Repo | **bestätigt** | Siehe 1.2 und Abschnitt 2 |
| **W03** Mac-Relay zeigt ins Leere | **bestätigt, an zwei Stellen kaputt** | Siehe 1.3 |
| **W04** Serverstand im Board veraltet | **bestätigt** | Siehe 1.4 |

### 1.1 W01 – 4AllPass-Images

- Die Images `4allpass-backend:latest` (`sha256:d8a510bd…`) und `4allpass-web:latest`
  (`sha256:1058c968…`) wurden am **19.08.2026 um 04:35:36 bzw. 04:35:39 (+02:00)** gebaut.
  Gebaut wurde aus `/opt/4allpass/src`, Git-Commit `6da2fbc1` vom 19.08.2026, 03:36.
- Seit diesem Commit liegen auf `4AllPass` `main` (`d81abb2`, 08.11., 14:06) **34
  Backend-Commits**, 156 Frontend-Commits und 415 Commits insgesamt. Der Bauplan nannte 33
  Backend-Commits, `main` ist inzwischen einen weiter.
- Die Container wurden am 19.08. erstellt und laufen seit dem Neustart am 18.10. Nur Caddy wurde
  am 08.11. um 00:38 neu erstellt, für die ThreadDesk-Route `:8443`.
- **Korrektur zum Bauplan, Abschnitt 2 („öffentlich unter `pass.netzwerkpunkt.de`“):**
  Die DNS-Einträge für `pass.`, `4allpass.` und `tollgate.netzwerkpunkt.de` zeigen **nicht**
  auf netcup (`152.53.110.140` / `2a0a:4cc0:80:3e62:…`), sondern auf `185.243.11.43` /
  `2a03:4000:2c:7a9:19:4076:0:4`. Unter dieser IPv6-Adresse kommt ein Zertifikat für eine fremde
  Domain zurück, über IPv4 scheitert die TLS-Kette. Auf netcup liefern diese vHosts nur
  **selbstsignierte Zertifikate** (`O=4AllPass` bzw. `O=Tollgate`), die am **17.11.2026**
  ablaufen. Erzwingt man den Weg zu netcup, antwortet `/healthz` mit 200.
  Folge: Der veraltete 4AllPass-Stack ist unter seiner Domain derzeit nicht öffentlich
  erreichbar. Das senkt die Dringlichkeit von (a). Für die Abnahme von BP-SEC-01 („Login und
  Sync mit Testkonto“) müssen vorher Domain und Zertifikat geklärt werden.
- (b) Der Desktop-Download RC2 war nicht Teil dieses Pakets und wurde nicht geprüft.

### 1.2 W02 – `serve_handoff.py`

- Der Dienst `threaddesk-server.service` läuft als `daniel`, PID 2118562, seit
  08.11.2026 01:30:34. Er startet **über das Drop-in**
  `/etc/systemd/system/threaddesk-server.service.d/public.conf`, das `ExecStart` ersetzt:
  `venv/bin/python /home/daniel/.local/share/threaddesk-server-20261107/serve_handoff.py <data> 172.18.0.1 8766 https://v2202608211799501333.goodsrv.de:8443 172.18.0.0/16`.
- Die Datei: `serve_handoff.py`, 53 Zeilen, Rechte 0600 `daniel`, mtime 08.11.2026 01:30:32,
  **sha256 `bb76d00ecd7e04faae1f65f98a8130131722eec677d639b98f83ea94aa110494`**.
  Daneben liegt die Vorgängerin `serve_handoff.py.bak.v1` (01:10). Sie enthält nur den
  Start mit `handoff_rpc=True`, ohne Monkey-Patch.
- Die Datei steht weder in `landjunge/threaddesk-server` `main` (`1f993b1`) noch in
  `landjunge/threaddesk` `main` (`e7cec44`). In beiden fehlt das Werkzeug `list_issued_handoffs`
  in `server_sync/handoffs.py`.
- Das installierte Paket selbst ist sauber: Alle **271** Quell- und Asset-Dateien unter
  `venv/.../site-packages/threaddesk` stimmen byte-genau mit `threaddesk-server` `main` überein.
  Laut `checkout/INSTALLED-COMMIT` stammt es aus `2a703696`. Von dort bis `main` ändern sich nur
  Doku, Evidenz und `packaging/server/issue_loopback_cert.sh`, kein `src`. Der Ordner
  `checkout` ist kein Git-Repo, sondern ein exportierter Baum.

### 1.3 W03 – Mac-Sync-Relay

- Auf dem Mac läuft launchd `com.landjunge.threaddesk-sync-relay` (PID 67898). Es führt
  `/usr/bin/python3 ~/.config/threaddesk-sync/http-relay.py` aus (sha256 `4daca372…`) und
  lauscht auf `127.0.0.1:18446`.
- Jede Anfrage geht per `ssh netcup-daniel` an `/home/daniel/.local/bin/td-http-relay.py`
  (sha256 `85760564…`). Dieses Skript ruft `https://127.0.0.1:8446` auf.
- `threaddesk-server-tls.service` ist `inactive/dead` und `disabled`. Laut Journal wurde der
  Dienst am **08.11.2026 um 00:37:01** gestoppt. Der Bauplan nennt 01:30, das ist aber der
  Neustart des Hauptdienstes mit `serve_handoff.py` v2. Auf Port 8446 lauscht nichts.
- **Zweiter Bruch:** Auch eingeschaltet würde der TLS-Proxy nichts erreichen. Sein Backend ist
  `http://127.0.0.1:8766`, der Server bindet aber `172.18.0.1:8766`. Ein bloßes
  Wiedereinschalten repariert das Relay also nicht.
- Beide Relay-Skripte liegen außerhalb jedes Repos. Auf dem Server liegt zusätzlich ein älteres
  `td-tls-relay.py`.

### 1.4 W04 – tatsächliche Bindung

- `ss -tlnp` zeigt `172.18.0.1:8766` (python, PID 2118562). Auf `127.0.0.1:8766` und
  `127.0.0.1:8446` lauscht nichts.
- Caddy (`4allpass-caddy-1`) bedient `v2202608211799501333.goodsrv.de:8443` mit
  `reverse_proxy 172.18.0.1:8766` und Body-Grenzen von 96 MiB, 4 MiB und 512 KiB. Vom Mac aus
  liefert `GET :8443/` 200 und `GET :8443/api/health` 401, ohne Anmeldung also wie erwartet.
- Der Server widerspricht sich selbst: Die Basis-Unit nennt noch `--host 127.0.0.1` und
  `--public-origin https://127.0.0.1:8446`, gültig ist das Drop-in. Die README von
  `threaddesk-server` („bindet nur `127.0.0.1:8766`“) und Board `c2d4c7bc985a` sind
  überholt. Das ist mit BP-OPS-02 bzw. BP-TRUTH-01 zu korrigieren und wurde hier nicht geändert.

---

## 2. BP-OPS-02: laufender Stand gegen `threaddesk-server` `main`

Verglichen wurde mit `landjunge/threaddesk-server` `main` = `1f993b1` (07.11., 13:58), lokal
geklont in den Scratch-Ordner. Dort wurde nichts gepusht.

| Punkt | Repo `main` (`threaddesk-server serve`) | Laufend (`serve_handoff.py`) |
|---|---|---|
| Einstieg | Console-Script `threaddesk-server serve` mit argparse | eigenes Skript, positionelle `argv` |
| Handoff-HTTP | `create_app(..., handoff_rpc=False)`; die CLI hat **keinen Schalter** dafür | `create_app(..., handoff_rpc=True)` |
| Werkzeuge | 9: `issue_handoff`, `get_issued_handoff`, `bind_handoff_run`, `record_handoff_question`, `answer_handoff_question`, `import_return`, `get_return`, `review_return`, `reserve_handoff_delivery` | dieselben 9 **plus `list_issued_handoffs`** |
| Technik | – | Monkey-Patch: `handoffs.TOOLS` und `handoffs.scoped_call` werden zur Laufzeit ersetzt. Das wirkt, weil `handoff_call` und `capabilities` die Modul-Globals erst beim Aufruf auflösen. |
| Host | `127.0.0.1` (Unit) | `172.18.0.1` |
| `public_origin` | `https://127.0.0.1:8446` (Unit) | `https://v2202608211799501333.goodsrv.de:8443` |
| `trusted_proxy` | `127.0.0.1` | `172.18.0.0/16` (ganze Docker-Bridge, `forwarded_allow_ips`) |
| Guard `--allow-http-loopback` | vorhanden | entfällt (wird nicht gebraucht) |
| Vertrag | `docs/contracts/server-handoff-http-v1.md` ohne `list_issued_handoffs` | – |

Verhalten von `list_issued_handoffs`: Das Werkzeug liest nur. Es nimmt keine Argumente an
(sonst 400) und filtert `core.store.list_issued_handoffs()` auf `handoff.thread_id ==
project_id`. Die Treffer sortiert es nach `issued_at` absteigend und begrenzt sie auf 100. Es
liefert `handoff_id`, `task`, `target_system`, `created_at`, `issued_at`, `content_hash`, `bound`
und `remote_delivery`. Unter `GET /api/projects/{pid}/handoff` erscheint es in `tools`.

Vorschlag für BP-OPS-02 (nicht ausgeführt):

1. `list_issued_handoffs` als normalen Zweig in `server_sync/handoffs.py` (TOOLS und
   `scoped_call`) aufnehmen, mit Tests zu Mandantentrennung, leerer Liste, Argumentfehler und
   Obergrenze 100. Den Vertrag `server-handoff-http-v1` ergänzen.
2. `threaddesk-server serve --handoff-rpc` als Schalter einführen.
3. `ExecStart` in der Unit selbst auf die Repo-CLI umstellen, mit
   `--host 172.18.0.1 --public-origin https://…:8443 --trusted-proxy 172.18.0.5 --handoff-rpc`.
   Dann das Drop-in `public.conf` entfernen. `trusted_proxy` auf die Caddy-Adresse
   `172.18.0.5/32` einengen.
4. Aus einem Git-Pin installieren statt aus einem exportierten Baum, dann `INSTALLED-COMMIT`
   gegen `git rev-parse` prüfen.
5. Den TLS-Proxy 8446 endgültig entfernen: Die Unit ist deaktiviert und das Backend falsch. Das
   Relay auf `https://…:8443` umstellen oder entfernen.

Inhalt der laufenden Datei, wortgetreu (sha256 `bb76d00e…`, keine Geheimnisse), als Beleg für die Übernahme:

```text
"""threaddesk-server serve with the opt-in handoff HTTP adapter enabled.

Adds one read-only tool, list_issued_handoffs, so a home relay can discover
issued handoffs of the authenticated user's project. It never writes.
"""
import ipaddress
import sys
from pathlib import Path

import uvicorn

from threaddesk.server_sync import handoffs
from threaddesk.server_sync.app import create_app

LIST_TOOL = "list_issued_handoffs"
_original_scoped_call = handoffs.scoped_call


def _summary(record):
    handoff = record.get("handoff") or {}
    return {
        "handoff_id": handoff.get("handoff_id"),
        "task": handoff.get("task"),
        "target_system": handoff.get("target_system"),
        "created_at": handoff.get("created_at"),
        "issued_at": record.get("issued_at"),
        "content_hash": record.get("content_hash"),
        "bound": record.get("binding") is not None,
        "remote_delivery": record.get("remote_delivery"),
    }


def scoped_call(core, project_id, tool, arguments):
    if tool != LIST_TOOL:
        return _original_scoped_call(core, project_id, tool, arguments)
    if arguments not in ({}, None):
        raise handoffs.HTTPException(400, "No arguments accepted")
    records = [
        r for r in core.store.list_issued_handoffs()
        if (r.get("handoff") or {}).get("thread_id") == project_id
    ]
    records.sort(key=lambda r: r.get("issued_at") or "", reverse=True)
    return {"ok": True, "isError": False, "result": {"items": [_summary(r) for r in records[:100]]}}


handoffs.TOOLS = handoffs.TOOLS | {LIST_TOOL}
handoffs.scoped_call = scoped_call

data_dir, host, port, public_origin, trusted_proxy = sys.argv[1:6]
ipaddress.ip_network(trusted_proxy, strict=False)
app = create_app(Path(data_dir), public_origin=public_origin, handoff_rpc=True)
uvicorn.run(app, host=host, port=int(port), workers=1, proxy_headers=True,
            forwarded_allow_ips=trusted_proxy, access_log=False, timeout_graceful_shutdown=10)
```

---

## 3. Weitere Befunde (neu)

| Nr. | Schwere | Befund | Zuordnung |
|---|---|---|---|
| N1 | A | Im `/opt/4allpass/Caddyfile` (0600 root) steht für die Agent-Authority-Route ein **64-stelliger Proxy-Token als Klartext** (`header_up`). Vermutlich gilt das auch für die Sicherungskopien im selben Ordner. Der Wert wurde nicht erfasst. | X3. Den Token als Datei oder Umgebungsvariable einbinden und die Backups prüfen. |
| N2 | B | Über das gemeinsame `env_file` erhält der **Postgres-Container auch `FOURALLPASS_SESSION_SECRET`** und die übrigen Backend-Variablen (nur Namen geprüft). | BP-SEC-01 |
| N3 | B | **ufw nennt 8443 nicht**, der Port ist aber über die Docker-Portfreigabe öffentlich erreichbar. Docker umgeht ufw. Die Firewall-Liste spiegelt die Wirklichkeit also nicht. | X2 / BP-OPS-02 |
| N4 | B | Die selbstsignierten Zertifikate für `pass.` und `tollgate.netzwerkpunkt.de` laufen am 17.11.2026 ab, die DNS-Einträge zeigen auf einen anderen Host (siehe W01). | BP-SEC-01, E1 |
| N5 | C | Im Produktionsordner des ThreadDesk-Servers liegen die Testnutzer `alt/alice`, `alt/bob` mit Token-Dateien (Dateien 0600, Ordner 0775) sowie `acceptance/` und `restore-1/`. | BP-OPS-02 |
| N6 | C | KI-Hilfezentrum: Die Runtime stammt aus Release `601de6bb`, das `WorkingDirectory` aus Release `66bf2c4a`. Das Projekt liegt außerhalb der fünf Produkte, es ist nur vermerkt. | – |
| N7 | C | Plattenbelegung **7 %** (Bauplan: 6 %). Journal 702 MB, Docker-Build-Cache 757 MB freigebbar, Runner-`_work` je 1,9 GB, Testordner zusammen ~1,6 GB. | BP-OPS-01 |
| N8 | C | `tunnel-client` v0.0.16 (mit `cloudflared`) wurde am 08.11. um 00:59 heruntergeladen, `kirabridge-tunnel-setup` liegt bereit. Es läuft kein Tunnelprozess. | BP-DEBIAN-02 |
| N9 | C | Der ssh-Alias `netcup` meldet sich als **root** an. Für Nur-Lese-Inventur genügt ein eigener Benutzer mit eingeschränktem sudo. | X2 |
| N10 | C | Ein `ubuntu:24.04`-Image (02.10.) ist ungenutzt. | BP-OPS-01 |

Bestätigt ohne Abweichung: `kirabridge.service` (systemd `--user` als `daniel`, Linger) läuft
RC41 `350d368` nur auf `127.0.0.1:8765`. Die zwei KiraBridge-Runner laufen als `github-runner`,
Version 2.338.2. `agent-authority-browser` ist nur über den Unix-Socket hinter Caddy
erreichbar. KI-Hilfezentrum bindet `172.18.0.1:8787` (ufw lässt nur Caddy zu) und
`127.0.0.1:8796`.

## 4. Testordner (nur aufgelistet)

Unter `/home/daniel` liegen **14** Ordner `kb-debian-dirktest-*` und **2** Smoke-/Verify-Ordner,
wie im Bauplan angegeben. Acht Namen enthalten `%` bzw. `%$`, also eine fehlerhafte Expansion.
Die vollständige Liste mit Größen steht in `ops/netcup.json` → `test_folders`. Sichern und
Entfernen ist ein eigener, freizugebender Schritt von BP-OPS-01. Danach muss die Liste geleert
werden, sonst meldet das Prüfskript die Abweichung.

## 5. Vorbereitung BP-TRUTH-01

`ops/netcup.json` ist die Serverquelle für das Ist-Stand-Register. Vorschlag für das Feld
`server` je `STATUS.json`:

| Produkt | `server.unit` | `server.pin` | `server.route` |
|---|---|---|---|
| KiraBridge | `kirabridge.service` (user `daniel`) | `0.8.0rc41` / `350d36854fc9` | keine (nur `127.0.0.1:8765`) |
| ThreadDesk Server | `threaddesk-server.service` | Paket `2a703696` (= `main` `1f993b1` in `src`) **plus** `serve_handoff.py` `bb76d00e…` | `https://v2202608211799501333.goodsrv.de:8443` |
| 4AllPass | Compose `4allpass` | Quelle `6da2fbc1`, Backend `sha256:d8a510bd…` (19.08.) | vHost vorhanden, DNS zeigt woanders hin |
| TollGate | statisch `/opt/4allpass/sites/tollgate` | – | vHost vorhanden, DNS zeigt woanders hin |
| Agent Authority | `agent-authority-browser.service` | Release `account-4da5fa818b7b590711d5` | `https://v2202608211799501333.goodsrv.de/agent-authority/` |

Das Prüfskript kann später je Produkt nur den `server`-Teil gegen `STATUS.json` abgleichen. Dafür
ist kein zweiter Sammelweg nötig. Aufruf: `python3 scripts/ops_inventory_check.py`. Offline mit
gesicherter Rohausgabe: `--raw <datei>`. Den beobachteten Stand als JSON liefert
`--dump-observed`.
