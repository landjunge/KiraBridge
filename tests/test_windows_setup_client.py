"""Download/identity/start guards only; no Windows binary or network is executed."""

import hashlib
import io
import json
import os
import struct
import subprocess
import urllib.request
import zipfile
from types import SimpleNamespace

import pytest

from kirabridge import windows_setup_client as client
from kirabridge.bridge_core.models import BridgeError
from kirabridge.private_files import write_private

TUNNEL = "tunnel_" + "a" * 32
TOKEN = "local_dummy_token_" + "a" * 48
KEY = "sk-runtime-test-secret-never-argv"
REAL_DOWNLOAD = client.download


def pe():
    data = bytearray(128)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 64)
    data[64:70] = b"PE\0\0\x64\x86"
    return bytes(data)


def archive(files):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as output:
        for name, value in files.items():
            output.writestr(name, value)
    return data.getvalue()


@pytest.fixture
def bundle(monkeypatch):
    monkeypatch.setattr(client, "windows", lambda: None)
    files = {
        name: pe() if name.endswith(".exe") else ("fixture-" + name).encode()
        for name in client.FILE_SHA256
    }
    data = archive(files)
    monkeypatch.setattr(
        client,
        "FILE_SHA256",
        {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()},
    )
    monkeypatch.setattr(client, "FILE_SIZES", {name: len(raw) for name, raw in files.items()})
    monkeypatch.setattr(client, "ARCHIVE_SHA256", hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(client, "ARCHIVE_SIZE", len(data))
    monkeypatch.setattr(client, "download", lambda: data)
    return files, data


@pytest.fixture
def prepared(bundle, tmp_path):
    binary = client.install_client(tmp_path)
    connection = tmp_path / "connection"
    connection.mkdir(mode=0o700)
    key = connection / "runtime.key"
    write_private(key, KEY)
    profile = client.prepare_profile(binary, tmp_path, TUNNEL, key, "http://127.0.0.1:8768/mcp")
    return binary, profile, tmp_path, key


def test_install_pins_every_file_and_reuses_without_download_or_execution(
    bundle, tmp_path, monkeypatch
):
    binary = client.install_client(tmp_path)
    assert binary.name == "tunnel-client.exe"
    for name, value in bundle[0].items():
        assert (binary.parent / name).read_bytes() == value
    proof = json.loads((binary.parent / "provenance.json").read_bytes())
    assert proof["archive_sha256"] == client.ARCHIVE_SHA256
    assert proof["source_commit"] == client.SOURCE_COMMIT
    assert proof["program_executed_by_installer"] is False
    monkeypatch.setattr(client, "download", lambda: pytest.fail("Existing client must be reused"))
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: pytest.fail("Installer never executes")
    )
    assert client.find_client(tmp_path) == binary
    assert client.install_client(tmp_path) == binary


def test_partial_or_modified_installation_is_preserved(bundle, tmp_path):
    binary = client.install_client(tmp_path)
    binary.write_bytes(b"modified")
    with pytest.raises(BridgeError, match="existing state"):
        client.install_client(tmp_path)
    assert binary.read_bytes() == b"modified"
    (binary.parent / "provenance.json").unlink()
    with pytest.raises(BridgeError):
        client.find_client(tmp_path)
    assert binary.exists()


@pytest.mark.parametrize("kind", ["extra", "traversal", "missing", "changed", "wrong-pe"])
def test_archive_rejects_unknown_paths_wrong_bytes_and_wrong_architecture(
    bundle, kind, monkeypatch
):
    files = dict(bundle[0])
    if kind == "extra":
        files["unexpected.cmd"] = b"never run"
    elif kind == "traversal":
        files["../escape"] = files.pop("NOTICE")
    elif kind == "missing":
        del files["cloudflared.exe"]
    elif kind == "changed":
        files["NOTICE"] += b"modified"
    else:
        files["tunnel-client.exe"] = pe().replace(b"\x64\x86", b"\xaa\xbb")
        monkeypatch.setitem(
            client.FILE_SHA256,
            "tunnel-client.exe",
            hashlib.sha256(files["tunnel-client.exe"]).hexdigest(),
        )
    with pytest.raises(BridgeError) as error:
        client.archive_files(archive(files))
    assert error.value.code == "setup_client_archive"


def test_symlink_install_destination_is_not_followed(bundle, tmp_path):
    target = tmp_path / "actual"
    target.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(BridgeError) as error:
        client.install_client(alias)
    assert error.value.code == "setup_client_path"
    assert list(target.iterdir()) == []


