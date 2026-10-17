from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from kirabridge.bridge_core.models import BridgeError


class PrincipalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capabilities: list[str] = Field(default_factory=lambda: ["bridge.health", "task.read"])
    roots: list[str] = Field(default_factory=list)
    executables: list[str] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)
    token_env: str | None = None


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    executable: str | None = None
    model: str | None = None
    api_key_env: str = "XAI_API_KEY"


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data_dir: str = str(Path.home() / ".local/share/kirabridge")
    concurrency: int = Field(default=2, ge=1, le=32)
    max_queued: int = Field(default=1000, ge=1, le=100000)
    max_control_queued: int = Field(default=32, ge=1, le=1000)
    max_task_bytes: int = Field(default=2097152, ge=1024, le=8388608)
    lease_seconds: float = Field(default=30, ge=2, le=600)
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    allow_remote: bool = False
    credentials_file: str | None = None
    tls_cert: str | None = None
    tls_key: str | None = None
    allowed_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1", "[::1]"])
    allowed_origins: list[str] = Field(default_factory=list)
    max_http_requests: int = Field(default=32, ge=1, le=256)
    principals: dict[str, PrincipalConfig] = Field(
        default_factory=lambda: {"local": PrincipalConfig()}
    )
    agents: dict[str, AgentConfig] = Field(default_factory=dict)

    @property
    def state_path(self) -> Path:
        return Path(self.data_dir).expanduser().absolute()

    def validate_network(self) -> None:
        local = self.host in {"127.0.0.1", "::1", "localhost"}
        if not local and not (self.allow_remote and self.tls_cert and self.tls_key):
            raise BridgeError(
                "unsafe_bind", "Remote binding requires allow_remote and TLS cert/key"
            )
        if bool(self.tls_cert) != bool(self.tls_key):
            raise BridgeError("tls_config", "Configure both TLS certificate and key")
        if not any(p.token_env for p in self.principals.values()):
            raise BridgeError("auth_config", "HTTP requires a configured bearer token environment")
        tokens = [os.environ.get(p.token_env, "") for p in self.principals.values() if p.token_env]
        if any(len(t) < 32 for t in tokens) or len(set(tokens)) != len(tokens):
            raise BridgeError(
                "auth_config", "HTTP tokens must be unique and at least 32 characters"
            )


def load_config(path: str | None = None) -> Config:
    path = path or os.environ.get("KIRABRIDGE_CONFIG")
    default = Path.home() / ".config/kirabridge/config.toml"
    if path is None and default.is_file():
        path = str(default)
    if path:
        with open(path, "rb") as source:
            return Config.model_validate(tomllib.load(source))
    return Config()


def private_directory(path: Path) -> None:
    if path.is_symlink():
        raise BridgeError("unsafe_state", "State directory must not be a symlink")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if sys.platform != "win32":
        if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
            raise BridgeError("unsafe_state", "State directory must be owner-only (chmod 700)")
