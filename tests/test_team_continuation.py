"""Pinned READY work and idempotent selection through the existing TeamWork store."""

import asyncio
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

from test_team_coordinator_roles import record, setup_team
from test_team_manager import core
from test_team_manager import domain as imported_domain

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import NativeCodexBinding, TeamContinuationConfig
from kirabridge.bridge_core.models import canonical, digest
from kirabridge.team_manager import continuation

domain = imported_domain
TEAM = "auto-coordinator"
WORKSPACE = "ws-approved"


class Owner:
    def __init__(self):
        self.boards = {"product-a": [], "product-b": []}
        self.revision = 9
        self.invalid_digest = False

    def entry(self, board, name, **changes):
        body = canonical(
            {
                "schema": "kirabridge-team-ready.v1",
                "task_id": name,
                "state": "READY",
                "title": f"Task {name}",
                "body": "Read and report the isolated source fixture",
                "assignee": "grok",
                **changes,
            }
        )
        row = {
            "id": f"entry-{name}",
            "thread_id": board,
            "entry_type": "task",
            "metadata": {},
            "content": body,
        }
        self.boards[board].append(row)
        return row

    async def read(self, _bridge, principal, name, request):
        assert request["workspace_id"] == WORKSPACE
        assert principal == "codex"
        args = request["arguments"]
        board = args["id"]
        rows = self.boards[board]
        if name == "td_whiteboard__get":
            result = {
                "id": board,
                "thread_id": board,
                "revision": self.revision,
                "entry_count": len(rows),
                "state": "open",
            }
            command = "whiteboard.get"
        else:
            assert name == "td_whiteboard__list"
            command = "whiteboard.list"
            if "entry_id" in args:
                matching = [row for row in rows if row["id"] == args["entry_id"]]
                result = {"total": len(matching), "items": matching, "next_offset": None}
            else:
                assert args["metadata_only"] is True
                start = args["offset"]
                stop = start + args["limit"]
                result = {
                    "total": len(rows),
                    "items": [
                        {key: value for key, value in row.items() if key != "content"}
                        for row in rows[start:stop]
                    ],
                    "next_offset": stop if stop < len(rows) else None,
                }
        return {
            "success": True,
            "value": {
                "schema": "threaddesk.command-result.v1",
                "result": result,
                "next_offset": None,
                "result_digest": "invalid" if self.invalid_digest else digest(result),
                "workspace_id": WORKSPACE,
                "command": command,
            },
        }


def pinned(domain, rows):
    worker = domain.config.team.workers["grok"]
    worker.cwd = str(Path(worker.cwd).resolve())
    domain.config.team.coordinator_resume = True
    domain.config.team.continuation = TeamContinuationConfig(
        team_id=TEAM,
        workspace_id=WORKSPACE,
        board_id="product-a",
        authority_ref="fixture mandate",
        sources=[
            {
                "task_id": row["id"].removeprefix("entry-"),
                "entry_id": row["id"],
                "board_id": row["thread_id"],
                "assignee": "grok",
                "cwd": worker.cwd,
                "content_sha256": hashlib.sha256(row["content"].encode()).hexdigest(),
            }
            for row in rows
        ],
    )


async def select(domain):
    domain.continuation.next_scan = 0
    return await domain.continuation.select()


def finish(domain, work_id, reply, session):
    claimed = domain.claim(work_id)
    assert claimed
    observed = core(
        domain,
        claimed,
        result={"success": True, "text": reply},
        evidence={"adapter": "codex", "session_id": session},
    )
    domain.bind_task(work_id, observed)
    domain.finish(work_id, reply, {"model_turn_completed": True})


