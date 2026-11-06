"""Explicit saved-connection restart; no account, native process or input actions."""

import json
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_windows_setup_ui import complete, fixture

from kirabridge import windows_setup as setup
from kirabridge import windows_setup_client as client
from kirabridge.bridge_core.models import BridgeError
from kirabridge.private_files import write_private

TUNNEL = "tunnel_" + "a" * 32
KEY = "sk-local-only-" + "b" * 48


@pytest.fixture
def saved(monkeypatch, tmp_path):
    controller = setup.WindowsSetup(tmp_path)
    controller.lease = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(controller, "_require_local", lambda: {"ready": True})
    folder = tmp_path / "connection"
    folder.mkdir(mode=0o700)
    write_private(
        folder / "identity.json", json.dumps({"tunnel_id": TUNNEL, "endpoint": controller.endpoint})
    )
    write_private(folder / "runtime.key", KEY)
    write_private(tmp_path / "preview-credentials.json", json.dumps({"local": "t" * 48}))
    effects = []
    monkeypatch.setattr(client, "find_client", lambda root: Path("verified-client.exe"))

    def profile(binary, root, tunnel, key, endpoint):
        effects.append(("profile", tunnel, key, endpoint))
        return root / "connection" / "profile.yaml"

    monkeypatch.setattr(client, "prepare_profile", profile)
    monkeypatch.setattr(client, "start_client", lambda *args: effects.append(("start",)))
    monkeypatch.setattr(
        controller,
        "connection_status",
        lambda: setup.result("tunnel_pending", "Prüfen", "Offen lassen", connection_saved=True),
    )
    return controller, folder, effects


def test_saved_connection_starts_only_after_explicit_blank_connect_without_new_key(saved):
    controller, folder, effects = saved
    before = {path.name: path.read_bytes() for path in folder.iterdir()}
    assert controller._saved_connection() == {
        "tunnel_id": TUNNEL,
        "endpoint": controller.endpoint,
    }
    assert effects == []
    response = controller.connect("", "")
    assert [effect[0] for effect in effects] == ["profile", "start"]
    assert effects[0][1:] == (TUNNEL, folder / "runtime.key", controller.endpoint)
    assert response["connection_saved"] and response["verified"] is False
    assert {path.name: path.read_bytes() for path in folder.iterdir()} == before
    assert KEY not in json.dumps(response)


def test_different_tunnel_preserves_identity_and_key_without_start(saved):
    controller, folder, effects = saved
    before = {path.name: path.read_bytes() for path in folder.iterdir()}
    with pytest.raises(BridgeError) as caught:
        controller.connect("tunnel_" + "c" * 32, "new-key-" * 8)
    assert caught.value.code == "existing_tunnel" and effects == []
    assert {path.name: path.read_bytes() for path in folder.iterdir()} == before


@pytest.mark.parametrize("field", ["tunnel_id", "endpoint", "extra"])
def test_foreign_or_malformed_saved_identity_is_preserved(saved, field):
    controller, folder, effects = saved
    identity = folder / "identity.json"
    value = json.loads(identity.read_text())
    value[field] = "invalid"
    identity.write_text(json.dumps(value))
    before = identity.read_bytes()
    with pytest.raises(BridgeError) as caught:
        controller.connect("", "")
    assert caught.value.code == "existing_tunnel" and effects == []
    assert identity.read_bytes() == before and (folder / "runtime.key").read_text() == KEY


@pytest.mark.parametrize("missing", ["identity.json", "runtime.key"])
def test_incomplete_saved_connection_never_starts_or_recreates_files(saved, missing):
    controller, folder, effects = saved
    (folder / missing).unlink()
    with pytest.raises(BridgeError) as caught:
        controller.connect("", "")
    assert caught.value.code == "setup_start_unknown" and effects == []
    assert not (folder / missing).exists()


