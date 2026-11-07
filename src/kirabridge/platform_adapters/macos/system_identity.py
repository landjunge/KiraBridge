"""Bind a native worker to its exact installed release and binary manifest."""

import json
import re
from pathlib import Path


def _release_document(package_path):
    package = Path(package_path).resolve()
    ancestors = list(package.parents)
    if any(
        parent.name == "src"
        and (parent.parent / ".git").exists()
        and (parent.parent / "pyproject.toml").is_file()
        for parent in ancestors
    ):
        return None, None, True
    # This is the installer's managed layout, not a search through user files.
    environment = next((p for p in ancestors if p.name == ".venv"), None)
    if environment is None or environment.parent.name != "source":
        return None, None, False
    release = environment.parent.parent
    manifest = release / "release.json"
    try:
        if manifest.is_symlink():
            return release, None, False
        with manifest.open("rb") as stream:
            data = stream.read(65537)
        value = json.loads(data) if len(data) <= 65536 else None
        return release, value if isinstance(value, dict) else None, False
    except (OSError, ValueError, TypeError, RecursionError):
        return release, None, False


def installed_source_commit(package_path):
    """None means a real development checkout; empty means an invalid install."""
    _, value, development = _release_document(package_path)
    if development:
        return None
    commit = (value or {}).get("source_commit", "")
    return commit if isinstance(commit, str) and re.fullmatch(r"[a-f0-9]{40}", commit) else ""


def installed_native_contract(package_path):
    """An invalid installed native descriptor never falls back to the global UI app."""
    release, value, development = _release_document(package_path)
    if development:
        return {"expected_commit": None}
    invalid = {"expected_commit": ""}
    if release is None or value is None:
        return invalid
    commit = value.get("source_commit", "")
    native = value.get("native_app")
    if (
        not isinstance(commit, str)
        or not re.fullmatch(r"[a-f0-9]{40}", commit)
        or not isinstance(native, dict)
        or native.get("schema") != "kirabridge.native-app.v1"
        or native.get("path") != "native/KiraBridge.app"
        or type(native.get("protocol")) is not int
        or native["protocol"] != 1
        or native.get("source_commit") != commit
        or not isinstance(native.get("binary_sha256"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", native["binary_sha256"])
    ):
        return invalid
    return {
        "app_path": release / "native/KiraBridge.app",
        "expected_commit": commit,
        "expected_binary_sha256": native["binary_sha256"],
    }
