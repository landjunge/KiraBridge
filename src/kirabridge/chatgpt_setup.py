"""Explicit local account linking. Never takes a literal runtime key in command arguments."""

from __future__ import annotations

import getpass
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import time
import uuid
import warnings
import webbrowser
from pathlib import Path

from kirabridge.bridge_core.config import Config
from kirabridge.bridge_core.models import BridgeError
from kirabridge.install_ui import SetupUI
from kirabridge.local_runtime import LABEL, private_json, write_private
from kirabridge.task_manager.store import Store

TUNNELS_URL = "https://platform.openai.com/settings/organization/tunnels"
KEYS_URL = "https://platform.openai.com/settings/organization/api-keys"
PLUGINS_URL = "https://chatgpt.com/#settings/Connectors"


def replace_private(path: Path, value: str) -> None:
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex)
    try:
        write_private(temporary, value)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def persist_stdio_notification(config_path: Path) -> None:
    """Native runtimes connect generates JSON-as-YAML and drops optional MCP fields.

    Keep the documented lifecycle shim across subsequent starts. This completes
    a successful initialize, never synthesizes initialize or replays a tool.
    """
    profile = config_path.parent / "tunnel/kirabridge.yaml"
    settings = private_json(profile)
    mcp = settings.get("mcp")
    if not isinstance(mcp, dict) or not isinstance(mcp.get("commands"), list):
        raise BridgeError("tunnel_profile_format", "Expected the generated native stdio profile")
    mcp["stdio_send_initialized_notification"] = True
    replace_private(profile, json.dumps(settings, indent=2) + "\n")


def runtime_status(binary: str) -> dict:
    result = subprocess.run(
        [binary, "runtimes", "status", "kirabridge", "--json"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode:
        return {"connected": False, "account_setup_required": True}
    payload = json.loads(result.stdout)
    evidence = {}

    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"process_running", "healthy", "ready"} and isinstance(item, bool):
                    evidence[key] = evidence.get(key, True) and item
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(payload)
    return {
        "connected": all(evidence.get(key) for key in ("process_running", "healthy", "ready")),
        "runtime_evidence": evidence,
        "chatgpt_tool_call": "unverified",
    }


def wait_for_service(config_path: Path, *, timeout: float = 30) -> None:
    """Wait for authenticated health after a restart; never retry an execution."""
    deadline = time.monotonic() + timeout
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "kirabridge.cli",
                    "--config",
                    str(config_path),
                    "--principal",
                    "chatgpt",
                    "status",
                ],
                capture_output=True,
                text=True,
                timeout=min(6, remaining),
            )
            if result.returncode == 0:
                health = json.loads(result.stdout)
                if (
                    isinstance(health, dict)
                    and health.get("name") == "KiraBridge"
                    and health.get("api_version") == "1"
                    and health.get("dispatcher_active") is True
                ):
                    return
        except (subprocess.TimeoutExpired, ValueError):
            pass
        time.sleep(min(0.25, max(0, deadline - time.monotonic())))
    raise BridgeError(
        "service_not_ready", "Local service is not ready; check kirabridge service status"
    )


