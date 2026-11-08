"""Comparison logic of scripts/ops_inventory_check.py without ssh."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ops_inventory_check", ROOT / "scripts/ops_inventory_check.py"
)
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)

IMG_A = "sha256:" + "a" * 64
IMG_B = "sha256:" + "b" * 64
HASH = "c" * 64

RAW = f"""
@@@system_units
threaddesk-server.service loaded active running ThreadDesk Server and Sync loopback
threaddesk-server-tls.service loaded inactive dead ThreadDesk Server loopback TLS proxy
cron.service loaded active running Regular background program processing daemon
@@@system_unit_files
threaddesk-server.service enabled enabled
threaddesk-server-tls.service disabled enabled
cron.service enabled enabled
@@@user_units
kirabridge.service loaded active running KiraBridge private MCP bridge
@@@user_unit_files
kirabridge.service enabled enabled
@@@tcp_listen
LISTEN 0 2048 172.18.0.1:8766 0.0.0.0:* users:(("python",pid=1,fd=7))
LISTEN 0 4096 [::]:8443 [::]:* users:(("docker-proxy",pid=2,fd=8))
LISTEN 0 2048 127.0.0.1:54787 0.0.0.0:* users:(("python3",pid=3,fd=10))
@@@containers
/4allpass-backend-1|{IMG_A}|4allpass-backend|running|backend
@@@images
{IMG_A}|2026-08-19 04:35:36 +0200 CEST
@@@files
{HASH}  /srv/serve_handoff.py
MISSING  /srv/gone.py
@@@caddyfile
{{
\tauto_https off
}}
(headers) {{
\theader {{
\t\t-Server
\t}}
}}
example.test:8443 {{
\thandle @manifest {{
\t\treverse_proxy 172.18.0.1:8766
\t}}
\thandle /agent/* {{
\t\treverse_proxy unix//sites/browser.sock {{
\t\t}}
\t}}
\thandle {{
\t\tredir https://example.org/ 302
\t}}
}}
@@@test_folders
/home/daniel/kb-debian-dirktest-run01
/home/daniel/kb-debian-dirktest-20261107-040%dirk
@@@disk
Filesystem 1024-blocks Used Available Capacity Mounted on
/dev/vda4 329000000 20000000 296000000 7% /
@@@runner_bins
/opt/actions-runner /opt/actions-runner/bin.2.338.2
"""

INVENTORY = {
    "format": check.FORMAT,
    "observed_at": "2026-11-08T16:59:45Z",
    "host": {"ssh_alias": "netcup", "service_user": "daniel"},
    "systemd_system": [
        {
            "unit": "threaddesk-server.service",
            "active_state": "active",
            "sub_state": "running",
            "unit_file_state": "enabled",
        },
        {
            "unit": "threaddesk-server-tls.service",
            "active_state": "inactive",
            "sub_state": "dead",
            "unit_file_state": "disabled",
        },
        {"unit": "cron.service", "active_state": "active", "sub_state": "running"},
    ],
    "systemd_user": [
        {"unit": "kirabridge.service", "active_state": "active", "sub_state": "running"}
    ],
    "listener_ignore_loopback_from_port": 32768,
    "listeners": [
        {"address": "172.18.0.1", "port": 8766, "process": "python"},
        {"address": "[::]", "port": 8443, "process": "docker-proxy"},
    ],
    "docker": {
        "containers": [{"name": "4allpass-backend-1", "image_id": IMG_A, "state": "running"}]
    },
    "tracked_files": [
        {"path": "/srv/serve_handoff.py", "sha256": HASH},
        {"path": "/srv/gone.py", "sha256": "MISSING"},
    ],
    "caddy": {
        "config_path": "/opt/4allpass/Caddyfile",
        "routes": [
            {
                "site": "example.test:8443",
                "upstreams": [
                    "172.18.0.1:8766",
                    "unix//sites/browser.sock",
                    "redir:https://example.org/",
                ],
            }
        ],
    },
    "test_folders": [
        {"name": "kb-debian-dirktest-20261107-040%dirk"},
        {"name": "kb-debian-dirktest-run01"},
    ],
    "disk": {"root_alert_percent": 80},
    "runners": [{"path": "/opt/actions-runner", "bin": "/opt/actions-runner/bin.2.338.2"}],
}


@pytest.fixture
def observed():
    return check.parse_observed(RAW)


def test_matching_inventory_has_no_deviation(observed):
    assert check.compare(INVENTORY, observed) == []


def test_caddy_parser_skips_global_and_snippets(observed):
    assert observed["caddy_routes"] == INVENTORY["caddy"]["routes"]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda inv, obs: obs["system_units"]["threaddesk-server.service"].update(
                active="failed", sub="failed"
            ),
            "threaddesk-server.service active_state failed",
        ),
        (
            lambda inv, obs: obs["system_units"].update(
                {"rogue.service": {"load": "loaded", "active": "active", "sub": "running"}}
            ),
            "unerwarteter laufender Dienst rogue.service",
        ),
        (
            lambda inv, obs: obs["system_unit_files"].update(
                {"threaddesk-server-tls.service": "enabled"}
            ),
            "threaddesk-server-tls.service unit_file_state enabled",
        ),
        (
            lambda inv, obs: obs["tcp_listeners"].update({"127.0.0.1:8446": "python"}),
            "unerwartet offen 127.0.0.1:8446",
        ),
        (
            lambda inv, obs: obs["tcp_listeners"].pop("172.18.0.1:8766"),
            "172.18.0.1:8766 lauscht nicht",
        ),
        (
            lambda inv, obs: obs["containers"]["4allpass-backend-1"].update(image_id=IMG_B),
            "4allpass-backend-1 Image",
        ),
        (
            lambda inv, obs: obs["files"].update({"/srv/serve_handoff.py": "d" * 64}),
            "/srv/serve_handoff.py sha256",
        ),
        (
            lambda inv, obs: obs["caddy_routes"].append({"site": "new.test", "upstreams": []}),
            "unerwartete Route new.test",
        ),
        (
            lambda inv, obs: obs["test_folders"].remove("kb-debian-dirktest-run01"),
            "testordner: kb-debian-dirktest-run01 nicht mehr vorhanden",
        ),
        (lambda inv, obs: obs.update(disk_root_use_percent=91), "platte: / zu 91%"),
        (
            lambda inv, obs: obs["runner_bins"].update({"/opt/actions-runner": "/x"}),
            "runner: /opt/actions-runner",
        ),
        (
            lambda inv, obs: inv.pop("listener_ignore_loopback_from_port"),
            "unerwartet offen 127.0.0.1:54787",
        ),
    ],
)
def test_each_drift_is_reported(observed, mutate, expected):
    inventory = copy.deepcopy(INVENTORY)
    mutate(inventory, observed)
    deviations = check.compare(inventory, observed)
    assert any(expected in line for line in deviations), deviations


def test_main_exit_codes_from_raw_file(tmp_path, capsys):
    inv = tmp_path / "inv.json"
    raw = tmp_path / "raw.txt"
    inv.write_text(json.dumps(INVENTORY), encoding="utf-8")
    raw.write_text(RAW, encoding="utf-8")
    assert check.main(["--inventory", str(inv), "--raw", str(raw)]) == 0
    drifted = copy.deepcopy(INVENTORY)
    drifted["docker"]["containers"][0]["image_id"] = IMG_B
    inv.write_text(json.dumps(drifted), encoding="utf-8")
    assert check.main(["--inventory", str(inv), "--raw", str(raw)]) == 1
    assert "ABWEICHUNG docker" in capsys.readouterr().out
    inv.write_text(json.dumps({"format": "other"}), encoding="utf-8")
    assert check.main(["--inventory", str(inv), "--raw", str(raw)]) == 2


def test_remote_script_stays_read_only():
    assert check.remote_script_is_read_only() == []
    assert check.remote_script_is_read_only("systemctl restart x\n")
    assert check.remote_script_is_read_only("docker pull caddy\n")
    assert check.remote_script_is_read_only("rm -rf /home/daniel/kb-debian-dirktest-x\n")
    assert check.remote_script_is_read_only("echo x > /etc/file\n")


def test_repository_inventory_is_well_formed():
    inventory = json.loads((ROOT / "ops/netcup.json").read_text(encoding="utf-8"))
    assert inventory["format"] == check.FORMAT
    assert inventory["observed_at"]
    for key in ("systemd_system", "systemd_user", "listeners", "tracked_files", "test_folders"):
        assert inventory[key], key
    text = json.dumps(inventory).lower()
    for marker in ("password=", "secret=", "token=", "begin private key"):
        assert marker not in text
