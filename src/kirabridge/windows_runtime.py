"""Inventory a bundled Windows CPython directory before an installer copies it.

Required files are python.exe and exactly one versioned Python DLL
(python3NN.dll). The check reuses the package guards for links, reparse
points, hard links and paths that leave the runtime root. No install,
service, registry or execution-policy change happens here.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from kirabridge.windows_package import (
    PackageError,
    _inside,
    _is_link_or_reparse,
    _read_nofollow,
    _reject_special,
)

_VERSIONED_DLL = re.compile(r"python3\d+\.dll\Z")


def _reject_traversal_root(root: Path) -> None:
    if ".." in root.parts:
        raise PackageError("Refusing a traversal path in the bundled runtime")


def _require_file(root: Path, name: str) -> str:
    if name != Path(name).name or name in {".", ".."}:
        raise PackageError("Refusing a traversal path in the bundled runtime")
    path = root / name
    if _is_link_or_reparse(path):
        raise PackageError("Refusing a link or reparse point in the bundled runtime")
    try:
        _reject_special(path)
    except FileNotFoundError:
        raise PackageError(f"Bundled runtime is missing {name}") from None
    resolved = _inside(root, path)
    if resolved.relative_to(root.resolve()).as_posix() != name:
        raise PackageError("Refusing a traversal path in the bundled runtime")
    data = _read_nofollow(path)
    if not data:
        raise PackageError(f"Bundled runtime file is empty: {name}")
    return hashlib.sha256(data).hexdigest()


def _versioned_dll_names(root: Path) -> list[str]:
    names = []
    try:
        entries = list(os.scandir(root))
    except FileNotFoundError:
        raise PackageError("Bundled runtime root is not a real directory") from None
    for entry in entries:
        if _VERSIONED_DLL.fullmatch(entry.name):
            names.append(entry.name)
    return sorted(names)


def validate_bundled_runtime(root: Path) -> dict:
    """Return SHA256 hashes for python.exe and its matching Python DLL.

    Missing files, empty files, symlinks, reparse points and traversal paths
    raise PackageError. python3.dll alone is not the versioned runtime DLL.
    """
    root = Path(root)
    _reject_traversal_root(root)
    if root.is_symlink() or _is_link_or_reparse(root):
        raise PackageError("Refusing a linked bundled runtime root")
    if not root.is_dir():
        raise PackageError("Bundled runtime root is not a real directory")
    root = _inside(root, root)
    files = {"python.exe": _require_file(root, "python.exe")}
    dll_names = _versioned_dll_names(root)
    if not dll_names:
        raise PackageError("Bundled runtime is missing the Python DLL")
    for name in dll_names:
        files[name] = _require_file(root, name)
    if len(dll_names) != 1:
        raise PackageError("Bundled runtime must contain exactly one Python DLL")
    return {"files": files, "python_dll": dll_names[0]}