def test_no_saved_connection_does_not_create_a_profile(saved):
    controller, folder, effects = saved
    for path in folder.iterdir():
        path.unlink()
    with pytest.raises(BridgeError) as caught:
        controller.connect("", "")
    assert caught.value.code == "setup_connection_missing" and effects == []
    assert list(folder.iterdir()) == []


def test_first_configuration_still_writes_new_identity_and_private_key_once(saved):
    controller, folder, effects = saved
    for path in folder.iterdir():
        path.unlink()
    response = controller.connect(TUNNEL, KEY)
    assert json.loads((folder / "identity.json").read_text()) == {
        "tunnel_id": TUNNEL,
        "endpoint": controller.endpoint,
    }
    assert (folder / "runtime.key").read_text() == KEY
    assert [effect[0] for effect in effects] == ["profile", "start"]
    assert response["connection_saved"] and not response["verified"]


def test_saved_key_owner_guard_refusal_is_preserved_without_start(saved, monkeypatch):
    controller, _, effects = saved

    def refuse(*args):
        raise BridgeError("unsafe_credentials", "Owner guard refused the file")

    monkeypatch.setattr(client, "read_private", refuse)
    with pytest.raises(BridgeError) as caught:
        controller.connect("", "")
    assert caught.value.code == "unsafe_credentials" and effects == []


def test_inspect_and_local_start_report_saved_configuration_without_auto_connect(
    saved, monkeypatch
):
    controller, _, effects = saved
    monkeypatch.setattr(setup, "require_windows", lambda: None)
    monkeypatch.setattr(setup, "require_desktop", lambda: None)
    monkeypatch.setattr(controller, "_owned_health", lambda: {"ready": True})
    for response in (controller.inspect(), controller.start_local()):
        assert response["connection_saved"] and response["client_installed"]
        assert response["local_ready"] and not response["verified"]
        assert KEY not in json.dumps(response) and TUNNEL not in json.dumps(response)
    assert effects == []


def test_presenter_accepts_only_boolean_saved_flag_and_never_starts_during_inspect():
    presenter, controller, _, jobs, _ = fixture()
    controller.replies["inspect"] = {
        "state": "local_ready",
        "local_ready": True,
        "client_installed": True,
        "connection_saved": True,
    }
    presenter.inspect()
    complete(presenter, jobs)
    assert presenter.state.connection_saved and not presenter.state.consent
    assert not presenter.connect_saved()
    assert controller.calls == [("inspect", ())]
    assert not presenter.state.verified
    controller.replies["inspect"]["connection_saved"] = "not-a-boolean"
    presenter.inspect()
    complete(presenter, jobs)
    assert presenter.state.connection_saved is True


@pytest.mark.parametrize("missing", ["consent", "local_ready", "client_ready", "connection_saved"])
def test_presenter_saved_connect_requires_fresh_consent_and_all_readiness(missing):
    presenter, controller, _, jobs, _ = fixture()
    flags = dict(consent=True, local_ready=True, client_ready=True, connection_saved=True)
    flags[missing] = False
    presenter.state = replace(presenter.state, **flags)
    assert not presenter.connect_saved()
    assert not controller.calls and not jobs


def test_saved_connect_is_one_explicit_dispatch_and_unknown_blocks_both_start_buttons():
    presenter, controller, view, jobs, _ = fixture()
    presenter.state = replace(
        presenter.state,
        consent=True,
        local_ready=True,
        client_ready=True,
        connection_saved=True,
    )
    controller.replies["connect"] = BridgeError("setup_client_start_unknown", "private detail")
    assert presenter.connect_saved()
    assert view.key_cleared == 1 and not presenter.connect_saved()
    complete(presenter, jobs)
    assert controller.calls == [("connect", ("", ""))]
    assert not presenter.connect_saved() and not presenter.connect(TUNNEL, KEY)
    assert "connect" in presenter.state.blocked_operations and not presenter.state.verified
    assert KEY not in json.dumps([asdict(state) for state in view.states])
