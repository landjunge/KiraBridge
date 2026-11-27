"""Central path resolution for the KiraBridge Family directory architecture (v1).

New layout: <FAMILY>/KiraBridge/{program,data,config,state,backups,work}.
Until a migration has explicitly marked the new layout "active" in
<FAMILY>/KiraBridge/tool.json, every function returns the historical legacy
paths (~/.config/kirabridge, ~/.local/share/kirabridge, ~/.local/state/kirabridge,
~/Library/Logs). Resolution never creates anything; only write_manifests() writes,
and only when a command asks for it.
"""

import json
import os
import sys
from pathlib import Path

from kirabridge.private_files import write_private

CONTRACT = "directory-architecture-v1"
FAMILY_DIR = "KiraBridge Family"
TOOL_KEY = "kirabridge"
TOOL_DIR = "KiraBridge"
SUBDIRS = ("program", "data", "config", "state", "backups", "work")


def family_root() -> Path:
    override = os.environ.get("KIRABRIDGE_FAMILY_HOME")
    if override:
        return Path(override).expanduser().absolute()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support" / FAMILY_DIR
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData/Local")
        return Path(base) / FAMILY_DIR
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    return Path(base) / FAMILY_DIR


def tool_root() -> Path:
    return family_root() / TOOL_DIR


def layout_active() -> bool:
    """True only when tool.json exists and says layout_state == "active"."""
    try:
        manifest = json.loads((tool_root() / "tool.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(manifest, dict) and manifest.get("layout_state") == "active"


def _pick(sub: str, legacy: Path) -> Path:
    return tool_root() / sub if layout_active() else legacy


def config_dir() -> Path:
    return _pick("config", Path.home() / ".config/kirabridge")


def data_dir() -> Path:
    return _pick("data", Path.home() / ".local/share/kirabridge")


def state_dir() -> Path:
    return _pick("state", Path.home() / ".local/state/kirabridge")


def program_dir() -> Path:
    return _pick("program", Path.home() / ".local/share/kirabridge/install")


def backups_dir() -> Path:
    return _pick("backups", Path.home() / ".local/share/kirabridge/backups")


def work_dir() -> Path:
    return _pick("work", Path.home() / ".local/share/kirabridge/work")


def log_dir() -> Path:
    if layout_active():
        return tool_root() / "state/logs"
    return Path.home() / "Library/Logs" if sys.platform == "darwin" else state_dir()


def config_file() -> Path:
    return config_dir() / "config.toml"


def credentials_file() -> Path:
    return config_dir() / "credentials.json"


def relay_config_file() -> Path:
    return config_dir() / "remote-relay.json"


def family_windows_file() -> Path:
    return config_dir() / "family-windows.json"


def relay_log_file() -> Path:
    return log_dir() / "kirabridge-remote-relay.log"


def _replace_private(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.unlink(missing_ok=True)
    write_private(temporary, text)
    os.replace(temporary, path)


def describe() -> dict:
    """Read-only snapshot of the resolved paths."""
    return {
        "contract": CONTRACT,
        "family_root": str(family_root()),
        "layout_active": layout_active(),
        **{
            name: str(getattr(sys.modules[__name__], f"{name}_dir")())
            for name in ("program", "data", "config", "state", "backups", "work", "log")
        },
    }


def write_manifests(version: str) -> dict:
    """Write/refresh tool.json and family.json. Creates only <FAMILY>/KiraBridge.

    Never switches the layout on: an existing layout_state is kept, otherwise
    "prepared" is recorded (resolution keeps returning legacy paths).
    """
    root = tool_root()
    root.mkdir(parents=True, exist_ok=True)
    tool_json = root / "tool.json"
    state = "prepared"
    try:
        old = json.loads(tool_json.read_text(encoding="utf-8"))
        if isinstance(old, dict) and old.get("layout_state") in {"prepared", "active"}:
            state = old["layout_state"]
    except (OSError, ValueError):
        pass
    tool = {
        "contract": CONTRACT,
        "key": TOOL_KEY,
        "dir": TOOL_DIR,
        "version": version,
        "layout_state": state,
        "subdirs": list(SUBDIRS),
    }
    _replace_private(tool_json, json.dumps(tool, indent=2) + "\n")
    registry = family_root() / "family.json"
    try:
        family = json.loads(registry.read_text(encoding="utf-8"))
        if not isinstance(family, dict):
            family = {}
    except (OSError, ValueError):
        family = {}
    tools = family.get("tools") if isinstance(family.get("tools"), dict) else {}
    tools[TOOL_KEY] = {"dir": TOOL_DIR, "manifest": f"{TOOL_DIR}/tool.json"}
    family.update({"contract": CONTRACT, "tools": tools})
    _replace_private(registry, json.dumps(family, indent=2) + "\n")
    return {"tool_json": str(tool_json), "family_json": str(registry), "layout_state": state}
