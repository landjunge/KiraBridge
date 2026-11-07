#!/usr/bin/env python3
"""Offline Windows package entry point, using only its bundled CPython."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PAYLOAD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PAYLOAD / "src"))
from kirabridge.windows_package import (  # noqa: E402
    PackageError,
    install,
    rollback,
    status,
    uninstall,
)
from kirabridge.windows_runtime import validate_bundled_runtime  # noqa: E402


def launcher(root: Path) -> None:
    current = status(root)["current"]
    release = root / "releases" / current["release"]
    # CMD must exit from this already parsed line: rollback can rewrite this
    # batch file to a different length while the Python process is running.
    command = (
        '@echo off\r\n"%~dp0releases\\'
        + current["release"]
        + '\\runtime\\python.exe" -I -B "%~dp0releases\\'
        + current["release"]
        + '\\scripts\\windows_standalone.py" --root "%~dp0." %* & exit /b\r\n'
    )
    target = root / "KiraBridge.cmd"
    if target.is_symlink():
        raise PackageError("Refusing a linked launcher")
    temporary = root / "KiraBridge.cmd.new"
    with temporary.open("x", encoding="utf-8", newline="") as stream:
        stream.write(command)
    os.replace(temporary, target)
    validate_bundled_runtime(release / "runtime")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "action", choices=("install", "update", "rollback", "uninstall", "status", "run")
    )
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    rest = args.arguments
    if args.action != "run" and rest:
        parser.error("Only run accepts application arguments")
    root = args.root.absolute()
    if args.action in {"install", "update"}:
        validate_bundled_runtime(PAYLOAD / "runtime")
        provenance = json.loads((PAYLOAD / "provenance.json").read_text(encoding="utf-8"))
        result = install(
            root,
            PAYLOAD,
            version=provenance["version"],
            commit=provenance["commit"],
            update=args.action == "update",
        )
        launcher(root)
    elif args.action == "rollback":
        result = rollback(root)
        launcher(root)
    elif args.action == "uninstall":
        if root in PAYLOAD.parents:
            raise PackageError(
                "Uninstall from the extracted package: Manage.cmd --root <root> uninstall"
            )
        result = uninstall(root)
        (root / "KiraBridge.cmd").unlink(missing_ok=True)
    elif args.action == "status":
        result = status(root)
    else:
        current = status(root)["current"]
        if current is None:
            raise PackageError("No installed release")
        release = root / "releases" / current["release"]
        # Isolated mode ignores host PYTHONPATH; inject only the verified installed source.
        code = (
            "import sys;sys.path.insert(0,sys.argv.pop(1));from kirabridge.cli import main;main()"
        )
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.call(
            [
                str(release / "runtime" / "python.exe"),
                "-I",
                "-B",
                "-c",
                code,
                str(release / "src"),
                *rest,
            ]
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PackageError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
