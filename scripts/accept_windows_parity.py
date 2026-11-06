#!/usr/bin/env python3
"""Windows parity acceptance for an existing Python. No policy change.

This process does not start a VM, change ExecutionPolicy, or install on the
Mac. It does not start the old Restricted PowerShell runner and it does not
use -EncodedCommand or Bypass. A Mac run is not a Windows pass.

Guest, in the already visible console, with the prepared Python 3.14.10.
ExecutionPolicy stays Restricted. No new policy approval is required for this
ordinary Python process.

Prerequisites: the prepared python.exe, a new LOCALAPPDATA root, and this
extracted payload or a git archive of the pinned commit. Do not point PYTHONPATH
at an older RC31/RC33 checkout.

1. python -B scripts/windows_parity_package.py build --output dist\\parity.zip
2. Compare the printed SHA256 with the correction result JSON.
3. python -B scripts/windows_parity_package.py install --root <new-root>\\install --payload <zip>
4. python -B scripts/accept_windows_parity.py --native-visible --root <new-root>
5. Optional original harnesses, after the activated release is the script tree
   or sys.path[0] is that release's src (these scripts insert their own src):
   python -B scripts/accept_windows_keyboard.py --output <new-file>.json
   python -B scripts/accept_windows_windows.py --output <new-file>.json
   The keyboard harness needs an interactive desktop and its own window.
   The window harness needs an interactive desktop and an owned top-level window.
   git archive <pinned-commit> scripts/accept_windows_keyboard.py
   git archive <pinned-commit> scripts/accept_windows_windows.py
6. python -B scripts/windows_parity_package.py rollback --root <new-root>\\install

This harness does not claim full Windows parity. The report lists the native
checks it did not run.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kirabridge import __file__ as package_file  # noqa: E402
from kirabridge import __version__  # noqa: E402
from kirabridge.desktop_input import DesktopInput  # noqa: E402
from kirabridge.platform_adapters.windows.apps import (  # noqa: E402
    CREATE_NO_WINDOW,
    launch_plan,
)
from kirabridge.platform_adapters.windows.text import text_strokes  # noqa: E402
from kirabridge.platform_adapters.windows.visible_console import runtime_identity  # noqa: E402
from kirabridge.windows_console import (  # noqa: E402
    WindowsConsoleHandoffInput,
    WindowsConsoleManager,
    WindowsConsoleStatusInput,
)
from kirabridge.windows_package import install, rollback  # noqa: E402
from kirabridge.windows_preview import CAPABILITIES  # noqa: E402

NOT_RUN_BY_THIS_HARNESS = (
    "native WM_CHAR into an owned window; run scripts/accept_windows_keyboard.py",
    "native owned-window foreground transition; run scripts/accept_windows_windows.py",
    "windows.app.launch CreateProcess of a GUI program",
    "windows.app.focus of a real HWND",
    "attachment to an existing Windows Terminal tab",
    "Windows service installation",
    "standalone exe or msi; this delivery is a zip plus the existing Python",
    "ExecutionPolicy change; Restricted stays unchanged",
    "full macOS terminal, clipboard, and voice parity",
)


def refuse_policy(argv: list[str]) -> None:
    for item in argv:
        lowered = item.lower()
        if "executionpolicy" in lowered or "encodedcommand" in lowered or lowered == "bypass":
            raise SystemExit("Refusing an execution-policy change or encoded command")


def portable() -> dict:
    strokes = text_strokes("Größe €\n")
    plan = launch_plan(r"C:\Windows\System32\cmd.exe", console=True)
    return {
        "unicode_strokes": len(strokes),
        "enter_is_named": strokes[-1].named == "enter",
        "launch_plan_show": plan["show"],
        "launch_plan_hidden": bool(plan["creation_flags"] & CREATE_NO_WINDOW),
        "native_createprocess": False,
        "preview_capabilities_unchanged": "windows.console.handoff" not in CAPABILITIES,
        "execution_policy_changed": False,
    }


def _import_release(runtime_root: Path) -> dict:
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import kirabridge\n"
        "marker = Path(kirabridge.__file__).resolve().parent / 'parity_marker.py'\n"
        "print(Path(kirabridge.__file__).resolve())\n"
        "print(kirabridge.__version__)\n"
        "print(marker.read_text(encoding='utf-8').strip() if marker.is_file() else 'absent')\n"
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, "-P", "-B", "-c", code, str(runtime_root)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    location, version, marker = completed.stdout.splitlines()
    return {"import_path": location, "version": version, "marker": marker}


def _load_package_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "windows_parity_package", ROOT / "scripts" / "windows_parity_package.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _extract_build(destination: Path) -> tuple[Path, dict]:
    archive_path = destination / "parity.zip"
    module = _load_package_module()
    built = module.build(archive_path)
    extracted = destination / "extracted"
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(extracted)
    if not (extracted / "LICENSE").is_file():
        raise SystemExit("Built package is missing LICENSE")
    return extracted, built


def _distinguished(payload: Path, copy_root: Path) -> tuple[Path, str]:
    shutil.copytree(payload, copy_root, symlinks=False)
    marker = copy_root / "src" / "kirabridge" / "parity_marker.py"
    marker.write_text("two\n", encoding="utf-8")
    provenance_path = copy_root / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    inventory = {}
    for path in sorted(item for item in copy_root.rglob("*") if item.is_file()):
        if path.name == "provenance.json" or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(copy_root).as_posix()
        inventory[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    commit = hashlib.sha256(b"distinguished-copy\n").hexdigest()
    provenance.update(
        {
            "commit": commit,
            "commit_source": "distinguished-copy",
            "dirty": False,
            "files": inventory,
            "git_commit": None,
        }
    )
    provenance_path.write_text(
        json.dumps(provenance, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    return copy_root, commit


def package_roundtrip(root: Path) -> dict:
    extracted, built = _extract_build(root / "build")
    installed = install(
        root / "install",
        extracted,
        version="0.8.0rc40",
        commit=built["commit"],
    )
    (root / "install" / "data" / "keep.txt").write_text("behalten", encoding="utf-8")
    first = _import_release(root / "install" / "releases" / installed["release"] / "src")
    copy, copy_commit = _distinguished(extracted, root / "copy")
    updated = install(
        root / "install", copy, version="0.8.0rc40", commit=copy_commit, update=True
    )
    second = _import_release(root / "install" / "releases" / updated["release"] / "src")
    restored = rollback(root / "install")
    rolled = _import_release(root / "install" / "releases" / restored["release"] / "src")
    kept = (root / "install" / "data" / "keep.txt").read_text(encoding="utf-8")
    return {
        "installed": installed["release"],
        "provenance_commit": built["commit"],
        "provenance_verified": installed["provenance_verified"],
        "standalone_executable": False,
        "first_import": first,
        "updated": updated["release"],
        "second_import": second,
        "restored": restored["release"],
        "rollback_import": rolled,
        "data": kept,
        "license_in_package": True,
        "execution_policy_changed": False,
    }


async def native_visible(root: Path) -> dict:
    if sys.platform != "win32":
        raise SystemExit("native-visible requires Windows and does not fake a pass")
    from kirabridge.platform_adapters.windows.visible_console import Win32VisibleSpawner

    identity = runtime_identity()
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

    task = {"principal": "local", "operation": "windows.console.handoff"}
    result = await manager.execute(task, args, running)
    status = await manager.execute(
        {"principal": "local", "operation": "windows.console.status"},
        WindowsConsoleStatusInput.model_validate({"handoff_id": "parityvis01"}),
        running,
    )
    again = await manager.execute(task, args, running)
    return {
        "state": result["state"],
        "deduplicated": result["deduplicated"],
        "again_deduplicated": again["deduplicated"],
        "again_spawned": again["spawned"],
        "status_state": status["state"],
        "status_deduplicated": status["deduplicated"],
        "stdout": result["stdout"],
        "stdout_encoding": result["stdout_encoding"],
        "import_path": result["import_path"],
        "source_sha256": result["source_sha256"],
        "import_matches_parent": result["import_path"] == identity["import_path"],
        "source_matches_parent": result["source_sha256"] == identity["source_sha256"],
        "pid": result["pid"],
        "show": result["show"],
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
        "package_version": __version__,
        "runtime": runtime_identity(),
        "portable": portable(),
        "native_visible": None,
        "package": None,
        "windows_vm_tested_by_this_process": False,
        "standalone_executable": False,
        "not_run_by_this_harness": list(NOT_RUN_BY_THIS_HARNESS),
        "full_windows_parity": False,
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
    failed = (
        report["package"]["first_import"]["marker"] != "absent"
        or report["package"]["second_import"]["marker"] != "two"
        or report["package"]["rollback_import"]["marker"] != "absent"
        or report["package"]["data"] != "behalten"
        or report["package"]["first_import"]["version"] != __version__
        or not report["package"]["first_import"]["import_path"].endswith(
            f"{report['package']['installed']}/src/kirabridge/__init__.py".replace("/", os.sep)
        )
    )
    if report["native_visible"] is not None:
        native = report["native_visible"]
        failed = failed or not (
            native["import_matches_parent"]
            and native["source_matches_parent"]
            and native["again_deduplicated"]
            and native["again_spawned"] is False
            and "Größe" in native["stdout"]
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
