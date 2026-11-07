import asyncio
import copy
import hashlib
import json
import os
import sqlite3
import sys
from types import SimpleNamespace

import pytest
from conftest import request

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import load_config
from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.operations_service import OperationsService, installed_source_sha, replace_section
from kirabridge.operator_application import operator_application

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX ownership and launchd supervisor")


@pytest.fixture
def operations(config, tmp_path):
    path = tmp_path / "active.toml"
    text = "data_dir=" + json.dumps(config.data_dir) + "\n"
    for name, policy in config.principals.items():
        policy.permission_level = "full"
        policy.approval_mode = "automatic"
        text = replace_section(text, "principals." + name, policy.model_dump())
    path.write_text(text)
    bridge = Bridge(load_config(str(path)))
    state = SimpleNamespace(
        path=path,
        bridge=bridge,
        commands=[],
        health=bridge.health("local"),
        fail=False,
        restarted=asyncio.Event(),
        continue_restart=asyncio.Event(),
        pause=False,
        reads=0,
    )

    async def rpc(tool, **kwargs):
        assert not bridge.store.db.in_transaction
        assert tool == "bridge_health"
        state.reads += 1
        await asyncio.sleep(0)
        return copy.deepcopy(state.health)

    async def command(*argv):
        assert not bridge.store.db.in_transaction
        # A separate connection can acquire a writer while supervision awaits.
        second = sqlite3.connect(bridge.config.state_path / "bridge.sqlite3", timeout=0.01)
        second.execute("BEGIN IMMEDIATE")
        second.rollback()
        second.close()
        assert bridge.store.maintenance_state() is not None
        state.commands.append(argv)
        state.restarted.set()
        if state.pause:
            await state.continue_restart.wait()
        if state.fail:
            return 1, "", "failed-supervisor"
        loaded = load_config(str(path))
        state.health = {
            **bridge.health("local"),
            "dispatcher_active": True,
            "runtime": {
                **bridge.runtime,
                "instance_id": "restarted-" + str(len(state.commands)),
                "config_sha256": loaded._source_sha256,
                "effective_config_sha256": loaded._effective_sha256,
                "source_tree_sha256": installed_source_sha(),
            },
        }
        return 0, "", ""

    service = OperationsService(
        bridge.store,
        lambda: load_config(str(path)),
        rpc,
        command,
        bridge.runtime,
        work_queries=operator_application(bridge).control.queries.maintenance_counts,
    )
    service.drain_timeout = 0.25
    state.service = service
    yield state
    bridge.store.close()


async def test_restart_releases_sql_writer_and_blocks_concurrent_submission(operations):
    rig = operations
    rig.pause = True
    call = asyncio.create_task(rig.service.activate())
    await asyncio.wait_for(rig.restarted.wait(), 2)
    assert rig.bridge.store.maintenance_state()["state"] == "verifying"
    for number in range(3):
        with pytest.raises(BridgeError) as error:
            rig.bridge.prepare(
                "local",
                request(
                    "file.list",
                    {"path": rig.bridge.config.principals["local"].roots[0]},
                    task_id=f"during-{number}",
                ),
            )
        assert error.value.code == "service_maintenance"
    assert not rig.bridge.store.db.execute("SELECT 1 FROM tasks").fetchone()
    rig.continue_restart.set()
    result = await call
    assert result["operations"]["accepting_new_work"]
    assert rig.bridge.store.maintenance_state() is None
    assert len(rig.commands) == 1 and rig.commands[0][-1].endswith("com.kirabridge.bridge")
    assert (
        rig.bridge.prepare(
            "local", request("file.list", {"path": rig.bridge.config.principals["local"].roots[0]})
        )["state"]
        == "queued"
    )


