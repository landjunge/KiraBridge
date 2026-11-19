"""Private browser login and a separate, loopback-only local operator service."""

from __future__ import annotations

import hashlib
import hmac
import os
import plistlib
import secrets
import shlex
import subprocess
import sys
import time
import uuid
import webbrowser
from pathlib import Path

import httpx

from kirabridge.approval_console import ORIGIN, PORT, ApprovalConsole, signature, signed_token
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config, private_directory
from kirabridge.bridge_core.models import BridgeError
from kirabridge.local_runtime import private_json, write_private
from kirabridge.operator_application import operator_application

LABEL = "com.kirabridge.approvals"


def console_key(config_path: Path) -> str:
    import json

    private_directory(config_path.parent)
    path = config_path.parent / "console-credentials.json"
    if not path.exists():
        try:
            write_private(path, json.dumps({"token": secrets.token_urlsafe(48)}))
        except FileExistsError:
            pass
    key = private_json(path).get("token", "")
    if not isinstance(key, str) or len(key) < 32:
        raise BridgeError("unsafe_credentials", "Invalid console credential")
    return key


def install_console_service(config_path: Path) -> None:
    if sys.platform != "darwin":
        raise BridgeError("console_start", "Start kirabridge approval-server in a local terminal")
    path = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    path.parent.mkdir(parents=True, exist_ok=True)
    arguments = [
        sys.executable,
        "-m",
        "kirabridge.cli",
        "--config",
        str(config_path),
        "approval-server",
    ]
    if path.exists():
        if plistlib.loads(path.read_bytes()).get("ProgramArguments") != arguments:
            raise BridgeError("service_conflict", "Existing approval service differs")
    else:
        write_private(
            path,
            plistlib.dumps(
                {
                    "Label": LABEL,
                    "ProgramArguments": arguments,
                    "RunAtLoad": True,
                    "KeepAlive": {"SuccessfulExit": False},
                    "ThrottleInterval": 3,
                    "Umask": 0o077,
                    "ProcessType": "Background",
                    "EnvironmentVariables": {
                        "HOME": str(Path.home()),
                        "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                        "LANG": "en_US.UTF-8",
                    },
                }
            ),
        )
    target = f"gui/{os.getuid()}"
    result = subprocess.run(
        ["/bin/launchctl", "print", f"{target}/{LABEL}"], capture_output=True, timeout=10
    )
    command = (
        ["/bin/launchctl", "bootstrap", target, str(path)]
        if result.returncode
        else ["/bin/launchctl", "kickstart", f"{target}/{LABEL}"]
    )
    if subprocess.run(command, capture_output=True, timeout=15).returncode:
        raise BridgeError("console_start", "Could not start the local approval service")


def _reload_console_service(path: Path, *, bootstrap_if_unloaded: bool = False) -> None:
    """Restart the approvals job from `path`.

    A job that is not loaded stays unloaded, unless `bootstrap_if_unloaded` is set
    (rollback after a failed reload, where bootout may already have unloaded it).
    """
    target = f"gui/{os.getuid()}"
    loaded = subprocess.run(
        ["/bin/launchctl", "print", f"{target}/{LABEL}"], capture_output=True, timeout=10
    )
    if not loaded.returncode:
        if subprocess.run(
            ["/bin/launchctl", "bootout", f"{target}/{LABEL}"], capture_output=True, timeout=15
        ).returncode:
            raise BridgeError("console_start", "Could not stop the local approval service")
    elif not bootstrap_if_unloaded:
        return
    if subprocess.run(
        ["/bin/launchctl", "bootstrap", target, str(path)], capture_output=True, timeout=15
    ).returncode:
        raise BridgeError("console_start", "Could not start the local approval service")


def reconcile_console_service(config_path: Path, interpreter: str) -> dict:
    """Point an existing approvals LaunchAgent at the release interpreter.

    Only our exact known definition (same label, module, config and command, differing
    only in the interpreter) is changed. Other keys, the config and credentials are
    untouched. The previous plist is kept byte-exact beside it and restored if the
    reload fails. A missing service is not created here.
    """
    result = {"path": None, "changed": False, "backup": None}
    if sys.platform != "darwin":
        return result
    path = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    result["path"] = str(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise BridgeError("service_conflict", "Symlinked approval service preserved")
    if not path.exists():
        return result
    old = path.read_bytes()
    try:
        actual = plistlib.loads(old)
    except (ValueError, plistlib.InvalidFileException) as exc:
        raise BridgeError("service_conflict", "Invalid approval service file preserved") from exc
    tail = ["-m", "kirabridge.cli", "--config", str(config_path), "approval-server"]
    arguments = actual.get("ProgramArguments")
    if (
        actual.get("Label") != LABEL
        or not isinstance(arguments, list)
        or not arguments
        or arguments[1:] != tail
        or not isinstance(arguments[0], str)
    ):
        raise BridgeError("service_conflict", "Custom approval service definition preserved")
    if arguments[0] == interpreter:
        return result
    digest = hashlib.sha256(old).hexdigest()
    backup = path.with_name(path.name + ".backup-" + digest[:16])
    if backup.exists() or backup.is_symlink():
        if backup.is_symlink() or backup.read_bytes() != old:
            raise BridgeError("service_conflict", "Approval service backup differs; preserved")
    else:
        write_private(backup, old)
    updated = {**actual, "ProgramArguments": [interpreter, *tail]}
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex)
    try:
        write_private(temporary, plistlib.dumps(updated))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    result.update(changed=True, backup=str(backup))
    try:
        _reload_console_service(path)
    except BaseException as failure:
        # Keep the original failure; a rollback failure is only noted on it.
        try:
            restore_console_service(result, bootstrap_if_unloaded=True)
        except Exception as rollback:
            failure.add_note(f"Approval service rollback failed: {type(rollback).__name__}")
        raise
    return result


