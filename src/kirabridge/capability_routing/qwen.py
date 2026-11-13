"""Scoped Qwen gate inside an existing sealed Core/Team adapter invocation.

Compose this inside the owner's Observed adapter at owned Core startup. It adds
no dispatcher, state store, session, cleanup or live-process registration API.
"""

from __future__ import annotations

import asyncio
import math
import time
from pathlib import Path

from kirabridge.bridge_core.models import AgentInput, BridgeError

from .router import RoutingError, Task, fingerprint


class ScopedQwenAdapter:
    interface_version = "1"

    def __init__(self, bridge, adapter, guard):
        self.bridge, self.adapter, self.guard = bridge, adapter, guard
        self.runtime_ref = fingerprint(guard.runtime)
        self.routing_ref = fingerprint(bridge.config.team.routing)

    def __getattr__(self, name):
        return getattr(self.adapter, name)

    def _binding(self, task, args, config):
        """Observe the actual sealed request and its current Core lease."""
        b = self.bridge
        if (
            fingerprint(self.guard.runtime) != self.runtime_ref
            or fingerprint(b.config.team.routing) != self.routing_ref
        ):
            raise RoutingError("Scoped Qwen runtime binding requires controlled reinitialization")
        stored = b.store.get(task["id"], task["principal"])
        if (
            stored["operation"] != "agent.execute"
            or stored["state"] not in {"accepted", "running"}
            or any(stored.get(k) != task.get(k) for k in ("id", "principal", "operation", "args"))
            or AgentInput.model_validate(stored["args"]).model_dump() != args.model_dump()
            or fingerprint(b.config.agents.get(args.agent)) != fingerprint(config)
        ):
            raise RoutingError("Actual scoped Qwen request or agent configuration changed")
        rows = b.store.db.execute(
            "SELECT id FROM team_work WHERE core_task_id=?", (task["id"],)
        ).fetchall()
        if len(rows) != 1:
            raise RoutingError("Scoped Qwen requires exactly one sealed Team owner")
        work = b.teams._work(rows[0]["id"])
        if (
            work["assignee"] != task["principal"]
            or work.get("claimed") is None
            or work["state"] not in {"dispatching", "created", "queued", "accepted", "running"}
        ):
            raise RoutingError("Scoped Qwen Team claim is no longer executable")
        b.teams.authorize_execution(stored)
        if authorize := getattr(b.agents, "worktree_guard", None):
            authorize(stored, args)
        lease = b.store.db.execute(
            "SELECT lease_owner,lease_until,receipt,attempt,request_hash FROM tasks WHERE id=?",
            (task["id"],),
        ).fetchone()
        if (
            not lease["lease_owner"]
            or not lease["receipt"]
            or type(lease["lease_until"]) not in (int, float)
            or not math.isfinite(lease["lease_until"])
            or lease["lease_until"] <= time.time()
        ):
            raise RoutingError("Scoped Qwen Core lease is absent or expired")
        worker = b.config.team.workers[task["principal"]]
        if worker.execution_scope != "separate_managed_session":
            raise RoutingError("Scoped Qwen cannot replace an existing visible session")
        route = worker.routing
        if route is not None and (
            route.model not in (None, config.model) or route.effort != config.qwen_reasoning_effort
        ):
            raise RoutingError("Scoped Qwen selection differs from the trusted worker route")
        root = Path(args.cwd).resolve(strict=True)
        info = root.stat()
        # Heartbeat may extend lease_until; owner/receipt/attempt must stay fixed.
        identity = {
            "work_id": work["id"],
            "team_id": work["team_id"],
            "assigned_by": work["assigned_by"],
            "assignee": work["assignee"],
            "core_task_id": task["id"],
            "request_sha256": lease["request_hash"],
            "lease_owner": lease["lease_owner"],
            "receipt": lease["receipt"],
            "attempt": lease["attempt"],
            "worker": worker.model_dump(),
            "principal": b.config.principals[task["principal"]].model_dump(),
            "cwd": [str(root), info.st_dev, info.st_ino],
        }
        profile = Task(
            task_id=task["id"],
            workload=route.workload if route is not None else "implementation",
            prompt=args.prompt,
            cwd=args.cwd,
            ownership_ref="sealed-qwen:" + fingerprint(identity),
            allowed_clis=["qwen"],
            explicit_cli="qwen",
            explicit_model=config.model,
            explicit_effort=config.qwen_reasoning_effort,
            min_effort=route.min_effort if route is not None else None,
            independent_of_provider=route.independent_of_provider if route is not None else None,
            execution_adapter="qwen_acp",
            read_only=True,
            timeout_seconds=int(args.timeout),
        )
        if profile.timeout_seconds != args.timeout:
            raise RoutingError("Scoped Qwen requires an exact whole-second timeout")
        return fingerprint(identity), profile

    async def execute(
        self, task, args, config, roots, running, progress, *, before_spawn=None, **kwargs
    ):
        if any(
            kwargs.get(k) for k in ("resume_session", "owned_resume_session", "recovery_binding")
        ):
            raise BridgeError(
                "routing_preflight_blocked", "Scoped reads never adopt or retry a session"
            )
        try:
            binding, profile = self._binding(task, args, config)
            decision = await asyncio.to_thread(
                self.guard.validate_qwen_task, profile, args=args, config=config
            )
        except (RoutingError, OSError, ValueError, KeyError):
            raise BridgeError(
                "routing_preflight_blocked", "Scoped Qwen preflight rejected"
            ) from None

        await progress({"event": "scoped_qwen_preflight", "routing_decision": decision})

        def final_check():
            if before_spawn is not None:
                before_spawn()
            try:
                current, actual = self._binding(task, args, config)
                if current != binding or fingerprint(actual) != fingerprint(profile):
                    raise RoutingError("Actual scoped Qwen ownership changed before spawn")
                self.guard.validate_qwen_task(actual, args=args, config=config, expected=decision)
                # Public version/auth/source probes above perform IO. Recheck
                # the live Core lease/config/arguments after that IO as well.
                current, actual = self._binding(task, args, config)
                if (
                    current != binding
                    or fingerprint(actual) != fingerprint(profile)
                    or fingerprint(args) != decision["agent_input_sha256"]
                    or fingerprint(config) != decision["configured_agent_sha256"]
                ):
                    raise RoutingError("Scoped Qwen effect binding changed during final probes")
            except (RoutingError, OSError, ValueError, KeyError):
                raise BridgeError(
                    "routing_preflight_blocked", "Scoped Qwen effect gate rejected"
                ) from None

        # QwenACPAdapter calls this inside its opened CWD descriptor immediately
        # before spawn_process. Preserve its exact result/UNKNOWN/cleanup contract.
        return await self.adapter.execute(
            task, args, config, roots, running, progress, before_spawn=final_check, **kwargs
        )
