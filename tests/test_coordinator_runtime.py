"""Runtime profile and explicit route admission, without touching installed profiles."""

import importlib.util
import sys
from pathlib import Path

import pytest

from kirabridge.bridge_core.config import TeamWorkerConfig

spec = importlib.util.spec_from_file_location(
    "loop_runtime", Path(__file__).parents[1] / "scripts/bigplan_loop.py"
)
runtime = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runtime
spec.loader.exec_module(runtime)


def profile(tmp_path):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".git").write_text("isolated fixture")
    return dict(
        cwd=str(worktree),
        state_dir=str(tmp_path / "state"),
        search_path=["/usr/bin", "/bin"],
        codex="/bin/false",
        grok="/bin/false",
        workspace=str(tmp_path / "desk"),
        threaddesk_source=str(tmp_path / "source"),
    )


def test_dedicated_worker_route_is_explicit_and_global_visible_route_stays_on(tmp_path):
    cfg = runtime.configuration(profile(tmp_path))
    assert cfg.visible_handoffs.enabled is True
    assert not cfg.visible_handoffs.bindings
    assert all(
        cfg.team.workers[n].execution_scope == "separate_managed_session" for n in ("codex", "grok")
    )
    assert cfg.agents["grok"].sandbox_mode == "read-only"
    assert cfg.agents["grok"].kind == "grok_structured"
    assert not cfg.agents["grok"].allow_local_tools
    assert (
        TeamWorkerConfig(agent="codex", cwd=str(tmp_path)).execution_scope
        == "existing_visible_terminal"
    )
    assert cfg.state_path == tmp_path / "state"
    assert not cfg.autonext.enabled


def test_runtime_refuses_productive_state(tmp_path):
    value = profile(tmp_path)
    value["state_dir"] = str(Path.home() / ".local/share/kirabridge")
    with pytest.raises(ValueError, match="dedicated"):
        runtime.configuration(value)


def test_no_subscription_quota_probe_with_api_billing_env(monkeypatch):
    import asyncio

    monkeypatch.setenv("OPENAI_API_KEY", "fixture-never-exposed")
    with pytest.raises(RuntimeError, match="API-key billing"):
        asyncio.run(runtime.quota("/bin/false"))


def test_profile_does_not_treat_string_false_as_permission(tmp_path):
    import json

    value = profile(tmp_path)
    value.update(
        report_cli="/bin/false", instance="fixture-loop", board_id="board", enabled="false"
    )
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        runtime.load_profile(path)
