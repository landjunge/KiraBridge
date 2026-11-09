#!/usr/bin/env python3
"""Read-only drift check: compare ``ops/netcup.json`` with the live VServer.

The remote side runs only listing commands (systemctl list/show, ss, docker
ps/inspect/images, sha256sum, ls, df, readlink, sed on the Caddyfile). It never
restarts, writes, deletes or pulls anything. Lines of the Caddyfile that can
carry credentials (``header_up``, ``basic_auth``, ``Authorization``) are
dropped on the server before the text leaves it; only route targets are parsed.

Exit codes: 0 = no deviation, 1 = deviation(s), 2 = collection/usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

FORMAT = "kirabridge.ops-inventory.v1"
DEFAULT_INVENTORY = Path(__file__).resolve().parents[1] / "ops" / "netcup.json"
SECTION = "@@@"

# Positional args: $1 = service user, $2 = caddyfile, $3.. = files to hash.
REMOTE_SCRIPT = r"""
set -u
svc_user="$1"; caddyfile="$2"; shift 2
uid="$(id -u "$svc_user")"
section() { printf '\n@@@%s\n' "$1"; }
section system_units
systemctl list-units --type=service --all --no-legend --plain --no-pager
section system_unit_files
systemctl list-unit-files --type=service --no-legend --no-pager
section user_units
sudo -n -u "$svc_user" XDG_RUNTIME_DIR="/run/user/$uid" \
  systemctl --user list-units --type=service --all --no-legend --plain --no-pager
section user_unit_files
sudo -n -u "$svc_user" XDG_RUNTIME_DIR="/run/user/$uid" \
  systemctl --user list-unit-files --type=service --no-legend --no-pager
section tcp_listen
ss -tlnpH
section containers
fmt='{{.Name}}|{{.Image}}|{{.Config.Image}}|{{.State.Status}}|'
fmt="$fmt"'{{index .Config.Labels "com.docker.compose.service"}}'
for c in $(docker ps -a --format '{{.Names}}'); do docker inspect "$c" --format "$fmt"; done
section images
docker images --no-trunc --format '{{.ID}}|{{.CreatedAt}}'
section files
for f in "$@"; do
  if [ -e "$f" ]; then sha256sum "$f"; else printf 'MISSING  %s\n' "$f"; fi
done
section caddyfile
sed -E '/header_up|basic_?auth|[Aa]uthorization/Id' "$caddyfile"
section test_folders
ls -1d /home/"$svc_user"/kb-debian-dirktest-* /home/"$svc_user"/kirabridge-smoke-* \
  /home/"$svc_user"/kirabridge-verify-* 2>/dev/null
