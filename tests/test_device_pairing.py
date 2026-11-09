import os

import pytest
from test_remote_relay import intent, relay
from test_remote_relay import remote as remote  # noqa: F401

from kirabridge.bridge_core.models import BridgeError
from kirabridge.device_pairing import DevicePairing


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def pairing(tmp_path):
    clock = Clock()
    return DevicePairing(tmp_path / "pairing.json", clock=clock), clock


def test_pairing_issues_key_once_and_stores_only_hash(pairing, tmp_path):
    reg, _ = pairing
    code = reg.begin("home-mac", "ws1")
    key = reg.complete(code, "home-mac")
    assert reg.authorize("home-mac", "ws1", key)["workspace_ref"] == "ws1"
    text = (tmp_path / "pairing.json").read_text()
    assert key not in text and code not in text
    with pytest.raises(BridgeError, match="pairing code"):
        reg.complete(code, "home-mac")  # one-time


def test_revocation_blocks_authorization(pairing):
    reg, _ = pairing
    key = reg.complete(reg.begin("home-mac", "ws1"), "home-mac")
    reg.revoke("home-mac")
    with pytest.raises(BridgeError, match="revoked"):
        reg.authorize("home-mac", "ws1", key)


def test_wrong_device_scope_key_and_unpaired(pairing):
    reg, _ = pairing
    code = reg.begin("home-mac", "ws1")
    with pytest.raises(BridgeError, match="mismatched"):
        reg.complete(code, "other-mac")
    with pytest.raises(BridgeError, match="mismatched"):
        reg.complete(code, "home-mac")  # wrong device burned the code
    key = reg.complete(reg.begin("home-mac", "ws1"), "home-mac")
    with pytest.raises(BridgeError, match="scope"):
        reg.authorize("home-mac", "ws2", key)
    with pytest.raises(BridgeError, match="does not match"):
        reg.authorize("home-mac", "ws1", "wrong")
    with pytest.raises(BridgeError, match="does not match"):
        reg.authorize("home-mac", "ws1", None)
    with pytest.raises(BridgeError, match="not paired"):
        reg.authorize("other-mac", "ws1", "x")


def test_expired_pairing_approval_and_device(pairing):
    reg, clock = pairing
    code = reg.begin("home-mac", "ws1", code_ttl=60, device_ttl=100)
    clock.now += 61
    with pytest.raises(BridgeError, match="expired"):
        reg.complete(code, "home-mac")
    key = reg.complete(reg.begin("home-mac", "ws1", device_ttl=100), "home-mac")
    clock.now += 101
    with pytest.raises(BridgeError, match="expired"):
        reg.authorize("home-mac", "ws1", key)


@pytest.mark.skipif(
    not os.environ.get("KIRABRIDGE_TEST_REMOTE_THREADDESK_SOURCE"),
    reason="pinned ThreadDesk source",
)
async def test_relay_executes_only_for_paired_device_with_key_and_never_after_revoke(
    remote, pairing, tmp_path
):
    reg, _ = pairing
    envelope = await intent(remote)
    b = remote.binding

    def none():
        assert not remote.counter.exists()
        assert remote.bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0

    async def refused(match, **kw):
        async with relay(remote, pairing=reg, **kw) as coordinator:
            with pytest.raises(BridgeError, match=match):
                await coordinator.deliver(envelope)
        none()

    await refused("not paired", device_key="k")
    key = reg.complete(reg.begin(b.device_ref, b.workspace_ref), b.device_ref)
    await refused("does not match")  # no key
    await refused("does not match", device_key="wrong")
    keyfile = tmp_path / "device.key"
    keyfile.write_text(key)
    keyfile.chmod(0o644)
    await refused("0600", device_key=str(keyfile))
    reg.revoke(b.device_ref)
    await refused("revoked", device_key=key)
    key = reg.complete(reg.begin(b.device_ref, b.workspace_ref), b.device_ref)
    keyfile.write_text(key)
    keyfile.chmod(0o600)
    async with relay(remote, pairing=reg, device_key=str(keyfile)) as coordinator:
        task = await coordinator.deliver(envelope)
    assert task["id"] == envelope["request"]["task_id"]
