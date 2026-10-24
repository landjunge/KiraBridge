"""Read-only selected-file/export adapters; no account crawling or stored signed URLs."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import mimetypes
import os
import socket
import stat
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from kirabridge.bridge_core.models import BridgeError
from kirabridge.file_transfer.integrity import name
from kirabridge.file_transfer.models import OpenAIFile
from kirabridge.filesystem_manager import PathScope


class PublicDownloadTransport(httpx.AsyncBaseTransport):
    """Validate DNS and pin the connection address while retaining the original TLS SNI."""

    def __init__(self, hosts, *, inner=None, resolver=None):
        self.hosts = frozenset(hosts)
        self.inner = inner or httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        self.resolver = resolver

    async def handle_async_request(self, request):
        host = request.url.host
        if (
            request.url.scheme != "https"
            or request.url.port not in (None, 443)
            or host not in self.hosts
            or request.url.username
            or request.url.password
        ):
            raise BridgeError(
                "transfer_source_denied", "Download host/scheme is not operator-authorized"
            )
        try:
            addresses = (
                await self.resolver(host)
                if self.resolver
                else {
                    item[4][0]
                    for item in await asyncio.get_running_loop().getaddrinfo(
                        host, 443, type=socket.SOCK_STREAM
                    )
                }
            )
            if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
                raise BridgeError("transfer_source_denied", "Non-public download address rejected")
            address = sorted(addresses)[0]
        except (OSError, ValueError):
            raise BridgeError(
                "transfer_source_denied", "Download DNS could not be validated"
            ) from None
        headers = httpx.Headers(request.headers)
        headers["host"] = host
        # Source capabilities never inherit MCP tokens/cookies or environment proxies.
        for key in ("authorization", "cookie", "proxy-authorization"):
            headers.pop(key, None)
        pinned = httpx.Request(
            request.method,
            request.url.copy_with(host=address),
            headers=headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": host},
        )
        return await self.inner.handle_async_request(pinned)

    async def aclose(self):
        await self.inner.aclose()


@dataclass
class SelectedFile:
    name: str
    mime_type: str
    reference: str
    download_url: str = field(repr=False)
    hosts: tuple[str, ...] = ()
    max_bytes: int = 2 * 1024**3
    kind: str = "chatgpt_file_param"
    transport: object = field(default=None, repr=False)

    async def chunks(self, chunk_bytes):
        transport = self.transport or PublicDownloadTransport(self.hosts)
        try:
            async with httpx.AsyncClient(
                transport=transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(60, connect=15),
            ) as client:
                async with client.stream(
                    "GET", self.download_url, headers={"Accept-Encoding": "identity"}
                ) as response:
                    if response.status_code in {401, 403, 404, 410}:
                        raise BridgeError(
                            "transfer_source_expired",
                            "Select the file again for a fresh capability",
                        )
                    if response.status_code != 200:
                        raise BridgeError(
                            "transfer_source_download", "Download did not return a complete file"
                        )
                    if response.headers.get("content-encoding", "identity") not in {"identity", ""}:
                        raise BridgeError(
                            "transfer_source_download", "Encoded HTTP representation rejected"
                        )
                    declared = response.headers.get("content-length")
                    if declared and (not declared.isdecimal() or int(declared) > self.max_bytes):
                        raise BridgeError(
                            "transfer_size_limit", "Source exceeds the configured byte limit"
                        )
                    total = 0
                    async for data in response.aiter_raw(chunk_size=chunk_bytes):
                        total += len(data)
                        if total > self.max_bytes:
                            raise BridgeError(
                                "transfer_size_limit", "Source exceeds the configured byte limit"
                            )
                        yield data
                    if declared and total != int(declared):
                        raise BridgeError(
                            "transfer_integrity", "Download length differs from declared length"
                        )
        except (httpx.HTTPError, OSError):
            raise BridgeError(
                "transfer_source_download", "Source download failed; capability not logged"
            ) from None


@dataclass
class AuthorizedExport:
    path: str = field(repr=False)
    scope: PathScope = field(repr=False)
    reference: str
    name: str
    mime_type: str
    kind: str = "authorized_export"

    async def chunks(self, chunk_bytes):
        try:
            with self.scope.parent(self.path) as (parent, leaf):
                fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                try:
                    before = os.fstat(fd)
                    if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid():
                        raise BridgeError(
                            "transfer_source_denied",
                            "Only caller-owned regular export files are readable",
                        )
                    while data := await asyncio.to_thread(os.read, fd, chunk_bytes):
                        yield data
                    after = os.fstat(fd)

                    def identity(value):
                        return (
                            value.st_dev,
                            value.st_ino,
                            value.st_size,
                            value.st_mtime_ns,
                            value.st_ctime_ns,
                        )

                    if identity(before) != identity(after):
                        raise BridgeError(
                            "transfer_source_changed", "Export changed while taking the snapshot"
                        )
                finally:
                    os.close(fd)
        except OSError:
            raise BridgeError(
                "transfer_source_denied", "Export path is unavailable or linked"
            ) from None


class SourceRegistry:
    """Ephemeral capabilities; stable IDs let exact-task retries refresh an expired URL."""

    def __init__(self, max_sources=128, ttl=900):
        self.entries, self.max_sources, self.ttl = {}, max_sources, ttl

    def register(self, principal, stable_key, source):
        now = time.monotonic()
        self.entries = {key: entry for key, entry in self.entries.items() if entry[2] > now}
        from kirabridge.bridge_core.models import digest

        identifier = digest(
            [principal, stable_key, source.reference, source.name, source.mime_type, source.kind]
        )
        if identifier not in self.entries and len(self.entries) >= self.max_sources:
            raise BridgeError("transfer_source_limit", "Too many pending source capabilities")
        self.entries[identifier] = (principal, source, now + self.ttl, "detected")
        return identifier

    def get(self, principal, identifier):
        entry = self.entries.get(identifier)
        if not entry or entry[0] != principal or entry[2] <= time.monotonic():
            raise BridgeError(
                "transfer_source_expired",
                "Source capability is absent/expired; select the same file again",
            )
        return entry[1]

    def inventory(self, principal):
        return [
            {
                "source_id": key,
                "name": entry[1].name,
                "mime_type": entry[1].mime_type,
                "source_kind": entry[1].kind,
                "source_ref": entry[1].reference,
                "state": entry[3],
                "size": None,
            }
            for key, entry in self.entries.items()
            if entry[0] == principal and entry[2] > time.monotonic()
        ]

    def state(self, principal, identifier, state):
        entry = self.entries.get(identifier)
        if entry and entry[0] == principal:
            self.entries[identifier] = (*entry[:3], state)

    def selected(self, principal, stable_key, file: OpenAIFile, settings):
        try:
            parsed = urlsplit(file.download_url)
            port = parsed.port
        except ValueError:
            raise BridgeError("transfer_source_denied", "Invalid source capability URL") from None
        if (
            parsed.scheme != "https"
            or parsed.hostname not in settings.source_hosts
            or parsed.username
            or parsed.password
            or parsed.fragment
            or port not in (None, 443)
        ):
            raise BridgeError(
                "transfer_source_denied", "Source URL is not an authorized download capability"
            )
        filename = name(file.file_name or file.file_id)
        source = SelectedFile(
            filename,
            file.mime_type or "application/octet-stream",
            hashlib.sha256(file.file_id.encode()).hexdigest(),
            file.download_url,
            tuple(settings.source_hosts),
            settings.limits.max_file_bytes,
        )
        return self.register(principal, stable_key, source)

    def export(self, principal, stable_key, path, roots):
        from pathlib import Path

        filename = name(Path(path).name)
        scope = PathScope(roots)
        scope.split(path)
        source = AuthorizedExport(
            path,
            scope,
            hashlib.sha256(path.encode()).hexdigest(),
            filename,
            mimetypes.guess_type(filename)[0] or "application/octet-stream",
        )
        return self.register(principal, stable_key, source)