async def test_drain_finishes_running_task_and_preserves_completion(operations):
    rig = operations
    started, finish = asyncio.Event(), asyncio.Event()

    async def execute(task, running, progress):
        await running({"started": True})
        started.set()
        await finish.wait()
        return {"success": True, "text": "completed existing work"}

    rig.bridge.tasks.executor = execute
    task = request("file.list", {"path": rig.bridge.config.principals["local"].roots[0]})
    rig.bridge.prepare("local", task)
    await rig.bridge.tasks.start()
    try:
        await asyncio.wait_for(started.wait(), 2)
        activation = asyncio.create_task(rig.service.activate())
        async with asyncio.timeout(2):
            while not rig.bridge.store.maintenance_state():
                await asyncio.sleep(0.01)
        assert not rig.commands
        finish.set()
        await activation
        assert rig.bridge.store.get(task.task_id, "local")["state"] == "completed"
        assert rig.bridge.store.db.execute("SELECT 1 FROM completion_notices").fetchone()
    finally:
        await rig.bridge.tasks.stop()


async def test_preexisting_queue_may_drain_but_no_new_task_can_steal_run_id(operations):
    rig = operations
    task = request("file.list", {"path": rig.bridge.config.principals["local"].roots[0]})
    original = rig.bridge.prepare("local", task)
    with rig.bridge.store.transaction():
        now = __import__("time").time()
        rig.bridge.store.db.execute(
            "INSERT INTO activation_runs VALUES('held','draining',?,?,?,NULL)",
            (now, now, canonical({})),
        )
    assert rig.bridge.prepare("local", task)["id"] == original["id"]
    claimed = rig.bridge.store.claim("existing-worker", 30)
    assert claimed["id"] == task.task_id
    with pytest.raises(BridgeError) as error:
        rig.bridge.prepare(
            "other",
            request(
                "file.list",
                {"path": rig.bridge.config.principals["other"].roots[0]},
                task_id="new-work",
            ),
        )
    assert error.value.code == "service_maintenance"
    rig.service.update("held", "verifying")
    assert rig.bridge.store.claim("paused-worker", 30) is None


async def test_busy_timeout_leaves_original_task_and_config_untouched(operations):
    rig = operations
    before = rig.path.read_bytes()
    task = request("file.list", {"path": rig.bridge.config.principals["local"].roots[0]})
    rig.bridge.prepare("local", task)
    rig.bridge.store.claim("busy", 30)
    rig.service.drain_timeout = 0
    with pytest.raises(BridgeError) as error:
        await rig.service.configure(level="ask")
    assert error.value.code == "service_busy"
    assert rig.path.read_bytes() == before and not rig.commands
    assert rig.bridge.store.get(task.task_id, "local")["state"] == "accepted"
    assert rig.bridge.store.maintenance_state() is None


async def test_failed_restart_restores_matching_config_and_requires_verified_recovery(operations):
    rig = operations
    before = rig.path.read_bytes()
    rig.fail = True
    with pytest.raises(BridgeError) as error:
        await rig.service.configure(level="ask")
    assert error.value.code == "service_restart"
    assert rig.path.read_bytes() == before
    assert rig.bridge.store.maintenance_state()["state"] == "failed_blocked"
    with pytest.raises(BridgeError):
        rig.bridge.prepare("local", request("file.list", {"path": str(rig.path.parent)}))
    rig.fail = False
    result = await rig.service.recover()
    assert result["runtime"]["config_sha256"] == hashlib.sha256(before).hexdigest()
    assert rig.bridge.store.maintenance_state() is None
    assert len(rig.commands) == 2


async def test_stale_console_and_invalid_candidate_never_start_activation(operations):
    rig = operations
    original = rig.service.source_sha
    rig.service.source_sha = "outdated-console"
    with pytest.raises(BridgeError) as error:
        await rig.service.activate()
    assert error.value.code == "stale_control_process"
    rig.service.source_sha = original
    with pytest.raises(BridgeError) as error:
        await rig.service.activate(text="not valid TOML!")
    assert error.value.code == "invalid_config"
    assert not rig.commands and rig.bridge.store.maintenance_state() is None


