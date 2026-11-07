"""Opt-in authenticated setup reply handshake; never submit desktop tasks.

The public challenge is not an authentication credential. The response code is
returned only by the authenticated read and is never stored in clear text. User
confirmation demonstrates a returned authenticated reply, not cloud-origin
attestation or continuing connectivity. Native/local tests must use simulated=True.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field

from kirabridge.bridge_core.models import BridgeError, Input

OPERATION = "windows.setup.verify"
ID_PATTERN = r"^[a-f0-9]{32}$"
CHALLENGE_PATTERN = r"^[a-f0-9]{32}\.[a-f0-9]{32}$"
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
SCHEMA = "kirabridge.windows-setup-verification.v1"
MAX_RECORDS = 512


class WindowsSetupVerifyInput(Input):
    challenge: str = Field(strict=True, pattern=CHALLENGE_PATTERN)


def host_platform():
    return sys.platform


def _digest(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _iso(nanoseconds):
    return datetime.fromtimestamp(nanoseconds / 1_000_000_000, timezone.utc).isoformat()


class _PrivateRecords:
    """Existing native owner/DACL/reparse checks and exclusive handle locking."""

    def __init__(self, state_root):
        from kirabridge.bridge_core.config import private_directory

        self.root = Path(state_root) / "setup-verification"
        private_directory(self.root)

    def _path(self, identity, kind):
        if re.fullmatch(ID_PATTERN, identity) is None or kind not in {
            "challenge",
            "reply",
            "consumed",
        }:
            raise BridgeError("setup_record_invalid", "Invalid private verification record")
        return self.root / f"{identity}.{kind}.json"

    @contextmanager
    def locked(self):
        from kirabridge.platform_adapters import RuntimeLock

        lock = RuntimeLock(self.root / "verification.runtime.lock")
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    def read(self, identity, kind):
        from kirabridge.private_files import private_json

        try:
            return private_json(self._path(identity, kind))
        except (ValueError, TypeError, UnicodeError):
            raise BridgeError(
                "setup_record_invalid", "Invalid private verification record"
            ) from None

    def create(self, identity, kind, value):
        from kirabridge.private_files import write_private

        write_private(self._path(identity, kind), json.dumps(value, separators=(",", ":")))

    def count(self):
        count = 0
        for count, _ in enumerate(self.root.iterdir(), 1):
            if count >= MAX_RECORDS:
                return count
        return count


class WindowsSetupVerification:
    def __init__(
        self,
        state_root,
        runtime_generation,
        *,
        enabled=False,
        principal="local",
        records=None,
        wall_clock=time.time_ns,
        monotonic_clock=time.monotonic_ns,
        host=None,
    ):
        if enabled is not True:
            raise BridgeError(
                "windows_setup_disabled", "Setup verification requires explicit opt-in"
            )
        if (host_platform() if host is None else host) != "win32":
            raise BridgeError("unsupported_platform", "Windows setup verification requires Windows")
        if (
            not isinstance(runtime_generation, str)
            or re.fullmatch(ID_PATTERN, runtime_generation) is None
        ):
            raise ValueError("An exact running instance_id is required")
        if (
            not isinstance(principal, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", principal) is None
        ):
            raise ValueError("An exact authenticated setup principal is required")
        self.generation, self.principal = runtime_generation, principal
        self.runtime_generation = runtime_generation
        self.records = records if records is not None else _PrivateRecords(state_root)
        self.wall, self.monotonic = wall_clock, monotonic_clock
        self._active = None
        self._active_hash = None
        self._confirmed = None

    def _validate(self, record, identity, kind):
        fields = {
            "schema",
            "kind",
            "verification_id",
            "runtime_generation",
            "principal",
            "simulated",
            "challenge_sha256",
            "issued_wall_ns",
            "expires_wall_ns",
            "issued_monotonic_ns",
            "expires_monotonic_ns",
        }
        if kind == "reply":
            fields.add("response_sha256")
        if (
            not isinstance(record, dict)
            or record.get("schema") != SCHEMA
            or set(record) != fields
            or record.get("kind") != kind
            or record.get("verification_id") != identity
            or record.get("runtime_generation") != self.generation
            or record.get("principal") != self.principal
            or type(record.get("simulated")) is not bool
        ):
            raise BridgeError(
                "setup_record_invalid", "Verification record does not match this runtime"
            )
        if (
            not isinstance(record.get("challenge_sha256"), str)
            or re.fullmatch(r"[a-f0-9]{64}", record["challenge_sha256"]) is None
        ):
            raise BridgeError("setup_record_invalid", "Verification challenge digest is invalid")
        for name in (
            "issued_wall_ns",
            "expires_wall_ns",
            "issued_monotonic_ns",
            "expires_monotonic_ns",
        ):
            if type(record.get(name)) is not int or record[name] <= 0:
                raise BridgeError("setup_record_invalid", "Verification timestamps are invalid")
        wall, monotonic = self.wall(), self.monotonic()
        if not (
            record["issued_wall_ns"] <= wall < record["expires_wall_ns"]
            and record["issued_monotonic_ns"] <= monotonic < record["expires_monotonic_ns"]
        ):
            raise BridgeError("setup_verification_expired", "Start a fresh verification challenge")
        if (
            record["expires_wall_ns"] - record["issued_wall_ns"] > 600_000_000_000
            or record["expires_monotonic_ns"] - record["issued_monotonic_ns"] > 600_000_000_000
        ):
            raise BridgeError("setup_record_invalid", "Verification lifetime exceeds its bound")
        return record

    def begin_verification(self, ttl_seconds=300, *, simulated=False):
        if (
            type(ttl_seconds) is not int
            or not 30 <= ttl_seconds <= 600
            or type(simulated) is not bool
        ):
            raise ValueError("Verification lifetime must be 30..600 seconds")
        identity, nonce = secrets.token_hex(16), secrets.token_hex(16)
        challenge = identity + "." + nonce
        wall, monotonic = self.wall(), self.monotonic()
        record = {
            "schema": SCHEMA,
            "kind": "challenge",
            "verification_id": identity,
            "runtime_generation": self.generation,
            "principal": self.principal,
            "simulated": simulated,
            "challenge_sha256": _digest(challenge),
            "issued_wall_ns": wall,
            "expires_wall_ns": wall + ttl_seconds * 1_000_000_000,
            "issued_monotonic_ns": monotonic,
            "expires_monotonic_ns": monotonic + ttl_seconds * 1_000_000_000,
        }
        with self.records.locked():
            if self.records.count() >= MAX_RECORDS:
                raise BridgeError(
                    "setup_history_limit", "Preserve and reconcile existing setup history"
                )
            self.records.create(identity, "challenge", record)
        self._active, self._confirmed = identity, None
        self._active_hash = record["challenge_sha256"]
        query = {"operation": OPERATION, "challenge": challenge}
        return {
            "verification_id": identity,
            "challenge": challenge,
            "query": query,
            "expires_at": _iso(record["expires_wall_ns"]),
            "simulated": simulated,
            "prompt": (
                "Bitte rufe in KiraBridge das Werkzeug read_query mit diesem query auf: "
                + json.dumps(query, separators=(",", ":"))
                + ". Nenne mir nur den zurückgegebenen response_code. "
                "Führe keine Tastatur- oder Fensteraktion aus."
            ),
        }

    def answer(self, challenge, principal):
        if principal != self.principal:
            raise BridgeError("forbidden", "Setup verification capability is required")
        value = WindowsSetupVerifyInput(challenge=challenge)
        identity = value.challenge.split(".", 1)[0]
        with self.records.locked():
            try:
                record = self._validate(
                    self.records.read(identity, "challenge"), identity, "challenge"
                )
            except FileNotFoundError:
                raise BridgeError(
                    "setup_challenge_unknown", "Unknown verification challenge"
                ) from None
            if not hmac.compare_digest(record.get("challenge_sha256", ""), _digest(challenge)):
                raise BridgeError("setup_challenge_unknown", "Unknown verification challenge")
            try:
                self.records.read(identity, "reply")
            except FileNotFoundError:
                pass
            else:
                raise BridgeError(
                    "setup_challenge_answered",
                    "This challenge was already answered; no second code",
                )
            response = "".join(secrets.choice(CODE_ALPHABET) for _ in range(16))
            receipt = {
                **record,
                "kind": "reply",
                "response_sha256": self._response_digest(identity, response),
            }
            try:
                self.records.create(identity, "reply", receipt)
            except FileExistsError:
                raise BridgeError(
                    "setup_challenge_answered",
                    "This challenge was already answered; no second code",
                ) from None
        return {
            "operation": OPERATION,
            "verification_id": identity,
            "response_code": response,
            "expires_at": _iso(record["expires_wall_ns"]),
            "simulated": record["simulated"],
            "cloud_attested": False,
            "desktop_effects_tested": False,
            "scope": "Authenticated reply for manual confirmation; cloud origin is not attested",
        }

    def _response_digest(self, identity, response):
        return _digest(SCHEMA + ":" + self.generation + ":" + identity + ":" + response)

    def finish_verification(self, code):
        if (
            self._active is None
            or not isinstance(code, str)
            or not code.isascii()
            or len(code) > 64
        ):
            return False
        normalized = code.replace("-", "").replace(" ", "").upper()
        if len(normalized) != 16 or any(char not in CODE_ALPHABET for char in normalized):
            return False
        identity = self._active
        with self.records.locked():
            try:
                challenge = self._validate(
                    self.records.read(identity, "challenge"), identity, "challenge"
                )
                reply = self._validate(self.records.read(identity, "reply"), identity, "reply")
            except FileNotFoundError:
                return False
            except BridgeError as error:
                if error.code in {"setup_verification_expired", "setup_record_invalid"}:
                    return False
                raise
            if challenge["challenge_sha256"] != self._active_hash:
                raise BridgeError("setup_record_invalid", "Active challenge changed after issue")
            if any(reply.get(key) != value for key, value in challenge.items() if key != "kind"):
                raise BridgeError(
                    "setup_record_invalid", "Reply is not bound to the active challenge"
                )
            expected = reply.get("response_sha256")
            if not isinstance(expected, str) or re.fullmatch(r"[a-f0-9]{64}", expected) is None:
                raise BridgeError("setup_record_invalid", "Reply digest is invalid")
            if not hmac.compare_digest(expected, self._response_digest(identity, normalized)):
                return False
            proof = {
                "schema": SCHEMA,
                "kind": "consumed",
                "verification_id": identity,
                "runtime_generation": self.generation,
                "principal": self.principal,
                "simulated": challenge["simulated"],
                "confirmed_at": _iso(self.wall()),
                "cloud_attested": False,
                "desktop_effects_tested": False,
                "permissions_tested": False,
            }
            try:
                self.records.create(identity, "consumed", proof)
            except FileExistsError:
                return False
        self._confirmed = proof
        return True

    def public_proof(self):
        proof = self._confirmed
        simulated = bool(proof and proof["simulated"])
        return {
            "verified": bool(proof) and not simulated,
            "local_test_verified": bool(proof) and simulated,
            "simulated": simulated,
            "cloud_attested": False,
            "desktop_effects_tested": False,
            "permissions_tested": False,
            "confirmed_at": proof["confirmed_at"] if proof else None,
            "scope": (
                "Not verified"
                if proof is None
                else "Local simulation"
                if simulated
                else "User-confirmed authenticated reply; no cloud attestation"
            ),
        }


def verification_available(bridge):
    return (
        host_platform() == "win32"
        and getattr(bridge.config, "windows_setup_verification_enabled", False) is True
    )


def verify_read(bridge, principal, challenge):
    bridge.security.authorize(principal, OPERATION)
    if not verification_available(bridge):
        raise BridgeError("windows_setup_disabled", "Windows setup verification is not enabled")
    service = WindowsSetupVerification(
        bridge.config.state_path,
        bridge.runtime["instance_id"],
        enabled=True,
        principal=principal,
    )
    return service.answer(challenge, principal)


def verification_catalog(bridge, principal):
    if not verification_available(bridge):
        return {}
    from kirabridge.permissions import decision

    policy = decision(bridge.config, principal, OPERATION)
    if not policy["authorized"]:
        return {}
    return {
        OPERATION: {
            "capability": OPERATION,
            "effect": "read",
            "execution_class": "read",
            "arguments": WindowsSetupVerifyInput.model_json_schema(),
            "approval_required": policy["approval_required"],
            "permission_decision": policy,
            "transport": "read_query",
            "task_submission_supported": False,
            "scope": (
                "Private setup receipt only; no input, window control or cloud-origin attestation"
            ),
        }
    }
