"""Recorded timings through existing deterministic CLI/Core/TeamWork fixtures."""

import json

import pytest
from test_autonext import scenario, until  # noqa: F401
from test_autonext_coordinator import configure
from test_mcp import http_bridge  # noqa: F401

from kirabridge.autonext.status import coordinator_status
from kirabridge.autonext.timings import task_timings
from kirabridge.bridge_core.models import BridgeError

FIELDS = {
    "task_id",
    "core_created_at",
    "core_accepted_at",
    "core_started_at",
    "core_finished_at",
    "task_accepted_at",
    "queue_seconds",
    "execution_seconds",
    "acceptance_seconds",
    "total_seconds",
}


@pytest.fixture
async def completed(scenario, tmp_path, monkeypatch):  # noqa: F811
    s, b = scenario, scenario["bridge"]
    card = configure(s, tmp_path, monkeypatch)
    await s["start"]()
    await until(lambda: b.autonext.inspect()["state"] in {"complete", "stopped"})
    assert b.autonext.inspect()["state"] == "complete", b.autonext.inspect()
    return s, card


async def test_completed_timings_are_exact_stored_values_and_status_is_read_only(completed):
    s, card = completed
    b, task_id = s["bridge"], card["task_id"]
    item = b.store.db.execute("SELECT * FROM autonext_items WHERE task_id=?", (task_id,)).fetchone()
    work = b.teams.work_get("codex", "auto-team", item["work_id"])
    core = b.store.get(work["core_task_id"], "codex")
    receipt = json.loads(item["receipt"])
    count = b.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0]
    times = task_timings(b, "codex", task_id)
    assert set(times) == FIELDS
    for projected, stored in (
        ("core_created_at", "created"),
        ("core_accepted_at", "accepted"),
        ("core_started_at", "started"),
        ("core_finished_at", "finished"),
    ):
        assert times[projected] == core[stored]
    assert times["task_accepted_at"] == receipt["accepted_at"]
    assert times["queue_seconds"] == core["accepted"] - core["created"]
    assert times["execution_seconds"] == core["finished"] - core["started"]
    assert times["acceptance_seconds"] == receipt["accepted_at"] - core["finished"]
    assert times["total_seconds"] == receipt["accepted_at"] - core["created"]
    status = coordinator_status(b, "codex")
    assert status["tasks"][0]["timings"] == times
    assert coordinator_status(b, "codex")["tasks"][0]["timings"] == times
    assert b.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == count
    rendered = json.dumps(times, allow_nan=False)
    assert card["instruction"] not in rendered and str(s["root"]) not in rendered
    assert work["result"] not in rendered


async def test_waiting_or_missing_core_has_no_invented_times(scenario, tmp_path, monkeypatch):  # noqa: F811
    s, b = scenario, scenario["bridge"]
    card = configure(s, tmp_path, monkeypatch)
    await b.autonext.tick()
    count = b.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0]
    expected = dict.fromkeys(FIELDS)
    expected["task_id"] = card["task_id"]
    assert task_timings(b, "codex", card["task_id"]) == expected
    assert coordinator_status(b, "codex")["tasks"][0]["timings"] == expected
    b.store.db.execute(
        "UPDATE team_work SET core_task_id='missing-native-core',started=10,finished=20 "
        "WHERE id=(SELECT work_id FROM autonext_items WHERE task_id=?)",
        (card["task_id"],),
    )
    assert task_timings(b, "codex", card["task_id"]) == expected
    assert b.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == count
    assert b.autonext.worker is None


