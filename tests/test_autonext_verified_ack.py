"""Same-daemon accepted-result processing; deterministic CLI, no model/provider."""

# ruff: noqa: F811 -- imported pytest fixtures.

import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_autonext import scenario, until  # noqa: F401
from test_autonext_coordinator import configure
from test_mcp import http_bridge  # noqa: F401

from kirabridge.autonext.completion_processing import ProcessedCompletion
from kirabridge.autonext.coordinator import CoordinatedAutoNext
from kirabridge.autonext.manager import AutoNextManager, text_sha
from kirabridge.autonext.models import ApprovedCard, AutoNextConfig
from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.task_manager.store import Store
from kirabridge.whiteboard_read import append_whiteboard


def setup(s, tmp_path, monkeypatch):
    card = configure(s, tmp_path, monkeypatch)
    second = {**card, "task_id": "coordinated-two", "title": "Second original card"}
    content = json.dumps(second)
    entry = append_whiteboard(
        str(s["desk"]),
        "board",
        actor="operator",
        actor_type="human",
        entry_type="task",
        content=content,
        external_key="second-card",
    )
    cfg = s["config"].autonext
    cfg.cards.append(
        ApprovedCard(
            task_id=second["task_id"], entry_id=entry["id"], content_sha256=text_sha(content)
        )
    )
    # Revalidate the typed operator input rather than inventing runtime attributes.
    s["config"].autonext = AutoNextConfig.model_validate(
        {
            **cfg.model_dump(),
            "completion_target": "server-owned-results",
            "completion_mode": "verified_ack",
        }
    )
    return s["bridge"]


def count_items(b):
    return b.store.db.execute("SELECT count(*) FROM autonext_items").fetchone()[0]


def first_notice(b):
    return b.store.db.execute(
        "SELECT * FROM completion_notices WHERE source='autonext' AND source_id='coordinated-one'"
    ).fetchone()


async def accepted_without_consumer(s, tmp_path, monkeypatch):
    b = setup(s, tmp_path, monkeypatch)
    consume = b.autonext.completion_consumer.process
    monkeypatch.setattr(b.autonext.completion_consumer, "process", lambda: None)
    await s["start"]()
    await until(lambda: b.autonext.receipt("codex", "coordinated-one") is not None)
    await b.autonext.stop()
    assert count_items(b) == 1
    assert first_notice(b)["acknowledged"] is None
    return b, consume


async def finish(b):
    await b.autonext.start()
    b.autonext.notify()
    await until(lambda: b.autonext.inspect()["state"] in {"complete", "stopped"})
    assert b.autonext.inspect()["state"] == "complete", b.autonext.inspect()
    assert count_items(b) == 2
    assert b.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 4


async def test_same_daemon_two_cards_ack_precedes_actual_followup_without_stage_change(
    scenario,
    tmp_path,
    monkeypatch,  # noqa: F811
):
    b = setup(scenario, tmp_path, monkeypatch)
    for index in range(5):
        b.store.db.execute(
            "INSERT INTO tasks(id,principal,idem,request_hash,operation,args,state,"
            "created,updated) "
            "VALUES(?, 'codex', ?, 'historical-seal','agent.execute','{}','unknown',1,2)",
            (f"historical-{index}", f"historical-{index}"),
        )
    for index in range(6):
        b.store.db.execute(
            "INSERT INTO autonext_leases VALUES(?,?,?,1)",
            (str(tmp_path / f"old-scope-{index}"), f"old-{index}", "historical-owner"),
        )
    history = [tuple(r) for r in b.store.db.execute("SELECT * FROM tasks WHERE state='unknown'")]
    leases = [tuple(r) for r in b.store.db.execute("SELECT * FROM autonext_leases")]
    await scenario["start"]()
    await until(lambda: b.autonext.inspect()["state"] in {"complete", "stopped"})
    assert b.autonext.inspect()["state"] == "complete", b.autonext.inspect()
    rows = b.store.db.execute(
        "SELECT * FROM autonext_processed_completions ORDER BY rowid"
    ).fetchall()
    assert len(rows) == count_items(b) == 2
    processed = ProcessedCompletion.model_validate_json(rows[0]["record"])
    receipt = b.autonext.receipt("codex", "coordinated-two")
    core = b.store.get(receipt["core_task_id"], "codex")
    work = b.teams.work_get("codex", "auto-team", receipt["work_id"])
    assert processed.acknowledged <= work["created"] <= core["started"]
    claim = b.store.db.execute(
        "SELECT content FROM autonext_outbox WHERE task_id='coordinated-two' AND phase='claimed'"
    ).fetchone()[0]
    assert json.loads(claim)["predecessor_ack"]["notice_id"] == processed.notice_id
    assert first_notice(b)["acknowledged"] == processed.acknowledged
    assert b.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 9
    assert [
        tuple(r) for r in b.store.db.execute("SELECT * FROM tasks WHERE state='unknown'")
    ] == history
    assert [tuple(r) for r in b.store.db.execute("SELECT * FROM autonext_leases")] == leases


