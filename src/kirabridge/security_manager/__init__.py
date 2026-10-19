from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

from kirabridge.bridge_core.config import Config, PrincipalConfig
from kirabridge.bridge_core.models import BridgeError, TaskRequest, digest
from kirabridge.task_manager.store import Store


def request_hash(request: TaskRequest) -> str:
    return digest(request.model_dump())


class SecurityManager:
    def __init__(self, config: Config, store: Store):
        self.config, self.store = config, store

    def principal(self, name: str, capability: str | None = None) -> PrincipalConfig:
        principal = self.config.principals.get(name)
        if principal is None or (capability and capability not in principal.capabilities):
            raise BridgeError("forbidden", "Capability not granted")
        return principal

    def authenticate(self, token: str) -> str:
        if len(token) < 32:
            raise BridgeError("unauthorized", "Authentication required")
        for name, principal in self.config.principals.items():
            expected = os.environ.get(principal.token_env, "") if principal.token_env else ""
            if expected and hmac.compare_digest(token, expected):
                return name
        raise BridgeError("unauthorized", "Authentication required")

    def grant(self, principal: str, request: TaskRequest, ttl: int = 300) -> str:
        with self.store.transaction():
            return self.grant_in_transaction(principal, request, ttl)

    def grant_in_transaction(self, principal: str, request: TaskRequest, ttl: int = 300) -> str:
        """Trusted local operator only; caller owns the enclosing transaction."""
        self.principal(principal, request.operation)
        if request.api_version != "1" or not 1 <= ttl <= 3600:
            raise BridgeError("invalid_grant", "Invalid API version or approval lifetime")
        token = secrets.token_urlsafe(32)
        self.store.db.execute(
            "INSERT INTO approvals(token_hash,principal,task_id,request_hash,expires) "
            "VALUES(?,?,?,?,?)",
            (
                hashlib.sha256(token.encode()).hexdigest(),
                principal,
                request.task_id,
                request_hash(request),
                time.time() + ttl,
            ),
        )
        self.store.audit(
            "approval.granted",
            principal,
            request.task_id,
            {"operation": request.operation, "request_hash": request_hash(request)},
        )
        return token

    def consume(self, principal: str, request: TaskRequest, token: str) -> None:
        # Must share the enqueue transaction: a crash cannot consume a grant without storing a task.
        result = self.store.db.execute(
            "UPDATE approvals SET used=? WHERE token_hash=? AND principal=? AND task_id=? "
            "AND request_hash=? AND expires>? AND used IS NULL",
            (
                time.time(),
                hashlib.sha256(token.encode()).hexdigest(),
                principal,
                request.task_id,
                request_hash(request),
                time.time(),
            ),
        )
        if result.rowcount != 1:
            raise BridgeError(
                "approval_required", "Valid one-use approval for this exact task required"
            )
