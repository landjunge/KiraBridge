"""Owned Windows Tk/local-MCP acceptance, explicitly without a ChatGPT account.

Outer preparation installs the frozen wheel in one fresh disposable venv, never
over the protected base interpreter. The inner phase displays its own Tk UI and
proves a simulated authenticated response. It sends no desktop input. Its own
read-only test server is stopped only through the retained, generation-checked
Popen handle; production setup has no such stop operation.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import importlib.util
import json
import os
import queue
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace


def save(output, report):
    output.seek(0)
    output.write(json.dumps(report, indent=2, ensure_ascii=True) + "\n")
    output.truncate()
    output.flush()
    os.fsync(output.fileno())


def environment():
    env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "__PYVENV_LAUNCHER__", "VIRTUAL_ENV"):
        env.pop(name, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def stage(report, persist, name, operation=""):
    """Persist the intended step before dispatch; cleanup never overwrites it."""
    report.update(stage=name, operation=operation)
    persist()


def public_ui_status(state):
    """Only already-public presenter fields; never prompts, replies or entry values."""
    public = {}
    for name in ("message", "next_action", "operation"):
        value = getattr(state, name, None)
        maximum = 64 if name == "operation" else 2000
        if type(value) is str and len(value) <= maximum:
            public[name] = value
    for name in (
        "busy", "consent", "local_ready", "client_ready", "connection_saved",
        "connected", "verification_pending", "verified",
    ):
        value = getattr(state, name, None)
        if type(value) is bool:
            public[name] = value
    return public


def bundled_client(source):
    from kirabridge.windows_setup_client import ARCHIVE_SHA256, ARCHIVE_SIZE, ASSET

    archive = source.parent / "tools" / ASSET
    with archive.open("rb") as handle:
        data = handle.read(ARCHIVE_SIZE + 1)
    if len(data) != ARCHIVE_SIZE or hashlib.sha256(data).hexdigest() != ARCHIVE_SHA256:
        raise RuntimeError("Frozen bundled official client failed its size/hash guard")
    return data, {"asset": ASSET, "size": len(data), "sha256": ARCHIVE_SHA256}


def prepare_client_cache(source, state):
    from kirabridge.private_files import write_private

    data, receipt = bundled_client(source)
    # Exclusive, durable private IO. Existing state/cache is never replaced.
    write_private(state / "bundled-client.zip", data)
    return {**receipt, "private_test_cache_written": True, "network_download_required": False}


def prepare_command(arguments, report, label, *, timeout=150, allow_failure=False):
    report["preparation_steps"].append({"name": label, "exit_code": None})
    result = subprocess.run(
        arguments,
        env=environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=False,
    )
    report["preparation_steps"][-1]["exit_code"] = result.returncode
    if result.returncode and not allow_failure:
        raise RuntimeError("Owned isolated preparation failed")
    return result.returncode


def outer(output, report):
    from kirabridge.bridge_core.config import private_directory

    source = Path(__file__).resolve().parents[1]
    tree = ast.parse((source / "src/kirabridge/__init__.py").read_text(encoding="utf-8"))
    version = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)
    )
    wheel = source.parent / "wheels" / f"kirabridge-{version}-py3-none-any.whl"
    if not wheel.is_file():
        raise RuntimeError("Frozen wheel beside source is required")
    stage(report, lambda: save(output, report), "verify_bundled_client")
    _, report["bundled_client"] = bundled_client(source)
    report["candidate_wheel_sha256"] = hashlib.sha256(wheel.read_bytes()).hexdigest()
    work = Path(output.name).parent / ("setup-acceptance-" + uuid.uuid4().hex)
    private_directory(work)
    runtime = work / "Runtime"
    report["isolated_test_work"] = str(work)
    report["state_retained_for_reconciliation"] = True
    stage(report, lambda: save(output, report), "fresh_venv")
    base = str(getattr(sys, "_base_executable", sys.executable))
    prepare_command(
        [base, "-I", "-B", "-m", "venv", "--system-site-packages", "--without-pip", str(runtime)],
        report,
        "fresh_venv",
    )
    python = runtime / "Scripts/python.exe"
    stage(report, lambda: save(output, report), "offline_wheel_install")
    prepare_command(
        [
            str(python),
            "-I",
            "-B",
            "-m",
            "pip",
            "install",
            "--isolated",
            "--no-index",
            "--no-deps",
            "--ignore-installed",
            "--no-compile",
            "--disable-pip-version-check",
            "--no-user",
            str(wheel),
        ],
        report,
        "offline_wheel_only",
    )
    inner_output = work / "inner-receipt.json"
    report["phase"] = "owned_inner_gui_and_mcp"
    stage(report, lambda: save(output, report), "inner_acceptance")
    exit_code = prepare_command(
        [
            str(python),
            "-I",
            "-B",
            str(Path(__file__).resolve()),
            "--inner",
            "--output",
            str(inner_output),
        ],
        report,
        "inner_acceptance",
        timeout=300,
        allow_failure=True,
    )
    inner_raw = inner_output.read_bytes()
    inner_report = json.loads(inner_raw)
    preparation = report["preparation_steps"]
    report.update(inner_report)
    report["preparation_steps"] = preparation
    report["inner_exit_code"] = exit_code
    report["inner_receipt_sha256"] = hashlib.sha256(inner_raw).hexdigest()
    report["fresh_venv_wheel_installation"] = True
    if exit_code != 0 or inner_report.get("passed") is not True:
        raise RuntimeError("Original inner receipt did not pass")


def fresh_port():
    for _ in range(8):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        if port not in (8765, 8766, 8767, 8768):
            return port
    raise RuntimeError("No separate ephemeral test port")


def client_helper():
    path = Path(__file__).with_name("windows_setup_client_acceptance.py")
    spec = importlib.util.spec_from_file_location("native_setup_client_checks", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Official-client acceptance helper missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.verify_client


async def authenticated_check(controller, challenge):
    from kirabridge.mcp_gateway.client import MCPClientPool, Peer
    from kirabridge.private_files import private_json

    token = private_json(controller.state_dir / "preview-credentials.json")["local"]
    async with MCPClientPool(call_timeout=10) as clients:
        await clients.connect(Peer("setup-native", url=controller.endpoint, token=token))
        reply = await clients.call("setup-native", "read_query", {"query": challenge["query"]})
        value = reply.structuredContent
        if reply.isError or not isinstance(value, dict) or value.get("error"):
            raise RuntimeError("Authenticated local verification failed")
        tasks = await clients.call("setup-native", "task_list", {})
        if tasks.isError or tasks.structuredContent.get("tasks") != []:
            raise RuntimeError("Own test runtime has unexpected tasks")
    if value.get("simulated") is not True or value.get("cloud_attested") is not False:
        raise RuntimeError("Simulation marker missing from authenticated reply")
    return value["response_code"], token


async def require_zero_tasks(controller):
    from kirabridge.mcp_gateway.client import MCPClientPool, Peer
    from kirabridge.private_files import private_json

    token = private_json(controller.state_dir / "preview-credentials.json")["local"]
    async with MCPClientPool(call_timeout=10) as clients:
        await clients.connect(Peer("setup-cleanup", url=controller.endpoint, token=token))
        reply = await clients.call("setup-cleanup", "task_list", {})
        if (
            reply.isError
            or not isinstance(reply.structuredContent, dict)
            or reply.structuredContent.get("tasks") != []
        ):
            raise RuntimeError("Own test runtime tasks unresolved; preserve its original process")


def inner(output, report):
    stage(report, lambda: save(output, report), "installed_runtime_check")
    import tkinter as tk

    import kirabridge.windows_setup_runtime as runtime_module
    from kirabridge.bridge_core.config import private_directory
    from kirabridge.windows_setup import WindowsSetup
    from kirabridge.windows_setup_client import find_client
    from kirabridge.windows_setup_runtime import listeners, process_identity, same_process
    from kirabridge.windows_setup_ui import WindowsSetupApp

    package = __import__("kirabridge")
    expected_site = Path(sys.prefix) / "Lib/site-packages/kirabridge"
    if (
        Path(package.__file__).resolve().parent != expected_site.resolve()
        or sys.prefix == sys.base_prefix
    ):
        raise RuntimeError("Native inner phase must use the freshly installed wheel")
    port = fresh_port()
    state = Path(output.name).parent / "PrivateSetupState"
    if state.exists():
        raise RuntimeError("Original setup state exists; never replay acceptance")
    protected_before = {str(p): listeners(p) for p in (8765, 8766, 8767, 8768)}
    protected_processes = {
        str(row["pid"]): process_identity(row["pid"])
        for rows in protected_before.values()
        for row in rows
    }
    stage(report, lambda: save(output, report), "private_test_client_cache")
    private_directory(state)
    report["bundled_client"] = prepare_client_cache(Path(__file__).resolve().parents[1], state)
    stage(report, lambda: save(output, report), "controller_create")
    controller = WindowsSetup(state_dir=state, port=port)
    report.update(
        version=package.__version__,
        ephemeral_port=port,
        candidate_installed_package=True,
        protected_ports_before=protected_before,
    )
    report_lock = threading.RLock()

    def persist():
        with report_lock:
            save(output, report)

    captured, original_subprocess = [], runtime_module.subprocess

    def capture_popen(*args, **kwargs):
        report["server_start_attempted"] = None
        persist()
        child = original_subprocess.Popen(*args, **kwargs)
        captured.append(child)
        record = process_identity(child.pid)
        report["server_start_attempted"] = True
        report["owned_server_initial"] = record
        persist()
        return child

    # Isolate the observer to this module, not the shared subprocess module.
    runtime_module.subprocess = SimpleNamespace(
        Popen=capture_popen, CREATE_NEW_CONSOLE=subprocess.CREATE_NEW_CONSOLE
    )
    stage(report, persist, "native_tk_create")
    root = tk.Tk()
    app = WindowsSetupApp(root, controller)
    root.update_idletasks()
    root.update()
    gui_hwnd = root.winfo_id()
    if (
        app.presenter.state.consent
        or app.consent_value.get()
        or str(app.start_button.cget("state")) != "disabled"
    ):
        raise RuntimeError("Consent must be unchecked before native setup")
    if not root.winfo_ismapped() or not app.runtime_key.get() == "":
        raise RuntimeError("Owned native Tk UI did not become visible")
    if [bool(page.winfo_ismapped()) for page in app.pages] != [True, False, False, False]:
        raise RuntimeError("Hidden setup fields must not be mapped or take keyboard focus")
    report.update(
        gui_native_smoke=True,
        tcl_patchlevel=str(root.tk.call("info", "patchlevel")),
        consent_default_unchecked=True,
    )
    # Explicitly find the masked Entry without evaluating cget('show') on buttons.
    entries = [w for w in app.controls if w.winfo_class() == "TEntry"]
    if not any(w.cget("show") for w in entries):
        raise RuntimeError("No masked runtime-key field in native UI")
    report["runtime_key_field_masked"] = True
    commands = queue.Queue()

    def ui(function):
        done, result = threading.Event(), []
        commands.put((function, done, result))
        if not done.wait(8):
            raise RuntimeError("Own Tk thread stopped responding")
        if isinstance(result[0], BaseException):
            raise result[0]
        return result[0]

    def pump():
        while True:
            try:
                function, done, result = commands.get_nowait()
            except queue.Empty:
                break
            try:
                result.append(function())
            except BaseException as error:
                result.append(error)
            finally:
                done.set()
        if not app.presenter._closed:
            root.after(25, pump)

    def action(operation, function, *, timeout=150):
        stage(report, persist, "presenter_action", operation)
        if ui(function) is not True:
            raise RuntimeError("Own GUI rejected acceptance action")
        deadline = time.monotonic() + timeout
        while ui(lambda: app.presenter.state.busy):
            if time.monotonic() >= deadline:
                raise RuntimeError("Own GUI action remains unresolved; no retry")
            time.sleep(0.02)
        report["last_ui_status"] = ui(lambda: public_ui_status(app.presenter.state))
        persist()

    def worker():
        original = None
        try:
            action("inspect", app.presenter.inspect)
            stage(report, persist, "test_consent")
            ui(lambda: app.consent_value.set(True))
            ui(lambda: app.presenter.consent(True))
            report["consent_programmatic_test_only"] = True
            action("start_local", app.presenter.start_local)
            if not ui(lambda: app.presenter.state.local_ready) or len(captured) != 1:
                raise RuntimeError("Actual controller did not start exactly one owned runtime")
            original = report["owned_server_initial"]
            if not original or not same_process(original):
                raise RuntimeError("Own runtime generation not pinned")
            action("install_client", app.presenter.install_client, timeout=150)
            binary = find_client(state)
            if not binary or not ui(lambda: app.presenter.state.client_ready):
                raise RuntimeError("Official client was not installed/checked")
            stage(report, persist, "local_health_check")
            health = controller._require_local()
            verification = controller._verification(health)
            stage(report, persist, "begin_simulated_verification", "begin_verification")
            challenge = verification.begin_verification(simulated=True)
            stage(report, persist, "authenticated_local_mcp", "read_query")
            response, bearer = asyncio.run(authenticated_check(controller, challenge))
            stage(report, persist, "official_client_checks", "version_profile_doctor")
            report["official_client_checks"] = client_helper()(
                binary, state, controller.endpoint, bearer
            )
            bearer = None
            if report["official_client_checks"].get("passed") is not True:
                raise RuntimeError("Official client acceptance did not pass")
            ui(
                lambda: app.presenter._render(
                    prompt=challenge["prompt"], verification_pending=True, verified=False, step=2
                )
            )
            report["gui_prompt_scope"] = (
                "Real service challenge with simulated=True; no tunnel/account"
            )
            action("finish_verification", lambda: app.presenter.finish_verification(response))
            response = None
            stage(report, persist, "simulation_proof_check")
            proof = verification.public_proof()
            if (
                proof.get("simulated") is not True
                or proof.get("local_test_verified") is not True
                or proof.get("cloud_attested") is not False
            ):
                raise RuntimeError("Actual local simulation proof is missing")
            if ui(lambda: app.presenter.state.verified):
                raise RuntimeError("Simulation incorrectly marked ChatGPT complete")
            if "noch nicht bestätigt" not in ui(lambda: app.finish_title.get()):
                raise RuntimeError("Native GUI final heading incorrectly claims completion")
            report.update(
                authenticated_roundtrip_simulated=True,
                cloud_attested=False,
                simulation_does_not_mark_gui_complete=True,
                public_proof=proof,
            )
            report["passed"] = True
            stage(report, persist, "simulation_proved_no_cloud_attestation")
        except BaseException as error:
            report["passed"] = False
            report["error_type"] = type(error).__name__
            code = getattr(error, "code", None)
            if isinstance(code, str) and len(code) <= 64 and code.replace("_", "").isalnum():
                report["error_code"] = code
            try:
                report["failed_ui_status"] = ui(lambda: public_ui_status(app.presenter.state))
            except BaseException as diagnostic_error:
                report["ui_diagnostic_error_type"] = type(diagnostic_error).__name__
            persist()
        finally:
            try:
                report["cleanup_stage"] = "owned_child_identity"
                persist()
                if len(captured) == 1:
                    child = captured[0]
                    original = original or report.get("owned_server_initial")
                    if not original or not same_process(original) or child.pid != original["pid"]:
                        raise RuntimeError("Original test runtime cannot be safely stopped")
                    # Contact only this pinned runtime and refuse cleanup with active tasks.
                    report["cleanup_stage"] = "owned_child_health_and_task_zero"
                    persist()
                    controller._require_local()
                    asyncio.run(require_zero_tasks(controller))
                    report["cleanup_zero_tasks_verified"] = True
                    report["cleanup_own_child_attempted"] = None
                    report["cleanup_stage"] = "owned_child_stop"
                    persist()
                    try:
                        child.send_signal(signal.CTRL_BREAK_EVENT)
                        child.wait(timeout=3)
                        report["stop_method"] = "CTRL_BREAK exact owned child"
                    except (OSError, subprocess.TimeoutExpired):
                        if child.poll() is None:
                            if not same_process(original):
                                raise RuntimeError(
                                    "Test runtime generation changed before owned fallback"
                                ) from None
                            # Retained Popen HANDLE; test runtime only, never a PID kill.
                            child.terminate()
                            child.wait(timeout=8)
                            report["stop_method"] = (
                                "Exact retained test-child Popen terminate fallback"
                            )
                        else:
                            report["stop_method"] = "Own child exited after CTRL_BREAK request"
                    report["cleanup_own_child_attempted"] = True
                    report["cleanup_stage"] = "owned_child_independent_absence"
                    persist()
                    current = process_identity(original["pid"])
                    absent = (
                        not current
                        or current["created_100ns"] != original["created_100ns"]
                        or not current["running"]
                    )
                    report["independent_original_process_absent"] = absent
                    if not absent or listeners(port):
                        raise RuntimeError("Own runtime absence not independently confirmed")
                elif captured:
                    raise RuntimeError("Unexpected multiple owned runtime starts; preserve all")
                report["cleanup_stage"] = "protected_runtime_readback"
                persist()
                if {str(p): listeners(p) for p in (8765, 8766, 8767, 8768)} != protected_before:
                    raise RuntimeError("Protected listener observations changed")
                if any(
                    process_identity(int(pid)) != expected
                    for pid, expected in protected_processes.items()
                ):
                    raise RuntimeError("Protected runtime generations changed")
                report["protected_ports_unchanged"] = True
                report["cleanup_stage"] = "complete"
            except BaseException as error:
                report["passed"] = False
                report["cleanup_error_type"] = type(error).__name__
                code = getattr(error, "code", None)
                if isinstance(code, str) and len(code) <= 64 and code.replace("_", "").isalnum():
                    report["cleanup_error_code"] = code
            finally:
                try:
                    controller.close()
                except BaseException as error:
                    report["passed"] = False
                    report["lease_release_error_type"] = type(error).__name__
                finally:
                    runtime_module.subprocess = original_subprocess
                    persist()
                    try:
                        ui(lambda: app.presenter.close())
                    except BaseException:
                        pass

    root.after(25, pump)
    thread = threading.Thread(target=worker, name="native-setup-acceptance", daemon=True)
    thread.start()
    root.mainloop()
    thread.join(timeout=15)
    if thread.is_alive():
        raise RuntimeError("Original setup worker remains active")
    import ctypes

    user = ctypes.WinDLL("user32", use_last_error=True)
    user.IsWindow.argtypes, user.IsWindow.restype = [ctypes.c_void_p], ctypes.c_int32
    report["own_gui_closed"] = not bool(user.IsWindow(gui_hwnd))
    if not report["own_gui_closed"]:
        raise RuntimeError("Original owned Tk HWND remains alive")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inner", action="store_true")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Run only inside the owned Windows guest")
    try:
        output = args.output.open("x+", encoding="utf-8")
    except FileExistsError:
        parser.error("Original receipt exists; reconcile it, never replay acceptance")
    report = {
        "passed": False,
        "platform": "nt",
        "gui_native_smoke": False,
        "authenticated_roundtrip_simulated": False,
        "cloud_attested": False,
        "keyboard_events_requested": 0,
        "clipboard_used": False,
        "window_actions_requested": 0,
        "account_access_attempted": False,
        "automatic_retry": False,
        "preparation_steps": [],
    }
    with output:
        save(output, report)
        try:
            (inner if args.inner else outer)(output, report)
        except BaseException as error:
            report["passed"] = False
            report.setdefault("error_type", type(error).__name__)
        finally:
            save(output, report)
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
