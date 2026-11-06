"""Own durable coordinator events; native fixture turns never call a provider."""

import asyncio
import json

import pytest
from pydantic import ValidationError
from test_autonext import scenario, until  # noqa: F401
from test_autonext_coordinator import configure
from test_mcp import http_bridge  # noqa: F401

from kirabridge.autonext.coordinator import CoordinatedAutoNext
from kirabridge.autonext.manager import AutoNextManager, text_sha
from kirabridge.autonext.models import ApprovedCard, AutoNextConfig
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import BridgeError, canonical, digest
from kirabridge.queue_management.models import QueueControl
from kirabridge.whiteboard_read import append_whiteboard

TARGET = "native-coordinator.session-1"


def isolated_grant(bridge, config, *, target=TARGET, coordinator=True):
    config.principals["codex"] = config.principals["local"].model_copy(
        update={"capabilities": ["team.read"], "approval_mode": "automatic"}, deep=True
    )
    config.principals["other"].capabilities = ["team.read"]
    config.autonext = AutoNextConfig(
        grant_id="grant-v1",
        principal="codex" if coordinator else "local",
        coordinator_mode=coordinator,
        completion_target=target,
        team_id="isolated-team",
    )
    bridge.autonext._setup()
    return bridge.autonext


def notice_rows(bridge):
    return bridge.store.db.execute(
        "SELECT * FROM completion_notices WHERE source='autonext' ORDER BY seq"
    ).fetchall()


@pytest.mark.parametrize("target", [None, "default", TARGET, "a:b_C-1.2"])
def test_completion_target_accepts_existing_opaque_target_contract(target):
    assert AutoNextConfig(completion_target=target).completion_target == target


@pytest.mark.parametrize("target", ["", "with space", "a/b", "a\n", "x" * 129, 1])
def test_completion_target_rejects_invalid_routes(target):
    with pytest.raises(ValidationError):
        AutoNextConfig(completion_target=target)


def test_legacy_configuration_fingerprint_and_active_route_pin(bridge, config):
    manager = isolated_grant(bridge, config, target=None)
    legacy = digest(
        {
            "grant": config.autonext.model_dump(exclude={"completion_target"}),
            "worker": None,
            "agent": None,
            "executor_file": None,
            "policy": config.principals["codex"].model_dump(),
            "operator_policy": config.principals["codex"].model_dump(),
            "route": config.visible_handoffs.model_dump(),
            "team_enabled": config.team.enabled,
        }
    )
    assert manager._configuration_ref() == legacy
    config.autonext.completion_target = TARGET
    assert manager._configuration_ref() != legacy
    with pytest.raises(BridgeError) as error:
        manager._setup()
    assert error.value.code == "autonext_grant_changed"
    assert not notice_rows(bridge)


@pytest.mark.parametrize(
    "target,coordinator,phase",
    [(None, True, "completed"), (TARGET, False, "completed"), (TARGET, True, "claimed")],
)
def test_notices_are_opt_in_for_new_terminal_coordinator_events(
    bridge, config, target, coordinator, phase
):
    manager = isolated_grant(bridge, config, target=target, coordinator=coordinator)
    with bridge.store.transaction():
        manager._queue_note("section.one-1", phase, {})
    assert not notice_rows(bridge)
    assert bridge.store.db.execute("SELECT count(*) FROM autonext_outbox").fetchone()[0] == 1
    # Enabling a route cannot backfill an existing event or create a second queue entry.
    config.autonext.completion_target = TARGET
    bridge.autonext = AutoNextManager(bridge)
    with bridge.store.transaction():
        bridge.autonext._queue_note("section.one-1", phase, {})
    assert not notice_rows(bridge)


def test_stop_source_state_notice_and_audit_roll_back_together(bridge, config, monkeypatch):
    manager = isolated_grant(bridge, config)
    import kirabridge.autonext.manager as module

    original = module.record_notice

    def interrupted(*args):
        original(*args)
        raise RuntimeError("interrupted after notice insert")

    with monkeypatch.context() as patch:
        patch.setattr(module, "record_notice", interrupted)
        with pytest.raises(RuntimeError, match="interrupted"):
            manager._stop("autonext_completion_unknown")
    assert manager._run()["state"] == "idle"
    assert not bridge.store.db.execute("SELECT 1 FROM autonext_outbox").fetchone()
    assert not notice_rows(bridge)
    assert not bridge.store.db.execute(
        "SELECT 1 FROM audit WHERE kind='completion.recorded'"
    ).fetchone()
    manager._stop("autonext_completion_unknown")
    assert len(notice_rows(bridge)) == 1 and manager._run()["state"] == "stopped"


