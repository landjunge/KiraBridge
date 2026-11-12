"""Validate the documented operator recipe without provider or live-config effects."""

import re
import tomllib
from pathlib import Path

from kirabridge.agent_manager import AgentManager
from kirabridge.bridge_core.config import AgentConfig, Config, TeamWorkerConfig
from kirabridge.terminal_manager import TerminalManager


def documented_recipe():
    source = Path(__file__).resolve().parents[1] / "docs/providers/QWEN.md"
    blocks = [tomllib.loads(b) for b in re.findall(r"```toml\n(.*?)```", source.read_text(), re.S)]
    profile = next(b["agents"]["qwen"] for b in blocks if "agents" in b)
    worker = next(b["team"]["workers"]["qwen_worker"] for b in blocks if "team" in b)
    return AgentConfig.model_validate(profile), TeamWorkerConfig.model_validate(worker)


def test_documented_recipe_validates_current_readonly_worker_scope():
    profile, worker = documented_recipe()
    assert (profile.kind, profile.model, profile.qwen_auth_type, profile.qwen_reasoning_effort) == (
        "qwen_acp",
        "qwen4.0-max-preview",
        "qwen-subscription",
        "medium",
    )
    assert profile.bridge_tools and not profile.allow_local_tools
    assert profile.sandbox_mode == "read-only" and not worker.local_tools
    assert worker.agent == "qwen" and worker.execution_scope == "separate_managed_session"
    assert worker.timeout <= profile.qwen_max_timeout
    assert set(worker.mcp_operations) <= set(profile.qwen_mcp_operations)
    assert set(worker.mcp_read_roots) <= set(profile.qwen_mcp_read_roots)
    assert len(worker.mcp_grants) == 1
    grant = worker.mcp_grants[0]
    assert grant.tool in profile.qwen_mcp_tools and grant.calls == 1
    assert grant.arguments == {"id": "EXACT_AUTHORIZED_THREAD_ID", "max_chars": 100000, "offset": 0}


def test_inventory_needs_owner_allowlist_and_does_not_prove_live_readiness():
    profile, _ = documented_recipe()
    manager = AgentManager(Config(agents={"qwen": profile}), TerminalManager())
    assert manager.inventory([]) == {"agents": []}
    result = manager.inventory(["qwen"])["agents"]
    assert len(result) == 1
    entry = result[0]
    assert entry["id"] == "qwen" and entry["adapter_available"]
    assert entry["execution_mode"] == "task_scoped_mcp"
    assert not entry["supports_local_tools"]
    assert entry["supports_owned_resume"] and entry["resume_scope"] == "sealed_idle_team_session"
    assert not entry["executable_present"] and not entry["executable_runnable"]
    assert {entry[key] for key in ("daemon_status", "session_status", "task_status")} == {"unknown"}
