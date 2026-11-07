"""One guided flow over existing local setup and ChatGPT setup; managed files only."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from kirabridge.bridge_core.config import load_config, private_directory
from kirabridge.bridge_core.models import BridgeError
from kirabridge.chatgpt_setup import replace_private, wizard
from kirabridge.install_ui import SetupUI
from kirabridge.local_runtime import (
    LABEL,
    daemon_health,
    install_service,
    private_json,
    setup,
    write_private,
)
from kirabridge.task_manager.store import Store


def prerequisites() -> dict:
    return {
        "system": platform.system(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "service_manager": "launchd"
        if sys.platform == "darwin"
        else "systemd-user"
        if shutil.which("systemctl")
        else "unavailable",
        "agents": {name: bool(shutil.which(name)) for name in ("codex", "grok")},
        "tunnel_client": bool(shutil.which("tunnel-client")),
        "account_access": "unknown; check in the target OpenAI account",
    }


@contextmanager
def idle_queue(config):
    store = Store(config.state_path / "bridge.sqlite3")
    try:
        with store.transaction():
            tasks = store.db.execute(
                "SELECT count(*) FROM tasks WHERE state IN "
                "('created','queued','accepted','running')"
            ).fetchone()[0]
            jobs = store.db.execute(
                "SELECT count(*) FROM message_jobs WHERE state IN ('queued','running') "
                "AND (state='running' OR NOT EXISTS (SELECT 1 FROM queue_holds h "
                "WHERE h.queue_id='messages' AND h.item_id=message_jobs.message_id))"
            ).fetchone()[0]
            # Older stores have no team tables. Inspect only; an update check
            # must neither initialize a team domain nor dispatch queued work.
            team_table = store.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='team_work'"
            ).fetchone()
            team_work = (
                store.db.execute(
                    "SELECT count(*) FROM team_work WHERE state IN "
                    "('queued','dispatching','created','accepted','running','processing_result')"
                ).fetchone()[0]
                if team_table
                else 0
            )
            # External/manual assignments are durable data, without a running
            # model process; queued_manual/accepted_manual survive the update.
            if tasks or jobs or team_work:
                raise BridgeError("service_busy", "Pending/active work: finish it before updating")
            yield
    finally:
        store.close()


def quote_systemd(value):
    """Quote one ExecStart argument. systemd is not a shell and expands % and $."""
    escaped = (
        str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
    )
    return '"' + escaped + '"'


def render_linux_unit(argv):
    """User-service unit aligned with examples/kirabridge.service.

    secrets.env stays optional. A missing EnvironmentFile must not stop the server.
    Desktop session variables are intentionally absent.
    """
    if not argv:
        raise BridgeError("service_install", "Linux server command is empty")
    return (
        "[Unit]\n"
        "Description=KiraBridge private MCP bridge\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        "UMask=0077\n"
        "EnvironmentFile=-%h/.config/kirabridge/secrets.env\n"
        "ExecStart=" + " ".join(quote_systemd(part) for part in argv) + "\n"
        "Restart=on-failure\n"
        "RestartSec=3\n"
        "TimeoutStopSec=15\n"
        "NoNewPrivileges=true\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def legacy_linux_unit(argv):
    """Exact pre-server unit, accepted only for the same config and command."""
    return (
        "[Unit]\nDescription=KiraBridge private MCP bridge\nAfter=network.target\n"
        "[Service]\nType=simple\nUMask=0077\nExecStart="
        + " ".join(quote_systemd(part) for part in argv)
        + "\nRestart=on-failure\nRestartSec=3\n[Install]\nWantedBy=default.target\n"
    )


def linux_service(config_path, command, *, unit_path=None):
    if not shutil.which("systemctl"):
        raise BridgeError("service_manager_missing", "A user systemd session is required")
    unit = unit_path or Path.home() / ".config/systemd/user/kirabridge.service"
    args = [command, "--config", str(config_path), "serve", "--transport", "http"]
    body = render_linux_unit(args)
    unit.parent.mkdir(parents=True, exist_ok=True)
    if unit.is_symlink():
        raise BridgeError("service_conflict", "Existing user service symlink was preserved")
    previous = unit.read_text() if unit.exists() else None
    if previous is not None and previous not in {body, legacy_linux_unit(args)}:
        raise BridgeError("service_conflict", "Existing user service differs; it was preserved")
    if previous is not None and previous != body:
        info = unit.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise BridgeError("service_conflict", "Previous managed unit must remain owner-only")
        replace_private(unit, body)
    if not unit.exists():
        write_private(unit, body)
    for argv in (
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", unit.name],
    ):
        result = subprocess.run(argv, capture_output=True, timeout=20)
        if result.returncode:
            raise BridgeError(
                "service_install", "User systemd failed; no sudo or linger change made"
            )
    return {"loaded": True, "unit": str(unit)}


def activate_managed(config_path: Path, release_root: Path, *, service=True):
    """Only update our recorded launcher, while queues are idle. Never replace foreign setup."""
    config = load_config(str(config_path))
    manifest_path = config_path.parent / "installation.json"
    launcher = Path.home() / ".local/bin/kirabridge"
    previous = private_json(manifest_path) if manifest_path.exists() else None
    if previous and previous.get("status") == "prepared":
        previous = None
    if launcher.exists() or launcher.is_symlink():
        if (
            launcher.is_symlink()
            or not previous
            or hashlib.sha256(launcher.read_bytes()).hexdigest() != previous.get("launcher_sha256")
        ):
            raise BridgeError(
                "existing_installation", "Existing launcher preserved; see upgrade guide"
            )
    python = release_root / ".venv/bin/python3"
    if not python.is_file():
        raise BridgeError("release_incomplete", "Run install.sh from the extracted release package")
    wrapper = (
        "#!/bin/sh\nexec "
        + shlex.join([str(python), "-m", "kirabridge.cli", "--config", str(config_path)])
        + ' "$@"\n'
    )
    launcher.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = launcher.parent.stat()
    if launcher.parent.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise BridgeError(
            "unsafe_launcher", "Launcher directory must be owned and writable only by you"
        )
    with idle_queue(config):
        if previous and previous.get("service") and not service:
            raise BridgeError(
                "service_conflict", "Use the existing managed service for this update"
            )
        if previous:
            backup = config_path.parent / "backups"
            private_directory(backup)
            name = hashlib.sha256(launcher.read_bytes()).hexdigest()[:16]
            if not (backup / ("launcher-" + name)).exists():
                write_private(backup / ("launcher-" + name), launcher.read_bytes(), mode=0o700)
        replace_private(launcher, wrapper)
        launcher.chmod(0o700)
        record = {
            "release_root": str(release_root),
            "previous_root": previous.get("release_root") if previous else None,
            "launcher_sha256": hashlib.sha256(wrapper.encode()).hexdigest(),
            "service": service,
            "version": __import__("kirabridge").__version__,
        }
        try:
            if service:
                if sys.platform == "darwin":
                    install_service(config_path, command=str(launcher))
                else:
                    linux_service(config_path, str(launcher))
                if previous and previous.get("release_root") != str(release_root):
                    argv = (
                        ["/bin/launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{LABEL}"]
                        if sys.platform == "darwin"
                        else ["systemctl", "--user", "restart", "kirabridge.service"]
                    )
                    if subprocess.run(argv, capture_output=True, timeout=20).returncode:
                        raise BridgeError("service_restart", "Managed service restart failed")
            replace_private(manifest_path, json.dumps(record, indent=2) + "\n")
        except BaseException:
            # Restore only our launcher; never restore old databases or credentials.
            if previous:
                restored = backup / ("launcher-" + name)
                replace_private(launcher, restored.read_text())
                launcher.chmod(0o700)
            elif launcher.is_file() and launcher.read_text() == wrapper:
                launcher.unlink()
            raise
    return record


async def guided_install(
    config_path: Path, release_root: Path | None, language="de", *, check=False
):
    ui = SetupUI(language)
    if check:
        return {
            "prerequisites": prerequisites(),
            "configured": config_path.is_file(),
            "changes": False,
            "chatgpt_call": "unverified",
        }
    if not sys.stdin.isatty():
        raise BridgeError("interactive_setup", "Use a local Terminal; --check is read-only")
    ui.banner()
    ui.say(
        "Vibe Coding: Mit ChatGPT besprechen, über KiraBridge an Codex oder Grok übergeben.",
        "Vibe Coding: discuss with ChatGPT, delegate through KiraBridge to Codex or Grok.",
    )
    ui.step("1/4", "Voraussetzungen erkennen", "Detect prerequisites")
    found = prerequisites()
    ui.say(
        "Erkannte CLIs: " + ", ".join(k for k, v in found["agents"].items() if v) or "Keine CLIs",
        "Detected CLIs: " + ", ".join(k for k, v in found["agents"].items() if v) or "No CLIs",
    )
    if not any(found["agents"].values()):
        ui.say(
            "Codex/Grok fehlt. Die Bridge kann eingerichtet werden; Agentenaufträge erst "
            "nach CLI-Installation und Anmeldung.",
            "Codex/Grok missing. Bridge setup can continue; agent tasks need an "
            "installed, signed-in CLI.",
        )
    ui.step("2/4", "Private Einrichtung erkennen oder anlegen", "Detect or create private setup")
    existed = config_path.exists()
    if existed:
        config = load_config(str(config_path))
        ui.say(
            "Vorhandene Konfiguration erkannt. Daten, Zugänge und Rechte bleiben erhalten.",
            "Existing configuration detected. Data, credentials and permissions are preserved.",
        )
    else:
        workspace = ui.ask(
            "Projektordner (nur dieser Ordner wird freigegeben)",
            "Project folder (only this folder will be allowed)",
            str(Path.home() / "workspace/KiraBridge"),
        )
        ui.say(
            "Neue Zugänge verwenden Einzelauftragsfreigabe. Dateien/Terminal im "
            "gewählten Ordner; lokale Agentenausführung. Keine globale Dateifreigabe, "
            "kein sudo.",
            "New identities require per-task approval. Files/terminal in the selected "
            "folder; local agent execution. No global filesystem access, no sudo.",
        )
        if not ui.confirm("Diese begrenzte Einrichtung anlegen?", "Create this scoped setup?"):
            return {"status": "cancelled", "changes": False, "next": "Run install.sh when ready"}
        setup(str(Path(workspace).expanduser().absolute()), config_path, install_wrapper=False)
        write_private(config_path.parent / "installation.json", json.dumps({"status": "prepared"}))
        config = load_config(str(config_path))
    ui.step("3/4", "Lokaler Dienst", "Local service")
    # A healthy developer/custom installation is observed, never converted by rerunning setup.
    manifest = config_path.parent / "installation.json"
    custom = existed and not manifest.exists()
    if custom:
        ui.say(
            "Bestehende individuelle Installation bleibt unverändert. Updateweg siehe Anleitung.",
            "Existing custom installation is preserved. See the guide for its update procedure.",
        )
    elif release_root and ui.confirm(
        "Benutzerdienst installieren/aktualisieren (kein sudo)?",
        "Install/update the user service (no sudo)?",
    ):
        activate_managed(config_path, release_root)
    else:
        return {
            "status": "local_service_pending",
            "configuration_preserved": True,
            "next": "Run install.sh and allow the user service; no service was replaced",
        }
    health, error = {}, None
    for attempt in range(8):
        try:
            health = await daemon_health(config, "local")
            if health.get("dispatcher_active"):
                break
        except BridgeError as exc:
            error = exc.code
        if attempt < 7:
            await asyncio.sleep(0.25)
    if not health.get("dispatcher_active"):
        ui.say(
            "Dienst noch nicht bereit. Konfiguration bleibt erhalten. Nächster Schritt: "
            "kirabridge service status.",
            "Service not ready. Configuration preserved. Next: kirabridge service status.",
        )
        return {"status": "service_pending", "code": error, "next": "kirabridge service status"}
    ui.say(
        "Lokaler Dispatcher antwortet authentifiziert; dies belegt noch keine ChatGPT-Verbindung.",
        "Local dispatcher responds with authentication; this does not prove ChatGPT connectivity.",
    )
    ui.step("4/4", "ChatGPT verbinden", "Connect ChatGPT")
    if ui.confirm(
        "Jetzt durch die ChatGPT-Einrichtung führen?", "Continue with guided ChatGPT setup?"
    ):
        result = wizard(config, config_path, "setup", language=language)
        return {
            "status": "chatgpt_verification_pending",
            "local_version": health.get("version"),
            **result,
        }
    ui.say(
        "Nächster Schritt: kirabridge chatgpt setup. Die Zielchat-Abnahme steht aus.",
        "Next: kirabridge chatgpt setup. Verification from the target chat is pending.",
    )
    return {
        "status": "local_ready",
        "next": "kirabridge chatgpt setup",
        "chatgpt_call": "unverified",
        "local_version": health.get("version"),
    }
