"""Explicit sealed team-managed work never enters native input admission."""

import asyncio
import json

import pytest
from conftest import request
from test_autonext import scenario, until  # noqa: F401
from test_autonext_coordinator import configure
from test_mcp import http_bridge  # noqa: F401

from kirabridge.bridge_core.models import State, TaskRequest
from kirabridge.task_manager.store import Store


async def test_managed_team_turn_outlives_native_deadline(scenario, tmp_path, monkeypatch):  # noqa: F811
    s = scenario
    configure(s, tmp_path, monkeypatch)
    bridge = s["bridge"]
    bridge.config.visible_handoffs.enabled = True
    bridge.tasks.preflight = None
    bridge.tasks.native.timeout = 0.15
    for name in ("codex", "codex_verify"):
        executable = bridge.config.agents[name].executable
        # Both aliases use this one fixture executable; inject the delay once.
        if name == "codex":
            from pathlib import Path

            path = Path(executable)
            text = path.read_text()
            text = text.replace("import json,sys", "import json,sys,time", 1)
            emitter = "]:print(json.dumps(event),flush=True)"
            assert text.count(emitter) == 1
            text = text.replace(
                emitter,
                "]:\n print(json.dumps(event),flush=True)\n"
                " if event['type']=='turn.started':time.sleep(.4)",
                1,
            )
            path.write_text(text)
    await s["start"]()
    await until(lambda: bridge.autonext.inspect()["state"] in {"complete", "stopped"})
    assert bridge.autonext.inspect()["state"] == "complete", bridge.autonext.inspect()
    source = bridge.store.db.execute("SELECT work_id FROM autonext_items").fetchone()[0]
    verify = bridge.store.db.execute("SELECT verify_work_id FROM autonext_coordinator").fetchone()[
        0
    ]
    intervals = []
    for work_id in (source, verify):
        work = bridge.teams.work_get("codex", "auto-team", work_id)
        core = bridge.store.get(work["core_task_id"])
        assert core["state"] == State.COMPLETED
        assert core["finished"] - core["started"] > bridge.tasks.native.timeout
        assert bridge.tasks.native.native(core) is False
        assert core["id"] not in bridge.tasks.native.active
        assert work["evidence"]["session_scope"] == "separate_managed_session"
        intervals.append(
            {
                "task_id": core["id"],
                "started": core["started"],
                "finished": core["finished"],
                "elapsed": core["finished"] - core["started"],
                "native_timeout": bridge.tasks.native.timeout,
            }
        )
    (tmp_path / "managed-turn-intervals.json").write_text(json.dumps(intervals, indent=2) + "\n")
    assert bridge.config.visible_handoffs.enabled is True


async def test_unsealed_nonteam_agent_remains_native(scenario, tmp_path, monkeypatch):  # noqa: F811
    s = scenario
    configure(s, tmp_path, monkeypatch)
    bridge = s["bridge"]
    bridge.config.visible_handoffs.enabled = True
    bridge.tasks.preflight = None
    bridge.tasks.native.timeout = 0.1

    async def executor(task, running, progress):
        await running({"synthetic_direct_started": True})
        await asyncio.sleep(0.5)
        return {"success": True}

    bridge.tasks.executor = executor
    await bridge.tasks.start()
    try:
        value = request(
            "agent.execute",
            {"agent": "codex", "prompt": "synthetic direct", "cwd": str(s["root"]), "timeout": 1},
            task_id="direct-native-stays-native",
        )
        task = bridge.tasks.enqueue("codex", value, bridge.security.grant("codex", value))
        assert bridge.tasks.native.native(task) is True
        await until(lambda: bridge.store.get(task["id"])["state"] in {State.FAILED, State.UNKNOWN})
        assert bridge.store.get(task["id"])["error"]["code"] == "native_admission_timeout"
    finally:
        await bridge.tasks.stop()


@pytest.mark.parametrize("sealed", [False, True])
async def test_store_managed_lane_requires_exact_team_seal(scenario, tmp_path, monkeypatch, sealed):  # noqa: F811
    s = scenario
    configure(s, tmp_path, monkeypatch)
    bridge = s["bridge"]
    bridge.config.visible_handoffs.enabled = True
    await bridge.autonext.tick()
    work_id = bridge.store.db.execute("SELECT work_id FROM autonext_items").fetchone()[0]
    work = bridge.teams.claim(work_id)
    value = TaskRequest(
        task_id=work["core_task_id"],
        idempotency_key="lane-fixture",
        operation="agent.execute",
        arguments={"agent": "codex", "prompt": "fixture", "cwd": str(s["root"]), "timeout": 1},
    )
    bridge.teams.seal_request(work_id, value)
    task = bridge.tasks.enqueue("codex", value, bridge.security.grant("codex", value))
    if not sealed:
        bridge.store.db.execute(
            "UPDATE team_work SET core_request_hash='wrong' WHERE id=?", (work_id,)
        )
    assert bridge.tasks.native.native(task) is (not sealed)
    claimed = bridge.store.claim("fixture", 20, native_visible=True, managed_workers=("codex",))
    assert (claimed is not None) is sealed


def test_store_without_team_schema_preserves_native_exclusion(tmp_path):
    store = Store(tmp_path / "standalone.sqlite3")
    try:
        assert store.claim("fixture", 20, native_visible=True, managed_workers=("codex",)) is None
    finally:
        store.close()