@pytest.mark.parametrize(
    "tamper",
    [
        "missing_notice",
        "owner",
        "target",
        "source",
        "grant",
        "task",
        "request",
        "result",
        "receipt",
        "unverified",
        "outbox_hash",
        "phase",
    ],
)
async def test_missing_or_foreign_binding_never_acks_or_claims_and_late_original_recovers(
    scenario,
    tmp_path,
    monkeypatch,
    tamper,  # noqa: F811
):
    b, consume = await accepted_without_consumer(scenario, tmp_path, monkeypatch)
    notice = dict(first_notice(b))
    restore = None
    if tamper == "missing_notice":
        b.store.db.execute("DELETE FROM completion_notices WHERE id=?", (notice["id"],))

        def restore():
            return b.store.db.execute(
                "INSERT INTO completion_notices ("
                + ",".join(notice)
                + ") VALUES("
                + ",".join("?" for _ in notice)
                + ")",
                tuple(notice.values()),
            )
    elif tamper in {"owner", "target", "source"}:
        field = {"owner": "principal", "target": "target", "source": "source_id"}[tamper]
        b.store.db.execute(
            f"UPDATE completion_notices SET {field}='foreign' WHERE id=?", (notice["id"],)
        )

        def restore():
            return b.store.db.execute(
                f"UPDATE completion_notices SET {field}=? WHERE id=?", (notice[field], notice["id"])
            )
    elif tamper in {"grant", "task", "phase"}:
        payload = json.loads(notice["payload"])
        payload[{"grant": "grant_id", "task": "task_id", "phase": "phase"}[tamper]] = "foreign"
        b.store.db.execute(
            "UPDATE completion_notices SET payload=? WHERE id=?", (canonical(payload), notice["id"])
        )

        def restore():
            return b.store.db.execute(
                "UPDATE completion_notices SET payload=? WHERE id=?",
                (notice["payload"], notice["id"]),
            )
    elif tamper in {"request", "result"}:
        core_id = b.autonext.receipt("codex", "coordinated-one")["core_task_id"]
        field = "request_hash" if tamper == "request" else "result"
        previous = b.store.db.execute(
            f"SELECT {field} FROM tasks WHERE id=?", (core_id,)
        ).fetchone()[0]
        b.store.db.execute(
            f"UPDATE tasks SET {field}=? WHERE id=?",
            ("0" * 64 if tamper == "request" else "{}", core_id),
        )

        def restore():
            return b.store.db.execute(f"UPDATE tasks SET {field}=? WHERE id=?", (previous, core_id))
    elif tamper == "receipt":
        previous = b.store.db.execute(
            "SELECT receipt FROM autonext_items WHERE task_id='coordinated-one'"
        ).fetchone()[0]
        value = json.loads(previous)
        value["result_sha256"] = "0" * 64
        b.store.db.execute(
            "UPDATE autonext_items SET receipt=? WHERE task_id='coordinated-one'",
            (canonical(value),),
        )

        def restore():
            return b.store.db.execute(
                "UPDATE autonext_items SET receipt=? WHERE task_id='coordinated-one'", (previous,)
            )
    else:
        field = "verified" if tamper == "unverified" else "content"
        previous = b.store.db.execute(
            f"SELECT {field} FROM autonext_outbox "
            "WHERE task_id='coordinated-one' AND phase='completed'"
        ).fetchone()[0]
        b.store.db.execute(
            f"UPDATE autonext_outbox SET {field}=? "
            "WHERE task_id='coordinated-one' AND phase='completed'",
            (0 if tamper == "unverified" else "{}",),
        )

        def restore():
            return b.store.db.execute(
                f"UPDATE autonext_outbox SET {field}=? "
                "WHERE task_id='coordinated-one' AND phase='completed'",
                (previous,),
            )

    consume()
    assert not b.autonext.completion_consumer.barrier()[0]
    assert count_items(b) == 1
    assert not b.store.db.execute("SELECT 1 FROM autonext_processed_completions").fetchone()
    current = first_notice(b)
    assert current is None or current["acknowledged"] is None
    # Call the actual claim boundary: a background preflight cannot bypass the gate.
    approved = b.config.autonext.cards[1]
    b.autonext._claim(approved, b.autonext._card(approved))
    assert count_items(b) == 1
    restore()
    monkeypatch.setattr(b.autonext.completion_consumer, "process", consume)
    await finish(b)


