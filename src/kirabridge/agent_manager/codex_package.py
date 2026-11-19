"""Passive observations of the pinned official Codex 0.169 package layout.

Reference: openai/codex rust-v0.169.0 install-context/src/lib.rs and
scripts/codex_package/layout.py, targets.py, build_winget_package.py.
Never executes a launcher, parses wrapper commands or gates an agent request.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

REFERENCE_VERSION = "0.169.0"
METADATA_LIMIT = 16384
TARGETS = {
    "linux": {
        "x86_64-unknown-linux-gnu",
        "x86_64-unknown-linux-musl",
        "aarch64-unknown-linux-gnu",
        "aarch64-unknown-linux-musl",
    },
    "darwin": {"x86_64-apple-darwin", "aarch64-apple-darwin"},
    "win32": {"x86_64-pc-windows-msvc", "aarch64-pc-windows-msvc"},
}


def _read(path, limit, *, complete=False):
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or (complete and metadata.st_size > limit):
            raise ValueError("unsupported metadata file")
        result = os.read(fd, limit + int(complete))
        if complete and len(result) > limit:
            raise ValueError("metadata limit")
        return result
    finally:
        os.close(fd)


def _native_header(path, platform):
    header = _read(path, 64)
    if platform == "linux":
        return header.startswith(b"\x7fELF")
    if platform == "darwin":
        return header[:4] in {
            b"\xfe\xed\xfa\xce",
            b"\xce\xfa\xed\xfe",
            b"\xfe\xed\xfa\xcf",
            b"\xcf\xfa\xed\xfe",
            b"\xca\xfe\xba\xbe",
            b"\xbe\xba\xfe\xca",
            b"\xca\xfe\xba\xbf",
            b"\xbf\xba\xfe\xca",
        }
    if platform == "win32" and header.startswith(b"MZ") and len(header) == 64:
        offset = int.from_bytes(header[60:64], "little")
        if 64 <= offset <= 65536:
            # Read a bounded prefix, not the entire executable or its arguments.
            return _read(path, offset + 4)[offset:] == b"PE\0\0"
    return False


def _within(path, root):
    # Resolve a dangling link's destination before FileNotFoundError can turn
    # an external, unobserved layout into an in-package missing-file warning.
    if not path.resolve(strict=False).is_relative_to(root):
        raise ValueError("outside package")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError("outside package")
    return resolved


def _component(root, relative, platform, *, directory=False):
    row = {"relative_path": relative}
    try:
        path = _within(root / relative, root)
        if directory:
            state = "present" if path.is_dir() else "missing"
        elif not path.is_file():
            state = "missing"
        elif platform != "win32" and not os.access(path, os.X_OK):
            state = "not_executable"
        else:
            state = "present"
        return {**row, "state": state}
    except FileNotFoundError:
        return {**row, "state": "missing"}
    except (OSError, ValueError, RuntimeError):
        return {**row, "state": "unknown"}


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate metadata key")
        value[key] = item
    return value


def inspect_codex_package(executable, *, platform=None):
    """Observe files only; all statuses are informational, never admission gates.

    Metadata declares a package version; it does not attest the actual CLI or
    companion versions, publisher, ABI, authentication or successful tool use.
    No path, wrapper text or unknown metadata field is exported.
    """
    platform = sys.platform if platform is None else platform
    result = {
        "schema": "kirabridge.codex-package.v1",
        "status": "unknown",
        "reference_version": REFERENCE_VERSION,
        "declared_package_version": None,
        "cli_version_status": "not_probed",
        "companion_version_binding": "unverified",
        "publisher_integrity": "unverified",
        "abi_compatibility": "unverified",
        "tool_execution": "not_probed",
        "full_distribution_integrity": "unverified",
        "scope": "bounded passive filesystem observation; not atomic or runtime readiness",
        "non_blocking": True,
    }

    def unknown(reason):
        return {**result, "reason": reason}

    if platform not in TARGETS or not executable or not Path(executable).is_absolute():
        return unknown("unbound_executable_or_platform")
    try:
        exe = Path(executable).resolve(strict=True)
        if not _native_header(exe, platform):
            return unknown("launcher_target_not_observed")
        parent = exe.parent
        if parent.name == "bin":
            root, layout, bin_dir = parent.parent, "package_bin", "bin"
        elif (
            platform == "darwin"
            and parent.name == "MacOS"
            and parent.parent.name == "Contents"
            and parent.parent.parent.name == "CodexCLI.app"
        ):
            root, layout, bin_dir = parent.parent.parent.parent, "macos_provisioned", "bin"
        elif platform == "win32":
            root, layout, bin_dir = parent, "winget_root", "."
        else:
            return unknown("package_layout_not_observed")
        raw = _read(_within(root / "codex-package.json", root), METADATA_LIMIT, complete=True)
        metadata = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(metadata, dict):
            return unknown("invalid_package_metadata")
        version = metadata.get("version")
        if isinstance(version, str) and re.fullmatch(
            r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}", version
        ):
            result["declared_package_version"] = version
        if version != REFERENCE_VERSION:
            return unknown("package_version_not_covered")
        target = metadata.get("target")
        suffix = ".exe" if platform == "win32" else ""
        entrypoint = f"codex-{target}.exe" if layout == "winget_root" else f"bin/codex{suffix}"
        expected = {
            "layoutVersion": 1,
            "variant": "codex",
            "entrypoint": entrypoint,
            "execServer": f"bin/codex-exec-server{suffix}",
            "resourcesDir": "codex-resources",
            "pathDir": "codex-path",
        }
        if (
            not isinstance(target, str)
            or target not in TARGETS[platform]
            or type(metadata.get("layoutVersion")) is not int
            or any(metadata.get(key) != value for key, value in expected.items())
        ):
            return unknown("package_layout_not_covered")
        if _within(root / entrypoint, root) != exe:
            return unknown("configured_entrypoint_not_bound")
        result.update(layout=layout, target=target, metadata_sha256=hashlib.sha256(raw).hexdigest())
        resources = _component(root, "codex-resources", platform, directory=True)
        path_dir = _component(root, "codex-path", platform, directory=True)
        host = _component(root, f"codex-resources/codex-code-mode-host{suffix}", platform)
        # The real locator selects any regular resource file before its bin
        # fallback, including a non-executable one. Do not hide that failure.
        if host["state"] == "missing":
            host = _component(root, f"{bin_dir}/codex-code-mode-host{suffix}", platform)
        components = {
            "code_mode_host": host,
            "exec_server": _component(root, expected["execServer"], platform),
            "search_tool": _component(root, f"codex-path/rg{suffix}", platform),
            "resources_directory": resources,
            "path_directory": path_dir,
        }
        if platform == "linux":
            components["linux_sandbox_resource"] = _component(
                root, "codex-resources/bwrap", platform
            )
        elif platform == "win32":
            for name in ("codex-command-runner.exe", "codex-windows-sandbox-setup.exe"):
                components[name.removesuffix(".exe")] = _component(
                    root, "codex-resources/" + name, platform
                )
        states = {row["state"] for row in components.values()}
        status = (
            "layout_incomplete"
            if states & {"missing", "not_executable"}
            else "unknown"
            if "unknown" in states
            else "layout_observed"
        )
        return {
            **result,
            "status": status,
            "reason": "reference_files_observed"
            if status == "layout_observed"
            else "reference_files_incomplete"
            if status == "layout_incomplete"
            else "component_observation_unknown",
            "components": components,
        }
    except FileNotFoundError:
        return unknown("package_metadata_or_executable_not_observed")
    except (OSError, ValueError, RuntimeError, RecursionError):
        return unknown("package_observation_unavailable")
