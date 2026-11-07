import errno
import json
import os
from pathlib import Path

import pytest
from conftest import request, submit

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import BridgeError


async def test_move_task_returns_only_after_success_and_is_not_repeated(bridge, config):
    root = Path(config.principals["local"].roots[0])
    source, destination = root / "source", root / "destination"
    source.write_text("original data")
    task = request("file.move", {"path": str(source), "destination": str(destination)})
    submit(bridge, task)
    async with bridge:
        result = await bridge.tasks.wait("local", task.task_id)
        assert result["state"] == "completed"
        assert result["result"] == {"moved": True}
        assert bridge.submit("local", task, "")["id"] == task.task_id
    assert destination.read_text() == "original data"
    assert not source.exists()
    assert list(root.glob(".kirabridge-move-*")) == []


async def test_move_unknown_has_durable_owner_only_recovery_and_no_replay(
    bridge, config, monkeypatch
):
    root = Path(config.principals["local"].roots[0])
    source, destination = root / "source", root / "destination"
    source.write_text("original data")
    real_rename, attempts = os.rename, []

    def lose_capture_reply(*args, **kwargs):
        real_rename(*args, **kwargs)
        attempts.append(True)
        raise OSError(errno.EIO, "isolated error after capture")

    monkeypatch.setattr(os, "rename", lose_capture_reply)
    task = request("file.move", {"path": str(source), "destination": str(destination)})
    submit(bridge, task)
    async with bridge:
        result = await bridge.tasks.wait("local", task.task_id)
        with pytest.raises(BridgeError):
            bridge.task("other", task.task_id)
    assert result["state"] == "unknown"
    assert result["error"]["code"] == "file_move_recovery_required"
    assert result["evidence"]["automatic_retry"] is False
    receipt = result["evidence"]["provider_error"]
    stage = Path(receipt["recovery_dir"])
    assert receipt["retained"] is True
    assert receipt["automatic_recovery"] is False
    assert receipt["ref"] == stage.name.removeprefix(".kirabridge-move-")
    assert (stage / "captured").read_text() == "original data"
    assert (stage / "pin").read_text() == "original data"
    journal = json.loads((stage / "journal.json").read_text())
    assert journal["source"] == str(source)
    assert journal["destination"] == str(destination)
    assert journal["ref"] == receipt["ref"]
    assert not source.exists() and not destination.exists()
    reopened = Bridge(config)
    try:
        assert reopened.task("local", task.task_id)["evidence"]["provider_error"] == receipt
        async with reopened:
            assert reopened.submit("local", task, "")["state"] == "unknown"
        assert attempts == [True]
        assert (stage / "captured").read_text() == "original data"
    finally:
        reopened.store.close()
