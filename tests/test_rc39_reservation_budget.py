"""Unknown paste and optional audit limits must retain their distinct meaning."""

import pytest
from test_visible_dispatch_wait import enqueue
from test_visible_handoff import visible  # noqa: F401

from kirabridge.audit_manager import verify
from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.diagnostics import AuditObserver, export_audit


def unconfirmed_paste(bridge, key="rc39-old-paste"):
    old = enqueue(bridge, sender="codex", key=key)
    binding = bridge.config.visible_handoffs.bindings["grok"]
    bridge.store.db.execute(
        "INSERT INTO visible_handoffs VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            "rc39-unknown",
            "codex",
            "grok",
            "hash",
            canonical(binding.model_dump()),
            old["id"],
            "unknown",
            1,
            1,
            canonical({"reason": "visible_paste_unconfirmed"}),
        ),
    )
    bridge.visible_handoffs.transition(
        "rc39-unknown",
        "unknown",
        {
            "reason": "visible_paste_unconfirmed",
            "automatic_retry": False,
        },
    )
    return old


async def test_text_in_the_input_keeps_unconfirmed_paste_locked(visible):  # noqa: F811
    bridge, transport = visible
    old = unconfirmed_paste(bridge)
    transport["text"] = "╭\n│ ❯ half typed\n╰"
    before = bridge.visible_handoffs.status("codex", "rc39-unknown")
    with pytest.raises(BridgeError) as error:
        await bridge.visible_handoffs.dispatch_ready("chatgpt", "grok")
    # A filled field is not a positive ready observation, so the lock stays.
    assert error.value.code == "visible_target_unknown"
    assert bridge.visible_handoffs.status("codex", "rc39-unknown") == before
    assert transport["calls"] == []
    assert bridge.messages.get("codex", old["id"])["acknowledged"] is None


async def test_fresh_empty_input_releases_the_lock_and_never_replays(visible):  # noqa: F811
    bridge, transport = visible
    old = unconfirmed_paste(bridge)
    await bridge.visible_handoffs.dispatch_ready("chatgpt", "grok")
    status = bridge.visible_handoffs.status("codex", "rc39-unknown")
    assert status["state"] == "unknown"
    assert status["evidence"]["reason"] == "unconfirmed_input_lock_released"
    assert status["evidence"]["previous_reason"] == "visible_paste_unconfirmed"
    assert status["evidence"]["input_reservation_released"] is True
    assert status["evidence"]["automatic_retry"] is False
    # The old message stays unacknowledged, was never typed and is not sent again.
    assert transport["calls"] == []
    assert bridge.messages.get("codex", old["id"])["acknowledged"] is None
    rows = bridge.store.db.execute(
        "SELECT count(*) FROM visible_handoffs WHERE message_id=?", (old["id"],)
    ).fetchone()[0]
    assert rows == 1
    # A second observation is idempotent: no further transition, still no input.
    await bridge.visible_handoffs.dispatch_ready("chatgpt", "grok")
    assert bridge.visible_handoffs.status("codex", "rc39-unknown") == status
    assert transport["calls"] == []


def test_full_optional_budget_preserves_core_audit_and_export_is_not_reset(bridge, tmp_path):
    bridge.config.diagnostics.max_records = 10
    observer = AuditObserver(bridge.config, "local", bridge.runtime, bridge.store)
    for _ in range(10):
        assert observer("connection", {"phase": "connect.started"})
    assert observer.status()["recording"] == "budget_exhausted"
    export_audit(bridge.store, tmp_path / "preserved.json", limit=10)
    assert observer("connection", {"phase": "connect.started"}) and observer.archived == 1
    bridge.store.audit("rc39.regression.core", "local", None, {"preserved": True})
    assert verify(bridge.store)["valid"]
    assert verify(bridge.store)["records"] == 11
    assert observer.status()["records"] == 10
