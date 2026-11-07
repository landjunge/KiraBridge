"""Prepared non-input tasks consume exact operator grants on the same submit path."""

import json
import time
from pathlib import Path

import pytest
from conftest import request
from test_mcp import http_bridge  # noqa: F401

from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool, Peer


def pending_write(bridge, name="approved-file"):
    target = Path(bridge.config.principals["local"].roots[0]) / name
    value = request("file.write", {"path": str(target), "text": "approved"}, task_id=name)
    assert bridge.prepare("local", value)["state"] == "created"
    assert not target.exists()
    return value, target


async def test_prepared_write_consumes_operator_token_through_real_http_submit(http_bridge):  # noqa: F811
    bridge, endpoint = http_bridge
    value, target = pending_write(bridge)
    token = bridge.security.grant("local", value)
    async with MCPClientPool() as pool:
        await pool.connect(Peer("caller", url=endpoint, token="local-test-" + "a" * 40))
        arguments = {"request": value.model_dump(), "approval": token}
        submitted = (await pool.call("caller", "task_submit", arguments)).structuredContent
        assert submitted.get("state") != "created", submitted
        final = await bridge.tasks.wait("local", value.task_id, timeout=5)
        assert final["state"] == "completed", final
        replay = (await pool.call("caller", "task_submit", arguments)).structuredContent
        assert replay["id"] == value.task_id and replay["state"] == "completed"
    assert target.read_text() == "approved"
    assert bridge.store.db.execute("SELECT used FROM approvals").fetchone()[0] is not None
    assert (
        bridge.store.db.execute(
            "SELECT count(*) FROM events WHERE task_id=? AND state='queued'", (value.task_id,)
        ).fetchone()[0]
        == 1
    )
    assert token not in json.dumps(
        [dict(row) for row in bridge.store.db.execute("SELECT * FROM audit")]
    )


@pytest.mark.parametrize("failure", ["invalid", "expired", "arguments", "principal", "task-id"])
def test_pending_task_cannot_be_released_by_a_wrong_or_changed_grant(bridge, failure):
    value, target = pending_write(bridge)
    token = bridge.security.grant("local", value)
    approved_args = bridge.store.get(value.task_id, "local")["args"]
    principal = "local"
    if failure == "invalid":
        token = "invalid-token"
    elif failure == "expired":
        bridge.store.db.execute("UPDATE approvals SET expires=?", (time.time() - 1,))
    elif failure == "arguments":
        value = value.model_copy(update={"arguments": {**value.arguments, "text": "changed"}})
    elif failure == "principal":
        principal = "other"
    else:
        value = value.model_copy(update={"task_id": "other-task"})
    with pytest.raises(BridgeError):
        bridge.submit(principal, value, token)
    original = bridge.store.get("approved-file", "local")
    assert original["state"] == "created" and original["args"] == approved_args
    assert bridge.store.db.execute("SELECT used FROM approvals").fetchone()[0] is None
    assert not target.exists()


def test_consumed_token_cannot_release_a_different_prepared_request(bridge):
    first, _ = pending_write(bridge, "first")
    token = bridge.security.grant("local", first)
    assert bridge.submit("local", first, token)["state"] == "queued"
    second, target = pending_write(bridge, "second")
    with pytest.raises(BridgeError, match="one-use"):
        bridge.submit("local", second, token)
    assert bridge.store.get(second.task_id, "local")["state"] == "created"
    assert not target.exists()


def test_failed_release_transaction_does_not_consume_token(bridge, monkeypatch):
    value, target = pending_write(bridge)
    token = bridge.security.grant("local", value)
    approve = bridge.tasks._approve_in_transaction

    def unavailable(task_id, source):
        raise BridgeError("evidence_unavailable", "Cannot record approval")

    monkeypatch.setattr(bridge.tasks, "_approve_in_transaction", unavailable)
    with pytest.raises(BridgeError, match="record approval"):
        bridge.submit("local", value, token)
    assert bridge.store.get(value.task_id, "local")["state"] == "created"
    assert bridge.store.db.execute("SELECT used FROM approvals").fetchone()[0] is None
    assert not target.exists()
    monkeypatch.setattr(bridge.tasks, "_approve_in_transaction", approve)
    assert bridge.submit("local", value, token)["state"] == "queued"


def test_created_pending_task_is_not_approved_by_tokenless_duplicate(bridge):
    value, target = pending_write(bridge)
    assert bridge.submit("local", value)["state"] == "created"
    assert not target.exists()