async def test_two_boards_advance_only_after_original_processed_receipt(domain, monkeypatch):
    setup_team(domain, coordinator="codex")
    record(domain, "codex")
    owner = Owner()
    a, b = owner.entry("product-a", "first"), owner.entry("product-b", "second")
    pinned(domain, [a, b])
    monkeypatch.setattr(continuation, "read_thread_desk", owner.read)
    outcomes = await asyncio.gather(select(domain), select(domain))
    (first,) = [item for item in outcomes if item]
    assert first["title"] == "Task first"
    assert await select(domain) is None
    finish(domain, first["id"], "First work complete", "grok-session")
    assert await select(domain) is None
    assert domain.resume_coordinators() == 1
    assert await select(domain) is None
    review = domain.store.db.execute(
        "SELECT resume_work_id FROM team_coordinator_resumes WHERE work_id=?", (first["id"],)
    ).fetchone()["resume_work_id"]
    prompt = domain.continuation.review_prompt(domain._work(review))
    assert first["id"] in prompt and "First work complete" in prompt
    reopened = Bridge(domain.config)
    try:
        assert await select(reopened.teams) is None
        finish(
            reopened.teams,
            review,
            continuation.TeamContinuation.marker(first["id"]),
            "codex-session",
        )
        owner.revision += 1
        second = await select(reopened.teams)
        assert second["title"] == "Task second"
        assert await select(reopened.teams) is None
        originals = reopened.teams.store.db.execute(
            "SELECT DISTINCT object_id FROM team_operations WHERE operation='continuation'"
        ).fetchall()
        assert {i[0] for i in originals} == {first["id"], second["id"]}
    finally:
        reopened.store.close()


async def test_owner_revision_and_historic_correction_do_not_authorize_original(
    domain, monkeypatch
):
    setup_team(domain, coordinator="codex")
    record(domain, "codex")
    owner = Owner()
    original = owner.entry("product-a", "old-card")
    pinned(domain, [original])
    monkeypatch.setattr(continuation, "read_thread_desk", owner.read)
    owner.boards["product-a"].append(
        {
            "id": "owner-correction",
            "thread_id": "product-a",
            "entry_type": "note",
            "content": "The original task is stale",
            "metadata": {"whiteboard_edit": {"entry_id": original["id"]}},
        },
    )
    owner.revision += 1
    assert await select(domain) is None
    assert (
        domain.store.db.execute(
            "SELECT count(*) FROM team_operations WHERE operation='continuation'"
        ).fetchone()[0]
        == 0
    )


async def test_unverified_receipt_and_old_unknown_never_admit_replay(domain, monkeypatch):
    setup_team(domain, coordinator="codex")
    record(domain, "codex")
    owner = Owner()
    original = owner.entry("product-a", "unknown")
    pinned(domain, [original])
    monkeypatch.setattr(continuation, "read_thread_desk", owner.read)
    owner.invalid_digest = True
    assert await select(domain) is None
    owner.invalid_digest = False
    selected = await select(domain)
    domain.fail(selected["id"], "unknown", "peer_unknown", {})
    restarted = Bridge(domain.config)
    try:
        owner.revision += 1
        assert await select(restarted.teams) is None
        assert restarted.teams._work(selected["id"])["state"] == "unknown"
    finally:
        restarted.store.close()


async def test_bootstrap_uses_authenticated_read_without_starting_a_coordinator_turn(
    domain, monkeypatch, tmp_path
):
    setup_team(domain, coordinator="codex")
    binding = NativeCodexBinding(
        thread_id="11111111-1111-7111-8111-111111111111",
        session_id="11111111-1111-7111-8111-111111111111",
        source="vscode",
        codex_home=str(tmp_path),
        host_executable="/opt/codex/bin/codex",
    )
    domain.config.visible_handoffs.native_codex = binding
    domain.config.team.workers["codex"].execution_scope = "existing_native_codex_root"
    domain.config.principals["codex"].capabilities += ["session.inspect"]
    owner = Owner()
    pinned(domain, [owner.entry("product-a", "native")])
    monkeypatch.setattr(continuation, "read_thread_desk", owner.read)

    class ReadOnlyHost:
        eligible = False

        @asynccontextmanager
        async def connection(self, expected):
            assert expected == binding
            yield "authenticated-host", None

        async def read_bound_thread(self, transport, expected):
            assert transport == "authenticated-host" and expected == binding
            return {"canAcceptDirectInput": self.eligible, "status": {"type": "active"}}

    monkeypatch.setattr(continuation, "CodexHost", ReadOnlyHost)
    assert domain.coordinator_status("local", TEAM)["session"] is None
    assert await select(domain) is None
    assert domain.coordinator_status("local", TEAM)["session"] is None
    ReadOnlyHost.eligible = True
    work = await select(domain)
    assert work["assigned_by"] == "codex" and work["assignee"] == "grok"
    assert domain.coordinator_status("local", TEAM)["session"]["session_id"] == binding.session_id
    assert work["core_task_id"] is None
