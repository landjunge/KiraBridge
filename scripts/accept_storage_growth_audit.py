"""Reusable, read-only storage/data-growth audit (issue raised by Kira/ChatGPT
2026-11-27, message 25: sizes of every relevant directory/DB/log/archive/
release/backup/temp location, causes of unnecessary growth, diagnostics and
completion-notice counts).

Pure reporting: this script never deletes, moves, or compacts anything. Any
cleanup decision stays with the operator ("vor Datenlöschung Rücksprache").
Safe to re-run any time to see whether growth is still happening or was
actually addressed.

Usage: python3 scripts/accept_storage_growth_audit.py --output <new-dir>
"""

import argparse
import json
import sqlite3
import subprocess
from pathlib import Path

HOME = Path.home()

DIRECTORIES = {
    "kirabridge_data": HOME / ".local/share/kirabridge",
    "kirabridge_releases": HOME / ".local/share/kirabridge/install/releases",
    "kirabridge_backups": HOME / ".local/share/kirabridge/install/backups",
    "kirabridge_config": HOME / ".config/kirabridge",
    "kirabridge_logs": HOME / "Library/Logs",  # filtered to kirabridge-* below
    "kirabridge_remote_relay": HOME / ".local/share/kirabridge/remote-relay",
}

DB_PATH = HOME / ".local/share/kirabridge/bridge.sqlite3"


def du(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        out = subprocess.run(["du", "-sk", str(path)], capture_output=True, text=True, timeout=30)
        return int(out.stdout.split()[0]) * 1024 if out.returncode == 0 else None
    except Exception:
        return None


def human(n):
    if n is None:
        return None
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def kirabridge_logs_size():
    total = 0
    found = []
    for f in (HOME / "Library/Logs").glob("kirabridge*"):
        size = du(f) or 0
        total += size
        found.append({"path": str(f), "bytes": size})
    return total, found


def release_inventory():
    root = HOME / ".local/share/kirabridge/install/releases"
    if not root.exists():
        return []
    entries = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        entries.append({"name": child.name, "bytes": du(child), "mtime": child.stat().st_mtime})
    return entries


def backup_inventory():
    root = HOME / ".local/share/kirabridge/install/backups"
    if not root.exists():
        return []
    entries = []
    for child in sorted(root.iterdir()):
        entries.append({"name": child.name, "bytes": du(child), "mtime": child.stat().st_mtime})
    return entries


def db_table_counts():
    if not DB_PATH.exists():
        return {}
    db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    counts = {}
    for t in tables:
        try:
            counts[t] = db.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
        except sqlite3.Error:
            counts[t] = None
    extra = {}
    try:
        extra["completion_notices_unacknowledged"] = db.execute(
            "SELECT COUNT(*) FROM completion_notices WHERE acknowledged IS NULL"
        ).fetchone()[0]
    except sqlite3.Error:
        pass
    try:
        extra["audit_oldest_at"] = db.execute("SELECT MIN(at) FROM audit").fetchone()[0]
        extra["audit_newest_at"] = db.execute("SELECT MAX(at) FROM audit").fetchone()[0]
    except sqlite3.Error:
        pass
    db.close()
    return counts, extra


def config_subdirectory_breakdown():
    """`~/.config/kirabridge` top-level entries, sorted by size — surfaces
    unnecessary-growth drivers like stale per-session repair/rollback
    snapshots directly, instead of only a single folder-wide total."""
    root = HOME / ".config/kirabridge"
    if not root.exists():
        return []
    entries = []
    for child in root.iterdir():
        entries.append(
            {
                "name": child.name,
                "bytes": du(child)
                if child.is_dir()
                else (child.stat().st_size if child.is_file() else None),
                "is_dir": child.is_dir(),
                "mtime": child.stat().st_mtime,
            }
        )
    entries.sort(key=lambda e: e["bytes"] or 0, reverse=True)
    return entries


def directory_architecture_check():
    """Spot-check the shared family directory standard Kira asked about:
    one shared parent, one folder per tool, program vs. user-data separated.
    Reports observed structure; does not judge compliance (that needs the
    documented standard text, which lives in ThreadDesk, not here)."""
    candidates = {
        "KiraBridge": HOME / ".local/share/kirabridge",
        "ThreadDesk": HOME / ".local/share/threaddesk",
        "shared_family_root_candidate (~/KiraBridge Family)": HOME / "KiraBridge Family",
    }
    return {name: path.exists() for name, path in candidates.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.absolute()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)

    report = {"scope": "READ-ONLY storage/data-growth audit; nothing deleted or moved"}

    sizes = {}
    for name, path in DIRECTORIES.items():
        if name == "kirabridge_logs":
            continue
        sizes[name] = {"path": str(path), "bytes": du(path)}
    logs_bytes, logs_detail = kirabridge_logs_size()
    sizes["kirabridge_logs"] = {
        "path": str(HOME / "Library/Logs/kirabridge*"),
        "bytes": logs_bytes,
        "files": logs_detail,
    }
    report["directory_sizes"] = sizes

    report["db_file_bytes"] = DB_PATH.stat().st_size if DB_PATH.exists() else None
    table_counts, extra = db_table_counts()
    report["db_table_row_counts"] = table_counts
    report["db_notable"] = extra

    report["releases"] = release_inventory()
    report["backups"] = backup_inventory()
    report["config_subdirectory_breakdown"] = config_subdirectory_breakdown()
    report["directory_architecture_observed"] = directory_architecture_check()

    (root / "report.json").write_text(json.dumps(report, indent=2, default=str))

    print("=== Verzeichnisgrößen ===")
    for name, info in sizes.items():
        print(f"  {name}: {human(info['bytes'])}  ({info['path']})")
    print(f"\nbridge.sqlite3 Dateigröße: {human(report['db_file_bytes'])}")
    print("\n=== Auffällige Tabellen (Zeilenanzahl) ===")
    for t in (
        "audit",
        "events",
        "completion_notices",
        "messages",
        "team_messages",
        "message_events",
    ):
        if t in table_counts:
            print(f"  {t}: {table_counts[t]}")
    print(f"\ncompletion_notices unquittiert: {extra.get('completion_notices_unacknowledged')}")
    print(f"\n=== Releases ({len(report['releases'])}) ===")
    for r in report["releases"]:
        print(f"  {r['name']}: {human(r['bytes'])}")
    print(f"\n=== Backups ({len(report['backups'])}) ===")
    for b in report["backups"]:
        print(f"  {b['name']}: {human(b['bytes'])}")
    config_entries = report["config_subdirectory_breakdown"]
    print(f"\n=== ~/.config/kirabridge nach Größe (Top 10 von {len(config_entries)}) ===")
    import datetime

    for e in config_entries[:10]:
        age = datetime.datetime.fromtimestamp(e["mtime"]).strftime("%Y-%m-%d")
        print(f"  {e['name']}: {human(e['bytes'])}  (zuletzt geändert {age})")
    print("\n=== Verzeichnisarchitektur (nur beobachtet, nicht bewertet) ===")
    for name, exists in report["directory_architecture_observed"].items():
        print(f"  {name}: {'vorhanden' if exists else 'nicht vorhanden'}")
    print(f"\nVollständiger Bericht: {root / 'report.json'}")


if __name__ == "__main__":
    main()
