"""Interactive Windows desktop preview: private local MCP, no service installation."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path

from kirabridge.bridge_core.config import Config, PrincipalConfig, private_directory
from kirabridge.bridge_core.models import BridgeError
from kirabridge.private_files import private_json, write_private

TOKEN_ENV = "KIRABRIDGE_WINDOWS_PREVIEW_TOKEN"
CREDENTIAL_SCHEMA = "kirabridge.windows-preview.credentials.v1"
CAPABILITIES = (
    "bridge.health",
    "task.read",
    "task.cancel",
    "windows.keyboard.inspect",
    "windows.keyboard.sequence",
    "windows.keyboard.shortcut",
    "windows.window.list",
    "windows.window.control",
)


@dataclass(frozen=True)
class Preview:
    config: Config
    credential_path: Path
    token: str = field(repr=False)

    def public(self, transport):
        return {
            "status": "starting",
            "preview": "Windows keyboard and window MCP",
            "transport": transport,
            "endpoint": f"http://127.0.0.1:{self.config.port}/mcp" if transport == "http" else None,
            "state_dir": str(self.config.state_path),
            "credential_file": str(self.credential_path),
            "credential_key": "local",
            "capabilities": list(self.config.principals["local"].capabilities),
            "interactive_user_desktop_required": True,
            "service_installed": False,
            "native_acceptance": "not_asserted_by_startup",
        }


def require_windows():
    if sys.platform != "win32":
        raise BridgeError("unsupported_platform", "Run the preview inside Windows, not on the Mac")


def require_desktop():
    from kirabridge.platform_adapters.windows.keyboard import Win32KeyboardAPI

    Win32KeyboardAPI().validate_desktop()  # Read-only; no foreground keys or focus changes.


def prepare(state_dir: Path | None = None, *, port=8765, setup_verification=False) -> Preview:
    require_windows()  # Must precede all directory, credential or desktop work.
    if type(setup_verification) is not bool:
        raise BridgeError("invalid_setup_mode", "Setup verification requires an explicit boolean")
    if type(port) is not int or not 1024 <= port <= 65535:
        raise BridgeError("invalid_port", "Choose a port between 1024 and 65535")
    require_desktop()
    if state_dir is None:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise BridgeError("preview_state_missing", "LOCALAPPDATA is unavailable")
        state_dir = Path(local) / "KiraBridgePreview"
    root = Path(state_dir).expanduser().absolute()
    private_directory(root)
    credentials = root / "preview-credentials.json"
    try:
        payload = private_json(credentials)
    except FileNotFoundError:
        payload = {"schema": CREDENTIAL_SCHEMA, "local": secrets.token_urlsafe(48)}
        try:
            write_private(credentials, json.dumps(payload))
        except FileExistsError:
            payload = private_json(credentials)  # Another creator won; only read its original file.
    except (ValueError, TypeError, UnicodeError):
        raise BridgeError(
            "preview_credentials_invalid", "Invalid credentials preserved; inspect locally"
        ) from None
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema", "local"}
        or payload.get("schema") != CREDENTIAL_SCHEMA
        or not isinstance(payload.get("local"), str)
        or re.fullmatch(r"[A-Za-z0-9_-]{32,128}", payload["local"]) is None
    ):
        raise BridgeError(
            "preview_credentials_invalid", "Invalid credentials preserved; inspect locally"
        )
    policy = PrincipalConfig(
        approval_mode="automatic",
        client_type="operator",
        token_env=TOKEN_ENV,
        capabilities=list(CAPABILITIES) + (["windows.setup.verify"] if setup_verification else []),
        roots=[],
        read_roots=[],
        executables=[],
        agents=[],
        allow_any_executable=False,
    )
    config = Config(
        data_dir=str(root),
        credentials_file=str(credentials),
        host="127.0.0.1",
        port=port,
        allow_remote=False,
        windows_setup_verification_enabled=setup_verification,
        concurrency=1,
        read_concurrency=1,
        principals={"local": policy},
    )
    return Preview(config, credentials, payload["local"])


def build_bridge(config):
    from kirabridge.bridge_core.bridge import Bridge

    return Bridge(config)


def stdio_server(bridge):
    from kirabridge.mcp_gateway.server import create_server

    return create_server(bridge, principal="local")


def http_server(bridge):
    import uvicorn

    from kirabridge.mcp_gateway.http import create_http_app

    return uvicorn.Server(
        uvicorn.Config(
            create_http_app(bridge),
            host="127.0.0.1",
            port=bridge.config.port,
            access_log=False,
            log_level="critical",
            timeout_keep_alive=5,
            limit_concurrency=bridge.config.max_http_requests,
        )
    )


def listener(port):
    handle = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            handle.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        handle.bind(("127.0.0.1", port))
        handle.listen(128)
        handle.setblocking(False)
        return handle
    except BaseException:
        handle.close()
        raise


async def serve(preview: Preview, transport: str):
    require_windows()
    if transport not in {"http", "stdio"}:
        raise BridgeError("invalid_transport", "Choose http or stdio")
    previous = os.environ.get(TOKEN_ENV)
    bridge = handle = None
    os.environ[TOKEN_ENV] = preview.token
    try:
        if transport == "http":
            handle = listener(preview.config.port)
        bridge = build_bridge(preview.config)
        async with bridge:
            # Stdio stdout is reserved exclusively for the MCP protocol.
            print(json.dumps(preview.public(transport)), file=sys.stderr, flush=True)
            if transport == "stdio":
                await stdio_server(bridge).run_stdio_async()
            else:
                await http_server(bridge).serve(sockets=[handle])
    finally:
        try:
            if handle is not None:
                handle.close()
        finally:
            try:
                if bridge is not None:
                    # Also close after a failed __aenter__; SQLite close is idempotent.
                    bridge.store.close()
            finally:
                if previous is None:
                    os.environ.pop(TOKEN_ENV, None)
                else:
                    os.environ[TOKEN_ENV] = previous


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=("http", "stdio"), default="http")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--setup-verification", action="store_true")
    args = parser.parse_args(argv)
    try:
        asyncio.run(
            serve(
                prepare(args.state_dir, port=args.port, setup_verification=args.setup_verification),
                args.transport,
            )
        )
    except BridgeError as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        # Exceptions may contain credential values or URLs; never dump their text.
        print(
            f"Windows preview stopped ({type(error).__name__}); existing state preserved",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