def test_profile_contains_only_secret_references_and_reuses_without_rewrite(prepared):
    binary, profile, state, key = prepared
    raw, modified = profile.read_bytes(), profile.stat().st_mtime_ns
    value = json.loads(raw)
    assert KEY.encode() not in raw and TOKEN.encode() not in raw
    assert value["control_plane"]["api_key"] == "file:" + key.as_posix()
    assert value["mcp"]["extra_headers"] == {"Authorization": "env:" + client.AUTH_ENV}
    assert value["mcp"]["discovery_extra_headers"] == value["mcp"]["extra_headers"]
    assert "commands" not in value["mcp"]
    assert (
        client.prepare_profile(binary, state, TUNNEL, key, "http://127.0.0.1:8768/mcp") == profile
    )
    assert profile.read_bytes() == raw and profile.stat().st_mtime_ns == modified
    with pytest.raises(BridgeError) as error:
        client.prepare_profile(
            binary, state, "tunnel_" + "b" * 32, key, "http://127.0.0.1:8768/mcp"
        )
    assert error.value.code == "setup_client_profile_mismatch"
    assert profile.read_bytes() == raw


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/mcp",
        "http://localhost:8768/mcp",
        "http://127.0.0.1:8768/mcp?token=secret",
        "http://user:secret@127.0.0.1:8768/mcp",
    ],
)
def test_profile_refuses_external_or_credential_bearing_endpoint(prepared, url):
    binary, _, state, key = prepared
    with pytest.raises(BridgeError) as error:
        client.prepare_profile(binary, state, TUNNEL, key, url)
    assert error.value.code == "setup_client_endpoint"


def test_child_only_environment_removes_command_logging_and_network_overrides(monkeypatch):
    keys = {
        "MCP_COMMAND": "second-bridge",
        "CONTROL_PLANE_API_KEY": "inherited-secret",
        "TUNNEL_CLIENT_PROFILE_FILE": "other",
        "LOG_HTTP_RAW_UNSAFE": "true",
        "HEALTH_LISTEN_ADDR": "0.0.0.0:1",
        "CLOUDFLARED_MANAGED": "true",
        "ALLOW_REMOTE_UI": "true",
        "OPEN_WEB_UI": "true",
        "GODEBUG": "http2debug=2",
        "CA_BUNDLE": "wrong",
        "HTTPS_PROXY": "http://other",
        "SYSTEMROOT": "C:\\Windows",
    }
    for key, value in keys.items():
        monkeypatch.setenv(key, value)
    env = client.child_environment(TOKEN)
    assert env[client.AUTH_ENV] == "Bearer " + TOKEN
    assert env["SYSTEMROOT"] == "C:\\Windows"
    assert not (set(keys) - {"SYSTEMROOT"}) & set(env)
    assert os.environ["MCP_COMMAND"] == "second-bridge"
    assert TOKEN not in os.environ.values()


def stub_process(prepared, monkeypatch):
    binary, profile, state, _ = prepared
    record = {
        "pid": 1234,
        "created_100ns": "134382301975786026",
        "image": str(binary),
        "running": True,
    }
    calls = []

    def popen(arguments, **options):
        attempt = json.loads((state / "connection/tunnel-start-attempt.json").read_bytes())
        assert attempt["state"] == "attempted_no_automatic_restart"
        calls.append((arguments, options))
        return SimpleNamespace(pid=1234)

    monkeypatch.setattr(client.subprocess, "CREATE_NEW_CONSOLE", 0x10, raising=False)
    monkeypatch.setattr(client.subprocess, "Popen", popen)
    monkeypatch.setattr(client, "process_identity", lambda pid: dict(record))
    monkeypatch.setattr(client, "same_process", lambda value: value == record)
    return binary, profile, state, record, calls


def test_start_is_one_visible_owned_run_with_secret_only_in_child_env(prepared, monkeypatch):
    binary, profile, state, record, calls = stub_process(prepared, monkeypatch)
    child = client.start_client(binary, profile, state, TOKEN)
    assert child.pid == record["pid"] and len(calls) == 1
    args, options = calls[0]
    assert args[1] == "run" and "--profile-file" in args and "--mcp.command" not in args
    assert TOKEN not in repr(args) and KEY not in repr(args)
    assert options["env"][client.AUTH_ENV] == "Bearer " + TOKEN
    assert options["creationflags"] == 0x10 and options["close_fds"] is True
    assert "stdout" not in options and "stderr" not in options
    assert client.start_client(binary, profile, state, TOKEN) is None
    assert len(calls) == 1


