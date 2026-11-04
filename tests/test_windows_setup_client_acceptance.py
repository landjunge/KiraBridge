"""Native helper control guards, with no CLI, network or VM execution on the host."""

import importlib.util
import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.private_files import write_private

SPEC = importlib.util.spec_from_file_location(
    "windows_setup_client_acceptance",
    Path(__file__).parents[1] / "scripts/windows_setup_client_acceptance.py",
)
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)
TOKEN = "native_local_dummy_" + "a" * 48


def test_native_check_only_uses_four_readonly_commands_and_redacts_diagnostics(
    tmp_path, monkeypatch
):
    binary = tmp_path / "official.exe"
    monkeypatch.setattr(HELPER.client, "windows", lambda: None)
    monkeypatch.setattr(HELPER.client, "find_client", lambda _: binary)
    calls = []

    def run(program, arguments, env, folder, name):
        calls.append(arguments)
        assert env[HELPER.client.AUTH_ENV] == "Bearer " + TOKEN
        if name == "version":
            return 0, b"v0.0.19\n", b""
        if name == "quickstart":
            return 0, b"tunnel-client init run", b""
        if name == "parser":
            target = Path(arguments[arguments.index("--profile-dir") + 1])
            source = Path(arguments[arguments.index("--from-file") + 1])
            target.mkdir(mode=0o700)
            write_private(target / "parser-check.yaml", source.read_bytes())
            return 0, b"Added profile", b""
        checks = [{"id": key, "status": "PASS", "summary": TOKEN} for key in HELPER.REQUIRED_DOCTOR]
        checks.append({"id": "oauth_metadata", "status": "FAIL", "summary": TOKEN})
        return 2, json.dumps({"result": "fail", "checks": checks}).encode(), b""

    monkeypatch.setattr(HELPER, "_run", run)
    result = HELPER.verify_client(binary, tmp_path, "http://127.0.0.1:8768/mcp", TOKEN)
    assert result["passed"] and result["profile_parser_passed"]
    assert result["doctor_passed"] is False and result["local_oauth_diagnostic_limited"] is True
    assert result["no_account_contact_performed"] and result["no_tunnel_runtime_started"]
    assert TOKEN not in json.dumps(result)
    assert [args[0] for args in calls] == ["--version", "help", "profiles", "doctor"]
    assert all(
        "run" not in args and "connect" not in args and TOKEN not in repr(args) for args in calls
    )


def test_bounded_cli_capture_never_returns_unbounded_output(tmp_path, monkeypatch):
    child = SimpleNamespace(
        pid=1234, stdout=io.BytesIO(b"x" * 65537), stderr=io.BytesIO(), wait=lambda timeout: 0
    )
    monkeypatch.setattr(HELPER.subprocess, "CREATE_NEW_CONSOLE", 0x10, raising=False)
    monkeypatch.setattr(HELPER.subprocess, "Popen", lambda *args, **kwargs: child)
    monkeypatch.setattr(HELPER, "process_identity", lambda _: None)
    with pytest.raises(BridgeError) as error:
        HELPER._run(tmp_path / "unused.exe", ["--version"], {}, tmp_path, "fixture")
    assert error.value.code == "setup_client_native_output_limit"
    assert (tmp_path / "fixture-attempt.json").exists()
    assert not (tmp_path / "fixture-result.json").exists()


def test_cli_timeout_preserves_original_child_and_does_not_kill_or_replay(tmp_path, monkeypatch):
    calls = []

    def wait(timeout):
        assert timeout == 45
        raise subprocess.TimeoutExpired("owned readonly fixture", timeout)

    child = SimpleNamespace(
        pid=1234,
        stdout=io.BytesIO(),
        stderr=io.BytesIO(),
        wait=wait,
        kill=lambda: pytest.fail("Unknown child must not be killed"),
    )

    def spawn(*arguments, **options):
        calls.append(arguments)
        return child

    monkeypatch.setattr(HELPER.subprocess, "CREATE_NEW_CONSOLE", 0x10, raising=False)
    monkeypatch.setattr(HELPER.subprocess, "Popen", spawn)
    monkeypatch.setattr(HELPER, "process_identity", lambda _: None)
    with pytest.raises(BridgeError) as error:
        HELPER._run(tmp_path / "unused.exe", ["--version"], {}, tmp_path, "fixture")
    assert error.value.code == "setup_client_native_unknown" and len(calls) == 1
    assert (tmp_path / "fixture-attempt.json").exists()
