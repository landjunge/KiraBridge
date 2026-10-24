"""Activate the prepared private Events profile under a checked idle SQLite guard.

No remote tunnel creation, credentials replacement, global rights, or Bridge restart.
Rollback uses the same idle guard and only this known native runtime / sender label.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import sqlite3
import subprocess
import time
from pathlib import Path

from kirabridge.bridge_core.config import load_config

LABEL = "com.kirabridge.chat-events"
BINARY = str(Path.home() / ".local/bin/tunnel-client")
BASE = Path.home() / ".config/kirabridge"
PROFILE = BASE / "tunnel/kirabridge.yaml"
PREPARED = BASE / "chat-events-prepared-20261019"
PLIST = Path.home() / f"Library/LaunchAgents/{LABEL}.plist"
DOMAIN = f"gui/{os.getuid()}"
TABLES = [
    "tasks",
    "events",
    "approvals",
    "conversations",
    "messages",
    "message_jobs",
    "message_events",
    "handoff_bindings",
    "message_completion_routes",
    "completion_routes",
    "completion_notices",
]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def private_write(path, raw):
    tmp = path.with_name(path.name + ".new")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def run(argv, root, name, *, check=True, timeout=25, env=None):
    result = subprocess.run(argv, capture_output=True, timeout=timeout, env=env)
    private_write(root / (name + ".stdout"), result.stdout)
    private_write(root / (name + ".stderr"), result.stderr)
    if check and result.returncode:
        raise RuntimeError(name + "_failed; inspect private logs")
    return result


def status(root, name):
    return json.loads(
        run([BINARY, "runtimes", "status", "kirabridge", "--json"], root, name).stdout
    )


def fingerprints(db):
    return {
        table: sha(
            json.dumps(
                db.execute("SELECT * FROM " + table + " ORDER BY rowid").fetchall(),
                separators=(",", ":"),
            ).encode()
        )
        for table in TABLES
    }


def idle(db):
    tasks = db.execute(
        "SELECT count(*) FROM tasks WHERE state IN ('created','queued','accepted','running')"
    ).fetchone()[0]
    jobs = db.execute(
        "SELECT count(*) FROM message_jobs WHERE state IN ('queued','running')"
    ).fetchone()[0]
    if tasks or jobs:
        raise RuntimeError(
            f"busy: {tasks} active tasks, {jobs} active receiver jobs; no activation"
        )
    return {
        "active_tasks": tasks,
        "active_receiver_jobs": jobs,
        "guard": "BEGIN IMMEDIATE; no new task/message writes during switch",
    }


def connect(profile, root, name):
    control = profile["control_plane"]
    key_ref = control["api_key"]
    if not key_ref.startswith(("file:", "env:")):
        raise RuntimeError("Existing runtime key must remain a reference")
    command = next(c["command"] for c in profile["mcp"]["commands"] if c["channel"] == "main")
    args = [
        BINARY,
        "runtimes",
        "connect",
        "--alias",
        "kirabridge",
        "--tunnel-id",
        control["tunnel_id"],
        "--runtime-api-key",
        key_ref,
        "--profile",
        "kirabridge",
        "--profile-dir",
        str(PROFILE.parent),
        "--mcp-command",
        command,
        "--json",
    ]
    if control.get("base_url"):
        args += ["--control-plane-base-url", control["base_url"]]
    run(args, root, name, env={**os.environ, "MCP_STDIO_SEND_INITIALIZED_NOTIFICATION": "true"})


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()
    root = args.run_dir.expanduser().absolute()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    config = load_config(str(BASE / "config.toml"))
    original = PROFILE.read_bytes()
    before = status(root, "runtime-before")
    if not before.get("process_running") or before["process"]["config_path"] != str(PROFILE):
        raise RuntimeError("Expected known running native KiraBridge runtime")
    old_pid = before["process"]["pid"]
    process = subprocess.run(
        ["ps", "-p", str(old_pid), "-o", "command="], capture_output=True, text=True, check=True
    ).stdout
    if "tunnel-client" not in process or str(PROFILE.parent) not in process:
        raise RuntimeError("Native PID identity mismatch")
    prep = json.loads((PREPARED / "preparation.json").read_text())
    if sha(original) != prep["original_profile_sha256"]:
        raise RuntimeError("Profile changed since preparation; preserve and review first")
    candidate = (PREPARED / "tunnel-profile.candidate.json").read_bytes()
    target = json.loads(candidate)
    old = json.loads(original)
    if {k: v for k, v in target.items() if k != "mcp"} != {
        k: v for k, v in old.items() if k != "mcp"
    }:
        raise RuntimeError("Unexpected non-MCP profile changes")
    if PLIST.exists():
        raise RuntimeError("Sender LaunchAgent already exists; preserve it")
    plist_raw = (PREPARED / "com.kirabridge.chat-events.candidate.plist").read_bytes()
    sender_args = plistlib.loads(plist_raw)["ProgramArguments"]
    if "check_protocol.py" in " ".join(sender_args) or "--sender-only" not in sender_args:
        raise RuntimeError("Production sender required")
    private_write(root / "tunnel-profile.before.json", original)
    private_write(root / "config.before.toml", (BASE / "config.toml").read_bytes())
    report = {
        "implemented": True,
        "activated": False,
        "host_recognized": False,
        "subscribed": False,
        "webhook_delivered": False,
        "chat_processed": False,
        "old_native_pid": old_pid,
        "started": time.time(),
        "backup": str(root),
    }
    reconnect = f"""Vor der Umschaltung: Der bestehende Chat bleibt bestehen.