async def test_schema_change_blocks_rollback_without_restoring_database(operations):
    rig = operations
    rig.fail = True
    with pytest.raises(BridgeError):
        await rig.service.configure(level="ask")
    rig.bridge.store.db.execute("PRAGMA user_version=3")
    with pytest.raises(BridgeError) as error:
        await rig.service.recover()
    assert error.value.code == "activation_schema_plan_required"
    assert rig.bridge.store.db.execute("PRAGMA user_version").fetchone()[0] == 3
    assert rig.bridge.store.maintenance_state()["state"] == "failed_blocked"
    assert len(rig.commands) == 1


async def test_concurrent_external_config_change_is_preserved(operations):
    rig = operations
    real_rpc = rig.service.rpc

    async def changed(tool, **kwargs):
        result = await real_rpc(tool, **kwargs)
        rig.path.write_text(rig.path.read_text() + "\n# concurrent operator edit\n")
        return result

    rig.service.rpc = changed
    with pytest.raises(BridgeError) as error:
        await rig.service.configure(level="ask")
    assert error.value.code == "config_changed"
    assert "concurrent operator edit" in rig.path.read_text()
    assert not rig.commands
    assert rig.bridge.store.maintenance_state() is None


async def test_persistent_barrier_survives_reopened_store_and_dead_controller(operations):
    from kirabridge.task_manager.store import Store

    rig = operations
    rig.fail = True
    with pytest.raises(BridgeError):
        await rig.service.configure(level="ask")
    child = await asyncio.create_subprocess_exec(sys.executable, "-c", "pass")
    await asyncio.wait_for(child.wait(), 5)
    state = rig.bridge.store.maintenance_state()
    row = rig.bridge.store.db.execute(
        "SELECT plan FROM activation_runs WHERE id=?", (state["id"],)
    ).fetchone()
    plan = json.loads(row[0])
    plan["owner_pid"] = child.pid
    rig.bridge.store.db.execute(
        "UPDATE activation_runs SET state='draining',plan=? WHERE id=?",
        (canonical(plan), state["id"]),
    )
    other = Store(rig.bridge.config.state_path / "bridge.sqlite3")
    try:
        with pytest.raises(BridgeError) as error:
            other.assert_accepting()
        assert error.value.code == "service_maintenance"
        service = OperationsService(
            other,
            rig.service.config,
            rig.service.rpc,
            rig.service.command,
            rig.bridge.runtime,
            work_queries=rig.service.work_queries,
        )
        rig.fail = False
        await service.recover()
        assert other.maintenance_state() is None
        assert rig.bridge.store.maintenance_state() is None
    finally:
        other.close()


async def test_live_controller_is_not_replaced_by_doctor(operations):
    rig = operations
    rig.pause = True
    activation = asyncio.create_task(rig.service.activate())
    await asyncio.wait_for(rig.restarted.wait(), 2)
    try:
        with pytest.raises(BridgeError) as error:
            await rig.service.recover()
        assert error.value.code == "activation_in_progress"
        assert len(rig.commands) == 1
    finally:
        rig.continue_restart.set()
        await activation


async def test_second_controller_cannot_activate_over_existing_barrier(operations):
    from kirabridge.task_manager.store import Store

    rig = operations
    rig.pause = True
    activation = asyncio.create_task(rig.service.activate())
    await asyncio.wait_for(rig.restarted.wait(), 2)
    other = Store(rig.bridge.config.state_path / "bridge.sqlite3")
    try:
        service = OperationsService(
            other,
            rig.service.config,
            rig.service.rpc,
            rig.service.command,
            rig.bridge.runtime,
            work_queries=rig.service.work_queries,
        )
        with pytest.raises(BridgeError) as error:
            await service.configure(level="ask")
        assert error.value.code == "service_maintenance"
        assert len(rig.commands) == 1
    finally:
        other.close()
        rig.continue_restart.set()
        await activation


