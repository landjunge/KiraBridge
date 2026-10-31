"""Passive macOS transport discovery: no GUI, subprocess or permission requests."""

from __future__ import annotations

import os
import platform
import plistlib
import sys
from pathlib import Path


def host_facts():
    version, build = "", ""
    if sys.platform == "darwin":
        try:
            # Read a bounded OS metadata file, never an application/user data file.
            with Path("/System/Library/CoreServices/SystemVersion.plist").open("rb") as stream:
                raw = stream.read(65537)
            if len(raw) <= 65536:
                facts = plistlib.loads(raw)
                version = str(facts.get("ProductVersion", ""))
                build = str(facts.get("ProductBuildVersion", ""))
        except (OSError, ValueError, plistlib.InvalidFileException):
            pass
    return {
        "platform": sys.platform,
        "os_version": version,
        "os_build": build,
        "architecture": platform.machine(),
        "process": {"pid": os.getpid(), "executable": sys.executable},
    }


def version_tuple(value):
    try:
        return tuple(int(part) for part in value.split("."))
    except (AttributeError, TypeError, ValueError):
        return ()


class CapabilityProbe:
    """Capture metadata once; inspecting the snapshot never invokes a leaf adapter."""

    def __init__(self, *, facts=None, executable=None, native_metadata=None):
        self.facts = dict(host_facts() if facts is None else facts)
        self.executable = executable or (lambda path: os.access(path, os.X_OK))
        self.native_metadata = native_metadata

    def snapshot(self):
        darwin = self.facts.get("platform") == "darwin"
        version = version_tuple(self.facts.get("os_version"))
        supported = darwin and bool(version) and version >= (12,)
        result = {}
        for name, paths in {
            "files": (),
            "processes": (),
            "terminal_app": ("/usr/bin/osascript",),
            "clipboard": ("/usr/bin/pbcopy", "/usr/bin/pbpaste"),
            "desktop_session": ("/usr/sbin/ioreg",),
            "system_reports": ("/usr/sbin/system_profiler",),
        }.items():
            available = supported and all(self.executable(path) for path in paths)
            result[name] = {
                "available": available,
                "reason": "available"
                if available
                else "unsupported_platform"
                if not darwin
                else "unsupported_or_unknown_os_version"
                if not supported
                else "missing_transport",
                "minimum_os": "12.0",
                "permission_scope": "not_checked_by_technical_probe",
            }
        native = self.native_metadata() if self.native_metadata is not None else {}
        for name in (
            "system",
            "apps",
            "accessibility",
            "windows",
            "capture",
            "notifications",
            "preferences",
        ):
            minimum = (14,) if name == "capture" else (12,)
            available = supported and version >= minimum and native.get("available") is True
            result[name] = {
                "available": available,
                "reason": "available"
                if available
                else "unsupported_platform"
                if not darwin
                else "unsupported_or_unknown_os_version"
                if not supported or version < minimum
                else native.get("reason", "native_app_protocol_unavailable"),
                "minimum_os": "14.0" if name == "capture" else "12.0",
                "permission_scope": "executing_native_app_worker; checked for every operation",
                "permission_requested_automatically": False,
                "provider_revision": native.get("revision"),
            }
        result["desktop_session"]["support"] = "ioreg_key_compatibility_heuristic"
        return {"host": self.facts, "capabilities": result}