def configure_tunnel(
    config: Config, config_path: Path, tunnel_id: str, runtime_key: str, binary: str
) -> dict:
    if not re.fullmatch(r"tunnel_[a-zA-Z0-9_-]{8,128}", tunnel_id):
        raise BridgeError("invalid_tunnel", "Use the tunnel ID from your OpenAI account")
    if len(runtime_key) < 32 or any(ch.isspace() for ch in runtime_key):
        raise BridgeError("invalid_runtime_key", "Use a restricted tunnel runtime key")
    if config.credentials_file is None or not config_path.is_file():
        raise BridgeError("setup_required", "Run the private local setup first")
    key_path = config_path.parent / "openai-tunnel-runtime.key"
    if key_path.exists() or (config_path.parent / "tunnel/kirabridge.yaml").exists():
        raise BridgeError(
            "existing_tunnel", "Existing tunnel/key preserved; use setup to inspect it"
        )
    store = Store(config.state_path / "bridge.sqlite3")
    try:
        if (
            store.db.execute(
                "SELECT 1 FROM tasks WHERE state IN "
                "('created','queued','accepted','running') LIMIT 1"
            ).fetchone()
            or store.db.execute(
                "SELECT 1 FROM message_jobs WHERE state IN ('queued','running') LIMIT 1"
            ).fetchone()
        ):
            raise BridgeError("service_busy", "Wait for active local tasks before account setup")
    finally:
        store.close()
    credential_path = Path(config.credentials_file)
    credentials = private_json(credential_path)
    if "chatgpt" not in config.principals:
        policy = config.principals["local"].model_copy(deep=True)
        policy.token_env = "KIRABRIDGE_CHATGPT_TOKEN"
        section = "\n[principals.chatgpt]\n" + "".join(
            key + " = " + json.dumps(value) + "\n"
            for key, value in policy.model_dump().items()
            if value is not None
        )
        credentials["chatgpt"] = secrets.token_urlsafe(48)
        replace_private(credential_path, json.dumps(credentials))
        replace_private(config_path, config_path.read_text() + section)
        if sys.platform == "darwin":
            restarted = subprocess.run(
                ["/bin/launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{LABEL}"],
                capture_output=True,
                timeout=15,
            )
            if restarted.returncode:
                raise BridgeError("service_restart", "Restart the local KiraBridge service")
    wait_for_service(config_path)
    replace_private(key_path, runtime_key)
    command = shlex.join(
        [
            str(Path.home() / ".local/bin/kirabridge"),
            "--config",
            str(config_path.absolute()),
            "--principal",
            "chatgpt",
            "connect",
        ]
    )
    runtime_env = {**os.environ, "MCP_STDIO_SEND_INITIALIZED_NOTIFICATION": "true"}
    result = subprocess.run(
        [
            binary,
            "runtimes",
            "connect",
            "--alias",
            "kirabridge",
            "--tunnel-id",
            tunnel_id,
            "--runtime-api-key",
            "file:" + str(key_path),
            "--mcp-command",
            command,
            "--profile",
            "kirabridge",
            "--profile-dir",
            str(config_path.parent / "tunnel"),
        ],
        capture_output=True,
        text=True,
        timeout=90,
        env=runtime_env,
    )
    if result.returncode:
        raise BridgeError(
            "tunnel_access", "Tunnel setup failed; check account, workspace and Tunnels Read + Use"
        )
    persist_stdio_notification(config_path)
    return runtime_status(binary)


def verification_steps(ui, result):
    if not result.get("connected"):
        ui.say(
            "Tunnel noch nicht bereit. Nächster Schritt: kirabridge chatgpt status "
            "und lokale Runtime prüfen.",
            "Tunnel not ready. Next: kirabridge chatgpt status and inspect the local runtime.",
        )
        return {
            **result,
            "status": "tunnel_not_ready",
            "chatgpt_tool_call": "unverified",
            "next": "kirabridge chatgpt status; inspect the existing local runtime",
        }
    ui.say(
        "In ChatGPT einen privaten MCP-Server mit Verbindung Tunnel auswählen. Im "
        "Zielchat bridge_health aufrufen und Ergebnis prüfen. Ein grüner Tunnel ist "
        "noch keine ChatGPT-Abnahme.",
        "In ChatGPT select a private MCP server with Connection: Tunnel. Call "
        "bridge_health in the target chat and check the result. A green tunnel is "
        "not ChatGPT acceptance.",
    )
    ui.say(
        "Bei manueller Freigabe: kirabridge approvals öffnen. Keine Schlüssel oder "
        "Logs in den Chat kopieren.",
        "For manual task approval: open kirabridge approvals. Never paste keys or logs into chat.",
    )
    return {
        **result,
        "next": "Call bridge_health from the target ChatGPT chat and inspect the result",
        "chatgpt_tool_call": "unverified",
    }


