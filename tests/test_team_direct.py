"""Immediate team admission and restart safety, without native input or provider calls."""

import asyncio

import pytest
from conftest import DomainOnlyTeamPort
from test_mcp import http_bridge  # noqa: F401
from test_team_dispatcher import configure_team

from kirabridge.bridge_core.models import BridgeError
from kirabridge.team_manager.models import TeamCreate, TeamWorkCreate


@pytest.fixture
def team(http_bridge, config, tmp_path, monkeypatch):  # noqa: F811
    bridge, _ = http_bridge
    configure_team(bridge, config, tmp_path, monkeypatch)
    bridge.teams.create(
        "local",
        TeamCreate(
            team_id="direct-team",
            name="Direct",
            coordinator="local",
            members={"local": "coordinator", "codex": "worker", "grok": "worker"},
            idempotency_key="direct-team",
        ),
    )
    return bridge


def request(key="one", assignee="codex"):
    return TeamWorkCreate(
        team_id="direct-team",
        assignee=assignee,
        title="Direct work",
        body="Original retained content",
        idempotency_key=key,
    )


async def test_team_offline_rejects_before_saving_work(team):
    with pytest.raises(BridgeError) as refused:
        team.teams.delegate("local", request())
    assert refused.value.code == "team_receiver_unavailable"
    assert team.store.db.execute("SELECT count(*) FROM team_work").fetchone()[0] == 0


async def test_team_busy_and_idempotency_never_create_a_backlog(team, monkeypatch):
    release, entered = asyncio.Event(), asyncio.Event()
    calls = []

    async def held(work, *, existing):
        calls.append(work["id"])
        entered.set()
        await release.wait()
        team.teams.fail(work["id"], "failed", "synthetic_finished", {"automatic_retry": False})

    monkeypatch.setattr(team.team_dispatcher, "_run", held)
    await team.team_dispatcher.start()
    original = team.teams.delegate("local", request())
    await asyncio.wait_for(entered.wait(), 2)
    assert team.teams.delegate("local", request())["id"] == original["id"]
    with pytest.raises(BridgeError) as busy:
        team.teams.delegate("local", request("second"))
    assert busy.value.code == "execution_busy"
    assert team.store.db.execute("SELECT count(*) FROM team_work").fetchone()[0] == 1
    assert not team.store.db.execute("SELECT 1 FROM team_work WHERE state='queued'").fetchone()
    release.set()
    await asyncio.gather(*(task for _, task in team.team_dispatcher.active.values()))
    assert calls == [original["id"]]
    assert team.teams.delegate("local", request())["state"] == "failed"


async def test_team_shutdown_and_restart_preserve_unknown_without_reexecution(team, monkeypatch):
    entered = asyncio.Event()
    calls = []

    async def held(work, *, existing):
        calls.append(work["id"])
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(team.team_dispatcher, "_run", held)
    await team.team_dispatcher.start()
    work = team.teams.delegate("local", request())
    await asyncio.wait_for(entered.wait(), 2)
    await team.team_dispatcher.stop()
    await team.team_dispatcher.start()
    assert team.teams.work_get("local", "direct-team", work["id"])["state"] == "unknown"
    assert not team.team_dispatcher.active and calls == [work["id"]]


async def test_team_legacy_unstarted_work_is_archived_and_content_preserved(team):
    receiver = team.teams.direct_delivery
    team.teams.direct_delivery = DomainOnlyTeamPort()
    work = team.teams.delegate("local", request())
    team.teams.direct_delivery = receiver
    team.store.db.execute("UPDATE team_work SET state='queued' WHERE id=?", (work["id"],))
    await receiver.start()
    result = team.teams.work_get("local", "direct-team", work["id"])
    assert result["state"] == "cancelled" and result["body"] == work["body"]
    assert result["error"] == "execution_queue_removed" and not receiver.active


async def test_separate_console_forwards_exact_team_work_to_authenticated_daemon(team, monkeypatch):
    from kirabridge.bridge_core.bridge import Bridge
    from kirabridge.team_manager.local import delegate

    calls = []

    async def finish(work, *, existing):
        calls.append(work["id"])
        team.teams.fail(work["id"], "failed", "synthetic_done", {})

    monkeypatch.setattr(team.team_dispatcher, "_run", finish)
    await team.team_dispatcher.start()
    console = Bridge(team.config)
    try:
        first = await delegate(console.teams, "local", request())
        repeated = await delegate(console.teams, "local", request())
        assert first["id"] == repeated["id"] and calls == [first["id"]]
        assert team.store.db.execute("SELECT count(*) FROM team_work").fetchone()[0] == 1
    finally:
        console.store.close()
