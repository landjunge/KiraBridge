"""Real loopback HTTP boundary tests, with only temporary fake guest payloads."""

import hashlib
import http.client
import importlib.util
import json
import os
import sys
import threading
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "windows_guest_host", Path(__file__).parents[1] / "scripts/windows_guest_host.py"
)
host = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = host
spec.loader.exec_module(host)
TOKEN = "test_capability_0123456789abcdef"


@pytest.fixture
def staging(tmp_path):
    stage = tmp_path / "staging"
    stage.mkdir()
    rows = []
    for name in [
        "guest_runner.ps1",
        "source.zip",
        "python-installer.exe",
        "wheels/example-1.0-py3-none-any.whl",
        "tools/tunnel-client-v0.0.19-windows-amd64.zip",
    ]:
        path = stage / name
        path.parent.mkdir(exist_ok=True)
        body = ("fixture:" + name).encode()
        path.write_bytes(body)
        rows.append({"path": name, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)})
    (stage / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "python_version": "3.14.10",
                "files": rows,
                "requirements": ["pytest==9.0.1"],
            }
        )
    )
    return stage


@pytest.fixture
def live(staging, tmp_path):
    state = host.GuestState(staging, tmp_path / "state", TOKEN)
    server = host.ThreadingHTTPServer(("127.0.0.1", 0), host.handler_for(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(live, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", live[0], timeout=3)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def test_only_exact_capability_and_manifest_files_are_served(live, capsys):
    for path in [
        "/wrong/manifest.json",
        "/" + TOKEN + "/../manifest.json",
        "/" + TOKEN + "/%2e%2e/secret",
        "/" + TOKEN + "/manifest.json?extra=1",
        "/" + TOKEN + "/unlisted.txt",
    ]:
        assert request(live, "GET", path)[0] == 404
    status, body = request(live, "GET", "/" + TOKEN + "/manifest.json")
    assert status == 200 and json.loads(body)["python_version"] == "3.14.10"
    status, body = request(live, "GET", "/" + TOKEN + "/wheels/example-1.0-py3-none-any.whl")
    assert status == 200 and body.startswith(b"fixture:")
    status, body = request(
        live, "GET", "/" + TOKEN + "/tools/tunnel-client-v0.0.19-windows-amd64.zip"
    )
    assert status == 200 and body.startswith(b"fixture:")
    for name in [
        "tools/other.zip",
        "tools/tunnel-client-v0.0.20-windows-amd64.zip",
        "tools/../source.zip",
    ]:
        assert request(live, "GET", "/" + TOKEN + "/" + name)[0] == 404
    assert TOKEN not in capsys.readouterr().err


def test_changed_or_symlinked_payload_is_refused(live, tmp_path):
    path = live[1].staging / "source.zip"
    path.write_bytes(b"changed")
    assert request(live, "GET", "/" + TOKEN + "/source.zip")[0] == 409
    target = tmp_path / "secret"
    target.write_bytes(b"private secret")
    path.unlink()
    path.symlink_to(target)
    status, body = request(live, "GET", "/" + TOKEN + "/source.zip")
    assert status == 409 and b"private secret" not in body


def test_reports_are_idempotent_by_exact_bytes_and_never_overwritten(live):
    route = "/" + TOKEN + "/reports/run1-keyboard"
    body = b'{"events":["a","b"],"complete":true}'
    assert request(live, "POST", route, body)[0] == 201
    status, repeat = request(live, "POST", route, body)
    assert status == 200 and json.loads(repeat)["duplicate"] is True
    assert request(live, "POST", route, b'{"different":true}')[0] == 409
    stored = live[1].state / "report-run1-keyboard.json"
    assert stored.read_bytes() == body and stored.stat().st_mode & 0o777 == 0o600
    assert request(live, "POST", "/" + TOKEN + "/reports/../escape", body)[0] == 404


def test_event_and_report_limits_reject_incomplete_or_nonobject_json(live):
    assert request(live, "POST", "/" + TOKEN + "/events", b"[]")[0] == 400
    assert request(live, "POST", "/" + TOKEN + "/events", b"not-json")[0] == 400
    assert (
        request(
            live,
            "POST",
            "/" + TOKEN + "/events",
            b"{}",
            {"Content-Length": str(host.MAX_EVENT + 1)},
        )[0]
        == 413
    )
    assert (
        request(
            live,
            "POST",
            "/" + TOKEN + "/reports/large",
            b"{}",
            {"Content-Length": str(host.MAX_REPORT + 1)},
        )[0]
        == 413
    )
    assert request(live, "POST", "/" + TOKEN + "/events", b'{"phase":"finished"}')[0] == 201
    events = live[1].state / "events.jsonl"
    assert json.loads(events.read_text())["event"]["phase"] == "finished"
    assert events.stat().st_mode & 0o777 == 0o600


def test_manifest_hashes_and_all_symlink_components_are_checked(staging, tmp_path):
    (staging / "source.zip").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="does not match"):
        host.GuestState(staging, tmp_path / "state1", TOKEN)
    link = tmp_path / "alias"
    link.symlink_to(staging, target_is_directory=True)
    with pytest.raises(ValueError, match="Symlink"):
        host.GuestState(link, tmp_path / "state2", TOKEN)


def test_token_must_be_private_and_is_not_in_public_metadata(tmp_path):
    path = tmp_path / "token"
    path.write_text(TOKEN)
    path.chmod(0o600)
    assert host.read_private_token(path) == TOKEN
    path.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        host.read_private_token(path)


def test_state_directory_is_never_exposed_or_permissions_silently_changed(staging, tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o755)
    os.chmod(state, 0o755)
    with pytest.raises(ValueError, match="private"):
        host.GuestState(staging, state, TOKEN)
    assert state.stat().st_mode & 0o777 == 0o755


@pytest.mark.parametrize(
    "name",
    [
        "tools/other.zip",
        "tools/tunnel-client-v0.0.20-windows-amd64.zip",
        "tools/tunnel-client-v0.0.19-windows-arm64.zip",
        "tools/TUNNEL-client-v0.0.19-windows-amd64.zip",
        "tools/../source.zip",
    ],
)
def test_manifest_refuses_every_other_tool_archive_path(staging, tmp_path, name):
    manifest_path = staging / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"].append({"path": name, "sha256": "a" * 64, "bytes": 1})
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Invalid or duplicate manifest path"):
        host.GuestState(staging, tmp_path / "state", TOKEN)
