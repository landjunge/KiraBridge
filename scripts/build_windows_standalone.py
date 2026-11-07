#!/usr/bin/env python3
"""Build an offline Windows x64 package with a supplied complete CPython runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kirabridge.windows_package import _copy_regular_tree, _digest_tree  # noqa: E402
from kirabridge.windows_runtime import validate_bundled_runtime  # noqa: E402


def build(runtime: Path, output: Path, version: str) -> dict:
    pin = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    # Export committed bytes: unrelated dirty work cannot enter a release.
    source = subprocess.check_output(
        ["git", "archive", "--format=zip", pin, "src", "scripts", "pyproject.toml", "LICENSE"],
        cwd=ROOT,
    )
    runtime_identity = validate_bundled_runtime(runtime)
    with tempfile.TemporaryDirectory() as temporary:
        payload = Path(temporary) / "payload"
        payload.mkdir()
        archive = Path(temporary) / "source.zip"
        archive.write_bytes(source)
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(payload)
        _copy_regular_tree(runtime, payload / "runtime")
        # Runtime bytecode can embed machine paths and is regenerated nowhere (-B).
        for path in (payload / "runtime").rglob("__pycache__"):
            shutil.rmtree(path)
        (payload / "Manage.cmd").write_bytes(
            b"@echo off\r\n"
            b'"%~dp0runtime\\python.exe" -I -B "%~dp0scripts\\windows_standalone.py" %*\r\n'
        )
        (payload / "INSTALL.txt").write_text(
            "Offline Windows x64 package. Extract the complete directory.\n"
            "No Python installation required.\n"
            'Manage.cmd --root "%LOCALAPPDATA%\\KiraBridge" install\n'
            'Installed: "%LOCALAPPDATA%\\KiraBridge\\KiraBridge.cmd" status\n'
            "Start: KiraBridge.cmd run --help (then setup/serve using an explicit config).\n"
            "Update: extract a newer package, then Manage.cmd --root <same-root> update.\n"
            "KiraBridge.cmd rollback. Uninstall from the extracted package with:\n"
            "Manage.cmd --root <root> uninstall. Data stays in <root>\\data.\n"
            "No service, PATH, registry or PowerShell policy changes.\n"
            "Keep configuration in data.\n",
            encoding="utf-8",
        )
        inventory = _digest_tree(payload)
        document = {
            "commit": pin,
            "commit_source": "git-archive",
            "dirty": False,
            "version": version,
            "kind": "offline-bundled-cpython-windows-x64",
            "runtime": runtime_identity,
            "files": inventory,
        }
        (payload / "provenance.json").write_text(
            json.dumps(document, sort_keys=True), encoding="utf-8"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as zipped:
            for path in sorted(payload.rglob("*")):
                if path.is_file():
                    zipped.write(path, path.relative_to(payload).as_posix())
    return {
        "path": str(output),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "commit": pin,
        "version": version,
        "bundled_runtime": runtime_identity,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", default="0.8.0rc40")
    args = parser.parse_args()
    print(json.dumps(build(args.runtime, args.output, args.version), sort_keys=True))
