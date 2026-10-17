import time

import pytest
from conftest import request, submit

from kirabridge.bridge_core.config import Config, PrincipalConfig
from kirabridge.bridge_core.models import BridgeError
from kirabridge.task_manager.store import Store


def test_default_policy_fails_closed(bridge):
    bridge.config.principals["empty"] = PrincipalConfig()
    with pytest.raises(BridgeError, match="Capability"):
        bridge.security.grant("empty", request())


def test_exact_task_approval_and_replay(bridge, config):
    value = request(arguments={"path": config.principals["local"].roots[0]})
    token = bridge.security.grant("local", value)
    changed = value.model_copy(update={"arguments": {"path": "/"}})
    with pytest.raises(BridgeError, match="one-use"):
        bridge.submit("local", changed, token)
    with pytest.raises(BridgeError):
        bridge.submit("other", value, token)
    bridge.submit("local", value, token)
    other = value.model_copy(update={"task_id": "second", "idempotency_key": "second"})
    with pytest.raises(BridgeError):
        bridge.submit("local", other, token)


def test_expired_grant(bridge, config):
    value = request(arguments={"path": config.principals["local"].roots[0]})
    token = bridge.security.grant("local", value)
    bridge.store.db.execute("UPDATE approvals SET expires=?", (time.time() - 1,))
    with pytest.raises(BridgeError):
        bridge.submit("local", value, token)


def test_owner_isolation(bridge, config):
    value = request(arguments={"path": config.principals["local"].roots[0]})
    submit(bridge, value)
    for read in (
        lambda: bridge.task("other", value.task_id),
        lambda: bridge.events("other", value.task_id),
        lambda: bridge.tasks.cancel_queued("other", value.task_id),
    ):
        with pytest.raises(BridgeError, match="not found"):
            read()


def test_remote_requires_tls_and_explicit_policy(monkeypatch):
    monkeypatch.setenv("TEST_TOKEN", "a" * 40)
    config = Config(host="0.0.0.0", principals={"local": PrincipalConfig(token_env="TEST_TOKEN")})
    with pytest.raises(BridgeError, match="Remote"):
        config.validate_network()
    config.allow_remote = True
    with pytest.raises(BridgeError):
        config.validate_network()
    config.tls_cert, config.tls_key = "cert.pem", "key.pem"
    config.validate_network()


def test_http_rejects_missing_short_and_duplicate_tokens(monkeypatch):
    config = Config()
    with pytest.raises(BridgeError):
        config.validate_network()
    config.principals["local"].token_env = "TEST_TOKEN"
    monkeypatch.setenv("TEST_TOKEN", "short")
    with pytest.raises(BridgeError):
        config.validate_network()
    monkeypatch.setenv("TEST_TOKEN", "a" * 40)
    config.principals["other"] = config.principals["local"].model_copy()
    with pytest.raises(BridgeError):
        config.validate_network()


def test_private_state_permissions(tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o755)
    with pytest.raises(BridgeError, match="owner-only"):
        Store(state / "test.sqlite")
    state.chmod(0o700)
    store = Store(state / "test.sqlite")
    store.close()
    assert (state / "test.sqlite").stat().st_mode & 0o077 == 0


def test_database_symlink_rejected(tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    target = tmp_path / "target"
    target.write_text("do not change")
    (state / "test.sqlite").symlink_to(target)
    with pytest.raises(BridgeError, match="symlink"):
        Store(state / "test.sqlite")
    assert target.read_text() == "do not change"


def test_future_schema_rejected(tmp_path):
    state = tmp_path / "state"
    store = Store(state / "test.sqlite")
    store.db.execute("PRAGMA user_version=999")
    store.close()
    with pytest.raises(BridgeError, match="schema"):
        Store(state / "test.sqlite")


def test_unknown_and_unscoped_operations_rejected(bridge):
    with pytest.raises(BridgeError, match="not supported"):
        bridge.submit("local", request("shell.run"), "")
    with pytest.raises(BridgeError, match="schema"):
        bridge.submit("local", request("file.delete", {"path": "/tmp/x", "recursive": True}), "")