@pytest.mark.parametrize("boundary", ["receipt", "ack", "owner_ack"])
async def test_restart_between_receipt_ack_and_claim_reuses_originals(
    scenario,
    tmp_path,
    monkeypatch,
    boundary,  # noqa: F811
):
    b, consume = await accepted_without_consumer(scenario, tmp_path, monkeypatch)
    if boundary == "ack":
        consume()
    elif boundary == "owner_ack":
        n = b.completions.receive("codex", "server-owned-results", source_id="coordinated-one")[
            "notices"
        ][0]
        b.completions.ack("codex", n["id"], n["receipt"])
    b.autonext = CoordinatedAutoNext(b)
    await finish(b)
    ack = first_notice(b)["acknowledged"]
    await b.autonext.stop()
    b.autonext = CoordinatedAutoNext(b)
    await asyncio.gather(b.autonext.tick(), b.autonext.tick())
    assert count_items(b) == 2 and first_notice(b)["acknowledged"] == ack
    assert (
        b.store.db.execute("SELECT count(*) FROM autonext_processed_completions").fetchone()[0] == 2
    )


async def test_claim_rechecks_after_async_preflight_and_competing_background_tick(
    scenario,
    tmp_path,
    monkeypatch,  # noqa: F811
):
    b, consume = await accepted_without_consumer(scenario, tmp_path, monkeypatch)
    consume()
    original_route = b.autonext._route_ready
    notice = dict(first_notice(b))

    async def change_after_preflight(card):
        await original_route(card)
        b.store.db.execute(
            "UPDATE completion_notices SET target='wrong' WHERE id=?", (notice["id"],)
        )

    monkeypatch.setattr(b.autonext, "_route_ready", change_after_preflight)
    await b.autonext.tick()
    assert count_items(b) == 1
    b.store.db.execute(
        "UPDATE completion_notices SET target=? WHERE id=?", (notice["target"], notice["id"])
    )
    monkeypatch.setattr(b.autonext, "_route_ready", original_route)
    competing = CoordinatedAutoNext(b)
    await asyncio.gather(b.autonext.tick(), competing.tick())
    assert count_items(b) == 2
    monkeypatch.setattr(b.autonext.completion_consumer, "process", consume)
    await finish(b)


async def test_background_claim_hold_observes_restored_original_without_manual_wake(
    scenario,
    tmp_path,
    monkeypatch,
):
    b, consume = await accepted_without_consumer(scenario, tmp_path, monkeypatch)
    consume()
    monkeypatch.setattr(b.autonext.completion_consumer, "process", consume)
    original_route = b.autonext._route_ready
    notice = dict(first_notice(b))
    changed = []

    async def transient_original_observation(card):
        await original_route(card)
        if not changed:
            changed.append(card.task_id)
            b.store.db.execute(
                "UPDATE completion_notices SET target='temporarily-wrong' WHERE id=?",
                (notice["id"],),
            )
            # Simulates a late original journal observation. No manager notify,
            # manual tick, adopt, enable or external coordinator stage is used.
            asyncio.get_running_loop().call_later(
                0.1,
                b.store.db.execute,
                "UPDATE completion_notices SET target=? WHERE id=?",
                (notice["target"], notice["id"]),
            )

    monkeypatch.setattr(b.autonext, "_route_ready", transient_original_observation)
    await b.autonext.start()
    await until(lambda: bool(b.autonext.completion_consumer.pending))
    assert count_items(b) == 1
    await until(lambda: b.autonext.inspect()["state"] in {"complete", "stopped"}, timeout=20)
    assert b.autonext.inspect()["state"] == "complete", b.autonext.inspect()
    assert count_items(b) == 2 and len(changed) == 1


async def test_ack_and_processing_record_commit_atomically(scenario, tmp_path, monkeypatch):  # noqa: F811
    b, consume = await accepted_without_consumer(scenario, tmp_path, monkeypatch)
    original = b.store.audit

    def crash(kind, *args, **kwargs):
        if kind == "autonext.completion_processed":
            raise RuntimeError("simulated process loss before commit")
        return original(kind, *args, **kwargs)

    monkeypatch.setattr(b.store, "audit", crash)
    with pytest.raises(RuntimeError):
        consume()
    assert first_notice(b)["acknowledged"] is None
    assert first_notice(b)["receipt"] is None
    assert not b.store.db.execute("SELECT 1 FROM autonext_processed_completions").fetchone()
    monkeypatch.setattr(b.store, "audit", original)
    monkeypatch.setattr(b.autonext.completion_consumer, "process", consume)
    await finish(b)


