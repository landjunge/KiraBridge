"""Native, isolated acceptance of exact Windows Setup bytes; never sends input tasks.

Requires an absent product registry identity and new app/data roots. Existing
installations are observed by the external guarded wrapper, never opened here.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import importlib.util
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import time
import urllib.request
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def guard_log_paths(command, stdout_path):
    """Inno must be able to create its own /LOG file independently of stdout."""
    target = str(Path(stdout_path).absolute()).casefold()
    for argument in command:
        value = str(argument)
        if value.upper().startswith("/LOG="):
            if str(Path(value[5:]).absolute()).casefold() == target:
                raise ValueError("Installer log and process stdout must use distinct files")


def resume_after_uninstall(args, registered):
    """Continue one verified fixture after asynchronous uninstall and a WAL baseline error."""
    work = args.work.absolute()
    original, previous = work / "acceptance.json", work / "acceptance-continuation.json"
    if (
        sha(original) != args.original_receipt_sha256
        or sha(previous) != args.continuation_receipt_sha256
    ):
        raise RuntimeError("Original receipt digests differ; preserve without replay")
    old = json.loads(original.read_text())
    prior = json.loads(previous.read_text())
    app, data = work / "app", work / "data"
    group = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/KiraBridge"
    if (
        old.get("setup_sha256") != sha(args.setup)
        or prior.get("setup_sha256") != sha(args.setup)
        or prior.get("failed_check") != "application-removed-data-retained"
        or prior.get("phase") != "clean-uninstall"
        or prior.get("commands", [])[-1:] != [{"phase": "clean-uninstall", "exit_code": 0}]
        or Path(prior.get("app", "")) != app
        or Path(prior.get("data", "")) != data
        or prior.get("continues_receipt_sha256") != sha(original)
    ):
        raise RuntimeError("Previous owned fixture identity differs")
    names = (
        "installer-config.json",
        "preview-credentials.json",
        "bridge.sqlite3",
        "preserve-me.txt",
    )
    old_hashes = prior["preserved_data_sha256"]

    def removed():
        return (
            not registered()
            and not any((app / n).exists() for n in ("current.json", "launch.cmd", "unins000.exe"))
            and not group.exists()
        )

    def hashes():
        return {name: sha(data / name) for name in names}

    def integrity():
        uri = (data / "bridge.sqlite3").as_uri() + "?mode=ro"
        with contextlib.closing(sqlite3.connect(uri, uri=True)) as db:
            assert db.execute("PRAGMA quick_check").fetchall() == [("ok",)]
            assert db.execute("SELECT value FROM installer_acceptance_probe").fetchall() == [
                ("RC33 data sentinel",)
            ]
            assert db.execute("SELECT count(*) FROM tasks").fetchone() == (0,)

    if not removed():
        raise RuntimeError("Previous uninstall has not completed; no replay")
    integrity()
    wal = data / "bridge.sqlite3-wal"
    wal_before = wal.stat().st_size if wal.exists() else 0
    with contextlib.closing(sqlite3.connect(data / "bridge.sqlite3")) as db:
        checkpoint = db.execute("PRAGMA wal_checkpoint(FULL)").fetchone()
        assert checkpoint[0] == 0, "owned-sqlite-checkpoint-busy"
    integrity()  # Every connection closes before the stable main-file byte baseline.
    stable = hashes()
    if any(stable[name] != old_hashes[name] for name in names if name != "bridge.sqlite3"):
        raise RuntimeError("Configuration, credential or user-file bytes changed")
    receipt = work / "acceptance-after-uninstall.json"
    with receipt.open("x", encoding="utf-8"):
        pass
    report = {
        "passed": False,
        "setup_sha256": sha(args.setup),
        "exact_production_setup": True,
        "original_receipt_sha256": sha(original),
        "continuation_receipt_sha256": sha(previous),
        "previous_actions_replayed": False,
        "removal_observed_before_resume": True,
        "sqlite_integrity_sentinel_zero_tasks_verified": True,
        "old_sqlite_byte_baseline": old_hashes["bridge.sqlite3"],
        "old_sqlite_baseline_limit": "Connection remained open; main-file hash excluded WAL state",
        "closed_connection_data_baseline": stable,
        "owned_sqlite_checkpoint": {
            "mode": "FULL",
            "busy": checkpoint[0],
            "wal_bytes_before": wal_before,
            "wal_bytes_after_close": wal.stat().st_size if wal.exists() else 0,
        },
        "checks": [],
        "commands": [],
        "input_tasks_submitted": 0,
    }

    def save():
        receipt.write_text(json.dumps(report, indent=2), encoding="utf-8")

    def run(command, name):
        report["phase"] = name
        save()
        log_path = work / ("after-uninstall-" + name + "-stdout.log")
        guard_log_paths(command, log_path)
        with log_path.open("xb") as log:
            child = subprocess.Popen(
                [str(x) for x in command],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            report["active_process"] = {"pid": child.pid, "phase": name}
            save()
            exit_code = child.wait(timeout=360)  # A timeout preserves the exact own live process.
        report["commands"].append({"phase": name, "exit_code": exit_code})
        assert exit_code == 0, name
        report["checks"].append(name)
        save()

    save()
    try:
        run(
            [
                args.setup,
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/SP-",
                "/LANG=english",
                "/DIR=" + str(app),
                "/DataDir=" + str(data),
                "/LOG=" + str(work / "after-uninstall-reinstall-setup.log"),
            ],
            "retained-data-reinstall",
        )
        current = json.loads((app / "current.json").read_text())
        inventory = json.loads((args.runtime / "runtime-manifest.json").read_text())
        assert current["release"] == inventory["release_id"]
        assert current["version"] == "0.8.0rc33" and Path(current["data_dir"]) == data
        assert registered() and hashes() == stable
        integrity()
        assert hashes() == stable
        report["checks"].append("reinstall-preserves-closed-db-credentials-config-user-file")
        run(
            [
                app / "unins000.exe",
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/LOG=" + str(work / "after-uninstall-final-uninstall.log"),
            ],
            "final-uninstall",
        )
        deadline = time.monotonic() + 15
        while not removed() and time.monotonic() < deadline:
            time.sleep(0.2)
        assert removed(), "bounded-post-uninstall-absence"
        assert hashes() == stable
        integrity()
        report["checks"].append("final-absence-and-data-preservation")
        report["passed"] = True
        report["product_registry_present_after"] = registered()
        report["final_data_sha256"] = hashes()
        report["phase"] = "completed"
    except Exception as error:
        report["error_type"] = type(error).__name__
        if isinstance(error, AssertionError):
            report["failed_check"] = str(error)
    finally:
        save()
    return 0 if report["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--preview-harness", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--resume-from-shortcuts", action="store_true")
    parser.add_argument("--original-receipt-sha256")
    parser.add_argument("--resume-after-uninstall", action="store_true")
    parser.add_argument("--continuation-receipt-sha256")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Native Windows guest required; no files changed")
    import winreg

    product = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\KiraBridge.Windows_is1"

    def registered():
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, product, 0, winreg.KEY_READ | view)
            except FileNotFoundError:
                continue
            else:
                key.Close()
                return True
        return False

    if args.resume_after_uninstall:
        return resume_after_uninstall(args, registered)

    work = args.work.absolute()
    app, data = work / "app", work / "data"
    group = "KiraBridge"  # /GROUP is ignored when DisableProgramGroupPage=yes.
    group_path = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs" / group
    prior = None
    if args.resume_from_shortcuts:
        prior_path = work / "acceptance.json"
        if sha(prior_path) != args.original_receipt_sha256:
            parser.error("Original failed receipt digest differs; no replay")
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
        if (
            prior.get("passed") is not False
            or prior.get("phase") != "inspect-start-menu"
            or prior.get("error_type") != "JSONDecodeError"
            or prior.get("setup_sha256") != sha(args.setup)
            or Path(prior.get("app", "")) != app
            or Path(prior.get("data", "")) != data
            or prior.get("checks", [])[-1:] != ["inspect-start-menu"]
            or not registered()
            or (app / "pending.json").exists()
        ):
            parser.error("Original failure identity differs; preserve without replay")
        installed = json.loads((app / "current.json").read_text())
        inventory = json.loads((args.runtime / "runtime-manifest.json").read_text())
        if (
            installed.get("version") != "0.8.0rc33"
            or installed.get("release") != inventory.get("release_id")
            or Path(installed.get("data_dir", "")) != data
        ):
            parser.error("Existing owned installation pointer differs")
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, product, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY
        ) as key:
            location = winreg.QueryValueEx(key, "InstallLocation")[0]
            if Path(location) != app:
                parser.error("Registered installation is not the owned fixture")
    else:
        if registered() or group_path.exists():
            parser.error("Existing installer identity/start menu group preserved")
        if work.exists():
            parser.error("Existing acceptance work preserved; reconcile without rerun")
        work.mkdir()
    report = {
        "passed": False,
        "setup_sha256": sha(args.setup),
        "setup_bytes": args.setup.stat().st_size,
        "product_registry_absent_before": not bool(prior),
        "exact_production_setup": True,
        "app": str(app),
        "data": str(data),
        "group": group,
        "checks": [],
        "commands": [],
        "input_tasks_submitted": 0,
        "synthetic_prior_version_only": True,
    }
    receipt = work / ("acceptance-continuation.json" if prior else "acceptance.json")
    if receipt.exists():
        parser.error("Existing receipt preserved; no automatic replay")
    if prior:
        report["continues_receipt_sha256"] = sha(work / "acceptance.json")
        report["previously_completed_checks"] = prior["checks"]
    child = original = None

    progress_phase = [None]

    def save():
        receipt.write_text(json.dumps(report, indent=2), encoding="utf-8")
        url = os.environ.get("KIRA_INSTALLER_ACCEPTANCE_PROGRESS_URL")
        phase = report.get("phase")
        if url and phase and phase != progress_phase[0]:
            progress_phase[0] = phase
            try:
                request = urllib.request.Request(
                    url,
                    data=json.dumps({"phase": phase, "checks": len(report["checks"])}).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    response.read(1024)
            except OSError:
                pass  # Local progress transport is not a product acceptance result.

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        report["checks"].append(name)
        save()

    def run(command, name, success=True, timeout=240):
        report["phase"] = name
        save()
        log_path = work / (("continue-" if prior else "") + name + "-stdout.log")
        guard_log_paths(command, log_path)
        with log_path.open("xb") as log:
            process = subprocess.Popen(
                [str(x) for x in command],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            identity = harness.process_snapshot(process.pid)
            try:
                exit_code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                report["timeout_unknown_process"] = identity
                report["timeout_phase"] = name
                save()
                raise  # Retain the own process; never replay or broadly kill descendants.
        report["commands"].append({"phase": name, "exit_code": exit_code})
        save()
        check(name, (exit_code == 0) == success)
        return log_path.read_bytes()

    def install(name, success=True):
        return run(
            [
                args.setup,
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/SP-",
                "/LANG=english",
                "/DIR=" + str(app),
                "/DataDir=" + str(data),
                "/GROUP=" + group,
                "/LOG=" + str(work / (name + "-setup.log")),
            ],
            name,
            success,
        )

    def lifecycle(action, name, *extra, success=True):
        base = app / "maintenance"
        return run(
            [
                base / "python.exe",
                "-I",
                "-B",
                base / "windows_lifecycle.py",
                action,
                "--install-dir",
                app,
                *extra,
            ],
            name,
            success,
        )

    def current():
        return json.loads((app / "current.json").read_text())

    def snapshots():
        return {
            name: sha(data / name)
            for name in (
                "installer-config.json",
                "preview-credentials.json",
                "bridge.sqlite3",
                "preserve-me.txt",
            )
        }

    def uninstall(name, success=True):
        return run(
            [
                app / "unins000.exe",
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/LOG=" + str(work / (name + "-uninstall.log")),
            ],
            name,
            success,
        )

    harness = load(args.preview_harness, "installer_preview_harness")
    save()
    try:
        if prior:
            first = current()
        else:
            install("fresh-install")
            check("registry-created", registered())
            first = current()
            check(
                "fresh-data-dir-and-version",
                first["version"] == "0.8.0rc33" and Path(first["data_dir"]) == data,
            )
            check("no-pending-transaction", not (app / "pending.json").exists())
            config_initial = sha(data / "installer-config.json")
            import ctypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int32, ctypes.c_wchar_p]
            kernel.CreateMutexW.restype = ctypes.c_void_p
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle.restype = ctypes.c_int32
            mutex = kernel.CreateMutexW(
                None, False, "Local\\KiraBridge.Windows.Maintenance." + os.environ["USERNAME"]
            )
            if not mutex or ctypes.get_last_error() == 183:
                raise RuntimeError("Owned mutex fixture was not new")
            try:
                check("lifetime-mutex-fixture-held", True)
                install("maintenance-mutex-setup-refused", success=False)
                uninstall("maintenance-mutex-uninstall-refused", success=False)
                check(
                    "lifetime-mutex-preserves-pointer",
                    current() == first and not (app / "pending.json").exists(),
                )
            finally:
                kernel.CloseHandle(mutex)
            install("same-version-reinstall")
            check(
                "repeat-preserves-current-and-config",
                current() == first and sha(data / "installer-config.json") == config_initial,
            )
        shortcut_script = (
            "$ErrorActionPreference='Stop';$s=New-Object -ComObject WScript.Shell;@("
            + ";".join(
                "Get-ChildItem -LiteralPath '"
                + str(group_path).replace("'", "''")
                + "' -Filter '*.lnk'|ForEach-Object {"
                "$l=$s.CreateShortcut($_.FullName);"
                "@{name=$_.Name;target=$l.TargetPath;arguments=$l.Arguments}}"
                for _ in range(1)
            )
            + ")|ConvertTo-Json -Compress"
        )
        raw = run(
            ["powershell.exe", "-NoProfile", "-Command", shortcut_script], "inspect-start-menu"
        )
        shortcuts = json.loads(raw.decode("utf-8-sig"))
        report["shortcuts"] = shortcuts
        check(
            "three-correct-start-menu-targets",
            len(shortcuts) == 3
            and {Path(row["target"]).name.lower() for row in shortcuts}
            == {"launch.cmd", "configure.cmd", "unins000.exe"}
            and all(Path(row["target"]).parent == app for row in shortcuts),
        )
        status = json.loads(
            run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-STA",
                    "-File",
                    app / "windows_launcher.ps1",
                    "-Action",
                    "Status",
                    "-InstallDir",
                    app,
                ],
                "shipped-launcher-status",
            ).decode("utf-8-sig")
        )
        check(
            "launcher-reports-isolated-state",
            Path(status["data_dir"]) == data and status["version"] == "0.8.0rc33",
        )
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
            reservation.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            reservation.bind(("127.0.0.1", 18788))
        check("owned-test-port-freshly-unused", True)
        lifecycle("configure", "configure-owned-port", "--port", "18788")
        check(
            "owned-port-in-config",
            json.loads((data / "installer-config.json").read_text())["port"] == 18788,
        )
        runtime = app / "releases" / current()["release"] / "Runtime"
        log_path = work / "owned-runtime.log"
        with log_path.open("xb") as log:
            child = subprocess.Popen(
                [
                    runtime / "python.exe",
                    "-I",
                    "-B",
                    runtime / "windows_lifecycle.py",
                    "run",
                    "--install-dir",
                    app,
                ],
                cwd=app,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            original = harness.process_snapshot(child.pid)
            check("owned-process-generation-pinned", original is not None and original["running"])
            report["owned_process"] = original
            runtime_report = {"tool_samples": []}
            asyncio.run(
                harness.inspect_child(
                    child, data, log_path, "http://127.0.0.1:18788/mcp", runtime_report
                )
            )
            report["runtime_readback"] = runtime_report
            check(
                "native-auth-health-zero-tasks",
                runtime_report["unauthenticated_http_status"] == 401
                and runtime_report["runtime_pid"] == child.pid
                and runtime_report["owned_state_has_zero_tasks_before_stop"],
            )
            pointer_hash, credential_hash = (
                sha(app / "current.json"),
                sha(data / "preview-credentials.json"),
            )
            install("busy-upgrade-refused", success=False)
            uninstall("busy-uninstall-refused", success=False)
            check(
                "busy-failures-preserve-running-generation",
                child.poll() is None
                and harness.process_snapshot(child.pid) == original
                and sha(app / "current.json") == pointer_hash
                and sha(data / "preview-credentials.json") == credential_hash,
            )
            child.send_signal(signal.CTRL_BREAK_EVENT)
            try:
                child.wait(timeout=12)
                report["stop_method"] = "CTRL_BREAK to exact owned process group"
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait(timeout=8)
                report["stop_method"] = (
                    "TerminateProcess on retained owned Popen handle after CTRL_BREAK timeout"
                )
        observed = harness.process_snapshot(child.pid)
        check(
            "owned-runtime-independently-absent",
            observed is None
            or not observed["running"]
            or observed["created_100ns"] != original["created_100ns"],
        )
        child = None
        (data / "preserve-me.txt").write_bytes(
            b"Installer acceptance user file; preserve across lifecycle\n"
        )
        with contextlib.closing(sqlite3.connect(data / "bridge.sqlite3")) as db:
            with db:
                db.execute("CREATE TABLE installer_acceptance_probe (value TEXT NOT NULL)")
                db.execute(
                    "INSERT INTO installer_acceptance_probe VALUES (?)", ("RC33 data sentinel",)
                )
        preserved = snapshots()
        report["preserved_data_sha256"] = preserved
        saved_config = (data / "installer-config.json").read_bytes()
        (data / "installer-config.json").write_bytes(b"{")
        install("malformed-config-refused", success=False)
        check(
            "malformed-config-preserved",
            (data / "installer-config.json").read_bytes() == b"{" and current() == first,
        )
        (data / "installer-config.json").write_bytes(saved_config)
        synthetic = {**first, "version": "0.8.0rc34"}
        (app / "current.json").write_text(json.dumps(synthetic), encoding="utf-8")
        install("synthetic-newer-version-refused", success=False)
        check("newer-pointer-not-rewritten", current() == synthetic)
        (app / "current.json").write_text(
            json.dumps({**first, "version": "0.8.0rc32"}), encoding="utf-8"
        )
        install("synthetic-prior-version-upgrade")
        check(
            "upgrade-keeps-data-and-restores-rc33", current() == first and snapshots() == preserved
        )
        # A second owned release differs by one harmless source comment. Prepare,
        # commit and recover exercise the durable post-switch interruption path.
        fixture = work / "interruption-runtime"
        shutil.copytree(args.runtime, fixture)
        code = fixture / "windows_lifecycle.py"
        code.write_bytes(code.read_bytes() + b"\n# Native installer interruption fixture\n")
        inventory = json.loads((fixture / "runtime-manifest.json").read_text())
        inventory["files"]["windows_lifecycle.py"] = sha(code)
        inventory["release_id"] = hashlib.sha256(
            json.dumps(inventory["files"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:32]
        (fixture / "runtime-manifest.json").write_text(json.dumps(inventory), encoding="utf-8")
        transaction = work / "interruption-transaction.json"
        lifecycle(
            "prepare",
            "interruption-prepare",
            "--runtime-dir",
            fixture,
            "--transaction",
            transaction,
        )
        lifecycle("commit", "interruption-switch", "--transaction", transaction)
        check(
            "interrupted-switch-is-distinct",
            current()["release"] == inventory["release_id"] and current() != first,
        )
        lifecycle("recover", "interruption-recovery")
        check(
            "rollback-restores-prior-pointer-and-data",
            current() == first
            and snapshots() == preserved
            and not (app / "pending.json").exists()
            and not (app / "releases" / inventory["release_id"]).exists(),
        )
        uninstall("clean-uninstall")
        check(
            "application-removed-data-retained",
            not registered()
            and not (app / "current.json").exists()
            and not (app / "launch.cmd").exists()
            and not (app / "unins000.exe").exists()
            and not group_path.exists()
            and snapshots() == preserved,
        )
        install("retained-data-reinstall")
        check(
            "reinstall-preserves-credentials-db-config-user-file",
            current() == first and snapshots() == preserved,
        )
        with contextlib.closing(sqlite3.connect(data / "bridge.sqlite3")) as db:
            check(
                "sqlite-sentinel-and-integrity",
                db.execute("SELECT value FROM installer_acceptance_probe").fetchall()
                == [("RC33 data sentinel",)]
                and db.execute("PRAGMA quick_check").fetchall() == [("ok",)],
            )
        uninstall("final-uninstall")
        check(
            "final-registry-group-runtime-absent-data-retained",
            not registered()
            and not group_path.exists()
            and not (app / "current.json").exists()
            and snapshots() == preserved,
        )
        report["passed"] = True
        report["phase"] = "completed"
    except Exception as error:
        report["error_type"] = type(error).__name__
        if isinstance(error, AssertionError):
            report["failed_check"] = str(error)
        report["phase_at_failure"] = report.get("phase")
    finally:
        if child is not None and child.poll() is None:
            # Preserve unexpected task-bearing state; only the known empty own
            # instance is eligible for the bounded cleanup of the retained handle.
            if report.get("runtime_readback", {}).get("owned_state_has_zero_tasks_before_stop"):
                child.send_signal(signal.CTRL_BREAK_EVENT)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    child.wait(timeout=12)
        report["product_registry_present_after"] = registered()
        save()
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