def restore_console_service(update: dict, *, bootstrap_if_unloaded: bool = False) -> None:
    """Restore only the plist changed by `reconcile_console_service`, then reload it.

    With `bootstrap_if_unloaded`, an unloaded job (e.g. after a failed reload) is
    bootstrapped from the restored plist; a failure there raises BridgeError.
    """
    if not update.get("changed") or not update.get("backup"):
        return
    path = Path(update["path"])
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex)
    try:
        write_private(temporary, Path(update["backup"]).read_bytes())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    _reload_console_service(path, bootstrap_if_unloaded=bootstrap_if_unloaded)


def probe(client: httpx.Client, key: str) -> str | None:
    challenge = secrets.token_hex(16)
    try:
        response = client.get(ORIGIN + "/health", headers={"X-KiraBridge-Challenge": challenge})
    except (httpx.ConnectError, httpx.TimeoutException):
        return None
    try:
        payload = response.json()
        instance = payload["instance"]
        expected = signature(key, "probe", challenge + "." + instance)
        if (
            response.status_code != 200
            or payload.get("name") != "KiraBridge approvals"
            or not hmac.compare_digest(payload.get("proof", ""), expected)
        ):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise BridgeError(
            "console_conflict", "Port 8766 is not this private KiraBridge console"
        ) from None
    return instance


def open_console(config_path: Path) -> dict:
    key = console_key(config_path)
    with httpx.Client(trust_env=False, timeout=2, follow_redirects=False) as client:
        instance = probe(client, key)
        if instance is None:
            install_console_service(config_path)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                instance = probe(client, key)
                if instance is not None:
                    break
                time.sleep(0.2)
        if instance is None:
            raise BridgeError("console_start", "The local approval page is not ready")
    # The one-use ticket is passed in a POST body from a private file. No credential
    # is put in a URL, a process argument, a launchd plist, or terminal output.
    ticket = signed_token(key, "login:" + instance)
    page = (
        '<!doctype html><html lang="de"><meta charset="utf-8">'
        '<meta name="referrer" content="no-referrer"><title>KiraBridge öffnen</title>'
        "<body><p>Lokale KiraBridge-Freigaben öffnen …</p>"
        f'<form method="post" action="{ORIGIN}/login">'
        f'<input type="hidden" name="ticket" value="{ticket}">'
        '<button type="submit">Freigaben öffnen</button></form>'
        "<script>document.forms[0].submit()</script></body></html>"
    )
    destination = config_path.parent / "approval-login.html"
    temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex)
    try:
        write_private(temporary, page)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    native = Path.home() / "Applications/KiraBridge.app"
    if os.environ.get("KIRABRIDGE_CONSOLE_EMBED") == "1":
        opened = False
    elif sys.platform == "darwin" and native.is_dir():
        result = subprocess.run(
            ["/usr/bin/open", "-a", str(native)],
            capture_output=True,
            timeout=10,
        )
        opened = result.returncode == 0
    elif sys.platform == "darwin":
        result = subprocess.run(
            ["/usr/bin/open", str(destination)], capture_output=True, timeout=10
        )
        opened = result.returncode == 0
    else:
        opened = webbrowser.open(destination.as_uri())
    launcher = config_path.parent / "KiraBridge-Freigaben.command"
    if not launcher.exists():
        command = shlex.join(
            [sys.executable, "-m", "kirabridge.cli", "--config", str(config_path), "approvals"]
        )
        write_private(launcher, "#!/bin/sh\nexec " + command + "\n", mode=0o700)
    desktop = Path.home() / "Desktop/KiraBridge Freigaben.command"
    if sys.platform == "darwin" and desktop.parent.is_dir() and not desktop.exists():
        try:
            desktop.symlink_to(launcher)
        except FileExistsError:
            pass
    return {
        "url": ORIGIN + "/",
        "opened": opened,
        "launcher": str(launcher),
        "login_file": str(destination),
    }


async def serve_console(config: Config, config_path: Path) -> None:
    import uvicorn

    bridge = Bridge(config)
    try:
        server = uvicorn.Server(
            uvicorn.Config(
                ApprovalConsole(operator_application(bridge), console_key(config_path)),
                host="127.0.0.1",
                port=PORT,
                access_log=False,
                log_level="critical",
                limit_concurrency=16,
                timeout_keep_alive=5,
            )
        )
        await server.serve()
    finally:
        bridge.store.close()