@pytest.mark.parametrize("field", ["acknowledged", "receipt"])
async def test_different_ack_cannot_reuse_existing_processing_receipt(
    scenario,
    tmp_path,
    monkeypatch,
    field,
):
    b, consume = await accepted_without_consumer(scenario, tmp_path, monkeypatch)
    consume()
    notice = first_notice(b)
    value = notice[field] + 1 if field == "acknowledged" else "different-original-receipt"
    b.store.db.execute(f"UPDATE completion_notices SET {field}=? WHERE id=?", (value, notice["id"]))
    consume()
    assert not b.autonext.completion_consumer.barrier()[0]
    pin = b.config.autonext.cards[1]
    b.autonext._claim(pin, b.autonext._card(pin))
    assert count_items(b) == 1
    b.store.db.execute(
        f"UPDATE completion_notices SET {field}=? WHERE id=?",
        (notice[field], notice["id"]),
    )
    monkeypatch.setattr(b.autonext.completion_consumer, "process", consume)
    await finish(b)


async def test_user_completion_hold_blocks_processing_until_explicit_release(
    scenario,
    tmp_path,
    monkeypatch,
):
    b, consume = await accepted_without_consumer(scenario, tmp_path, monkeypatch)
    notice = first_notice(b)
    b.store.db.execute(
        "INSERT INTO queue_holds VALUES('completions',?,'codex',1,'explicit user hold')",
        (notice["id"],),
    )
    consume()
    assert not b.autonext.completion_consumer.barrier()[0]
    assert first_notice(b)["acknowledged"] is None and count_items(b) == 1
    assert (
        b.store.db.execute("SELECT reason FROM queue_holds").fetchone()[0] == "explicit user hold"
    )
    b.store.db.execute("DELETE FROM queue_holds WHERE item_id=?", (notice["id"],))
    monkeypatch.setattr(b.autonext.completion_consumer, "process", consume)
    await finish(b)


async def test_late_original_submit_observation_reaches_ack_and_followup_without_resubmit(
    scenario,
    tmp_path,
    monkeypatch,
):
    b = setup(scenario, tmp_path, monkeypatch)
    original = b.team_dispatcher._call
    submits = []
    lost = []

    async def lose_first_verifier_reply(pool, tool, args):
        result = await original(pool, tool, args)
        if tool == "task_submit":
            submits.append(args["request"]["task_id"])
            if args["request"]["arguments"]["agent"] == "codex_verify" and not lost:
                lost.append(args["request"]["task_id"])
                raise BridgeError("peer_unknown", "Original submit response lost after admission")
        return result

    monkeypatch.setattr(b.team_dispatcher, "_call", lose_first_verifier_reply)
    await scenario["start"]()
    await until(lambda: b.autonext.inspect()["state"] in {"complete", "stopped"})
    assert b.autonext.inspect()["state"] == "complete", b.autonext.inspect()
    assert len(lost) == 1 and len(submits) == len(set(submits)) == 4
    receipt = b.autonext.receipt("codex", "coordinated-two")
    assert first_notice(b)["acknowledged"] <= b.store.get(receipt["core_task_id"])["started"]
    assert (
        b.store.db.execute("SELECT count(*) FROM autonext_processed_completions").fetchone()[0] == 2
    )


def test_typed_opt_in_and_legacy_serialization():
    assert "completion_mode" not in AutoNextConfig().model_dump()
    for changes in (
        {},
        {"coordinator_mode": True, "principal": "codex"},
        {"completion_target": "t"},
    ):
        with pytest.raises(ValidationError):
            AutoNextConfig(completion_mode="verified_ack", **changes)
    cfg = AutoNextConfig(
        completion_mode="verified_ack",
        coordinator_mode=True,
        principal="codex",
        completion_target="t",
    )
    assert cfg.model_dump()["completion_mode"] == "verified_ack"


def test_additive_processing_schema_preserves_historical_rows(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    try:
        AutoNextManager(SimpleNamespace(store=store))
        store.db.execute(
            "INSERT INTO autonext_runs VALUES('old','oldhash','stopped','user_stop',1)"
        )
        store.db.execute("INSERT INTO autonext_leases VALUES('/historical','oldtask','oldowner',1)")
        before = list(store.db.iterdump())
        AutoNextManager(SimpleNamespace(store=store))
        assert list(store.db.iterdump()) == before
        assert (
            store.db.execute("SELECT count(*) FROM autonext_processed_completions").fetchone()[0]
            == 0
        )
    finally:
        store.close()