Der Tunnel kann kurz getrennt sein.
Wiederverbinden: tunnel-client runtimes status kirabridge --json
Bei nicht laufender Runtime: /Users/landjunge/KiraBridge/.venv/bin/python {root}/rollback.py
ChatGPT: https://chatgpt.com/plugins → KiraBridge → Refresh (bzw. Rescan MCP server).
Im ursprünglichen Chat Work/Cloud und KiraBridge beibehalten.
Keinen Ersatzchat als Nachweis verwenden.
Keine neue App, kein neuer Tunnel, kein Schlüsselwechsel erforderlich.
Privates Profilbackup: {root}/tunnel-profile.before.json
"""
    private_write(root / "RECONNECT.txt", reconnect.encode())
    print(reconnect, flush=True)
    rollback_source = Path(__file__).with_name("rollback_chat_events.py").read_bytes()
    private_write(root / "rollback.py", rollback_source)
    db = sqlite3.connect(config.state_path / "bridge.sqlite3", isolation_level=None, timeout=5)
    db.execute("BEGIN IMMEDIATE")
    switched = False
    try:
        report["idle"] = idle(db)
        print(
            "Leerlauf unter Schreibsperre belegt: 0 Tasks, 0 Empfängerjobs. Sichere Datenstand.",
            flush=True,
        )
        report["before_tables"] = fingerprints(db)
        report["config_before_sha256"] = sha((BASE / "config.toml").read_bytes())
        audit = db.execute("SELECT * FROM audit ORDER BY seq").fetchall()
        report["audit_prefix_rows"] = len(audit)
        report["audit_prefix_sha256"] = sha(json.dumps(audit, separators=(",", ":")).encode())
        with sqlite3.connect(
            f"file:{config.state_path / 'bridge.sqlite3'}?mode=ro", uri=True
        ) as reader:
            with sqlite3.connect(root / "bridge-before.sqlite3") as backup:
                reader.backup(backup)
        run(
            [BINARY, "runtimes", "stop", "kirabridge", "--json"],
            root,
            "stop-own-native",
            timeout=15,
        )
        switched = True
        private_write(PROFILE, candidate)
        print(
            "Eigene native Tunnel-Runtime gestoppt. Starte vorhandenen Tunnel mit Events-Fassade.",
            flush=True,
        )
        connect(target, root, "connect-events")
        # Native connect regenerates its profile; retain every pre-reviewed field for future starts.
        private_write(PROFILE, candidate)
        report["after_tables"] = fingerprints(db)
        if report["after_tables"] != report["before_tables"]:
            raise RuntimeError("Historical data changed under guard")
        report["profile_after_sha256"] = sha(PROFILE.read_bytes())
        report["profile_before_sha256"] = sha(original)
        report["config_unchanged"] = report["config_before_sha256"] == sha(
            (BASE / "config.toml").read_bytes()
        )
        report["preserved_tables"] = list(TABLES)
        prefix = db.execute("SELECT * FROM audit ORDER BY seq LIMIT ?", (len(audit),)).fetchall()
        report["audit_prefix_unchanged"] = (
            sha(json.dumps(prefix, separators=(",", ":")).encode()) == report["audit_prefix_sha256"]
        )
        if not report["config_unchanged"] or not report["audit_prefix_unchanged"]:
            raise RuntimeError("Preservation check failed")
    except BaseException:
        private_write(root / "activation-interrupted.json", json.dumps(report, indent=2).encode())
        if switched:
            print(
                "Umschaltfehler; Rückrollskript liegt bereit. "
                "Keine Bestandsdaten werden verworfen.",
                flush=True,
            )
        raise
    finally:
        db.rollback()
        db.close()
    private_write(PLIST, plist_raw)
    run(["launchctl", "bootstrap", DOMAIN, str(PLIST)], root, "bootstrap-sender")
    after = status(root, "runtime-after")
    report["new_native_pid"] = after.get("process", {}).get("pid")
    report["tunnel_healthy"] = after.get("healthy")
    report["tunnel_ready"] = after.get("ready")
    report["activated"] = bool(
        after.get("process_running") and after.get("healthy") and after.get("ready")
    )
    report["sender_launchagent"] = str(PLIST)
    report["completed_at"] = time.time()
    private_write(root / "activation.json", json.dumps(report, indent=2).encode())
    print(
        json.dumps(
            {
                k: report[k]
                for k in [
                    "activated",
                    "tunnel_healthy",
                    "tunnel_ready",
                    "old_native_pid",
                    "new_native_pid",
                    "config_unchanged",
                    "host_recognized",
                    "subscribed",
                    "webhook_delivered",
                    "chat_processed",
                ]
            },
            indent=2,
        ),
        flush=True,
    )
    if not report["activated"]:
        raise RuntimeError("Activation readiness failed; use recorded rollback under idle guard")


if __name__ == "__main__":
    main()