def test_missing_or_reused_generation_never_causes_replacement_start(prepared, monkeypatch):
    binary, profile, state, _, calls = stub_process(prepared, monkeypatch)
    client.start_client(binary, profile, state, TOKEN)
    monkeypatch.setattr(client, "same_process", lambda _: False)
    with pytest.raises(BridgeError) as error:
        client.start_client(binary, profile, state, TOKEN)
    assert error.value.code == "setup_client_start_unknown" and len(calls) == 1
    (state / "connection/tunnel-process.json").unlink()
    with pytest.raises(BridgeError):
        client.start_client(binary, profile, state, TOKEN)
    assert len(calls) == 1


def test_spawn_error_retains_attempt_without_exposing_provider_text(prepared, monkeypatch):
    binary, profile, state, _, _ = stub_process(prepared, monkeypatch)
    calls = []

    def failed(*arguments, **options):
        calls.append(True)
        raise OSError(TOKEN)

    monkeypatch.setattr(client.subprocess, "Popen", failed)
    for _ in range(2):
        with pytest.raises(BridgeError) as error:
            client.start_client(binary, profile, state, TOKEN)
        assert TOKEN not in str(error.value)
    assert len(calls) == 1
    assert (state / "connection/tunnel-start-attempt.json").exists()


def health_fixture(prepared, monkeypatch):
    binary, profile, state, record, calls = stub_process(prepared, monkeypatch)
    client.start_client(binary, profile, state, TOKEN)
    write_private(state / "connection/tunnel-health.url", "http://127.0.0.1:23456")
    monkeypatch.setattr(client, "listeners", lambda port: [{"pid": 1234, "host": "127.0.0.1"}])
    data = {
        "schema_version": 1,
        "live": True,
        "ready": True,
        "components": {
            "control-plane": {
                "status": "ok",
                "details": {"last_success": "2026-11-04T12:00:00Z", "consecutive_failures": 0},
            }
        },
    }
    responses = {
        "/healthz": (200, b"live"),
        "/readyz": (200, b"ready"),
        "/health?details=true": (200, json.dumps(data).encode()),
    }
    monkeypatch.setattr(client, "health_get", lambda base, route: responses[route])
    return state, responses, data, record


def test_status_requires_owned_http_readiness_and_successful_poll(prepared, monkeypatch):
    state, responses, data, _ = health_fixture(prepared, monkeypatch)
    observed = client.client_status(state)
    assert observed["ready"] is True and observed["active_polling"] is True
    assert observed["chatgpt_tool_call"] == "unverified"
    responses["/readyz"] = 200, b"ready (mcp initialize requires auth: 401)"
    assert client.client_status(state)["ready"] is False
    responses["/readyz"] = 200, b"ready"
    data["components"]["control-plane"]["details"].pop("last_success")
    responses["/health?details=true"] = 200, json.dumps(data).encode()
    assert client.client_status(state)["ready"] is False


def test_unknown_listener_is_not_contacted(prepared, monkeypatch):
    state, _, _, _ = health_fixture(prepared, monkeypatch)
    monkeypatch.setattr(client, "listeners", lambda _: [{"pid": 9999, "host": "127.0.0.1"}])
    monkeypatch.setattr(
        client, "health_get", lambda *args: pytest.fail("Unknown endpoint contacted")
    )
    with pytest.raises(BridgeError) as error:
        client.client_status(state)
    assert error.value.code == "setup_client_health_owner"


def test_external_health_file_is_never_followed(prepared, monkeypatch):
    state, _, _, _ = health_fixture(prepared, monkeypatch)
    (state / "connection/tunnel-health.url").write_text("https://external.example/")
    monkeypatch.setattr(
        client, "health_get", lambda *args: pytest.fail("External endpoint contacted")
    )
    with pytest.raises(BridgeError) as error:
        client.client_status(state)
    assert error.value.code == "setup_client_endpoint"


def test_redirect_handlers_refuse_downgrade_external_and_health_redirects():
    request = urllib.request.Request(client.ASSET_URL)
    for url in ("http://github.com/file", "https://evil.example/file"):
        with pytest.raises(BridgeError):
            client.ReleaseRedirect().redirect_request(request, None, 302, "", {}, url)
    with pytest.raises(BridgeError):
        client.NoRedirect().redirect_request(request, None, 302, "", {}, "http://127.0.0.1:1234/")


def test_real_host_guard_rejects_windows_operations_before_any_install(tmp_path):
    if os.name == "nt":
        pytest.skip("This guard is specifically for the non-Windows development host")
    with pytest.raises(BridgeError) as error:
        client.install_client(tmp_path)
    assert error.value.code == "setup_client_platform"
    assert list(tmp_path.iterdir()) == []


