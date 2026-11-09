"""Revocable home-device keys for the existing remote relay. No queue, no second authority.

A device is paired once with a short-lived one-time code. Pairing yields a per-device
secret key (shown once; only its SHA-256 is stored). The record binds device_ref, scope
(workspace_ref) and an optional expiry. Revocation takes effect on the next check.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import time
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError

REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
MAX_CODE_TTL = 900


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class DevicePairing:
    def __init__(self, path, *, clock=time.time):
        self.path, self.clock = Path(path), clock

    def _load(self):
        try:
            return json.loads(self.path.read_text())
        except FileNotFoundError:
            return {"codes": {}, "devices": {}}

    def _save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(data, handle, sort_keys=True)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def begin(self, device_ref, workspace_ref, *, code_ttl=300, device_ttl=None):
        """Operator side: one-time code for exactly this device and scope."""
        if not (REF.fullmatch(device_ref) and REF.fullmatch(workspace_ref)):
            raise BridgeError("pairing_invalid", "Invalid device or scope reference")
        if not 0 < code_ttl <= MAX_CODE_TTL:
            raise BridgeError("pairing_invalid", "Invalid pairing code lifetime")
        code = secrets.token_urlsafe(24)
        data = self._load()
        data["codes"][_hash(code)] = {
            "device_ref": device_ref,
            "workspace_ref": workspace_ref,
            "expires_at": self.clock() + code_ttl,
            "device_ttl": device_ttl,
        }
        self._save(data)
        return code

    def complete(self, code, device_ref):
        """Device side: trade the one-time code for the device key (returned once)."""
        data = self._load()
        entry = data["codes"].pop(_hash(code), None)
        if entry is None or entry["device_ref"] != device_ref:
            if entry is not None:  # wrong device burns the code
                self._save(data)
            raise BridgeError("pairing_denied", "Unknown or mismatched pairing code")
        self._save(data)
        now = self.clock()
        if now >= entry["expires_at"]:
            raise BridgeError("pairing_expired", "Pairing approval expired")
        key = secrets.token_urlsafe(32)
        data["devices"][device_ref] = {
            "key_sha256": _hash(key),
            "workspace_ref": entry["workspace_ref"],
            "paired_at": now,
            "expires_at": None if entry["device_ttl"] is None else now + entry["device_ttl"],
            "revoked": False,
        }
        self._save(data)
        return key

    def revoke(self, device_ref):
        data = self._load()
        record = data["devices"].get(device_ref)
        if record is None:
            raise BridgeError("pairing_denied", "Unknown device")
        record["revoked"] = True
        self._save(data)

    def authorize(self, device_ref, workspace_ref, key=None):
        """Raise unless the device is paired, current, in scope and (if given) key-correct."""
        record = self._load()["devices"].get(device_ref)
        if record is None:
            raise BridgeError("device_not_paired", "Device is not paired")
        if record["revoked"]:
            raise BridgeError("device_revoked", "Device key was revoked")
        if record["expires_at"] is not None and self.clock() >= record["expires_at"]:
            raise BridgeError("device_expired", "Device pairing expired")
        if record["workspace_ref"] != workspace_ref:
            raise BridgeError("device_scope", "Workspace is outside the paired scope")
        if key is not None and not hmac.compare_digest(record["key_sha256"], _hash(key)):
            raise BridgeError("device_key_invalid", "Device key does not match")
        return record
