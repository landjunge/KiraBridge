import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest

from kirabridge.audit_manager import verify
from kirabridge.bridge_core.models import BridgeError
from kirabridge.operator_actions import ControlActionRepository, ControlActions
from kirabridge.operator_control import OperatorControl
from kirabridge.task_manager.store import Store

VALUE = {"action_id": "one-start", "service": "bridge", "action": "start"}


def test_independent_console_connections_reserve_only_one_dispatch(tmp_path):
    path = tmp_path / "state/bridge.sqlite3"
    initial = Store(path)
    ControlActionRepository(initial)
    initial.close()
    barrier, lock, calls = Barrier(4), Lock(), []

    def console():
        store = Store(path)
        service = ControlActions(ControlActionRepository(store))
        barrier.wait(timeout=10)

        async def dispatch(*args):
            assert not store.db.in_transaction
            with lock:
                calls.append(args)
            await asyncio.sleep(0.05)
            return {"state": "starting"}

        try:
            return asyncio.run(service.execute(VALUE, dispatch))
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=4) as consoles:
        results = list(consoles.map(lambda _: console(), range(4)))
    assert len(calls) == 1
    assert all(result["state"] in {"requested", "starting"} for result in results)
    store = Store(path)
    try:
        row = store.db.execute("SELECT * FROM control_actions").fetchone()
        assert row["state"] == "starting"
        assert store.db.execute("SELECT count(*) FROM control_actions").fetchone()[0] == 1
        assert store.db.execute("SELECT count(*) FROM audit").fetchone()[0] == 2
        assert verify(store)["valid"]
    finally:
        store.close()


async def test_cancelled_operator_wait_preserves_unknown_and_does_not_repeat(bridge):
    service = ControlActions(ControlActionRepository(bridge.store))
    started = asyncio.Event()
    calls = []

    async def dispatch(*args):
        assert not bridge.store.db.in_transaction
        calls.append(args)
        started.set()
        await asyncio.Event().wait()

    running = asyncio.create_task(service.execute(VALUE, dispatch))
    await asyncio.wait_for(started.wait(), 2)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    replay = await service.execute(VALUE, dispatch)
    assert replay["state"] == "unknown" and len(calls) == 1
    assert verify(bridge.store)["valid"]


async def test_conflicting_click_and_recorded_failure_never_dispatch_again(bridge):
    service = ControlActions(ControlActionRepository(bridge.store))
    calls = []

    async def failed(*args):
        calls.append(args)
        assert not bridge.store.db.in_transaction
        raise BridgeError("service_start", "Actual service error")

    first = await service.execute(VALUE, failed)
    assert first["state"] == "failed"
    assert await service.execute(VALUE, failed) == first
    with pytest.raises(BridgeError) as error:
        await service.execute({**VALUE, "action": "restart"}, failed)
    assert error.value.code == "idempotency_conflict" and len(calls) == 1


async def test_runtime_application_uses_ports_without_core_and_records_verified_restart():
    seen = []

    async def activate():
        seen.append("verified")
        return {"activation_id": "verified-activation", "runtime": {"instance_id": "new"}}

    control = OperatorControl(
        config=lambda: None,
        queries=None,
        daemon=None,
        platform=None,
        actions=None,
        maintenance=lambda: None,
        grant_window=None,
        audit=None,
        connectors=None,
    )
    control.operations = SimpleNamespace(activate=activate)
    result = await control.reload_bridge()
    assert seen == ["verified"] and result["state"] == "completed"
    assert result["activation_id"] == "verified-activation"


async def test_missing_agent_restart_never_issues_window_grant_or_starts_replacement():
    config = SimpleNamespace(agents={"grok": object()})

    def forbidden(*args, **kwargs):
        pytest.fail("Missing agent restart must not open or authorize a replacement")

    control = OperatorControl(
        config=lambda: config,
        queries=None,
        daemon=SimpleNamespace(call=forbidden),
        platform=SimpleNamespace(command=forbidden),
        actions=None,
        maintenance=lambda: None,
        grant_window=forbidden,
        audit=None,
        connectors=None,
    )

    async def snapshot(**kwargs):
        return {"services": [{"id": "grok", "active": False}]}

    control.snapshot = snapshot
    with pytest.raises(BridgeError) as error:
        await control.service_action("grok", "restart", "preserve-existing")
    assert error.value.code == "agent_window_missing"


def test_http_presenters_do_not_know_sql_tables_core_or_process_apis():
    import ast
    from pathlib import Path

    root = Path(__file__).parents[1] / "src/kirabridge"
    for name in (
        "control_center.py",
        "approval_console.py",
        "team_console.py",
        "grok_connector/console.py",
    ):
        tree = ast.parse((root / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"db", "bridge", "create_subprocess_exec", "Popen"}, name
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not node.value.lstrip().startswith(("SELECT ", "UPDATE ", "INSERT ")), name
