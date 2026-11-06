"""Restart the actual supervisor process with a persisted, sealed Core request."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from test_agents import fake_cli
from test_autonext import until
from test_autonext_coordinator import CODEX
from test_coordinator_runtime import runtime

from kirabridge.autonext.manager import text_sha
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import TaskRequest
from kirabridge.whiteboard_read import append_whiteboard


@pytest.mark.parametrize("enabled", [False, True])
async def test_actual_service_restores_queued_core_before_workers_start(
    tmp_path,
    monkeypatch,
    enabled,
):
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "XAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    root = tmp_path / "worktree"
    root.mkdir()
    (root / ".git").write_text("isolated service fixture")
    desk = tmp_path / "desk"
    (desk / "threads").mkdir(parents=True)
    (desk / "whiteboard").mkdir()
    (desk / "threads/board.json").write_text('{"id":"board"}')
    cli = fake_cli(tmp_path, CODEX)
    check = {"argv": [sys.executable, "-c", "pass"], "timeout_seconds": 2}
    card = {
        "autonext": 1,
        "task_id": "persisted.core",
        "state": "READY",
        "product": "KiraBridge",
        "cwd": str(root),
        "sandbox": "read-only",
        "title": "Persisted service work",
        "instruction": "Fixture restart",
        "acceptance": {"kind": "coordinator_checks", "checks": [check]},
    }
    content = json.dumps(card)
    entry = append_whiteboard(
        str(desk), "board", actor="fixture", actor_type="codex", entry_type="task", content=content
    )
    profile = dict(
        cwd=str(root),
        state_dir=str(tmp_path / "state"),
        search_path=["/usr/bin", "/bin"],
        codex=cli,
        grok=cli,
        workspace=str(desk),
        threaddesk_source=str(root),
        report_cli="/usr/bin/true",
        instance="fixture-service",
        board_id="board",
        sandbox="read-only",
        enabled=True,
        cards=[],
        continuation={
            "authority_ref": "explicit service test mandate",
            "allowed_cwds": [str(root)],
            "products": ["KiraBridge"],
            "checks": [check],
            "sources": [
                {
                    "task_id": card["task_id"],
                    "entry_id": entry["id"],
                    "content_sha256": text_sha(content),
                }
            ],
        },
    )
    profile_path = tmp_path / "profile.json"
    runtime.save(profile_path, profile)
    cfg = runtime.configuration(profile)
    runtime.save(
        cfg.state_path / "coordinator-profile.json",
        {
            "instance": profile["instance"],
            "cwd": str(root),
            "workspace": str(desk),
        },
    )
    b = Bridge(cfg)
    from kirabridge.autonext.continuation import validate_source

    b.autonext.continuation_guard = lambda item: validate_source(b, profile, item)
    team, anchor = runtime.seed(b)
    monkeypatch.setattr(
        runtime,
        "quota",
        AsyncMock(
            return_value={
                "observed_at": time.time(),
                "source": "isolated fixture quota",
            }
        ),
    )
    await runtime.advance(b, profile, team, anchor, None)
    await until(lambda: b.autonext.inspect()["state"] == "waiting")
    await b.autonext.stop()
    work_id = b.store.db.execute("SELECT work_id FROM autonext_items").fetchone()[0]
    work = b.teams.claim(work_id)
    request = TaskRequest(
        task_id=work["core_task_id"],
        idempotency_key=work["core_task_id"],
        operation="agent.execute",
        arguments={
            "agent": "codex",
            "prompt": b.autonext.prompt_for(work),
            "cwd": str(root),
            "timeout": 120,
            "local_tools": False,
        },
    )
    b.teams.seal_request(work_id, request)
    b.tasks.enqueue("codex", request, "")
    original_core = work["core_task_id"]
    b.store.close()
    profile["enabled"] = enabled
    runtime.save(profile_path, profile)
    log = tmp_path / "service.log"
    with log.open("wb") as output:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(Path(runtime.__file__)),
            "--profile",
            str(profile_path),
            "serve",
            stdout=output,
            stderr=asyncio.subprocess.STDOUT,
            env=dict(os.environ),
        )
        try:
            status_path = cfg.state_path / "status.json"
            await until(lambda: status_path.exists() or process.returncode is not None, timeout=20)
            assert process.returncode is None, log.read_text()
            if enabled:
                await until(
                    lambda: (
                        json.loads(status_path.read_text())["autonext"]["state"]
                        in {"complete", "stopped"}
                    ),
                    timeout=25,
                )
                assert json.loads(status_path.read_text())["autonext"]["state"] == "complete", (
                    log.read_text() + status_path.read_text()
                )
            else:
                assert not json.loads(status_path.read_text())["autonext"]["enabled"]
            # Open a separate observer without worker startup; no second service.
            observer = Bridge(runtime.configuration(profile))
            try:
                original = observer.store.get(original_core, "codex")
                assert original["attempt"] == 1
                assert original["state"] == ("completed" if enabled else "queued")
                assert observer.store.db.execute(
                    "SELECT count(*) FROM tasks WHERE operation='agent.execute'"
                ).fetchone()[0] == (2 if enabled else 1)
            finally:
                observer.store.close()
        finally:
            if process.returncode is None:
                process.terminate()
            await asyncio.wait_for(process.wait(), 20)
    assert process.returncode == 0, log.read_text()
