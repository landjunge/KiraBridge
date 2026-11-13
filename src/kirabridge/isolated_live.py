"""Explicitly isolated KiraBridge Live instance for development and checks.

It reuses the existing bootstrap receipt, console authentication and origin
contract, but everything it owns is private to one instance:

* its own config directory (owner-only, never the production config directory),
* fresh local and console credentials (never a production key),
* one loopback console port chosen at bind time, and an origin bound to exactly
  that port,
* an in-process bridge that only serves ``live_status`` — no production daemon,
  no launch service, no launcher, no production login file.

The production defaults are unchanged: this module is only reached through the
explicit ``isolated-live`` command or an explicit isolated native start.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import uuid
from pathlib import Path

from kirabridge.approval_console import ApprovalConsole, signed_token
from kirabridge.audit_manager import AuditWriter
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config, load_config, private_directory
from kirabridge.bridge_core.models import BridgeError
from kirabridge.console_runtime import console_key
from kirabridge.live_status import project
from kirabridge.local_runtime import default_config, write_private

PRODUCTION_PORTS = frozenset({8765, 8766, 8767})
PRODUCTION_CONSOLE_PORT = 8766
_MIN_PORT = 1024


class IsolatedApplication:
    """The only operator surface of an isolated instance: audit plus live read.

    It deliberately has no control, action, reservation, service, connector or
    keyboard surface; the live-only console mounts no handler that could reach
    one. Production tokens and services are never consulted.
    """

    def __init__(self, bridge, principal: str = "local"):
        self.audit = AuditWriter(bridge.store)
        self.bridge = bridge
        self.principal = principal

    async def live_status(self):
        return project(self.bridge, self.principal)


def _protected_paths() -> set[Path]:
    home = Path.home()
    return {
        default_config().resolve(),
        default_config().parent.resolve(),
        (home / ".config/kirabridge").resolve(),
        (home / ".local/share/kirabridge").resolve(),
        (home / ".local/state").resolve(),
        (home / "Library/LaunchAgents").resolve(),
    }


def isolated_config_path(path: str | Path) -> Path:
    """Accept only an absolute, private config path outside production state."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise BridgeError("isolated_config_required", "An isolated config path must be absolute")
    if candidate.name != "config.toml":
        raise BridgeError(
            "isolated_config_required", "An isolated config path must end in config.toml"
        )
    if candidate.is_symlink():
        raise BridgeError("isolated_config_required", "An isolated config must not be a symlink")
    resolved = candidate.resolve()
    for protected in _protected_paths():
        if resolved == protected or protected in resolved.parents:
            raise BridgeError(
                "isolated_config_required",
                "The isolated Live instance must not use production config or state",
            )
    return resolved


def _config_text(directory: Path) -> str:
    data_dir = directory / "data"
    credentials = directory / "credentials.json"
    return (
        "# Explicitly isolated KiraBridge Live instance (created by isolated-live).\n"
        "# Private state only: never the production config, credentials or daemon.\n"
        f"data_dir = {json.dumps(str(data_dir))}\n"
        f"credentials_file = {json.dumps(str(credentials))}\n"
        'host = "127.0.0.1"\n'
        # The isolated console is in-process; this port is never the production
        # daemon and is not opened by this module.
        "port = 9\n"
        "allow_remote = false\n"
        "\n[principals.local]\n"
        'capabilities = ["bridge.health", "task.read", "logs.live", "team.read"]\n'
    )


