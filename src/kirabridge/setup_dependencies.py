"""Opt-in original-provider download; no package manager, sudo or key required."""

from __future__ import annotations

import hashlib
import io
import os
import platform
import shutil
import time
import urllib.request
import zipfile
from pathlib import Path

from kirabridge.bridge_core.config import private_directory
from kirabridge.bridge_core.models import BridgeError
from kirabridge.local_runtime import write_private

CLIENT_RELEASE = "https://github.com/openai/tunnel-client/releases/latest"
CLIENTS = {
    ("Darwin", "arm64"): (
        "darwin-arm64",
        "a160820d45089b5253d8d671fe2a689bde0f73d78c135d1497a7b33f28a3ac62",
    ),
    ("Darwin", "x86_64"): (
        "darwin-amd64",
        "57b3dd73f2d042c7aeb5664681f7538078359f55538b9e048640f1df71a0c83f",
    ),
    ("Linux", "x86_64"): (
        "linux-amd64",
        "d60cdba019bce451bcc3a15478cc5b9cb11270b049f5b56ea39a80b517f8b117",
    ),
}


def local_client(config_path):
    found = shutil.which("tunnel-client")
    if found:
        return found
    path = config_path.parent / "tools/tunnel-client-v0.0.16/tunnel-client"
    return str(path) if path.is_file() and os.access(path, os.X_OK) else None


def download_client(config_path: Path):
    target = CLIENTS.get((platform.system(), platform.machine()))
    if target is None:
        raise BridgeError(
            "unsupported_platform", "Use an officially supported tunnel-client platform"
        )
    label, expected = target
    folder = config_path.parent / "tools/tunnel-client-v0.0.16"
    if folder.exists():
        raise BridgeError(
            "existing_tool", "Existing tool folder preserved; inspect before retrying"
        )
    url = f"https://github.com/openai/tunnel-client/releases/download/v0.0.16/tunnel-client-v0.0.16-{label}.zip"
    start = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            if not response.url.startswith("https://"):
                raise BridgeError("download_transport", "HTTPS required")
            chunks, size = [], 0
            while chunk := response.read(65536):
                size += len(chunk)
                if size > 80_000_000 or time.monotonic() - start > 120:
                    raise BridgeError("download_limit", "Tunnel-client download exceeded bounds")
                chunks.append(chunk)
        data = b"".join(chunks)
    except (OSError, TimeoutError):
        raise BridgeError(
            "download_failed", "Official client download failed; check network and retry"
        ) from None
    if hashlib.sha256(data).hexdigest() != expected:
        raise BridgeError("download_checksum", "Checksum mismatch; no downloaded program executed")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if (
            len(entries) > 20
            or sum(x.file_size for x in entries) > 180_000_000
            or any(Path(x.filename).name != x.filename or x.is_dir() for x in entries)
            or not {"tunnel-client", "cloudflared", "cloudflared-manifest.json"}
            <= {x.filename for x in entries}
        ):
            raise BridgeError("download_archive", "Unexpected archive layout; nothing installed")
        private_directory(folder.parent)
        private_directory(folder)
        for item in entries:
            write_private(
                folder / item.filename,
                archive.read(item),
                mode=0o700 if item.filename in {"tunnel-client", "cloudflared"} else 0o600,
            )
    return str(folder / "tunnel-client")