section disk
df -P /
section runner_bins
for r in /opt/actions-runner*; do printf '%s %s\n' "$r" "$(readlink -f "$r/bin")"; done
"""

FORBIDDEN_REMOTE = (
    r"\bsystemctl\b[^\n]*\b(start|stop|restart|reload|enable|disable|kill|mask|daemon-reload)\b",
    r"\bdocker\s+(run|exec|pull|push|rm|rmi|stop|start|restart|kill|compose|build|prune|system)\b",
    r"(^|[\s;|&])(rm|rmdir|mv|cp|tee|chmod|chown|truncate|mkdir|touch|apt|apt-get|dpkg|pip|"
    r"kill|pkill|reboot|shutdown|curl|wget)\b",
    r"\bsed\s+-i",
    r"(?<![0-9])>(?!\s*/dev/null)",
)


def remote_script_is_read_only(script: str = REMOTE_SCRIPT) -> list[str]:
    """Return forbidden patterns found in the remote script (empty = read-only)."""
    # Quoted strings (docker format templates, printf formats) are data.
    code = re.sub(r"'[^']*'", "''", script)
    code = code.replace("2>/dev/null", "")
    return [pattern for pattern in FORBIDDEN_REMOTE if re.search(pattern, code, re.M)]


# ---------------------------------------------------------------- parsing


def split_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = None
    for raw in text.splitlines():
        if raw.startswith(SECTION):
            current = raw[len(SECTION) :].strip()
            sections[current] = []
        elif current is not None and raw.strip():
            sections[current].append(raw.rstrip())
    return sections


def parse_units(lines: list[str]) -> dict[str, dict[str, str]]:
    units = {}
    for line in lines:
        parts = line.split(None, 4)
        if len(parts) >= 4 and parts[0].endswith(".service"):
            units[parts[0]] = {"load": parts[1], "active": parts[2], "sub": parts[3]}
    return units


def parse_unit_files(lines: list[str]) -> dict[str, str]:
    result = {}
    for line in lines:
        parts = line.split()
        if len(parts) >= 2 and parts[0].endswith(".service"):
            result[parts[0]] = parts[1]
    return result


def parse_listeners(lines: list[str]) -> dict[str, str]:
    result = {}
    for line in lines:
        parts = line.split()
        if len(parts) < 4:
            continue
        local = parts[3]
        match = re.search(r'users:\(\("([^"]+)"', line)
        result[local] = match.group(1) if match else "?"
    return result


def parse_containers(lines: list[str]) -> dict[str, dict[str, str]]:
    result = {}
    for line in lines:
        parts = line.split("|")
        if len(parts) >= 5:
            result[parts[0].lstrip("/")] = {
                "image_id": parts[1],
                "image": parts[2],
                "state": parts[3],
                "compose_service": parts[4],
            }
    return result


def parse_images(lines: list[str]) -> dict[str, str]:
    return dict(line.split("|", 1) for line in lines if "|" in line)


def parse_files(lines: list[str]) -> dict[str, str]:
    result = {}
    for line in lines:
        digest, _, path = line.partition("  ")
        result[path.strip()] = "MISSING" if digest == "MISSING" else digest.strip()
    return result


def parse_caddy_routes(text: str) -> list[dict]:
    """Extract site label -> ordered upstream targets. Ignores snippets/global."""
    routes: list[dict] = []
    depth = 0
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        if depth == 0 and line.endswith("{"):
            label = line[:-1].strip()
            if label and not label.startswith("("):
                current = {"site": label, "upstreams": []}
                routes.append(current)
            else:
                current = None
        elif current is not None and tokens:
            target = None
            if tokens[0] == "reverse_proxy" and len(tokens) > 1 and tokens[1] != "{":
                target = tokens[1]
            elif tokens[0] == "root" and len(tokens) > 2:
                target = "file:" + tokens[2]
            elif tokens[0] == "redir" and len(tokens) > 1:
                target = "redir:" + tokens[1]
            if target and target not in current["upstreams"]:
                current["upstreams"].append(target)
        depth += line.count("{") - line.count("}")
        if depth == 0:
            current = None
    return routes


def parse_disk(lines: list[str]) -> int | None:
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 6 and parts[5] == "/":
            return int(parts[4].rstrip("%"))
    return None


def parse_observed(text: str) -> dict:
    s = split_sections(text)
    return {
        "system_units": parse_units(s.get("system_units", [])),
        "system_unit_files": parse_unit_files(s.get("system_unit_files", [])),
        "user_units": parse_units(s.get("user_units", [])),
        "user_unit_files": parse_unit_files(s.get("user_unit_files", [])),
        "tcp_listeners": parse_listeners(s.get("tcp_listen", [])),
        "containers": parse_containers(s.get("containers", [])),
        "images": parse_images(s.get("images", [])),
        "files": parse_files(s.get("files", [])),
        "caddy_routes": parse_caddy_routes("\n".join(s.get("caddyfile", []))),
        "test_folders": sorted(Path(p).name for p in s.get("test_folders", [])),
        "disk_root_use_percent": parse_disk(s.get("disk", [])),
        "runner_bins": dict(line.split(" ", 1) for line in s.get("runner_bins", []) if " " in line),
    }


# ------------------------------------------------------------- comparison


def _unit_deviations(kind, expected_units, observed_units, observed_files):
    out = []
    listed = set()
    for entry in expected_units:
        unit = entry["unit"]
        listed.add(unit)
        live = observed_units.get(unit)
        want_active = entry.get("active_state")
        if live is None:
            if want_active not in (None, "inactive"):
                out.append(f"{kind}: {unit} fehlt (erwartet {want_active})")
        else:
            for key, field in (("active", "active_state"), ("sub", "sub_state")):
                want = entry.get(field)
                if want is not None and live[key] != want:
                    out.append(f"{kind}: {unit} {field} {live[key]} != erwartet {want}")
        want_file = entry.get("unit_file_state")
        got_file = observed_files.get(unit)
        if want_file is not None and got_file is not None and got_file != want_file:
            out.append(f"{kind}: {unit} unit_file_state {got_file} != erwartet {want_file}")
    for unit, live in sorted(observed_units.items()):
        if live["sub"] == "running" and unit not in listed:
            out.append(f"{kind}: unerwarteter laufender Dienst {unit}")
    return out


def _is_ephemeral_loopback(addr: str, min_port: int) -> bool:
    host, _, port = addr.rpartition(":")
    return host in {"127.0.0.1", "[::1]"} and port.isdigit() and int(port) >= min_port


def compare(inventory: dict, observed: dict) -> list[str]:
    """Return human-readable deviations; empty list means inventory matches."""
    dev: list[str] = []
    dev += _unit_deviations(
        "systemd",
        inventory.get("systemd_system", []),
        observed["system_units"],
        observed["system_unit_files"],
    )
    dev += _unit_deviations(
        "systemd --user",
        inventory.get("systemd_user", []),
        observed["user_units"],
        observed["user_unit_files"],
    )

    want_listen = {f"{e['address']}:{e['port']}": e["process"] for e in inventory["listeners"]}
    got_listen = observed["tcp_listeners"]
    for addr in sorted(set(want_listen) - set(got_listen)):
        dev.append(f"port: {addr} lauscht nicht (erwartet {want_listen[addr]})")
    ignore_from = inventory.get("listener_ignore_loopback_from_port")
    for addr in sorted(set(got_listen) - set(want_listen)):
        if ignore_from is not None and _is_ephemeral_loopback(addr, ignore_from):
            continue
        dev.append(f"port: unerwartet offen {addr} ({got_listen[addr]})")
    for addr in sorted(set(want_listen) & set(got_listen)):
        if want_listen[addr] != got_listen[addr]:
            dev.append(f"port: {addr} Prozess {got_listen[addr]} != erwartet {want_listen[addr]}")

    want_c = {c["name"]: c for c in inventory["docker"]["containers"]}
    got_c = observed["containers"]
    for name in sorted(set(want_c) - set(got_c)):
        dev.append(f"docker: Container {name} fehlt")
    for name in sorted(set(got_c) - set(want_c)):
        dev.append(f"docker: unerwarteter Container {name}")
    for name in sorted(set(want_c) & set(got_c)):
        if got_c[name]["image_id"] != want_c[name]["image_id"]:
            dev.append(
                f"docker: {name} Image {got_c[name]['image_id'][:19]} "
                f"!= erwartet {want_c[name]['image_id'][:19]}"
            )
        if got_c[name]["state"] != want_c[name]["state"]:
            dev.append(f"docker: {name} Status {got_c[name]['state']} != {want_c[name]['state']}")

    for entry in inventory.get("tracked_files", []):
        got = observed["files"].get(entry["path"])
        if got is None:
            dev.append(f"datei: {entry['path']} nicht geprüft")
        elif got != entry["sha256"]:
            shown = got if got == "MISSING" else got[:12]
            dev.append(f"datei: {entry['path']} sha256 {shown} != {entry['sha256'][:12]}")

    want_routes = {r["site"]: list(r["upstreams"]) for r in inventory["caddy"]["routes"]}
    got_routes = {r["site"]: r["upstreams"] for r in observed["caddy_routes"]}
    for site in sorted(set(want_routes) - set(got_routes)):
        dev.append(f"caddy: Route {site} fehlt")
    for site in sorted(set(got_routes) - set(want_routes)):
        dev.append(f"caddy: unerwartete Route {site} -> {got_routes[site]}")
    for site in sorted(set(want_routes) & set(got_routes)):
        if want_routes[site] != got_routes[site]:
            dev.append(f"caddy: {site} -> {got_routes[site]} != erwartet {want_routes[site]}")

    want_tf = sorted(t["name"] for t in inventory.get("test_folders", []))
    got_tf = observed["test_folders"]
    for name in sorted(set(want_tf) - set(got_tf)):
        dev.append(f"testordner: {name} nicht mehr vorhanden")
    for name in sorted(set(got_tf) - set(want_tf)):
        dev.append(f"testordner: neu {name}")

    disk = inventory.get("disk", {})
    limit = disk.get("root_alert_percent")
    used = observed["disk_root_use_percent"]
    if used is None:
        dev.append("platte: Belegung von / nicht lesbar")
    elif limit is not None and used >= limit:
        dev.append(f"platte: / zu {used}% belegt (Grenze {limit}%)")

    for runner in inventory.get("runners", []):
        got = observed["runner_bins"].get(runner["path"])
        if got != runner["bin"]:
            dev.append(f"runner: {runner['path']} bin {got} != erwartet {runner['bin']}")
    return dev


# ------------------------------------------------------------- collection


def collect(inventory: dict) -> str:
    host = inventory["host"]
    files = [entry["path"] for entry in inventory.get("tracked_files", [])]
    args = [host["service_user"], inventory["caddy"]["config_path"], *files]
    remote = "bash -s -- " + " ".join(shlex.quote(a) for a in args)
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host["ssh_alias"], remote],
        input=REMOTE_SCRIPT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0 or SECTION not in proc.stdout:
        raise RuntimeError(f"ssh fehlgeschlagen (rc={proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--raw", type=Path, help="vorher gesicherte Rohausgabe statt ssh")
    parser.add_argument(
        "--dump-observed", action="store_true", help="beobachteten Stand als JSON ausgeben"
    )
    args = parser.parse_args(argv)
    try:
        inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
        if inventory.get("format") != FORMAT:
            raise ValueError(f"unbekanntes Format {inventory.get('format')!r}")
        raw = args.raw.read_text(encoding="utf-8") if args.raw else collect(inventory)
        observed = parse_observed(raw)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2
    if args.dump_observed:
        print(json.dumps(observed, indent=2, sort_keys=True))
    deviations = compare(inventory, observed)
    for line in deviations:
        print(f"ABWEICHUNG {line}")
    print(
        f"{len(deviations)} Abweichung(en) gegen {args.inventory.name} "
        f"(observed_at {inventory.get('observed_at')})"
    )
    return 1 if deviations else 0


if __name__ == "__main__":
    raise SystemExit(main())