async def test_timings_enforce_owner_capability_current_grant_and_membership(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    s, b = scenario, scenario["bridge"]
    card = configure(s, tmp_path, monkeypatch)
    await b.autonext.tick()
    for principal in ("local", "grok"):
        with pytest.raises(BridgeError) as error:
            task_timings(b, principal, card["task_id"])
        assert error.value.code == "coordinator_owner_required"
    with pytest.raises(BridgeError) as error:
        task_timings(b, "codex", "foreign-task")
    assert error.value.code == "not_found"
    original = s["config"].autonext.grant_id
    s["config"].autonext.grant_id = "another-grant"
    with pytest.raises(BridgeError) as error:
        task_timings(b, "codex", card["task_id"])
    assert error.value.code == "not_found"
    s["config"].autonext.grant_id = original
    policy = s["config"].principals["codex"]
    policy.capabilities.remove("team.read")
    with pytest.raises(BridgeError) as error:
        task_timings(b, "codex", card["task_id"])
    assert error.value.code == "forbidden"
    policy.capabilities.append("team.read")
    b.store.db.execute("UPDATE team_members SET active=0 WHERE principal='codex'")
    with pytest.raises(BridgeError):
        task_timings(b, "codex", card["task_id"])


async def test_completed_item_without_core_identity_has_no_acceptance_time(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    s, b = scenario, scenario["bridge"]
    card = configure(s, tmp_path, monkeypatch)
    await b.autonext.tick()
    item = b.store.db.execute(
        "SELECT * FROM autonext_items WHERE task_id=?", (card["task_id"],)
    ).fetchone()
    b.store.db.execute("UPDATE team_work SET core_task_id=NULL WHERE id=?", (item["work_id"],))
    receipt = {
        "task_id": item["task_id"],
        "work_id": item["work_id"],
        "source_sha256": item["source_ref"],
        "accepted_at": 150,
    }
    b.store.db.execute(
        "UPDATE autonext_items SET state='completed',receipt=? WHERE task_id=?",
        (json.dumps(receipt), item["task_id"]),
    )
    count = b.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0]
    times = task_timings(b, "codex", card["task_id"])
    assert times["task_accepted_at"] is None
    assert times["acceptance_seconds"] is None and times["total_seconds"] is None
    assert coordinator_status(b, "codex")["tasks"][0]["timings"] == times
    assert b.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == count


async def test_invalid_timestamps_and_intervals_remain_unknown(completed):
    s, card = completed
    b, task_id = s["bridge"], card["task_id"]
    item = b.store.db.execute("SELECT * FROM autonext_items WHERE task_id=?", (task_id,)).fetchone()
    receipt = json.loads(item["receipt"])
    core_id = receipt["core_task_id"]
    for field, value, absent in (
        ("created", float("inf"), "queue_seconds"),
        ("accepted", float("nan"), "queue_seconds"),
        ("started", "not a native timestamp", "execution_seconds"),
        ("finished", float("-inf"), "execution_seconds"),
        ("accepted", 90, "queue_seconds"),
        ("finished", 110, "execution_seconds"),
        ("created", -1e308, "total_seconds"),
    ):
        b.store.db.execute(
            "UPDATE tasks SET created=100,accepted=110,started=120,finished=140 WHERE id=?",
            (core_id,),
        )
        changed_receipt = {**receipt, "accepted_at": 1e308 if value == -1e308 else 150}
        b.store.db.execute(
            "UPDATE autonext_items SET receipt=? WHERE task_id=?",
            (json.dumps(changed_receipt), task_id),
        )
        b.store.db.execute(f"UPDATE tasks SET {field}=? WHERE id=?", (value, core_id))
        times = task_timings(b, "codex", task_id)
        assert times[absent] is None, (field, value, times)
        json.dumps(times, allow_nan=False)
    for invalid in (True, "150", float("inf"), 10**400):
        b.store.db.execute(
            "UPDATE autonext_items SET receipt=? WHERE task_id=?",
            (json.dumps({**receipt, "accepted_at": invalid}), task_id),
        )
        assert task_timings(b, "codex", task_id)["task_accepted_at"] is None


async def test_acceptance_requires_the_bound_receipt_and_ordered_endpoints(completed):
    s, card = completed
    b, task_id = s["bridge"], card["task_id"]
    item = b.store.db.execute("SELECT * FROM autonext_items WHERE task_id=?", (task_id,)).fetchone()
    receipt = json.loads(item["receipt"])
    for value in ("not json", "[]", json.dumps({**receipt, "task_id": "other-task"})):
        b.store.db.execute("UPDATE autonext_items SET receipt=? WHERE task_id=?", (value, task_id))
        times = task_timings(b, "codex", task_id)
        assert times["task_accepted_at"] is None and times["acceptance_seconds"] is None
    receipt["accepted_at"] = 130
    b.store.db.execute(
        "UPDATE tasks SET created=100,accepted=110,started=120,finished=140 WHERE id=?",
        (receipt["core_task_id"],),
    )
    b.store.db.execute(
        "UPDATE autonext_items SET receipt=? WHERE task_id=?", (json.dumps(receipt), task_id)
    )
    times = task_timings(b, "codex", task_id)
    assert times["task_accepted_at"] == 130
    assert times["acceptance_seconds"] is None and times["total_seconds"] == 30
