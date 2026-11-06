"""Unknown paste and optional audit limits must retain their distinct meaning."""

import pytest
from test_visible_dispatch_wait import enqueue
from test_visible_handoff import visible  # noqa: F401

from kirabridge.audit_manager import verify
from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.diagnostics import AuditObserver, export_audit


async def test_empty_grok_cannot_release_unconfirmed_paste(visible):  # noqa: F811
    bridge, transport = visible
    old = enqueue(bridge, sender="codex", key="rc39-old-paste")
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
    before = bridge.visible_handoffs.status("codex", "rc39-unknown")
    with pytest.raises(BridgeError) as error:
        await bridge.visible_handoffs.dispatch_ready("chatgpt", "grok")
    assert error.value.code == "visible_target_busy"
    assert error.value.observation["handoff_id"] == "rc39-unknown"
    assert bridge.visible_handoffs.status("codex", "rc39-unknown") == before
    assert transport["calls"] == []


def test_full_optional_budget_preserves_core_audit_and_export_is_not_reset(bridge, tmp_path):
    bridge.config.diagnostics.max_records = 10
    observer = AuditObserver(bridge.config, "local", bridge.runtime, bridge.store)
    for _ in range(10):
        assert observer("connection", {"phase": "connect.started"})
    assert observer.status()["recording"] == "budget_exhausted"
    export_audit(bridge.store, tmp_path / "preserved.json", limit=10)
    assert not observer("connection", {"phase": "connect.started"})
    bridge.store.audit("rc39.regression.core", "local", None, {"preserved": True})
    assert verify(bridge.store)["valid"]
    assert verify(bridge.store)["records"] == 11
    assert observer.status()["records"] == 10
