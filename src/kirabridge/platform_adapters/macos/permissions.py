"""Explicit public, no-prompt checks bound to the actual calling process.

These observations never grant a Bridge capability. In particular a Core check
cannot authorize osascript, pbpaste or the desktop application.

Public API references (also verified in Apple's local macOS 12.1 SDK headers):
https://developer.apple.com/documentation/applicationservices/1460720-axisprocesstrusted
https://developer.apple.com/documentation/coregraphics/cgpreflightscreencaptureaccess()
"""

from __future__ import annotations

import os
import sys
import threading
import time
from copy import deepcopy

STATES = {"granted", "denied", "not_determined", "unknown", "not_applicable"}


def core_permission(resource):
    """Check only this process. Never call AX/CG request APIs or read TCC storage."""
    if sys.platform != "darwin":
        return {"state": "not_applicable", "method": "platform"}
    if resource == "accessibility":
        library = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        name = "AXIsProcessTrusted"
    elif resource == "screen_capture":
        library = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        name = "CGPreflightScreenCaptureAccess"
    else:
        return {"state": "unknown", "method": "no_public_generic_preflight"}
    import ctypes

    try:
        function = getattr(ctypes.CDLL(library), name)
        function.argtypes = []
        function.restype = ctypes.c_bool
        raw = bool(function())
    except (OSError, AttributeError):
        return {"state": "unknown", "method": "public_symbol_unavailable"}
    # A false AX Boolean does not distinguish denied from not-yet-determined.
    return {"state": "granted" if raw else "unknown", "raw_granted": raw, "method": name}


class PermissionProbe:
    def __init__(self, *, reader=None, clock=None, max_age=5.0):
        self.reader = reader or core_permission
        self.clock = clock or time.monotonic
        self.max_age = max_age
        self._lock = threading.RLock()
        self._observations = {}
        self.identity = {"pid": os.getpid(), "executable": sys.executable}

    def refresh_core(self, resources=("accessibility", "screen_capture")):
        """Explicit status action only; never call this from tools/list."""
        for resource in resources:
            observed = dict(self.reader(resource))
            self.record(resource, actor="core", observation=observed, identity=self.identity)
        return self.snapshot()

    def record(self, resource, *, actor, observation, identity, target=None):
        """Internal injection seam, never exposed as caller-supplied MCP evidence."""
        if observation.get("state") not in STATES:
            raise ValueError("Unrecognized permission state")
        with self._lock:
            self._observations[(resource, actor, target)] = {
                **observation,
                "resource": resource,
                "actor": actor,
                "target": target,
                "identity": dict(identity),
                "observed_at": self.clock(),
            }

    def status(self, resource, *, actor, target=None, identity=None):
        with self._lock:
            observed = self._observations.get((resource, actor, target))
            if observed and 0 <= self.clock() - observed["observed_at"] <= self.max_age:
                if identity is not None and observed["identity"] == identity:
                    return deepcopy(observed)
        return {
            "resource": resource,
            "actor": actor,
            "target": target,
            "state": "unknown",
            "method": "no_fresh_matching_process_observation",
        }

    def snapshot(self):
        with self._lock:
            return [
                self.status(resource, actor=actor, target=target, identity=value["identity"])
                for (resource, actor, target), value in sorted(
                    self._observations.items(), key=lambda pair: repr(pair[0])
                )
            ]
