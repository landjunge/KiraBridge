"""Read-only report for the move from the legacy directories to the v1 layout.

Nothing here writes, moves or deletes. --apply is not released (PR4 needs user approval).
"""

import json
import os
import plistlib
import sys
from pathlib import Path

from kirabridge import paths

APPLY_REFUSED = "--apply ist nicht freigegeben (Migration erst nach Nutzerfreigabe, PR4)"
PLIST_PREFIXES = ("com.kirabridge.", "de.threaddesk.")


def _size(path: Path, limit: int = 200_000) -> int | None:
    """Bytes below path without following symlinks; None when the walk is cut off."""
    if not path.exists():
        return None
    if path.is_file():
        return path.stat().st_size
    total = seen = 0
    for base, dirs, files in os.walk(path, followlinks=False):
        for name in files + dirs:
            seen += 1
            if seen > limit:
                return None
            try:
                total += os.lstat(os.path.join(base, name)).st_size
            except OSError:
                pass
    return total


def plan(home: Path | None = None) -> list[dict]:
    home = home or Path.home()
    target = paths.tool_root()
    share = home / ".local/share/kirabridge"
    rows = [
        (home / ".config/kirabridge", target / "config"),
        (share / "install", target / "program"),
        (share / "backups", target / "backups"),
        (share, target / "data"),
        (home / ".local/state/kirabridge", target / "state"),
    ]
    if sys.platform == "darwin":
        logs = sorted((home / "Library/Logs").glob("kirabridge*.log"))
        rows += [(log, target / "state/logs" / log.name) for log in logs]
    out = []
    for source, dest in rows:
        row = {"from": str(source), "to": str(dest), "exists": source.exists()}
        size = _size(source) if source.exists() else 0
        if source == share and size:  # the data row excludes the sub-areas listed above
            size -= sum(_size(share / part) or 0 for part in ("install", "backups"))
        row["bytes"] = size
        out.append(row)
    return out


def _references(text: str, needles: list[str]) -> list[str]:
    return [needle for needle in needles if needle in text]


def references(home: Path | None = None) -> dict:
    home = home or Path.home()
    needles = [
        str(home / ".config/kirabridge"),
        str(home / ".local/share/kirabridge"),
        str(home / ".local/state/kirabridge"),
        str(home / "Library/Logs/kirabridge"),
    ]
    agents = home / "Library/LaunchAgents"
    services = []
    for plist in sorted(agents.glob("*.plist")) if agents.is_dir() else []:
        if not plist.name.startswith(PLIST_PREFIXES):
            continue
        try:
            text = json.dumps(plistlib.loads(plist.read_bytes()), default=str)
        except (OSError, ValueError, plistlib.InvalidFileException):
            services.append({"plist": plist.name, "unreadable": True})
            continue
        services.append({"plist": plist.name, "fixed_paths": _references(text, needles)})
    files = {}
    for label, path in (
        ("config.toml", paths.config_file()),
        ("remote-relay.json", paths.relay_config_file()),
    ):
        try:
            files[label] = _references(path.read_text(encoding="utf-8"), needles)
        except OSError:
            files[label] = None  # absent or unreadable
    return {"services": services, "files": files}


def risks(home: Path | None = None) -> list[str]:
    home = home or Path.home()
    found = [
        "Laufende Dienste muessen vor dem Verschieben gestoppt werden; Plists mit festen "
        "Pfaden zeigen sonst ins Leere."
    ]
    wal = [p.name for p in (home / ".local/share/kirabridge").glob("*.sqlite3-wal")]
    if wal:
        found.append(
            f"WAL aktiv ({', '.join(wal)}): nie per Dateikopie sichern, nur SQLite-Backup-API."
        )
    found.append("Aufruf am besten im Leerlauf; offene Locks/Sockets in state/ nicht kopieren.")
    return found


def report(home: Path | None = None) -> dict:
    return {
        "mode": "dry-run",
        "writes": False,
        "layout_active": paths.layout_active(),
        "paths": plan(home),
        "references": references(home),
        "risks": risks(home),
        "apply": "nicht freigegeben",
    }