def test_download_checks_whole_archive_and_disables_proxies(bundle, monkeypatch):
    captured = []

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == client.ASSET_URL and timeout == 15
            return io.BytesIO(bundle[1])

    def build(*handlers):
        captured.extend(handlers)
        return Opener()

    monkeypatch.setattr(client.urllib.request, "build_opener", build)
    assert REAL_DOWNLOAD() == bundle[1]
    assert isinstance(captured[0], urllib.request.ProxyHandler) and captured[0].proxies == {}
    assert isinstance(captured[1], client.ReleaseRedirect)
    monkeypatch.setattr(client, "ARCHIVE_SHA256", "f" * 64)
    with pytest.raises(BridgeError) as error:
        REAL_DOWNLOAD()
    assert error.value.code == "setup_client_checksum"


def test_download_limits_prevent_unbounded_body_or_provider_error_leak(bundle, monkeypatch):
    class Opener:
        def open(self, request, timeout):
            return io.BytesIO(bundle[1] + b"extra")

    monkeypatch.setattr(client.urllib.request, "build_opener", lambda *args: Opener())
    with pytest.raises(BridgeError) as error:
        REAL_DOWNLOAD()
    assert error.value.code == "setup_client_download_limit"

    class Failure:
        def open(self, request, timeout):
            raise OSError(TOKEN)

    monkeypatch.setattr(client.urllib.request, "build_opener", lambda *args: Failure())
    with pytest.raises(BridgeError) as error:
        REAL_DOWNLOAD()
    assert error.value.code == "setup_client_download_failed" and TOKEN not in str(error.value)


def test_health_body_is_bounded_and_proxy_free(monkeypatch):
    captured = []

    class Response(io.BytesIO):
        status = 200

    class Opener:
        def open(self, url, timeout):
            assert url == "http://127.0.0.1:23456/health" and timeout == 3
            return Response(b"x" * 65537)

    def build(*handlers):
        captured.extend(handlers)
        return Opener()

    monkeypatch.setattr(client.urllib.request, "build_opener", build)
    with pytest.raises(BridgeError) as error:
        client.health_get("http://127.0.0.1:23456", "/health")
    assert error.value.code == "setup_client_health_limit"
    assert isinstance(captured[0], urllib.request.ProxyHandler) and captured[0].proxies == {}
    assert isinstance(captured[1], client.NoRedirect)


@pytest.mark.parametrize(
    "name", ["tunnel-health.url", "tunnel-process.json", "tunnel-spawned.json", "tunnel.pid"]
)
def test_orphaned_start_evidence_blocks_even_without_original_attempt(prepared, monkeypatch, name):
    binary, profile, state, _ = prepared
    write_private(state / "connection" / name, "original evidence")
    monkeypatch.setattr(
        client.subprocess, "Popen", lambda *a, **k: pytest.fail("Orphaned start replayed")
    )
    with pytest.raises(BridgeError) as error:
        client.start_client(binary, profile, state, TOKEN)
    assert error.value.code == "setup_client_start_unknown"
    assert client.client_status(state)["started"] is None
    assert (state / "connection" / name).read_text() == "original evidence"


def test_native_private_creator_receives_absent_target_after_exclusive_reservation(
    bundle, tmp_path, monkeypatch
):
    original = client.private_directory
    folder = tmp_path / "tools" / ("tunnel-client-" + client.VERSION)
    reservation = folder.parent / (folder.name + "-install-reservation.json")
    seen = []

    def creating(path):
        if path == folder:
            assert not path.exists(), "Never precreate with Python3.14 mkdir(0700)"
            assert reservation.is_file(), "Exclusive reservation must precede native creation"
            seen.append(path)
        original(path)

    monkeypatch.setattr(client, "private_directory", creating)
    assert client.install_client(tmp_path) == folder / "tunnel-client.exe"
    assert seen == [folder]


def test_abandoned_reservation_blocks_before_a_new_download(bundle, tmp_path, monkeypatch):
    parent = tmp_path / "tools"
    parent.mkdir(mode=0o700)
    reservation = parent / ("tunnel-client-" + client.VERSION + "-install-reservation.json")
    write_private(reservation, '{"state":"original_unknown"}')
    monkeypatch.setattr(client, "download", lambda: pytest.fail("Reserved install replayed"))
    with pytest.raises(BridgeError) as error:
        client.install_client(tmp_path)
    assert error.value.code == "setup_client_existing"
    assert reservation.read_text() == '{"state":"original_unknown"}'
