"""Setup controller trust boundaries; no real account, child or input is used here."""

import json
from types import SimpleNamespace

import pytest

from kirabridge import __version__
from kirabridge import windows_setup as setup
from kirabridge import windows_setup_runtime as runtime
from kirabridge.bridge_core.models import BridgeError


@pytest.fixture
def controller(monkeypatch, tmp_path):
    from kirabridge import windows_setup_client

    value = setup.WindowsSetup(tmp_path)
    monkeypatch.setattr(setup, "require_windows", lambda: None)
    monkeypatch.setattr(setup, "require_desktop", lambda: None)
    monkeypatch.setattr(windows_setup_client, "find_client", lambda root: None)
    value.lease = SimpleNamespace(close=lambda: None)
    return value


def test_nonwindows_refuses_before_files_or_processes(monkeypatch, tmp_path):
    monkeypatch.setattr(setup.sys, "platform", "darwin")
    path = tmp_path / "absent"
    value = setup.WindowsSetup(path)
    with pytest.raises(BridgeError, match="Windows"):
        value.start_local()
    assert not path.exists()


def test_reuses_existing_owned_server_without_launch_or_input(controller, monkeypatch):
    monkeypatch.setattr(controller, "_owned_health", lambda: {"existing": True})
    monkeypatch.setattr(setup, "launch_server", lambda *a: pytest.fail("Never duplicate server"))
    response = controller.start_local()
    assert response["local_ready"] and not response["verified"]


@pytest.mark.parametrize(
    "pid,version,caps",
    [
        (777, __version__, ["windows.setup.verify"]),
        (123, "old-version", ["windows.setup.verify"]),
        (123, __version__, []),
    ],
)
def test_wrong_runtime_is_never_accepted_or_restarted(controller, monkeypatch, pid, version, caps):
    monkeypatch.setattr(setup, "saved_server", lambda p: {"pid": 123, "port": 8768})
    monkeypatch.setattr(setup, "listeners", lambda p: [{"pid": 123, "host": "127.0.0.1"}])
    monkeypatch.setattr(
        setup,
        "private_json",
        lambda p: {
            "schema": setup.CREDENTIAL_SCHEMA,
            "local": "t" * 48,
        },
    )

    async def health(*a):
        return {
            "version": version,
            "runtime": {"pid": pid},
            "dispatcher_active": True,
            "discovery": {"capabilities": caps},
        }

    monkeypatch.setattr(setup, "local_health", health)
    with pytest.raises(BridgeError) as error:
        controller._owned_health()
    assert error.value.code == "setup_version_mismatch"


def test_foreign_listener_not_contacted_and_never_receives_credentials(controller, monkeypatch):
    monkeypatch.setattr(setup, "saved_server", lambda p: {"pid": 123, "port": 8768})
    monkeypatch.setattr(setup, "listeners", lambda p: [{"pid": 999, "host": "127.0.0.1"}])
    monkeypatch.setattr(setup, "private_json", lambda p: pytest.fail("No token read"))
    with pytest.raises(BridgeError) as error:
        controller._owned_health()
    assert error.value.code == "setup_listener_changed"


def test_local_status_never_claims_cloud_connection(controller, monkeypatch):
    monkeypatch.setattr(controller, "_require_local", lambda: {"runtime": {"instance_id": "g1"}})
    from kirabridge import windows_setup_client as client

    monkeypatch.setattr(client, "client_status", lambda p: {"ready": True})
    response = controller.connection_status()
    assert response["tunnel_ready"] and response["verified"] is False


@pytest.mark.parametrize("simulated", [False, True])
def test_finish_needs_receipt_code_and_simulations_cannot_turn_green(
    controller, monkeypatch, simulated
):
    monkeypatch.setattr(controller, "_require_local", lambda: {"runtime": {"instance_id": "g1"}})
    verification = SimpleNamespace(
        finish_verification=lambda code: code == "valid-code",
        public_proof=lambda: {"simulated": simulated},
    )
    monkeypatch.setattr(controller, "_verification", lambda health: verification)
    assert not controller.finish_verification("wrong-code")["verified"]
    response = controller.finish_verification("valid-code")
    assert response["verified"] is (not simulated)
    assert response["cloud_attested"] is False


def test_gui_close_releases_only_lease_and_keeps_processes(controller):
    calls = []
    controller.lease = SimpleNamespace(close=lambda: calls.append("lease"))
    controller.close()
    controller.close()
    assert calls == ["lease"]


def test_pid_reuse_is_not_the_original_child(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "process_identity",
        lambda pid: {
            "pid": pid,
            "created_100ns": "new",
            "image": "python.exe",
            "running": True,
        },
    )
    assert not runtime.same_process({"pid": 123, "created_100ns": "old", "image": "python.exe"})


def test_unknown_start_receipt_blocks_replay(monkeypatch, tmp_path):
    path = tmp_path / "servers" / ("a" * 32)
    path.mkdir(parents=True)
    (path / "attempt.json").write_text(json.dumps({"port": 8768}))
    monkeypatch.setattr(runtime, "private_directory", lambda p: None)
    monkeypatch.setattr(runtime, "private_json", lambda p: json.loads(p.read_text()))
    with pytest.raises(BridgeError) as error:
        runtime.saved_server(tmp_path)
    assert error.value.code == "setup_start_unknown"


def test_generation_proof_instance_is_preserved_between_begin_and_finish(controller, monkeypatch):
    from kirabridge import windows_setup_verification as verification

    monkeypatch.setattr(
        verification,
        "WindowsSetupVerification",
        lambda root, *, runtime_generation, enabled: SimpleNamespace(
            runtime_generation=runtime_generation
        ),
    )
    first = controller._verification({"runtime": {"instance_id": "first"}})
    assert first is controller._verification({"runtime": {"instance_id": "first"}})
    assert first is not controller._verification({"runtime": {"instance_id": "second"}})