def prepare(config_path: str | Path) -> tuple[Config, Path, Path, str]:
    """Create or verify one private isolated instance.

    Returns the loaded config, its private directory, its config path and the
    console credential key.
    """
    path = isolated_config_path(config_path)
    directory = path.parent
    private_directory(directory)
    if not path.exists():
        try:
            write_private(path, _config_text(directory))
        except FileExistsError:
            pass
    config = load_config(str(path))
    expected_data = (directory / "data").resolve()
    expected_credentials = (directory / "credentials.json").resolve()
    credentials = config.credentials_file
    if (
        Path(config.data_dir).resolve() != expected_data
        or credentials is None
        or Path(credentials).resolve() != expected_credentials
        or "local" not in config.principals
        or "logs.live" not in config.principals["local"].capabilities
    ):
        raise BridgeError(
            "isolated_config_required",
            "The isolated config must keep its own data, credentials and live read",
        )
    credentials_path = directory / "credentials.json"
    if not credentials_path.exists():
        try:
            write_private(credentials_path, json.dumps({"local": secrets.token_urlsafe(48)}))
        except FileExistsError:
            pass
    key = console_key(path)
    return config, directory, path, key


def login_page(key: str, origin: str, instance: str) -> str:
    ticket = signed_token(key, "login:" + instance)
    return (
        '<!doctype html><html lang="de"><meta charset="utf-8">'
        '<meta name="referrer" content="no-referrer"><title>KiraBridge öffnen</title>'
        "<body><p>Lokale KiraBridge-Freigaben öffnen …</p>"
        f'<form method="post" action="{origin}/login">'
        f'<input type="hidden" name="ticket" value="{ticket}">'
        '<button type="submit">Freigaben öffnen</button></form>'
        "<script>document.forms[0].submit()</script></body></html>"
    )


def write_login(directory: Path, page: str) -> Path:
    destination = directory / "approval-login.html"
    temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex)
    try:
        write_private(temporary, page)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def receipt(origin: str, login_file: Path, config: Path) -> dict:
    return {
        "isolated": True,
        "origin": origin,
        "login_file": str(login_file),
        "config": str(config),
        "pid": os.getpid(),
    }


def live_console(
    config_path: str | Path, *, origin: str | None = None
) -> tuple[ApprovalConsole, Bridge, str, Path, Path]:
    """Build the live-only console for one isolated instance.

    The returned console mounts only login, health, the live page/assets and the
    read-only live projection; there is no operator, approval, keyboard, service
    or connector handler to reach.
    """
    config, directory, path, key = prepare(config_path)
    bridge = Bridge(config)
    console = ApprovalConsole(IsolatedApplication(bridge), key, origin=origin, live_only=True)
    return console, bridge, key, directory, path


async def serve_isolated(config_path: str | Path, *, port: int = 0) -> None:
    """Serve one isolated console and print exactly one receipt line.

    Port 0 binds an ephemeral loopback port; an explicit port is accepted only
    when it is a private port other than the production console port.
    """
    if port and (port < _MIN_PORT or port > 65535 or port in PRODUCTION_PORTS):
        raise BridgeError(
            "isolated_port_required",
            "Choose a private loopback port outside the production ports 8765-8767",
        )
    import uvicorn

    console, bridge, key, directory, path = live_console(config_path, origin="http://127.0.0.1:1")
    try:
        server = uvicorn.Server(
            uvicorn.Config(
                console,
                host="127.0.0.1",
                port=port,
                access_log=False,
                log_level="critical",
                limit_concurrency=16,
                timeout_keep_alive=5,
            )
        )
        serving = asyncio.create_task(server.serve())
        while not server.started:
            if serving.done():
                serving.result()
                raise BridgeError("isolated_start", "The isolated console did not start")
            await asyncio.sleep(0.02)
        actual = server.servers[0].sockets[0].getsockname()[1]
        if actual in PRODUCTION_PORTS:
            server.should_exit = True
            await serving
            raise BridgeError(
                "isolated_port_conflict",
                "The isolated console must not bind a production port",
            )
        origin = f"http://127.0.0.1:{actual}"
        console.set_origin(origin)
        login = write_login(directory, login_page(key, origin, console.instance)).resolve()
        print(json.dumps(receipt(origin, login, path), sort_keys=True), flush=True)
        await serving
    finally:
        bridge.store.close()