def test_event_payload_never_copies_raw_details(bridge, config):
    manager = isolated_grant(bridge, config)
    with bridge.store.transaction():
        manager._queue_note(
            "section.one-1",
            "stopped",
            {
                "reason": "PRIVATE_RAW_ERROR",
                "prompt": "PRIVATE_PROMPT",
                "result": {"stdout": "PRIVATE_RESULT"},
                "receipt_sha256": "PRIVATE_NOT_A_HASH",
                "result_sha256": "a" * 64,
            },
        )
    payload = json.loads(notice_rows(bridge)[0]["payload"])
    assert "PRIVATE" not in canonical(payload)
    assert "receipt_sha256" not in payload["evidence_refs"]
    assert payload["evidence_refs"]["result_sha256"] == "a" * 64


@pytest.mark.parametrize(
    "source_id", ["section.one-1", "a" * 94 + ".b", "grant-" + "g" * 94 + ".b"]
)
def test_source_filter_accepts_exact_autonext_and_synthetic_grant_ids(bridge, config, source_id):
    manager = isolated_grant(bridge, config)
    with bridge.store.transaction():
        manager._queue_note(source_id, "stopped", {"reason": "autonext_timeout_unknown"})
    notice = bridge.completions.receive("codex", TARGET, source_id=source_id)["notices"][0]
    assert notice["payload"]["task_id"] == source_id
    assert notice["payload"]["outcome"] == "stopped"


@pytest.mark.parametrize(
    "source_id", ["", ".leading", "../a", "a/b", "a:b", "a\n", "a b", "x" * 129, "a" * 95 + ".b", 1]
)
def test_source_filter_keeps_other_invalid_inputs_invalid(bridge, config, source_id):
    isolated_grant(bridge, config)
    with pytest.raises(BridgeError) as error:
        bridge.completions.receive("codex", TARGET, source_id=source_id)
    assert error.value.code == "invalid_arguments"


async def test_principal_target_team_permission_and_receipt_are_bound(bridge, config):
    manager = isolated_grant(bridge, config)
    manager._stop("autonext_completion_unknown")
    row = notice_rows(bridge)[0]
    assert not bridge.completions.receive("other", TARGET)["notices"]
    assert not bridge.completions.receive("codex", "another-target")["notices"]
    with pytest.raises(BridgeError) as error:
        bridge.completions.ack("other", row["id"], "unissued")
    assert error.value.code == "not_found"
    assert notice_rows(bridge)[0]["receipt"] is None
    notice = bridge.completions.receive("codex", TARGET)["notices"][0]
    view = bridge.queues.get("codex", "completions/" + TARGET, notice["id"])
    cancel = QueueControl(
        queue_id="completions/" + TARGET,
        item_id=notice["id"],
        action="cancel",
        revision=view["revision"],
        reason="isolated hold",
    )
    config.principals["codex"].capabilities = ["message.read", "task.read"]
    assert not bridge.completions.receive("codex", TARGET)["notices"]
    assert not bridge.queues.entries("codex", "completions")["entries"]
    for operation in (
        lambda: bridge.completions.ack("codex", notice["id"], notice["receipt"]),
        lambda: bridge.queues.get("codex", "completions", notice["id"]),
    ):
        with pytest.raises(BridgeError) as error:
            operation()
        assert error.value.code == "forbidden"
    with pytest.raises(BridgeError) as error:
        await bridge.queues.control("codex", cancel)
    assert error.value.code == "forbidden"
    config.principals["codex"].capabilities = ["team.read"]
    repeated = bridge.completions.receive("codex", TARGET)["notices"][0]
    assert repeated == notice
    with pytest.raises(BridgeError) as error:
        bridge.completions.ack("codex", notice["id"], "another-receipt")
    assert error.value.code == "receipt_conflict"
    first = bridge.completions.ack("codex", notice["id"], notice["receipt"])
    assert bridge.completions.ack("codex", notice["id"], notice["receipt"]) == first
    assert not bridge.completions.receive("codex", TARGET)["notices"]


async def test_team_only_queue_catalog_hold_and_restore_preserve_notice(bridge, config):
    manager = isolated_grant(bridge, config)
    manager._stop("autonext_completion_unknown")
    row = notice_rows(bridge)[0]
    queue_id = "completions/" + TARGET
    assert any(q["queue_id"] == queue_id for q in bridge.queues.catalog("codex")["queues"])
    for action in ("cancel", "restore"):
        view = bridge.queues.get("codex", queue_id, row["id"])
        assert view["detail"]["source"] == "autonext"
        result = await bridge.queues.control(
            "codex",
            QueueControl(
                queue_id=queue_id,
                item_id=row["id"],
                action=action,
                revision=view["revision"],
                reason="isolated delivery control",
            ),
        )
        assert not result["execution_stop_claimed"]
        assert notice_rows(bridge)[0]["receipt"] is None
        if action == "cancel":
            assert not bridge.completions.receive("codex", TARGET)["notices"]
    assert len(bridge.completions.receive("codex", TARGET)["notices"]) == 1
    assert len(notice_rows(bridge)) == 1 and manager._run()["state"] == "stopped"