def test_owned_stop_can_drain_but_cannot_race_activation(operations):
    rig = operations
    target = request("file.list", {"path": str(rig.path.parent)}, task_id="owned-target")
    rig.bridge.prepare("local", target)
    rig.bridge.store.claim("original-worker", 30)
    now = __import__("time").time()
    rig.bridge.store.db.execute(
        "INSERT INTO activation_runs VALUES('held','draining',?,?,?,NULL)", (now, now, "{}")
    )
    stop = request("process.terminate", {"task_id": target.task_id}, task_id="stop-owned-target")
    rig.bridge.prepare("local", stop)
    assert rig.bridge.store.claim("control-worker", 30, control=True)["id"] == stop.task_id
    rig.service.update("held", "verifying")
    with pytest.raises(BridgeError) as error:
        rig.bridge.prepare(
            "local",
            stop.model_copy(
                update={"task_id": "stop-after-freeze", "idempotency_key": "stop-after-freeze"}
            ),
        )
    assert error.value.code == "service_maintenance"


@pytest.mark.parametrize("field", ["source_tree_sha256", "config_sha256", "instance_id", "version"])
async def test_supervisor_success_is_not_verified_activation(operations, field):
    rig = operations
    command = rig.service.command

    async def wrong_runtime(*argv):
        result = await command(*argv)
        if len(rig.commands) == 1:
            rig.health["runtime"][field] = (
                rig.bridge.runtime[field] if field == "instance_id" else "wrong"
            )
        return result

    rig.service.command = wrong_runtime
    before = rig.path.read_bytes()
    with pytest.raises(BridgeError) as error:
        await rig.service.configure(level="ask")
    assert error.value.code == "activation_unconfirmed"
    assert rig.path.read_bytes() == before
    assert rig.bridge.store.maintenance_state()["state"] == "failed_blocked"
    result = await rig.service.recover()
    assert result["operations"]["accepting_new_work"]
    assert len(rig.commands) == 2


def test_process_and_network_waits_never_nest_in_write_transactions():
    import ast
    from pathlib import Path

    root = Path(__file__).parents[1] / "src/kirabridge"
    for name in [
        "operations_service.py",
        "control_center.py",
        "operator_actions.py",
        "operator_control.py",
    ]:
        tree = ast.parse((root / name).read_text())
        for block in ast.walk(tree):
            if not isinstance(block, ast.With) or not any(
                isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Attribute)
                and item.context_expr.func.attr == "transaction"
                for item in block.items
            ):
                continue
            assert not any(isinstance(node, ast.Await) for node in ast.walk(block)), (
                name,
                block.lineno,
            )
            assert not any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"command", "rpc", "run", "Popen", "create_subprocess_exec"}
                for node in ast.walk(block)
            ), (name, block.lineno)


async def test_restart_transport_requires_actual_owned_idle_reservation(operations):
    rig = operations
    with pytest.raises(BridgeError) as error:
        await rig.service.restart("missing")
    assert error.value.code == "activation_ownership_required"
    assert not rig.commands


async def test_configuration_snapshot_stays_private_and_out_of_audit(operations):
    rig = operations
    marker = "CONFIG_COMMENT_MUST_NOT_ENTER_AUDIT"
    rig.path.write_text(rig.path.read_text() + "\n# " + marker + "\n")
    loaded = load_config(str(rig.path))
    rig.health["runtime"]["config_sha256"] = loaded._source_sha256
    rig.health["runtime"]["effective_config_sha256"] = loaded._effective_sha256
    await rig.service.activate()
    snapshot = (
        rig.bridge.config.state_path / "activation-configs" / (loaded._source_sha256 + ".toml")
    )
    assert marker in snapshot.read_text()
    assert snapshot.stat().st_mode & 0o077 == 0
    assert snapshot.parent.stat().st_mode & 0o077 == 0
    assert marker not in str(
        [tuple(row) for row in rig.bridge.store.db.execute("SELECT metadata FROM audit")]
    )


