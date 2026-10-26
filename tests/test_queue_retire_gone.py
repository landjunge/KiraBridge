"""Retire only a proved absent original target, never a merely changed assignment."""

import time
from types import SimpleNamespace

import pytest
from test_queue_management import command, queues  # noqa: F401
from test_queue_withdrawal import history, unknown

from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.queue_management.models import QueueControl

# Imported fixture is resolved by pytest.
# ruff: noqa: F811


@pytest.fixture
def gone(queues, bridge, config):
    identifier = unknown(bridge, "handoffs")
    config.principals["local"].capabilities.append("session.inspect")
    calls = []

    async def processes():
        calls.append("ps")
        return frozenset({1, 999})

    async def windows():
        calls.append("windows")
        return {"running": True, "windows": [{"window_id": 2, "ttys": ["/dev/ttys002"]}]}

    async def old_target_missing(*args, **kwargs):
        calls.append("old-target")
        raise BridgeError("visible_target_changed", "Old original target no longer exists")

    bridge.sessions.terminal_app = SimpleNamespace(
        available=True, process_ids=processes, window_inventory=windows
    )
    bridge.visible_handoffs.check_target = old_target_missing
    entry = queues.get("local", "handoffs", identifier)
    value = QueueControl(
        queue_id="handoffs",
        item_id=identifier,
        action="retire",
        revision=entry["revision"],
        reason="Explicit isolated retirement; execution remains unknown",
        acknowledge_execution_unknown=True,
    )
    return queues, bridge, identifier, value, calls


async def test_retire_gone_original_preserves_unknown_and_releases_only_original_reservation(gone):
    queues, bridge, identifier, value, calls = gone
    original = tuple(bridge.store.db.execute("SELECT * FROM visible_handoffs").fetchone())
    result = await queues.control("local", value)
    assert result["fully_removed"] and not result["execution_stop_claimed"]
    assert calls == ["ps", "windows", "ps"]
    assert tuple(bridge.store.db.execute("SELECT * FROM visible_handoffs").fetchone()) == original
    assert queues.get("local", "handoffs", identifier)["state"] == "unknown"
    assert {
        (r["queue_id"], r["item_id"]) for r in bridge.store.db.execute("SELECT * FROM queue_holds")
    } == {("handoffs", identifier), ("messages", "one")}
    # No input is required after the exact original reservation has been retired.
    binding = bridge.config.visible_handoffs.bindings["other"]
    await bridge.visible_handoffs.reconcile_target_reservations("local", "other", binding)
    import json

    audit = json.loads(
        bridge.store.db.execute("SELECT metadata FROM audit WHERE kind='queue.retire'").fetchone()[
            0
        ]
    )
    assert audit["retirement_basis"] == "original_target_gone"
    assert "fresh_target_idle" not in audit
    assert audit["absence_evidence"]["observed_at"] <= time.time()


@pytest.mark.parametrize("present", ["window", "shell-pid", "agent-pid-reused", "agent-reappeared"])
async def test_gone_retire_refuses_any_existing_or_reused_original_identity(gone, present):
    queues, bridge, _, value, calls = gone
    before = history(bridge)
    if present == "window":

        async def windows():
            return {"running": True, "windows": [{"window_id": 1, "ttys": ["/dev/ttys999"]}]}

        bridge.sessions.terminal_app.window_inventory = windows
    else:
        count = 0

        async def processes():
            nonlocal count
            count += 1
            existing = 123 if present == "shell-pid" else 124
            if present == "agent-reappeared" and count == 1:
                return frozenset({1, 999})
            return frozenset({1, 999, existing})

        bridge.sessions.terminal_app.process_ids = processes
    with pytest.raises(BridgeError) as error:
        await queues.control("local", value)
    assert error.value.code == "visible_absence_unproven"
    assert (
        history(bridge) == before
        and not bridge.store.db.execute("SELECT 1 FROM queue_holds").fetchone()
    )
    assert "old-target" not in calls


@pytest.mark.parametrize(
    "failure",
    [
        "catalog-error",
        "invalid-catalog",
        "empty-ps",
        "ps-error",
        "ambiguous-binding",
        "coerced-pid",
    ],
)
async def test_gone_retire_refuses_unproved_or_ambiguous_observations(gone, failure):
    queues, bridge, identifier, value, _ = gone

    async def windows():
        if failure == "catalog-error":
            raise BridgeError("session_automation_denied", "No window observation")
        return {"windows": []}  # No positive running/completion proof.

    async def processes():
        if failure == "ps-error":
            raise BridgeError("visible_absence_unproven", "No process observation")
        return frozenset()

    if failure in {"catalog-error", "invalid-catalog"}:
        bridge.sessions.terminal_app.window_inventory = windows
    elif failure in {"empty-ps", "ps-error"}:
        bridge.sessions.terminal_app.process_ids = processes
    else:
        import json

        binding = json.loads(
            bridge.store.db.execute("SELECT binding FROM visible_handoffs").fetchone()[0]
        )
        binding["agent_pid"] = binding["expected_pid"] if failure == "ambiguous-binding" else "124"
        bridge.store.db.execute("UPDATE visible_handoffs SET binding=?", (canonical(binding),))
        value = value.model_copy(
            update={"revision": queues.get("local", "handoffs", identifier)["revision"]}
        )
    before = history(bridge)
    with pytest.raises(BridgeError):
        await queues.control("local", value)
    assert (
        history(bridge) == before
        and not bridge.store.db.execute("SELECT 1 FROM queue_holds").fetchone()
    )


