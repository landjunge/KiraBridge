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


def list_directory(scope, path, *, limit=1000, cursor="", expected_identity=None):
    """Rescan with bounded page memory; a mutation invalidates the entire page.

    A cursor is an untrusted position, never an authorization token. Every page
    traverses PathScope again and binds the exact directory metadata generation.
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
            identity = _identity(os.fstat(fd))
            if any(
                x is not None and x != identity for x in (continuation_identity, expected_identity)
            ):
                raise BridgeError("directory_changed", "Directory changed; start a new traversal")

            def entries():
                with os.scandir(fd) as iterator:
                    for entry in iterator:
                        if entry.name > after:
                            yield {
                                "name": entry.name,
                                "directory": entry.is_dir(follow_symlinks=False),
                                "symlink": entry.is_symlink(),
                            }

            selected = heapq.nsmallest(limit + 1, entries(), key=lambda entry: entry["name"])
            if _identity(os.fstat(fd)) != identity:
                raise BridgeError("directory_changed", "Directory changed during enumeration")
            # Reopening the full descriptor path also detects replacement of an ancestor.
            with scope.directory(path) as current:
                if _identity(os.fstat(current)) != identity:
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
        "scope": "ordered directory page; continuation requires unchanged directory generation",
    }
