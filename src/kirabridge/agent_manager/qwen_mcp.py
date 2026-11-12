"""A private, expiring task restriction for the existing KiraBridge connect path."""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from kirabridge.agent_manager.full_access import bridge_server
from kirabridge.bridge_core.models import BridgeError, digest
from kirabridge.mcp_gateway.agent_policy import AgentTaskPolicy
from kirabridge.operations import OPERATIONS, READ_OPERATIONS, capability_for
from kirabridge.private_files import write_private


@contextmanager
def task_server(bridge_config, task, args, timeout, *, team_scope=None):
    owner = task["principal"]
    policy = bridge_config.principals.get(owner) if bridge_config else None
    if (
        policy is None
        or not {"bridge.health", "task.read"} <= set(policy.capabilities)
        or not isinstance(task.get("args"), dict)
        or task["args"].get("cwd") != args.cwd
        or task["args"].get("agent") != args.agent
    ):
        raise BridgeError(
            "agent_tools_denied", "MCP metadata requires the existing task owner grant"
        )
    if team_scope is not None and "team.read" not in policy.capabilities:
        raise BridgeError("agent_tools_denied", "Qwen resume needs the existing team read grant")
    binding = AgentTaskPolicy(
        team_scope=team_scope,
        owner=owner,
        task_id=task["id"],
        agent=args.agent,
        cwd=args.cwd,
        arguments_sha256=digest(task["args"]),
        expires_at=time.time() + timeout,
        grants=args.mcp_grants,
        operations=args.mcp_operations,
        read_roots=args.mcp_read_roots,
        tools=bridge_config.agents[args.agent].qwen_mcp_tools,
        capabilities=policy.capabilities,
        read_only=not args.local_tools,
        full_access=bridge_config.agents[args.agent].sandbox_mode == "danger-full-access",
        max_calls=bridge_config.agents[args.agent].qwen_max_tool_calls,
    )
    profile = bridge_config.agents[args.agent]
    if any(g.tool not in profile.qwen_mcp_tools for g in args.mcp_grants) or not set(
        args.mcp_operations
    ) <= set(profile.qwen_mcp_operations):
        raise BridgeError("agent_tools_denied", "Task MCP grants exceed the operator profile")
    if any(
        op not in OPERATIONS
        or capability_for(op) not in policy.capabilities
        or (not args.local_tools and op not in READ_OPERATIONS)
        for op in args.mcp_operations
    ):
        raise BridgeError(
            "agent_tools_denied", "Task operations exceed the existing principal grant"
        )
    if binding.full_access and (not args.local_tools or policy.permission_level != "full"):
        raise BridgeError(
            "agent_tools_denied", "Full MCP scope requires existing explicit full rights"
        )
    operator_roots = [Path(r).resolve() for r in profile.qwen_mcp_read_roots]
    principal_roots = [Path(r).resolve() for r in [*policy.roots, *policy.read_roots]]
    for root in args.mcp_read_roots:
        path = Path(root)
        if (
            not path.is_absolute()
            or not any(path.resolve().is_relative_to(r) for r in operator_roots)
            or not any(path.resolve().is_relative_to(r) for r in principal_roots)
        ):
            raise BridgeError("agent_tools_denied", "Task source root exceeds the existing profile")
    server = bridge_server(bridge_config._source_path, owner)
    with TemporaryDirectory(prefix="kirabridge-qwen-mcp-") as temporary:
        path = Path(temporary) / "task-policy.json"
        encoded = binding.model_dump_json()
        if len(encoded) > 65536:
            raise BridgeError("agent_tools_denied", "MCP task scope exceeds the policy file budget")
        write_private(path, encoded)
        server["args"] += ["--agent-task-policy", str(path)]
        yield {
            "name": "kirabridge",
            **server,
            "env": [{"name": "PYTHONPATH", "value": str(Path(__file__).resolve().parents[2])}],
        }
