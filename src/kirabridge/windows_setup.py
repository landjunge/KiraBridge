"""German Windows setup controller; installation and account actions are explicit."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

from kirabridge import __version__
from kirabridge.bridge_core.config import private_directory
from kirabridge.bridge_core.models import BridgeError
from kirabridge.private_files import private_json, write_private
from kirabridge.windows_preview import (
    CAPABILITIES,
    CREDENTIAL_SCHEMA,
    require_desktop,
    require_windows,
)
from kirabridge.windows_setup_runtime import SetupLease, launch_server, listeners, saved_server

DEFAULT_PORT = 8768
TUNNEL_ID = re.compile(r"tunnel_(?:[a-z0-9]{4}_)?[a-z0-9]{32}\Z")


def result(state: str, message: str, next_action: str, **facts) -> dict:
    return {
        "state": state,
        "message": message,
        "next_action": next_action,
        "verified": False,
        **facts,
    }


async def local_health(endpoint: str, token: str) -> dict:
    from kirabridge.mcp_gateway.client import MCPClientPool, Peer

    async with asyncio.timeout(8), MCPClientPool(call_timeout=5) as clients:
        await clients.connect(Peer("windows-setup", url=endpoint, token=token))
        response = await clients.call("windows-setup", "bridge_health", {})
        data = response.structuredContent
        if response.isError or not isinstance(data, dict) or data.get("error"):
            raise BridgeError("setup_health_failed", "Local health check failed")
        return data


class WindowsSetup:
    def __init__(self, state_dir: Path | None = None, *, port: int = DEFAULT_PORT):
        if type(port) is not int or not 1024 <= port <= 65535:
            raise BridgeError("invalid_port", "Invalid setup port")
        local = os.environ.get("LOCALAPPDATA")
        self.state_dir = state_dir or (Path(local) / "KiraBridgeWindowsSetup" if local else None)
        self.port = port
        self.endpoint = f"http://127.0.0.1:{port}/mcp"
        self.lease = None
        self.verification = None

    def _prepare(self):
        require_windows()
        if self.state_dir is None:
            raise BridgeError("preview_state_missing", "LOCALAPPDATA is unavailable")
        if self.lease is None:
            self.lease = SetupLease(self.state_dir)

    def close(self):
        if self.lease:
            self.lease.close()
            self.lease = None

    def _owned_health(self):
        record = saved_server(self.state_dir)
        if record is None:
            return None
        if record.get("port") != self.port or listeners(self.port) != [
            {"pid": record["pid"], "host": "127.0.0.1"}
        ]:
            raise BridgeError("setup_listener_changed", "Original setup listener unavailable")
        payload = private_json(self.state_dir / "preview-credentials.json")
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schema", "local"}
            or payload.get("schema") != CREDENTIAL_SCHEMA
            or not isinstance(payload.get("local"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", payload["local"])
        ):
            raise BridgeError("preview_credentials_invalid", "Existing credentials preserved")
        try:
            data = asyncio.run(local_health(self.endpoint, payload["local"]))
        except BridgeError:
            raise
        except Exception:
            raise BridgeError("setup_health_failed", "Local health check failed") from None
        if (
            data.get("version") != __version__
            or not data.get("dispatcher_active")
            or data.get("runtime", {}).get("pid") != record["pid"]
            or data.get("discovery", {}).get("capabilities")
            != sorted([*CAPABILITIES, "windows.setup.verify"])
        ):
            raise BridgeError("setup_version_mismatch", "Existing runtime differs; preserved")
        from kirabridge.windows_setup_runtime import same_process

        if not same_process(record) or listeners(self.port) != [
            {"pid": record["pid"], "host": "127.0.0.1"}
        ]:
            raise BridgeError("setup_listener_changed", "Setup process changed during health check")
        return data

    def _saved_connection(self):
        """Validate saved configuration without starting a process or returning a key."""
        folder = self.state_dir / "connection"
        if not os.path.lexists(folder):
            return None
        private_directory(folder)
        identity, key = folder / "identity.json", folder / "runtime.key"
        identity_exists, key_exists = os.path.lexists(identity), os.path.lexists(key)
        if not identity_exists and not key_exists:
            return None
        if not identity_exists or not key_exists:
            raise BridgeError("setup_start_unknown", "Incomplete connection preserved")
        previous = private_json(identity)
        if (
            not isinstance(previous, dict)
            or set(previous) != {"tunnel_id", "endpoint"}
            or not isinstance(previous.get("tunnel_id"), str)
            or TUNNEL_ID.fullmatch(previous["tunnel_id"]) is None
            or previous.get("endpoint") != self.endpoint
        ):
            raise BridgeError("existing_tunnel", "Existing connection preserved")
        from kirabridge.windows_setup_client import read_private

        try:
            saved_key = read_private(key, 512).decode("ascii")
        except UnicodeError:
            raise BridgeError("invalid_runtime_key", "Existing runtime key preserved") from None
        if not 32 <= len(saved_key) <= 512 or any(char.isspace() for char in saved_key):
            raise BridgeError("invalid_runtime_key", "Existing runtime key preserved")
        return previous

    def _connection_facts(self):
        from kirabridge.windows_setup_client import find_client

        return {
            "connection_saved": self._saved_connection() is not None,
            "client_installed": find_client(self.state_dir) is not None,
        }

    def inspect(self):
        require_windows()
        require_desktop()
        self._prepare()
        health = self._owned_health()
        return result(
            "local_ready" if health else "windows_ready",
            "KiraBridge läuft auf diesem PC." if health else "Windows ist bereit für KiraBridge.",
            "Weiter zu Schritt 2: Verbindung vorbereiten."
            if health
            else "Klicke auf „KiraBridge starten“.",
            local_ready=health is not None,
            version=__version__,
            **self._connection_facts(),
        )

    def start_local(self):
        self._prepare()
        require_desktop()
        health = self._owned_health()
        if health:
            return result(
                "local_ready",
                "KiraBridge läuft bereits auf diesem PC.",
                "Weiter zu Schritt 2: Verbindung vorbereiten.",
                local_ready=True,
                **self._connection_facts(),
            )
        record = launch_server(self.state_dir, self.port)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            from kirabridge.windows_setup_runtime import same_process

            if not same_process(record):
                raise BridgeError("setup_start_unknown", "Setup child no longer matches")
            try:
                health = self._owned_health()
            except (FileNotFoundError, BridgeError) as error:
                if isinstance(error, BridgeError) and error.code not in {
                    "setup_listener_changed",
                    "setup_health_failed",
                }:
                    raise
                time.sleep(0.15)
                continue
            if health:
                return result(
                    "local_ready",
                    "KiraBridge läuft jetzt auf diesem PC.",
                    "Lass das zusätzliche KiraBridge-Fenster geöffnet. Weiter zu Schritt 2.",
                    local_ready=True,
                    **self._connection_facts(),
                )
        raise BridgeError("setup_start_pending", "Server start remains unconfirmed; do not repeat")

    def install_client(self):
        self._prepare()
        from kirabridge.windows_setup_client import install_client

        install_client(self.state_dir)
        return result(
            "client_installed",
            "Die Verbindungshilfe ist installiert und geprüft.",
            "Öffne die Kontoseite und folge den Hinweisen in Schritt 2.",
            client_installed=True,
        )

    def _require_local(self):
        self._prepare()
        health = self._owned_health()
        if not health:
            raise BridgeError("setup_local_missing", "Start the local setup server first")
        return health

    def connect(self, tunnel_id: str, runtime_key: str):
        self._require_local()
        from kirabridge.windows_setup_client import (
            find_client,
            prepare_profile,
            start_client,
        )

        if not isinstance(tunnel_id, str) or not isinstance(runtime_key, str):
            raise BridgeError("invalid_tunnel", "Invalid connection fields")
        tunnel_id = tunnel_id.strip()
        saved = self._saved_connection()
        if not tunnel_id and not runtime_key.strip():
            if saved is None:
                raise BridgeError("setup_connection_missing", "No saved connection is available")
            tunnel_id = saved["tunnel_id"]
        if TUNNEL_ID.fullmatch(tunnel_id) is None:
            raise BridgeError("invalid_tunnel", "Invalid tunnel ID")
        if saved is not None and saved["tunnel_id"] != tunnel_id:
            raise BridgeError("existing_tunnel", "Existing connection preserved")
        binary = find_client(self.state_dir)
        if not binary:
            raise BridgeError("setup_client_missing", "Install the connection helper first")
        folder = self.state_dir / "connection"
        private_directory(folder)
        identity, key = folder / "identity.json", folder / "runtime.key"
        if saved is None:
            if (
                not isinstance(runtime_key, str)
                or not 32 <= len(runtime_key) <= 512
                or not runtime_key.isascii()
                or any(c.isspace() for c in runtime_key)
            ):
                raise BridgeError("invalid_runtime_key", "Enter a restricted runtime key locally")
            write_private(identity, json.dumps({"tunnel_id": tunnel_id, "endpoint": self.endpoint}))
            write_private(key, runtime_key)
        profile = prepare_profile(binary, self.state_dir, tunnel_id, key, self.endpoint)
        credentials = private_json(self.state_dir / "preview-credentials.json")
        start_client(binary, profile, self.state_dir, credentials["local"])
        return self.connection_status()

    def connection_status(self):
        self._require_local()
        from kirabridge.windows_setup_client import client_status

        observed = client_status(self.state_dir)
        ready = observed.get("ready") is True
        return result(
            "tunnel_ready" if ready else "tunnel_pending",
            "Die Verbindung ist bereit. Jetzt fehlt noch der Test aus ChatGPT."
            if ready
            else "Die Verbindung ist noch nicht bereit.",
            "Öffne Schritt 3 und füge KiraBridge in ChatGPT hinzu."
            if ready
            else "Lass die KiraBridge-Fenster offen. Prüfe Internet und Kontoberechtigungen; "
            "klicke danach auf „Verbindung prüfen“.",
            tunnel_ready=ready,
            local_ready=True,
            connection_saved=self._saved_connection() is not None,
        )

    def _verification(self, health):
        from kirabridge.windows_setup_verification import WindowsSetupVerification

        generation = health["runtime"]["instance_id"]
        if self.verification is None or self.verification.runtime_generation != generation:
            self.verification = WindowsSetupVerification(
                self.state_dir, runtime_generation=generation, enabled=True
            )
        return self.verification

    def begin_verification(self):
        health = self._require_local()
        check = self._verification(health).begin_verification()
        return result(
            "verification_pending",
            "Der Verbindungstest ist vorbereitet.",
            "Kopiere den Prüfauftrag in ChatGPT. Trage danach den Antwortcode unten ein.",
            prompt=check["prompt"],
            local_ready=True,
        )

    def finish_verification(self, response_code: str):
        health = self._require_local()
        verification = self._verification(health)
        if not verification.finish_verification(response_code.strip()):
            return result(
                "verification_pending",
                "Dieser Antwortcode wurde noch nicht bestätigt.",
                "Nimm den Code aus der neuen ChatGPT-Antwort. Bei abgelaufenem Test "
                "erstelle einen neuen Prüfauftrag.",
            )
        proof = verification.public_proof()
        if proof.get("simulated"):
            return result(
                "local_test_verified",
                "Der lokale Test war erfolgreich.",
                "Dies war eine Simulation. Die ChatGPT-Verbindung ist noch offen.",
                cloud_attested=False,
                simulated=True,
            )
        return result(
            "verified",
            "Alles verbunden – du kannst loslegen.",
            "Lass die beiden KiraBridge-Fenster für die Verbindung geöffnet. "
            "Der Test hat keine Tasten gedrückt und keine Fenster verändert.",
            verified=True,
            cloud_attested=False,
            local_ready=True,
            verification_scope="user_confirmed_authenticated_roundtrip",
        )


def create_controller():
    return WindowsSetup()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="KiraBridge mit ChatGPT verbinden – Schritt für Schritt"
    )
    parser.parse_args(argv)
    if sys.platform != "win32":
        print("Dieser Einrichtungsassistent läuft unter Windows.", file=sys.stderr)
        return 1
    try:
        from kirabridge.windows_setup_ui import main as show

        return show()
    except ImportError:
        print(
            "Die Windows-Oberfläche fehlt. "
            "Starte Einrichtung-starten.cmd aus dem vollständigen Paket.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
