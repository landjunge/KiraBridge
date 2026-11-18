"""Synthetic local socket/registry guards; never connect to a Codex process."""

import json
import os
import socket
import struct
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.config import NativeCodexBinding
from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters import codex_host

REAL_CENSUS = codex_host._host_socket_path
REAL_SOCKET = socket.socket


@pytest.fixture
def local_host(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="kb-host-") as folder:
        root = Path(folder).resolve()
        path = root / "fixture.sock"
        endpoint = socket.socket(socket.AF_UNIX)
        endpoint.bind(str(path))
        path.chmod(0o600)
        registry_dir = root / "app-server-daemon"
        registry_dir.mkdir(mode=0o700)
        registry = registry_dir / "daemon.pid"
        started = int(datetime(2026, 11, 13, 10, 38, 7).timestamp())
        saved = {"pid": 1234, "processIdentity": {"startSeconds": started, "bootId": "boot"}}
        registry.write_text(json.dumps(saved))
        registry.chmod(0o644)
        binding = NativeCodexBinding(
            thread_id="11111111-1111-7111-8111-111111111111",
            session_id="11111111-1111-7111-8111-111111111111",
            source="vscode",
            codex_home=str(root),
            host_executable="/fixture/codex",
        )
        state = SimpleNamespace(
            peer_pid=1234,
            uid=os.getuid(),
            process_path=binding.host_executable,
            raw=None,
        )

        class Raw:
            def __init__(self, *_):
                self.closed = False
                state.raw = self

            def settimeout(self, _):
                pass

            def setblocking(self, _):
                pass

            def connect(self, selected):
                assert selected == str(path)

            def getsockopt(self, *_):
                return struct.pack("i", state.peer_pid)

            def close(self):
                self.closed = True

        def process(*_args, **kwargs):
            assert kwargs["timeout"] == 2
            return SimpleNamespace(
                stdout=f"{state.uid} Fri Nov 13 10:38:07 2026 "
                "/fixture/codex app-server --listen unix:// --managed-daemon"
            )

        monkeypatch.setattr(codex_host.sys, "platform", "darwin")
        monkeypatch.setattr(codex_host.socket, "socket", Raw)
        monkeypatch.setattr(codex_host.subprocess, "run", process)
        monkeypatch.setattr(codex_host, "_process_path", lambda _: state.process_path)
        monkeypatch.setattr(codex_host, "_host_socket_path", lambda _: state.path)
        state.path = path
        yield binding, state, registry, saved, path
        endpoint.close()


def test_owned_daemon_registry_0644_inside_private_directory_is_supported(local_host):
    binding, state, _, _, _ = local_host
    raw, generation = codex_host._socket(binding)
    assert raw is state.raw and len(generation) == 64
    raw.close()


@pytest.mark.parametrize(
    "change",
    [
        "peer_pid",
        "uid",
        "process_path",
        "reused_pid",
        "socket_permissions",
        "directory_permissions",
        "registry_symlink",
        "socket_symlink",
    ],
)
def test_stale_forged_and_reused_physical_host_identities_are_refused(local_host, change):
    binding, state, registry, saved, path = local_host
    if change == "peer_pid":
        state.peer_pid += 1
    elif change == "uid":
        state.uid += 1
    elif change == "process_path":
        state.process_path = "/another/codex"
    elif change == "reused_pid":
        saved["processIdentity"]["startSeconds"] += 1
        registry.write_text(json.dumps(saved))
    elif change == "socket_permissions":
        path.chmod(0o666)
    elif change == "directory_permissions":
        registry.parent.chmod(0o755)
    elif change == "registry_symlink":
        actual = registry.with_name("other-registry")
        registry.rename(actual)
        registry.symlink_to(actual)
    else:
        alias = path.with_name("alias.sock")
        alias.symlink_to(path)
        state.path = alias
    with pytest.raises(BridgeError):
        codex_host._socket(binding)
    assert state.raw is None or state.raw.closed


@pytest.mark.parametrize("mode", ["unique", "moved", "ambiguous", "wrong_pid"])
def test_socket_census_refreshes_only_one_endpoint_owned_by_registered_host(
    local_host, monkeypatch, mode
):
    _, _, _, _, path = local_host
    census = REAL_CENSUS
    other = path.with_name("moved.sock")
    endpoint = REAL_SOCKET(socket.AF_UNIX)
    try:
        endpoint.bind(str(other))
        other.chmod(0o600)
        names = [path, path] if mode == "unique" else [other]
        if mode == "ambiguous":
            names = [path, other]
        pid = 5678 if mode == "wrong_pid" else 1234
        monkeypatch.setattr(
            codex_host.subprocess,
            "run",
            lambda *_args, **_kwargs: SimpleNamespace(
                stdout=f"p{pid}\n" + "".join(f"n{candidate}\n" for candidate in names)
            ),
        )
        if mode in {"ambiguous", "wrong_pid"}:
            with pytest.raises(BridgeError):
                census(1234)
        else:
            assert census(1234) == (path if mode == "unique" else other)
    finally:
        endpoint.close()


def _release(home, version, arch="x86_64-apple-darwin"):
    binary = home / "packages" / "app-server-daemon" / "releases" / f"{version}-{arch}" / "bin"
    binary.mkdir(parents=True)
    (binary / "codex").write_text("")
    return str(binary / "codex")


def _binding(home, pinned):
    from kirabridge.bridge_core.config import NativeCodexBinding

    return NativeCodexBinding(
        thread_id="11111111-1111-7111-8111-111111111111",
        session_id="11111111-1111-7111-8111-111111111111",
        codex_home=str(home),
        host_executable=pinned,
        source="vscode",
    )


def test_host_patch_update_keeps_the_assignment_but_nothing_else_does(tmp_path):
    from kirabridge.platform_adapters.codex_host import _same_host_line

    home = tmp_path.resolve() / ".codex"
    pinned = _release(home, "0.169.0")
    binding = _binding(home, pinned)
    assert _same_host_line(binding, pinned)
    assert _same_host_line(binding, _release(home, "0.169.1"))  # patch update
    assert not _same_host_line(binding, _release(home, "0.170.0"))  # other minor line
    assert not _same_host_line(binding, _release(home, "0.169.2", "aarch64-apple-darwin"))
    outside = tmp_path.resolve() / "elsewhere" / "bin"
    outside.mkdir(parents=True)
    (outside / "codex").write_text("")
    assert not _same_host_line(binding, str(outside / "codex"))
    assert not _same_host_line(binding, str(home / "packages" / "missing" / "bin" / "codex"))
