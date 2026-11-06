#!/usr/bin/env python3
"""Portable Windows parity acceptance. Codex runs the native half in the guest.

This process does not start a VM, change ExecutionPolicy, or install on the
Mac. On Windows, --native-visible opens one shown console and waits for its
result file. Without that flag the checks are import, Unicode, package and
deduplicated-handoff contracts only.

Guest, when Codex has a fresh confirmation of VM 2B6EE828-02F0-42AE-B4FE-BE57C448F65E
and an explicit approval to run this hash-checked file under the existing
Restricted PowerShell policy (do not pass -ExecutionPolicy Bypass):

1. Build on the Mac or inside the guest with the same script bytes:
   python -B scripts/windows_parity_package.py build --output dist\\parity.zip
2. Compare the printed SHA256 with docs/evidence/windows-parity-grok-result-20261106.json.
3. From an already-open visible console, using the prepared Python 3.14, run
   accept_windows_parity.py --native-visible against a new LOCALAPPDATA root.
4. Read the report JSON. A Mac run of this file is not a Windows pass.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kirabridge import __file__ as package_file  # noqa: E402
from kirabridge.desktop_input import DesktopInput  # noqa: E402
from kirabridge.platform_adapters.windows.text import text_strokes  # noqa: E402
from kirabridge.windows_console import (  # noqa: E402
    WindowsConsoleHandoffInput,
    WindowsConsoleManager,
)
from kirabridge.windows_package import install, rollback  # noqa: E402
from kirabridge.windows_preview import CAPABILITIES  # noqa: E402


def refuse_policy(argv: list[str]) -> None:
    for item in argv:
        lowered = item.lower()
        if "executionpolicy" in lowered or "encodedcommand" in lowered or lowered == "bypass":
            raise SystemExit("Refusing an execution-policy change or encoded command")


def portable() -> dict:
    strokes = text_strokes("Größe €\n")
    return {
        "unicode_strokes": len(strokes),
        "enter_is_named": strokes[-1].named == "enter",
        "preview_capabilities_unchanged": "windows.console.handoff" not in CAPABILITIES,
        "execution_policy_changed": False,
    }


async def native_visible(root: Path) -> dict:
    if sys.platform != "win32":
        raise SystemExit("native-visible requires Windows and does not fake a pass")
    from kirabridge.platform_adapters.windows.visible_console import Win32VisibleSpawner

    manager = WindowsConsoleManager(
        lambda *_args: None,
        DesktopInput(asyncio.Lock()),
        root,
        spawner=Win32VisibleSpawner(),
        host="win32",
    )
    args = WindowsConsoleHandoffInput.model_validate(
        {
            "handoff_id": "parityvis01",
            "argv": [sys.executable, "-c", "print('KIRABRIDGE_VISIBLE_OK Größe')"],
            "cwd": str(root),
            "timeout_seconds": 8,
        }
    )

    async def running(_event):
        return None

    result = await manager.execute(
        {"principal": "local", "operation": "windows.console.handoff"}, args, running
    )
    return {
        "state": result["state"],
        "deduplicated": result["deduplicated"],
        "stdout": result["stdout"],
        "pid": result["pid"],
        "show": result["show"],
    }


def package_roundtrip(root: Path) -> dict:
    payload = root / "payload"
    payload.mkdir()
    (payload / "marker.txt").write_text("parity\n", encoding="utf-8")
    installed = install(root / "install", payload, version="0.8.0rc40", commit="d12838ae97c7")
    (root / "install" / "data" / "keep.txt").write_text("behalten", encoding="utf-8")
    other = root / "other"
    other.mkdir()
    (other / "marker.txt").write_text("next\n", encoding="utf-8")
    install(root / "install", other, version="0.8.0rc40", commit="aabbccddeeff", update=True)
    restored = rollback(root / "install")
    kept = (root / "install" / "data" / "keep.txt").read_text(encoding="utf-8")
    return {
        "installed": installed["release"],
        "restored": restored["release"],
        "data": kept,
        "execution_policy_changed": False,
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    refuse_policy(argv)
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-visible", action="store_true")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    report = {
        "interpreter": sys.executable,
        "version": sys.version,
        "platform": sys.platform,
        "import_path": package_file,
        "portable": portable(),
        "native_visible": None,
        "package": None,
        "windows_vm_tested_by_this_process": False,
    }
    with tempfile.TemporaryDirectory(prefix="kirabridge-parity-") as temporary:
        report["package"] = package_roundtrip(Path(temporary))
    if args.native_visible:
        root = args.root or Path(tempfile.mkdtemp(prefix="kirabridge-visible-"))
        root.mkdir(parents=True, exist_ok=True)
        report["native_visible"] = asyncio.run(native_visible(root))
        report["windows_vm_tested_by_this_process"] = sys.platform == "win32"
    if args.report:
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