def wizard(config: Config, config_path: Path, action: str, *, language="de") -> dict:
    from kirabridge.setup_dependencies import CLIENT_RELEASE, download_client, local_client

    binary = local_client(config_path)
    if action == "status":
        if not binary:
            return {
                "tunnel_client_installed": False,
                "connected": False,
                "next": CLIENT_RELEASE,
                "chatgpt_tool_call": "unverified",
            }
        return {"tunnel_client_installed": True, **runtime_status(binary)}
    if not sys.stdin.isatty():
        raise BridgeError(
            "interactive_setup", "Run kirabridge chatgpt setup in your local Terminal"
        )
    ui = SetupUI(language)
    ui.banner()
    if not binary:
        ui.say(
            "Offizieller Tunnel-Client fehlt. Geprüfter Download v0.0.16 vom Originalanbieter, "
            "nur für deinen Benutzer. SHA-256 wird vor Verwendung geprüft. "
            "Andere Versionen siehe offizielle Release-Seite.",
            "Official tunnel client missing. Verified v0.0.16 download from its publisher, "
            "for your user only. SHA-256 checked before use. "
            "See official releases for other versions.",
        )
        ui.say(CLIENT_RELEASE)
        if not ui.confirm("Offiziellen Client jetzt laden?", "Download the official client now?"):
            return {
                "status": "tunnel_client_pending",
                "connected": False,
                "next": CLIENT_RELEASE,
                "chatgpt_tool_call": "unverified",
            }
        binary = download_client(config_path)
    profile = config_path.parent / "tunnel/kirabridge.yaml"
    key = config_path.parent / "openai-tunnel-runtime.key"
    if profile.exists() or key.exists() or "chatgpt" in config.principals:
        state = runtime_status(binary)
        if (
            state["connected"]
            and profile.exists()
            and key.exists()
            and "chatgpt" in config.principals
        ):
            ui.say(
                "Vorhandene Tunnel-Einrichtung ist bereit. Schlüssel, Rechte und Profil "
                "bleiben unverändert.",
                "Existing tunnel setup is ready. Key, permissions and profile remain unchanged.",
            )
            return verification_steps(ui, state)
        ui.say(
            "Vorhandene oder unvollständige Einrichtung erkannt; kein Schlüssel wird "
            "ersetzt. Nächster Schritt: kirabridge chatgpt status und bestehendes "
            "Runtime-Profil lokal prüfen.",
            "Existing or incomplete setup detected; no key is replaced. Next: kirabridge "
            "chatgpt status and inspect the existing runtime profile locally.",
        )
        return {
            **state,
            "status": "existing_setup_needs_attention",
            "configuration_preserved": True,
            "next": "kirabridge chatgpt status; inspect the existing local runtime profile",
        }
    ui.step("1/3", "OpenAI-Kontozugang prüfen", "Check OpenAI account access")
    ui.say(
        "Benötigt werden ein passender ChatGPT-Workspace mit privaten "
        "MCP-Verbindungen sowie Platform-Tunnelrechte. Kontoverfügbarkeit und "
        "mögliche Kosten im eigenen Konto prüfen. Ein Codex-Login oder beliebiger "
        "API-Key ersetzt keinen Runtime-Schlüssel.",
        "You need a ChatGPT workspace with private MCP connections and Platform "
        "tunnel access. Check availability and possible charges in your account. A "
        "Codex login or ordinary API key is not a runtime key.",
    )
    ui.say(TUNNELS_URL)
    if not ui.confirm(
        "Kontofunktionen vorhanden und weiter zur Einrichtung?",
        "Account features available; continue setup?",
    ):
        return {
            "status": "account_access_pending",
            "connected": False,
            "next": TUNNELS_URL,
            "chatgpt_tool_call": "unverified",
        }
    webbrowser.open(TUNNELS_URL)
    tunnel_id = ui.ask("Tunnel-ID (beginnt mit tunnel_)", "Tunnel ID (starts with tunnel_)")
    if not re.fullmatch(r"tunnel_[a-zA-Z0-9_-]{8,128}", tunnel_id):
        raise BridgeError("invalid_tunnel", "Use the tunnel ID from your OpenAI account")
    ui.step("2/3", "Berechtigungen und Runtime-Schlüssel", "Permissions and runtime key")
    policy = config.principals.get("local")
    if policy is None:
        raise BridgeError("setup_required", "Local principal is missing")
    ui.say(
        "ChatGPT übernimmt die vorhandene lokale Policy: " + ", ".join(policy.capabilities),
        "ChatGPT will use the existing local policy: " + ", ".join(policy.capabilities),
    )
    if not ui.confirm(
        "Diesen vorhandenen Umfang für ChatGPT zulassen?", "Allow this existing scope for ChatGPT?"
    ):
        return {
            "status": "permissions_pending",
            "connected": False,
            "next": "kirabridge chatgpt setup",
            "chatgpt_tool_call": "unverified",
        }
    ui.say(
        "Eingeschränkten Runtime-Schlüssel mit Tunnels Read + Use verwenden. Tunnel "
        "anlegen/ändern benötigt getrennt Read + Manage. Geheimnis nur hier verdeckt "
        "eingeben.",
        "Use a restricted runtime key with Tunnels Read + Use. Creating/editing a "
        "tunnel separately requires Read + Manage. Enter the secret only here, "
        "hidden.",
    )
    ui.say(KEYS_URL)
    webbrowser.open(KEYS_URL)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            runtime_key = getpass.getpass(
                ui.text("Runtime-Schlüssel (verdeckt): ", "Runtime key (hidden): ")
            ).strip()
    except getpass.GetPassWarning:
        raise BridgeError(
            "secure_input_unavailable", "A local Terminal with hidden input is required"
        ) from None
    result = configure_tunnel(config, config_path, tunnel_id, runtime_key, binary)
    if result["connected"]:
        ui.step("3/3", "Im Zielchat prüfen", "Verify in the target chat")
        webbrowser.open(PLUGINS_URL)
    return verification_steps(ui, result)