@pytest.mark.parametrize("missing", ["session.inspect", "task.cancel", "approval"])
async def test_gone_retire_requires_observation_and_control_rights_before_probing(gone, missing):
    queues, bridge, _, value, calls = gone
    policy = bridge.config.principals["local"]
    if missing == "approval":
        policy.permission_level, policy.approval_mode = "ask", "manual"
    else:
        policy.capabilities.remove(missing)
    with pytest.raises(BridgeError) as error:
        await queues.control("local", value)
    assert error.value.code in {"forbidden", "approval_required"}
    assert calls == [] and not bridge.store.db.execute("SELECT 1 FROM queue_holds").fetchone()


async def test_gone_retire_rechecks_persisted_original_revision_after_probe(gone):
    queues, bridge, _, value, _ = gone
    original = bridge.sessions.terminal_app.window_inventory

    async def changed():
        bridge.store.db.execute(
            "UPDATE visible_handoffs SET evidence=?", (canonical({"concurrent_receipt": True}),)
        )
        return await original()

    bridge.sessions.terminal_app.window_inventory = changed
    with pytest.raises(BridgeError) as error:
        await queues.control("local", value)
    assert error.value.code == "queue_changed"
    assert not bridge.store.db.execute("SELECT 1 FROM queue_holds").fetchone()


async def test_old_retire_without_unknown_ack_retains_assigned_ready_contract(gone):
    queues, bridge, _, value, calls = gone
    with pytest.raises(BridgeError) as error:
        await queues.control(
            "local", value.model_copy(update={"acknowledge_execution_unknown": False})
        )
    assert error.value.code == "visible_target_changed"
    assert (
        calls == ["old-target"]
        and not bridge.store.db.execute("SELECT 1 FROM queue_holds").fetchone()
    )


async def test_gone_retire_rechecks_observation_permission_after_await(gone):
    queues, bridge, _, value, _ = gone
    original = bridge.sessions.terminal_app.window_inventory

    async def revoked():
        bridge.config.principals["local"].capabilities.remove("session.inspect")
        return await original()

    bridge.sessions.terminal_app.window_inventory = revoked
    with pytest.raises(BridgeError) as error:
        await queues.control("local", value)
    assert error.value.code == "forbidden"
    assert not bridge.store.db.execute("SELECT 1 FROM queue_holds").fetchone()


@pytest.mark.parametrize(
    "failure", [None, "status", "empty", "stderr", "malformed", "timeout", "permission"]
)
async def test_native_pid_evidence_never_treats_failed_ps_as_absence(monkeypatch, failure):
    import asyncio

    from kirabridge.platform_adapters.terminal_app import TerminalAppTransport

    calls = []

    class Child:
        returncode = None if failure == "timeout" else (1 if failure == "status" else 0)

        async def communicate(self):
            if failure == "timeout":
                raise TimeoutError
            return (
                b""
                if failure == "empty"
                else b"1\n123\n"
                if failure != "malformed"
                else b"not-a-pid\n",
                b"not permitted" if failure == "stderr" else b"",
            )

        def kill(self):
            calls.append("kill-own-ps")

        async def wait(self):
            self.returncode = -9

    async def spawn(*args, **kwargs):
        calls.append(args)
        if failure == "permission":
            raise PermissionError
        return Child()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(TerminalAppTransport, "available", property(lambda self: True))
    transport = TerminalAppTransport(asyncio.Lock())
    if failure is None:
        assert await transport.process_ids() == frozenset({1, 123})
    else:
        with pytest.raises(BridgeError) as error:
            await transport.process_ids()
        assert error.value.code == "visible_absence_unproven"
    assert calls[0] == ("/bin/ps", "-axo", "pid=")
    if failure == "timeout":
        assert calls[-1] == "kill-own-ps"


async def test_gone_retire_rejects_a_catalog_with_transport_error_even_if_window_list_is_empty(
    gone,
):
    queues, bridge, _, value, _ = gone

    async def failed_catalog():
        return {"running": True, "windows": [], "transport_errors": {"terminal_app": "denied"}}

    bridge.sessions.terminal_app.window_inventory = failed_catalog
    with pytest.raises(BridgeError) as error:
        await queues.control("local", value)
    assert error.value.code == "visible_absence_unproven"
    assert not bridge.store.db.execute("SELECT 1 FROM queue_holds").fetchone()