async def test_non_posix_owner_probe_never_sends_a_process_signal(operations, monkeypatch):
    import kirabridge.operations_service as module

    rig = operations
    rig.fail = True
    with pytest.raises(BridgeError):
        await rig.service.activate()
    state = rig.bridge.store.maintenance_state()
    rig.service.update(state["id"], "verifying")

    def never_signal(*args):
        pytest.fail("A non-POSIX process must never receive kill(pid,0)")

    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt", kill=never_signal))
    with pytest.raises(BridgeError) as error:
        await rig.service.recover()
    assert error.value.code == "activation_in_progress"
    assert len(rig.commands) == 1


async def test_activation_waits_for_team_result_processing_without_holding_writer(operations):
    from test_activation_queries import processing_result_fixture

    rig = operations
    processing_result_fixture(rig.bridge.store)

    async def finish_result():
        async with asyncio.timeout(2):
            while not rig.bridge.store.maintenance_state():
                await asyncio.sleep(0.001)
        assert not rig.commands
        # The drain awaits outside a transaction; the domain can complete.
        with rig.bridge.store.transaction():
            rig.bridge.store.db.execute(
                "UPDATE team_work SET state='completed',result='Actual team result' WHERE id='work'"
            )

    result, _ = await asyncio.gather(rig.service.activate(), finish_result())
    assert result["dispatcher_active"] and len(rig.commands) == 1
    assert rig.bridge.store.maintenance_state() is None
    assert (
        rig.bridge.store.db.execute("SELECT result FROM team_work WHERE id='work'").fetchone()[0]
        == "Actual team result"
    )


async def test_unfinished_team_result_blocks_restart_and_keeps_config(operations):
    from test_activation_queries import processing_result_fixture

    rig = operations
    processing_result_fixture(rig.bridge.store)
    before = rig.path.read_bytes()
    rig.service.drain_timeout = 0
    with pytest.raises(BridgeError) as error:
        await rig.service.activate()
    assert error.value.code == "service_busy" and not rig.commands
    assert rig.path.read_bytes() == before
    assert rig.bridge.store.maintenance_state() is None


def external_wait(rig, state="confirmed"):
    from test_activation_queries import authenticated_delivery

    message_id, receipt = authenticated_delivery(rig.bridge)
    rig.bridge.messages.ack("other", message_id, receipt)
    rig.bridge.store.db.execute(
        "INSERT INTO visible_handoffs VALUES('external-wait','local','other','hash','{}',"
        "?,?,1,1,'{}')",
        (message_id, state),
    )
    return message_id


def principal_only_text(rig):
    import tomllib

    raw = tomllib.loads(rig.path.read_text())
    policy = raw["principals"]["local"]
    policy["roots"] = ["/"]
    return replace_section(rig.path.read_text(), "principals.local", policy)


async def test_local_principal_grant_preserves_external_wait_and_default_remains_strict(operations):
    rig = operations
    external_wait(rig)
    before_handoff = [
        tuple(row) for row in rig.bridge.store.db.execute("SELECT * FROM visible_handoffs")
    ]
    before_events = [
        tuple(row) for row in rig.bridge.store.db.execute("SELECT * FROM visible_handoff_events")
    ]
    rig.service.drain_timeout = 0
    with pytest.raises(BridgeError, match="läuft oder wartet"):
        await rig.service.activate(text=principal_only_text(rig))
    assert not rig.commands
    result = await rig.service.activate(text=principal_only_text(rig), principal_grant="local")
    assert result["operations"]["accepting_new_work"] and len(rig.commands) == 1
    assert [
        tuple(row) for row in rig.bridge.store.db.execute("SELECT * FROM visible_handoffs")
    ] == before_handoff
    assert [
        tuple(row) for row in rig.bridge.store.db.execute("SELECT * FROM visible_handoff_events")
    ] == before_events
    plan = json.loads(
        rig.bridge.store.db.execute(
            "SELECT plan FROM activation_runs WHERE state='completed'"
        ).fetchone()[0]
    )
    assert plan["principal_grant"] == "local" and plan["preserved_external_waits"] == 1
    assert (
        rig.bridge.store.db.execute(
            "SELECT count(*) FROM audit WHERE kind='activation.external_waits_preserved'"
        ).fetchone()[0]
        == 1
    )


