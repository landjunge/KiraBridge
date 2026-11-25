"""A failed selection says WHY: incomplete catalog, changed shell PID, reused TTY, or gone."""

import pytest

from kirabridge.bridge_core.models import BridgeError


def row(pane, pid, tty):
    return {"pane_id": pane, "expected_pid": pid, "tty": tty, "processes": []}


async def select(bridge, monkeypatch, sessions, truncated=False):
    async def catalog(principal, *, transport=None):
        return {"sessions": sessions, "transport_errors": {}, "truncated": truncated}

    monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    return await bridge.sessions.selected("local", "terminal:7:ttys004", 100)


async def test_exact_match_is_returned(bridge, monkeypatch):
    found = await select(bridge, monkeypatch, [row("terminal:7:ttys004", 100, "/dev/ttys004")])
    assert found["expected_pid"] == 100


@pytest.mark.parametrize(
    "sessions,truncated,code,reason",
    [
        ([], True, "session_catalog_incomplete", "catalog_truncated"),
        ([row("terminal:7:ttys004", 999, "/dev/ttys004")], False, None, "expected_pid_changed"),
        ([row("terminal:9:ttys004", 100, "/dev/ttys004")], False, None, "window_changed"),
        ([row("terminal:9:ttys005", 100, "/dev/ttys005")], False, None, "pane_missing"),
    ],
)
async def test_the_failure_names_its_cause(bridge, monkeypatch, sessions, truncated, code, reason):
    with pytest.raises(BridgeError) as failure:
        await select(bridge, monkeypatch, sessions, truncated)
    assert failure.value.code == (code or "session_selection_changed")
    assert failure.value.provider_error["reason"] == reason