async def test_native_checks_gate_completion_and_restart_keeps_receipt(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,  # noqa: F811
):
    s = scenario
    card = configure(s, tmp_path, monkeypatch, grok=True)
    bridge, config = s["bridge"], s["config"]
    card["task_id"] = "accepted.section-1"
    card["instruction"] = "PRIVATE_INSTRUCTION_MUST_NOT_ENTER_NOTICE"
    content = canonical(card)
    entry = append_whiteboard(
        str(s["desk"]),
        "board",
        actor="operator",
        actor_type="human",
        entry_type="task",
        content=content,
        external_key="native-completion-card",
    )
    config.autonext.cards = [
        ApprovedCard(
            task_id=card["task_id"], entry_id=entry["id"], content_sha256=text_sha(content)
        )
    ]
    config.autonext.completion_target = TARGET
    started, release = asyncio.Event(), asyncio.Event()
    original_checks = bridge.autonext._run_checks

    async def bounded_checks(value):
        started.set()
        await release.wait()
        return await original_checks(value)

    monkeypatch.setattr(bridge.autonext, "_run_checks", bounded_checks)
    await s["start"]()
    await asyncio.wait_for(started.wait(), 8)
    try:
        work = bridge.store.db.execute("SELECT work_id FROM autonext_items").fetchone()
        assert (
            bridge.teams.work_get("codex", config.autonext.team_id, work["work_id"])["state"]
            == "completed"
        )
        assert not notice_rows(bridge)  # Main and review model turns have already completed.
    finally:
        release.set()
    await until(lambda: bridge.autonext.inspect()["state"] in {"complete", "stopped"})
    assert bridge.autonext.inspect()["state"] == "complete"
    receipt = bridge.autonext.receipt("codex", card["task_id"])
    assert receipt["coordinator"]["checks"]["passed"] is True
    rows = notice_rows(bridge)
    assert len(rows) == 1
    source = bridge.store.db.execute(
        "SELECT rowid,* FROM autonext_outbox WHERE phase='completed'"
    ).fetchone()
    row = rows[0]
    assert (row["principal"], row["target"], row["source_id"], row["event_seq"]) == (
        "codex",
        TARGET,
        card["task_id"],
        source["rowid"],
    )
    assert not bridge.completions.receive("local", TARGET)["notices"]
    notice = bridge.completions.receive("codex", TARGET, source_id=card["task_id"])["notices"][0]
    payload = notice["payload"]
    assert payload["phase"] == "completed" and payload["outcome"] == "success"
    assert payload["completion_scope"] == "accepted_autonext_task"
    assert payload["agent_work_completion_verified"]
    assert not payload["project_completion_verified"] and not payload["chat_completion_verified"]
    assert payload["evidence_refs"] == {
        "autonext_outbox_key": source["key"],
        "content_sha256": text_sha(source["content"]),
        "receipt_sha256": digest(receipt),
        "result_sha256": receipt["result_sha256"],
    }
    assert all(
        text not in canonical(payload)
        for text in (card["instruction"], "DONE:", "fixture verified", "argv", "stdout", "prompt")
    )
    await bridge.autonext.stop()
    counts = tuple(
        bridge.store.db.execute(
            "SELECT (SELECT count(*) FROM team_work),(SELECT count(*) FROM tasks),"
            "(SELECT count(*) FROM autonext_outbox)"
        ).fetchone()
    )
    reopened = Bridge(config)
    try:
        reopened.autonext = CoordinatedAutoNext(reopened)
        await reopened.autonext.tick()
        assert reopened.completions.receive("codex", TARGET)["notices"] == [notice]
        assert (
            tuple(
                reopened.store.db.execute(
                    "SELECT (SELECT count(*) FROM team_work),(SELECT count(*) FROM tasks),"
                    "(SELECT count(*) FROM autonext_outbox)"
                ).fetchone()
            )
            == counts
        )
        first = reopened.completions.ack("codex", notice["id"], notice["receipt"])
        assert reopened.completions.ack("codex", notice["id"], notice["receipt"]) == first
        await reopened.autonext.tick()
        assert not reopened.completions.receive("codex", TARGET)["notices"]
        assert len(notice_rows(reopened)) == 1
    finally:
        reopened.store.close()


