"""Bounded raw-byte integrity, safe logical paths, secret and archive validation."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import struct
import unicodedata
import zipfile
from contextlib import contextmanager
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError
from kirabridge.file_transfer.models import Limits

SECRET_NAME = re.compile(
    r"^(?:\.env(?:\..*)?|credentials(?:\..*)?|id_(?:rsa|ed25519)|.*\.(?:pem|key|p12|pfx|keychain))$",
    re.I,
)
SECRET = re.compile(
    rb"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----|"
    rb"(?:AWS_SECRET_ACCESS_KEY|OPENAI_API_KEY|GITHUB_TOKEN|XAI_API_KEY)\s*[=:]\s*[^\s]{8,}|"
    rb"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,})"
)


def name(value):
    normalized = unicodedata.normalize("NFKC", value)
    if (
        not value
        or len(value.encode()) > 255
        or normalized in {".", ".."}
        or any(c in normalized for c in "/\\:")
        or any(unicodedata.category(c)[0] == "C" for c in value)
    ):
        raise BridgeError("transfer_path_denied", "Unsafe file name")
    if SECRET_NAME.fullmatch(value) or SECRET.search(value.encode()):
        raise BridgeError("transfer_secret_detected", "Credential/private-key file rejected")
    return value


def logical_path(value, *, allow_absolute=False):
    if not value:
        return ""
    if not allow_absolute and value.startswith("/"):
        raise BridgeError("transfer_path_denied", "Relative destination folder required")
    parts = value.lstrip("/").split("/")
    if any(not p for p in parts):
        raise BridgeError("transfer_path_denied", "Empty path component")
    for part in parts:
        name(part)
    return value


class SecretScan:
    def __init__(self):
        self.tail = b""

    def update(self, data):
        window = self.tail + data
        if SECRET.search(window):
            raise BridgeError(
                "transfer_secret_detected", "Possible secret rejected; no file was sent"
            )
        self.tail = window[-8192:]


def bounded_zip_directory(source, limits):
    source.seek(0, os.SEEK_END)
    size = source.tell()
    source.seek(max(0, size - 65557))
    tail = source.read(65557)
    at = tail.rfind(b"PK\x05\x06")
    if at < 0 or len(tail) - at < 22:
        raise BridgeError("transfer_invalid_archive", "ZIP end record is missing")
    _, disk, directory_disk, disk_entries, count, directory_size, _, comment = struct.unpack(
        "<4s4H2LH", tail[at : at + 22]
    )
    if disk or directory_disk or disk_entries != count or at + 22 + comment != len(tail):
        raise BridgeError("transfer_invalid_archive", "Multi-disk/trailing ZIP data rejected")
    if count == 65535 or directory_size == 0xFFFFFFFF:
        # Bound ZIP64 metadata before Python allocates the central directory.
        eocd_at = max(0, size - 65557) + at
        source.seek(eocd_at - 20)
        locator = source.read(20)
        if len(locator) != 20:
            raise BridgeError("transfer_invalid_archive", "Missing ZIP64 locator")
        signature, start_disk, offset, disks = struct.unpack("<4sLQL", locator)
        if signature != b"PK\x06\x07" or start_disk or disks != 1:
            raise BridgeError("transfer_invalid_archive", "Invalid ZIP64 locator")
        source.seek(offset)
        record = source.read(56)
        if len(record) != 56:
            raise BridgeError("transfer_invalid_archive", "Truncated ZIP64 record")
        values = struct.unpack("<4sQ2H2L4Q", record)
        if (
            values[0] != b"PK\x06\x06"
            or values[1] < 44
            or values[4]
            or values[5]
            or values[6] != values[7]
        ):
            raise BridgeError("transfer_invalid_archive", "Invalid ZIP64 directory")
        count, directory_size = values[7], values[8]
    if count > limits.max_archive_entries or directory_size > 16 * 1024**2:
        raise BridgeError("transfer_archive_limit", "ZIP entry/directory allocation limit exceeded")
    source.seek(0)


def validate_archive(path: Path, limits: Limits):
    try:
        with open_snapshot(path) as source:
            if not zipfile.is_zipfile(source):
                if path.suffix.lower() in {".zip", ".docx", ".xlsx", ".pptx"}:
                    raise BridgeError("transfer_invalid_archive", "ZIP structure is invalid")
                return
            bounded_zip_directory(source, limits)
            with zipfile.ZipFile(source) as archive:
                entries = archive.infolist()
                if len(entries) > limits.max_archive_entries:
                    raise BridgeError("transfer_archive_limit", "Archive entry limit exceeded")
                seen, expanded = set(), 0
                for entry in entries:
                    entry_path = entry.filename.rstrip("/")
                    if not entry_path or entry_path in seen:
                        raise BridgeError("transfer_path_denied", "Empty or duplicate archive path")
                    seen.add(entry_path)
                    logical_path(entry_path)
                    if stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                        raise BridgeError(
                            "transfer_path_denied", "Archive symlink/encryption rejected"
                        )
                    expanded += entry.file_size
                    if (
                        expanded > limits.max_archive_expanded_bytes
                        or entry.file_size
                        > max(entry.compress_size, 1) * limits.max_compression_ratio
                    ):
                        raise BridgeError(
                            "transfer_archive_limit", "Archive expansion limit exceeded"
                        )
                    scan = SecretScan()
                    with archive.open(entry) as content:
                        while data := content.read(limits.chunk_bytes):
                            scan.update(data)
    except (zipfile.BadZipFile, RuntimeError, OSError, NotImplementedError):
        raise BridgeError("transfer_invalid_archive", "Archive validation failed") from None


@contextmanager
def open_snapshot(path):
    from kirabridge.filesystem_manager import PathScope

    path = Path(path)
    with PathScope([str(path.parent)]).parent(str(path)) as (parent, leaf):
        fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise BridgeError("transfer_integrity", "Snapshot is not an owned regular file")
            with os.fdopen(fd, "rb", closefd=False) as source:
                yield source
        finally:
            os.close(fd)


def sha256_file(path, chunk_bytes=256 * 1024, length=None):
    checksum, consumed = hashlib.sha256(), 0
    with open_snapshot(path) as source:
        while length is None or consumed < length:
            data = source.read(
                chunk_bytes if length is None else min(chunk_bytes, length - consumed)
            )
            if not data:
                break
            checksum.update(data)
            consumed += len(data)
    if length is not None and consumed != length:
        raise BridgeError("transfer_integrity", "Snapshot shorter than acknowledged offset")
    return checksum.hexdigest()
