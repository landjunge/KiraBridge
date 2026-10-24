"""Private activation backup copy: restore only the tunnel route, never old task data."""

import json
import os
import sqlite3
import subprocess
from pathlib import Path

from kirabridge.bridge_core.config import load_config


def main():
    root = Path(__file__).resolve().parent
    base = Path.home() / ".config/kirabridge"
    profile = base / "tunnel/kirabridge.yaml"
    original = (root / "tunnel-profile.before.json").read_bytes()
    old = json.loads(original)
    config = load_config(str(base / "config.toml"))
    binary = str(Path.home() / ".local/bin/tunnel-client")
    db = sqlite3.connect(config.state_path / "bridge.sqlite3", isolation_level=None, timeout=5)
    db.execute("BEGIN IMMEDIATE")
    try:
        busy = db.execute(
            "SELECT count(*) FROM tasks WHERE state IN ('created','queued','accepted','running')"
        ).fetchone()[0]
        busy += db.execute(
            "SELECT count(*) FROM message_jobs WHERE state IN ('queued','running')"
        ).fetchone()[0]
        if busy:
            raise RuntimeError("Busy; rollback refused without stopping any job")
        label = f"gui/{os.getuid()}/com.kirabridge.chat-events"
        loaded = subprocess.run(["launchctl", "print", label], capture_output=True).returncode == 0
        plist = Path.home() / "Library/LaunchAgents/com.kirabridge.chat-events.plist"
        expected = base / "chat-events-prepared-20261019/com.kirabridge.chat-events.candidate.plist"
        if loaded:
            if not plist.exists() or plist.read_bytes() != expected.read_bytes():
                raise RuntimeError(
                    "Sender definition changed; preserve and inspect before rollback"
                )
            subprocess.run(
                ["launchctl", "bootout", label], capture_output=True, check=True, timeout=10
            )
        if plist.exists():
            if plist.read_bytes() != expected.read_bytes():
                raise RuntimeError("Sender file changed; preserve before rollback")
            os.replace(plist, root / "sender.disabled-after-rollback.plist")
        subprocess.run(
            [binary, "runtimes", "stop", "kirabridge", "--json"], capture_output=True, timeout=15
        )
        command = next(c["command"] for c in old["mcp"]["commands"] if c["channel"] == "main")
        control = old["control_plane"]
        key = control["api_key"]
        if not key.startswith(("file:", "env:")):
            raise RuntimeError("Private key reference required")
        result = subprocess.run(
            [
                binary,
                "runtimes",
                "connect",
                "--alias",
                "kirabridge",
                "--tunnel-id",
                control["tunnel_id"],
                "--runtime-api-key",
                key,
                "--profile",
                "kirabridge",
                "--profile-dir",
                str(profile.parent),
                "--mcp-command",
                command,
                "--json",
            ],
            capture_output=True,
            timeout=25,
            env={**os.environ, "MCP_STDIO_SEND_INITIALIZED_NOTIFICATION": "true"},
        )
        (root / "rollback-connect.stdout").write_bytes(result.stdout)
        (root / "rollback-connect.stderr").write_bytes(result.stderr)
        if result.returncode:
            raise RuntimeError("Reconnect failed; inspect private rollback logs")
        temporary = profile.with_name(profile.name + ".rollback-new")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(original)
        os.replace(temporary, profile)
        # Keep event journal and activation files; never overwrite the live task database.
        print("Original tunnel route restored under idle guard; Bridge and task data preserved.")
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    os.umask(0o077)
    main()