@pytest.mark.parametrize("exit_code,verdict", [(7, "pass"), (0, "fail")])
async def test_negative_acceptance_emits_only_stopped_notice(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,
    exit_code,
    verdict,  # noqa: F811
):
    s = scenario
    card = configure(s, tmp_path, monkeypatch, exit_code=exit_code, verdict=verdict)
    bridge = s["bridge"]
    s["config"].autonext.completion_target = TARGET
    await s["start"]()
    await until(lambda: bridge.autonext.inspect()["state"] == "stopped")
    assert bridge.autonext.receipt("codex", card["task_id"]) is None
    notice = bridge.completions.receive("codex", TARGET)["notices"][0]
    assert notice["payload"]["state"] == "stopped"
    assert notice["payload"]["outcome"] == "stopped"
    assert notice["payload"]["completion_scope"] == "autonext_continuation_stop"
    assert not notice["payload"]["agent_work_completion_verified"]
    assert not notice["payload"]["automatic_retry"]
    assert len(notice_rows(bridge)) == 1


async def test_failed_completion_commit_keeps_original_receipt_and_lease_unaccepted(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    s = scenario
    card = configure(s, tmp_path, monkeypatch)
    bridge = s["bridge"]
    s["config"].autonext.completion_target = TARGET
    import kirabridge.autonext.manager as module

    original = module.record_notice

    def interrupted(store, principal, target, source, source_id, event_seq, payload):
        original(store, principal, target, source, source_id, event_seq, payload)
        if payload["phase"] == "completed":
            raise RuntimeError("completion commit interrupted")

    monkeypatch.setattr(module, "record_notice", interrupted)
    await s["start"]()
    await until(lambda: bridge.autonext.inspect()["state"] == "stopped")
    assert bridge.autonext.inspect()["reason"] == "autonext_state_unknown"
    item = bridge.store.db.execute("SELECT * FROM autonext_items").fetchone()
    assert item["state"] == "waiting" and item["receipt"] is None
    assert bridge.store.db.execute(
        "SELECT 1 FROM autonext_leases WHERE task_id=?", (card["task_id"],)
    ).fetchone()
    assert not bridge.store.db.execute(
        "SELECT 1 FROM autonext_outbox WHERE phase='completed'"
    ).fetchone()
    assert json.loads(notice_rows(bridge)[0]["payload"])["outcome"] == "stopped"
    assert len(notice_rows(bridge)) == 1
    assert (
        bridge.store.db.execute(
            "SELECT count(*) FROM audit WHERE kind='completion.recorded' "
            "AND principal='codex' AND json_extract(metadata,'$.source')='autonext'"
        ).fetchone()[0]
        == 1
    )
    assert (
        bridge.teams.work_get("codex", s["config"].autonext.team_id, item["work_id"])["state"]
        == "completed"
    )
    await bridge.autonext.stop()
    count = bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0]
    bridge.autonext = CoordinatedAutoNext(bridge)
    await bridge.autonext.tick()
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == count
    assert len(notice_rows(bridge)) == 1


async def test_interrupted_checks_remain_unknown_and_do_not_replay(scenario, tmp_path, monkeypatch):  # noqa: F811
    s = scenario
    card = configure(s, tmp_path, monkeypatch)
    bridge = s["bridge"]
    s["config"].autonext.completion_target = TARGET
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def interrupted_checks(value):
        calls.append(value.task_id)
        started.set()
        await release.wait()
        return {"passed": True, "checks": []}

    monkeypatch.setattr(bridge.autonext, "_run_checks", interrupted_checks)
    await s["start"]()
    await asyncio.wait_for(started.wait(), 8)
    stop = asyncio.create_task(bridge.autonext.stop())
    release.set()
    await stop
    before = tuple(bridge.store.db.execute("SELECT * FROM autonext_coordinator").fetchone())
    bridge.autonext = CoordinatedAutoNext(bridge)
    await bridge.autonext.tick()
    assert bridge.autonext.inspect()["reason"] == "autonext_check_unknown"
    assert tuple(bridge.store.db.execute("SELECT * FROM autonext_coordinator").fetchone()) == before
    assert bridge.autonext.receipt("codex", card["task_id"]) is None
    assert calls == [card["task_id"]]
    assert json.loads(notice_rows(bridge)[0]["payload"])["outcome"] == "stopped"
    count = bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0]
    await bridge.autonext.tick()
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == count
    assert len(notice_rows(bridge)) == 1
