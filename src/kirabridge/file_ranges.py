"""Bounded, descriptor-relative regular-file pages; authorization remains with PathScope."""

import base64
import hashlib
import os
import stat

from kirabridge.bridge_core.models import BridgeError


def _identity(metadata):
    fields = (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )
    return hashlib.sha256(":".join(map(str, fields)).encode("ascii")).hexdigest()


def read_file_range(
    scope, path, max_bytes, *, offset=0, tail=False, encoding="utf-8", expected_identity=None
):
    """Read one page, never entire-file buffers. Identity is a change token, not content hash.

    Each page always includes exact base64 bytes. UTF-8 text is a compatibility
    display preview, explicitly marked when
    decoding replaces split/invalid sequences. Concatenate canonical base64 bytes
    before decoding split characters. Pin expected_identity on continuation to reject
    changed files; this deliberately rejects active appends as well. A stable file
    or separately authorized snapshot is required for a consistent full traversal.
    """
    if (
        type(max_bytes) is not int
        or not 1 <= max_bytes <= 1048576
        or type(offset) is not int
        or not 0 <= offset <= 2**63 - 1
        or type(tail) is not bool
        or (tail and offset)
        or encoding not in {"utf-8", "base64"}
        or expected_identity is not None
        and (
            not isinstance(expected_identity, str)
            or len(expected_identity) != 64
            or any(c not in "0123456789abcdef" for c in expected_identity)
        )
    ):
        raise BridgeError("invalid_arguments", "Invalid bounded file range selector")
    try:
        with scope.parent(path) as (parent, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode):
                    raise BridgeError("file_type", "Only regular files can be read")
                identity = _identity(before)
                if expected_identity is not None and expected_identity != identity:
                    raise BridgeError("file_changed", "File changed; restart from a new identity")
                start = max(0, before.st_size - max_bytes) if tail else offset
                data = os.pread(fd, max_bytes + 1, start)
                after = os.fstat(fd)
                current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if _identity(after) != identity or _identity(current) != identity:
                    raise BridgeError("file_changed", "File changed during range observation")
                if not data and start < before.st_size:
                    raise BridgeError(
                        "read_incomplete", "File range made no progress before observed EOF"
                    )
            finally:
                os.close(fd)
    except OSError:
        raise BridgeError("read_unavailable", "File unavailable or unsafe to open") from None
    data = data[:max_bytes]
    next_offset = start + len(data)
    text, text_status, text_lossless = "", "binary", False
    if encoding == "utf-8":
        try:
            text, text_status, text_lossless = (
                data.decode("utf-8", errors="strict"),
                "complete_utf8",
                True,
            )
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
            text_status = "invalid_or_partial_utf8"
    return {
        "text": text,
        "text_status": text_status,
        "text_lossless": text_lossless,
        "data_base64": base64.b64encode(data).decode("ascii"),
        "encoding": encoding,
        "bytes": len(data),
        "offset": start,
        "next_offset": next_offset,
        "eof": next_offset >= before.st_size,
        "truncated": next_offset < before.st_size,
        "has_before": start > 0,
        "size_observed": before.st_size,
        "modified_ns": before.st_mtime_ns,
        "identity": identity,
        "content_sha256": hashlib.sha256(data).hexdigest(),
        "scope": "observed file page; metadata change token, not an immutable snapshot",
    }
