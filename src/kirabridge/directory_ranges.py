"""Ordered directory pages with path-bound, change-detecting continuation tokens."""

import base64
import hashlib
import heapq
import json
import os

from pydantic import Field

from kirabridge.bridge_core.models import BridgeError, Input, canonical


class DirectoryInput(Input):
    path: str = Field(min_length=1, max_length=4096)
    limit: int = Field(default=1000, ge=1, le=1000)
    cursor: str = Field(default="", max_length=4096)
    expected_identity: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


def _identity(value):
    return hashlib.sha256(
        canonical([value.st_dev, value.st_ino, value.st_mtime_ns, value.st_ctime_ns]).encode()
    ).hexdigest()


def _scan(fd, *, after="", limit=None):
    """Bounded page plus order-independent namespace change checksum.

    This is a generation checksum, not an authenticated multiset or immutable
    snapshot. Count and summed SHA-512 entry hashes need constant memory; unlike
    timestamps alone they detect ordinary namespace changes within one FS tick.
    """
    count, total = 0, 0
    mask = (1 << 512) - 1
    # Each pass uses our own directory descriptor, starting from its beginning.
    os.lseek(fd, 0, os.SEEK_SET)

    def entries():
        nonlocal count, total
        with os.scandir(fd) as iterator:
            for entry in iterator:
                item = {
                    "name": entry.name,
                    "directory": entry.is_dir(follow_symlinks=False),
                    "symlink": entry.is_symlink(),
                }
                encoded = os.fsencode(entry.name)
                digest = hashlib.sha512(
                    len(encoded).to_bytes(8, "big")
                    + encoded
                    + bytes((item["directory"], item["symlink"]))
                    + str(entry.inode()).encode("ascii")
                ).digest()
                count += 1
                total = (total + int.from_bytes(digest, "big")) & mask
                if entry.name > after:
                    yield item

    if limit is None:
        for _ in entries():
            pass
        selected = None
    else:
        selected = heapq.nsmallest(limit + 1, entries(), key=lambda entry: entry["name"])
    return selected, (count, format(total, "0128x"))


def list_directory(scope, path, *, limit=1000, cursor="", expected_identity=None):
    """Rescan with bounded page memory; a mutation invalidates the entire page.

    A cursor is an untrusted position, never an authorization token. Every page
    traverses PathScope again and verifies a namespace checksum twice.
    Entry count is not silently capped; only the returned page has a size limit.
    """
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise BridgeError("invalid_arguments", "Directory page limit must be 1 through 1000")
    if not isinstance(cursor, str) or len(cursor) > 4096:
        raise BridgeError("invalid_arguments", "Invalid directory cursor")
    path_hash = hashlib.sha256(os.fsencode(path)).hexdigest()
    after = ""
    continuation_identity = None
    if cursor:
        try:
            decoded = base64.b64decode(cursor.encode("ascii"), altchars=b"-_", validate=True)
            value = json.loads(decoded)
            if (
                not isinstance(value, dict)
                or set(value) != {"v", "path", "identity", "after"}
                or type(value["v"]) is not int
                or value["v"] != 1
                or value["path"] != path_hash
                or not isinstance(value["after"], str)
                or not value["after"]
                or "/" in value["after"]
                or "\x00" in value["after"]
                or not isinstance(value["identity"], str)
                or len(value["identity"]) != 64
                or any(x not in "0123456789abcdef" for x in value["identity"])
            ):
                raise ValueError
            after, continuation_identity = value["after"], value["identity"]
        except (ValueError, UnicodeError, TypeError, RecursionError):
            raise BridgeError(
                "invalid_arguments", "Directory cursor does not match this path"
            ) from None
    if expected_identity is not None and (
        not isinstance(expected_identity, str)
        or len(expected_identity) != 64
        or any(x not in "0123456789abcdef" for x in expected_identity)
    ):
        raise BridgeError("invalid_arguments", "Invalid directory identity")
    try:
        with scope.directory(path) as fd:
            metadata_identity = _identity(os.fstat(fd))
            selected, content = _scan(fd, after=after, limit=limit)
            if _identity(os.fstat(fd)) != metadata_identity:
                raise BridgeError("directory_changed", "Directory changed during enumeration")
            _, verified = _scan(fd)
            if verified != content or _identity(os.fstat(fd)) != metadata_identity:
                raise BridgeError("directory_changed", "Directory changed during verification")
            identity = hashlib.sha256(canonical([metadata_identity, content]).encode()).hexdigest()
            if any(
                x is not None and x != identity for x in (continuation_identity, expected_identity)
            ):
                raise BridgeError("directory_changed", "Directory changed; start a new traversal")

            # Reopening the full descriptor path also detects replacement of an ancestor.
            with scope.directory(path) as current:
                if _identity(os.fstat(current)) != metadata_identity:
                    raise BridgeError(
                        "directory_changed", "Directory path changed during enumeration"
                    )
    except OSError:
        raise BridgeError(
            "directory_unavailable", "Directory could not be enumerated safely"
        ) from None
    more = len(selected) > limit
    page = selected[:limit]
    next_cursor = ""
    if more:
        next_cursor = base64.urlsafe_b64encode(
            json.dumps(
                {"v": 1, "path": path_hash, "identity": identity, "after": page[-1]["name"]},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).decode("ascii")
    return {
        "entries": page,
        "truncated": more,
        "eof": not more,
        "identity": identity,
        "next_cursor": next_cursor,
        "returned_count": len(page),
        "scope": "ordered directory page; metadata/namespace change checksum, "
        "not an authenticated or immutable snapshot",
    }
