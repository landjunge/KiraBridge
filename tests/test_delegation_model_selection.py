"""Per-assignment preferences through the real sealed dispatcher, without providers."""

import json
from types import SimpleNamespace

import pytest
from test_autonext import scenario  # noqa: F401
from test_capability_routing import NOW, setup  # noqa: F401
from test_mcp import http_bridge  # noqa: F401
from test_native_capability_routing import complete, routed, starts  # noqa: F401

from kirabridge.autonext.manager import text_sha
from kirabridge.bridge_core.models import AgentInput
from kirabridge.capability_routing.launcher import launch
from kirabridge.capability_routing.router import RoutingError, WorkerRouting, select
from kirabridge.capability_routing.source import BEGIN, END, ThreadDeskSource
from kirabridge.team_manager.models import TeamWorkCreate


def card_preferences(r, **preferences):
    pin = r.cfg.autonext.cards[0]
    path = r.s["desk"] / "whiteboard" / "board" / (pin.entry_id + ".json")
    entry = json.loads(path.read_text())
    entry["content"] = json.dumps({**r.card, **preferences})
    path.write_text(json.dumps(entry))
    pin.content_sha256 = text_sha(entry["content"])


def add_low_effort(r):
    from kirabridge.capability_routing.source import BEGIN, END

    matrix = json.loads(r.document["notes"].split(BEGIN)[1].split(END)[0])
    matrix["clis"][0]["models"][0]["efforts"] += ["low", "medium"]
    matrix["clis"][0]["models"][0]["fit"]["routine"] = 5
    r.document["notes"] = BEGIN + json.dumps(matrix) + END


def test_optional_preferences_preserve_old_request_serialization():
    base = dict(agent="codex", cwd="/tmp", prompt="fixture")
    old = AgentInput(**base).model_dump()
    assert "model" not in old and "effort" not in old
    assert AgentInput(**base, model=None, effort=None).model_dump() == old
    work = dict(team_id="team", assignee="codex", title="fixture", body="body", idempotency_key="k")
    assert TeamWorkCreate(**work).model_dump() == {**work, "parent_id": None}
    assert WorkerRouting(workload="routine").effort is None


def test_explicit_choice_beats_heuristics_but_not_declared_floor(setup):  # noqa: F811
    matrix, runtime, task = setup
    matrix.clis[0].models[0].fit["review"] = 0
    chosen = task.model_copy(
        update={"workload": "review", "explicit_model": "small", "explicit_effort": "low"}
    )
    result = select(matrix, runtime, chosen, now=NOW)
    assert (result["model"], result["effort"]) == ("small", "low")
    with pytest.raises(RoutingError, match="minimum"):
        select(matrix, runtime, chosen.model_copy(update={"min_effort": "high"}), now=NOW)
    with pytest.raises(RoutingError):
        select(
            matrix,
            runtime,
            chosen.model_copy(update={"independent_of_provider": "openai"}),
            now=NOW,
        )


async def test_native_automatic_choice_does_not_inherit_agent_default(routed):  # noqa: F811
    r = routed
    add_low_effort(r)
    r.cfg.agents["codex"].model = "legacy-unavailable-model"
    r.cfg.team.workers["codex"].routing = WorkerRouting(workload="routine")
    status = await complete(r)
    assert status["state"] == "complete", status
    assert 'model_reasoning_effort="low"' in starts(r)[0]
    assert r.profiles[0]["explicit_model"] is None
    assert r.profiles[0]["explicit_effort"] is None
    assert r.cfg.agents["codex"].model == "legacy-unavailable-model"
    core = r.b.store.db.execute("SELECT id FROM tasks WHERE principal='codex'").fetchone()
    evidence = r.b.store.get(core[0])["evidence"]
    assert evidence["routing_start_observation"]["spawn_observed"] is True
    assert evidence["routing_start_observation"]["confirmed_parameters"] == {
        "cli": "codex",
        "model": "fixture-codex",
        "effort": "low",
    }
    assert evidence["routing_decision"]["effective_effort"] == "unverified"