@pytest.mark.parametrize(
    "changed", ["other-principal", "credential", "source", "agent", "receiver"]
)
async def test_principal_grant_refuses_non_acl_changes_and_source_change(operations, changed):
    import tomllib

    rig = operations
    raw = tomllib.loads(principal_only_text(rig))
    if changed == "other-principal":
        raw["principals"]["other"]["roots"] = ["/"]
    elif changed == "credential":
        raw["principals"]["local"]["token_env"] = "OTHER_SECRET"
    elif changed == "agent":
        raw["agents"] = {"new": {"kind": "codex"}}
    elif changed == "receiver":
        raw["messaging"] = {"receivers": {"local": {"cwd": "/tmp"}}}
    else:
        rig.health["runtime"]["source_tree_sha256"] = "0" * 64
    from kirabridge.bridge_core.config import Config

    candidate = Config.model_validate(raw)
    if changed == "source":
        with pytest.raises(BridgeError) as error:
            await rig.service.activate(text=principal_only_text(rig), principal_grant="local")
        assert error.value.code == "principal_grant_source"
    else:
        with pytest.raises(BridgeError) as error:
            rig.service.validate_principal_grant(load_config(str(rig.path)), candidate, "local")
        assert error.value.code == "principal_grant_scope"
    assert not rig.commands and rig.bridge.store.maintenance_state() is None


@pytest.mark.parametrize(
    "work", ["queued-task", "running-job", "team-result", "inserting", "submitting", "return_sent"]
)
async def test_principal_grant_never_bypasses_bridge_work_or_partial_native_input(operations, work):
    from test_activation_queries import processing_result_fixture

    rig = operations
    message_id = external_wait(
        rig, state=work if work in {"inserting", "submitting", "return_sent"} else "confirmed"
    )
    if work == "queued-task":
        rig.bridge.prepare(
            "local", request("file.list", {"path": rig.bridge.config.principals["local"].roots[0]})
        )
    elif work == "running-job":
        rig.bridge.store.db.execute(
            "INSERT INTO message_jobs(message_id,state) VALUES(?,'running')", (message_id,)
        )
    elif work == "team-result":
        processing_result_fixture(rig.bridge.store)
    before = rig.path.read_bytes()
    rig.service.drain_timeout = 0
    with pytest.raises(BridgeError) as error:
        await rig.service.activate(text=principal_only_text(rig), principal_grant="local")
    assert error.value.code == "service_busy"
    assert not rig.commands and rig.path.read_bytes() == before


async def test_principal_grant_restart_rechecks_exact_config_and_recovery_stays_strict(
    operations, monkeypatch
):
    rig = operations
    external_wait(rig)
    original_restart = rig.service.restart

    async def changed_before_restart(identifier):
        # A concurrent operator change must never inherit the exceptional restart grant.
        rig.path.write_text(rig.path.read_text() + "\n# unrelated concurrent edit\n")
        await original_restart(identifier)

    monkeypatch.setattr(rig.service, "restart", changed_before_restart)
    with pytest.raises(BridgeError) as error:
        await rig.service.activate(text=principal_only_text(rig), principal_grant="local")
    assert error.value.code == "principal_grant_scope"
    assert not rig.commands
    assert rig.bridge.store.maintenance_state()["state"] == "failed_blocked"
    with pytest.raises(BridgeError) as recovery:
        await rig.service.recover()
    assert recovery.value.code == "service_busy"
    assert not rig.commands
    assert (
        rig.bridge.store.db.execute(
            "SELECT state FROM visible_handoffs WHERE id='external-wait'"
        ).fetchone()[0]
        == "confirmed"
    )
