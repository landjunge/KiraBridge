#!/usr/bin/env python3
"""Native offline-package lifecycle acceptance in a new explicit Windows root."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import platform
import subprocess
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, report):
    path.write_text(json.dumps(report, sort_keys=True, indent=2), encoding="utf-8")


async def health(root, report, persist):
    import httpx
    import mcp
    import uvicorn

    import kirabridge
    from kirabridge import windows_package

    for module in (kirabridge, windows_package, mcp, httpx, uvicorn):
        location = Path(module.__file__).resolve()
        assert ROOT in location.parents, str(location)
    report["imports"] = {
        m.__name__: str(Path(m.__file__).resolve())
        for m in (kirabridge, windows_package, mcp, httpx, uvicorn)
    }
    report["python"] = sys.executable
    report["platform"] = platform.platform()
    path = ROOT / "scripts/accept_windows_parity_e2e.py"
    spec = importlib.util.spec_from_file_location("native_health_support", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    async with module.NativeMCP(SimpleNamespace(root=root), report, persist) as client:
        reply = await client.call("bridge_health", {})
        assert "error" not in reply, reply
        report["authenticated_health"] = reply
    report["passed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--update", type=Path)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--health-only", action="store_true")
    args = parser.parse_args()
    assert sys.platform == "win32", "Native Windows required"
    assert not args.output.exists(), "Preserve original evidence; choose a new run"
    report = {
        "passed": False,
        "platform": platform.platform(),
        "python": sys.executable,
        "root": str(args.root),
        "commands": [],
    }
    persist = lambda: save(args.output, report)
    persist()
    try:
        if args.health_only:
            asyncio.run(health(args.root, report, persist))
            persist()
            return
        assert not args.root.exists(), "Preserve original installation; no replay"
        assert args.package and args.update
        packages = [args.package, args.update]
        for package in packages:
            provenance = json.loads((package / "provenance.json").read_text(encoding="utf-8"))
            report.setdefault("provenance", []).append(provenance)

        def run(argv, label):
            item = {"label": label, "argv": [str(x) for x in argv], "state": "started"}
            report["commands"].append(item)
            persist()
            result = subprocess.run(
                [str(x) for x in argv],
                capture_output=True,
                text=True,
                timeout=180,
                encoding="utf-8",
                errors="replace",
            )
            item.update(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
            item["state"] = "finished"
            persist()
            assert result.returncode == 0, item

        def manage(package, action):
            run(
                [
                    "C:\\Windows\\System32\\cmd.exe",
                    "/d",
                    "/c",
                    package / "Manage.cmd",
                    "--root",
                    args.root,
                    action,
                ],
                action,
            )

        def installed_health(label):
            current = json.loads((args.root / "current.json").read_text())
            release = args.root / "releases" / current["release"]
            output = args.output.with_name(args.output.stem + "-" + label + ".json")
            run(
                [
                    release / "runtime/python.exe",
                    "-I",
                    "-B",
                    release / "scripts/accept_windows_standalone.py",
                    "--root",
                    args.root / "data",
                    "--output",
                    output,
                    "--health-only",
                ],
                label,
            )
            found = json.loads(output.read_text())
            assert found["passed"]
            assert found["mcp_sessions"][-1]["unauthenticated_http_status"] == 401
            report[label] = found
            persist()

        manage(args.package, "install")
        initial = json.loads((args.root / "current.json").read_text())
        data = args.root / "data/user-record.bin"
        data.write_bytes(b"created after initial installation")
        run(
            [
                "C:\\Windows\\System32\\cmd.exe",
                "/d",
                "/c",
                args.root / "KiraBridge.cmd",
                "run",
                "--help",
            ],
            "installed_cli",
        )
        installed_health("initial_health")
        manage(args.update, "update")
        updated = json.loads((args.root / "current.json").read_text())
        assert updated["release"] != initial["release"]
        assert data.read_bytes() == b"created after initial installation"
        data.write_bytes(b"new user data after update must survive rollback")
        expected = digest(data)
        installed_health("updated_health")
        manage(args.update, "rollback")
        reverted = json.loads((args.root / "current.json").read_text())
        assert reverted["release"] == initial["release"]
        assert digest(data) == expected
        installed_health("rollback_health")
        manage(args.package, "uninstall")
        assert digest(data) == expected
        assert not (args.root / "current.json").exists()
        assert not (args.root / "KiraBridge.cmd").exists()
        assert not list((args.root / "releases").iterdir())
        report.update(
            passed=True,
            initial=initial,
            updated=updated,
            reverted=reverted,
            preserved_data_sha256=expected,
            uninstalled=True,
        )
        persist()
    except BaseException:
        report["original_error"] = traceback.format_exc()
        persist()
        raise


if __name__ == "__main__":
    main()