async def test_native_card_choice_is_sealed_and_overrides_worker_defaults(routed):  # noqa: F811
    r = routed
    add_low_effort(r)
    r.cfg.team.workers["codex"].routing = WorkerRouting(
        workload="review", model="worker-unavailable", effort="max"
    )
    card_preferences(r, model="fixture-codex", effort="low")
    assert (await complete(r))["state"] == "complete"
    argv = starts(r)[0]
    assert argv[argv.index("--model") + 1] == "fixture-codex"
    assert 'model_reasoning_effort="low"' in argv
    core = r.b.store.db.execute("SELECT args FROM tasks WHERE principal='codex'").fetchone()
    assert json.loads(core[0])["model"] == "fixture-codex"
    assert json.loads(core[0])["effort"] == "low"
    work = r.b.store.db.execute(
        "SELECT model,effort FROM team_work WHERE assignee='codex' AND core_task_id IS NOT NULL"
    ).fetchone()
    assert tuple(work) == ("fixture-codex", "low")
    assert r.cfg.team.workers["codex"].routing.effort == "max"


@pytest.mark.parametrize(
    "preferences",
    [{"model": "unknown"}, {"effort": "unsupported"}, {"effort": "ultra"}, {"effort": "low"}],
)
async def test_unsupported_or_below_declared_minimum_never_starts(routed, preferences):  # noqa: F811
    r = routed
    r.cfg.team.workers["codex"].routing.min_effort = "high"
    card_preferences(r, **preferences)
    assert (await complete(r))["state"] == "stopped"
    assert not starts(r)


def test_empty_model_is_invalid_instead_of_automatic():
    from pydantic import ValidationError

    from kirabridge.capability_routing.router import Task

    with pytest.raises(ValidationError):
        AgentInput(agent="codex", cwd="/tmp", prompt="x", model="")
    with pytest.raises(ValidationError):
        Task(
            task_id="x",
            workload="routine",
            prompt="x",
            cwd="/tmp",
            ownership_ref="x",
            explicit_model="",
        )


@pytest.mark.parametrize("spawned", [False, True])
def test_launcher_selection_and_actual_spawn_are_distinct(setup, monkeypatch, spawned):  # noqa: F811
    import kirabridge.capability_routing.router as router

    matrix, runtime, task = setup
    # Fixture timestamps stay deterministic; this does not refresh a live grant.
    original = router.select
    monkeypatch.setattr(
        "kirabridge.capability_routing.hook.select", lambda m, r, t: original(m, r, t, now=NOW)
    )
    source = ThreadDeskSource(
        lambda key: {
            "id": key,
            "revision": 5,
            "notes": BEGIN + json.dumps(matrix.model_dump()) + END,
        },
        "matrix",
    )
    child = SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
    if spawned:
        child.process_evidence = {"spawn_observed": True, "pid": 123, "spawned_at": 1.0}
    result = launch(source, runtime, task, execute=True, probe=False, runner=lambda *a, **k: child)
    assert result["selected_parameters"] == {"cli": "codex", "model": "small", "effort": "medium"}
    assert result["start_observation"]["spawn_observed"] is spawned
    assert result["start_observation"]["confirmed_parameters"] == (
        result["selected_parameters"] if spawned else None
    )
    assert result["effective_effort"] == "unverified"


def test_cli_arguments_cannot_disagree_with_selection():
    from kirabridge.capability_routing.launcher import _parameters

    decision = {"cli": "grok", "model": "fixture", "effort": "high"}
    with pytest.raises(RoutingError, match="differ"):
        _parameters(["grok", "--model", "wrong", "--effort", "high"], decision)
    with pytest.raises(RoutingError, match="unambiguous"):
        _parameters(
            ["grok", "--model", "fixture", "--model", "wrong", "--effort", "high"], decision
        )


async def test_assignment_selection_tampering_after_seal_never_starts(routed):  # noqa: F811
    r = routed
    card_preferences(r, model="fixture-codex", effort="high")
    adapter = r.b.agents.adapters["codex"]
    original = adapter.execute

    async def changed(task, args, *rest, **kwargs):
        r.b.store.db.execute(
            "UPDATE team_work SET effort='max' WHERE core_task_id=?", (task["id"],)
        )
        return await original(task, args, *rest, **kwargs)

    adapter.execute = changed
    assert (await complete(r))["state"] == "stopped"
    assert not starts(r)
