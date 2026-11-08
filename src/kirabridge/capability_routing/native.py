"""Native opt-in on existing sealed Team/Core authority, never a second queue."""

from __future__ import annotations

from pathlib import Path

from kirabridge.bridge_core.models import AgentInput, BridgeError

from .hook import DelegationGuard
from .integration import RoutedAdapter, new_routed_manager
from .router import RoutingError, Task, fingerprint, select
from .source import local_source

KINDS = {"codex": "codex", "grok_acp": "grok", "grok_structured": "grok"}


class NativeRouting:
    def __init__(self, bridge, guard=None):
        self.bridge = bridge
        self.settings = bridge.config.team.routing
        self.configuration = fingerprint(self.settings)
        self.workers = frozenset(
            name
            for name, worker in bridge.config.team.workers.items()
            if worker.routing is not None
        )
        if not self.workers or not bridge.config.team.enabled:
            raise BridgeError("routing_config", "Explicit enabled team and routed workers required")
        for name in self.workers:
            worker = bridge.config.team.workers[name]
            agent = bridge.config.agents.get(worker.agent)
            if (
                worker.execution_scope != "separate_managed_session"
                or not agent
                or agent.kind not in KINDS
            ):
                raise BridgeError(
                    "routing_config", "Routed worker requires a supported managed adapter"
                )
        if guard is None:
            workspace = Path(self.settings.workspace).resolve(strict=True)
            if not workspace.is_dir():
                raise BridgeError("routing_config", "Existing matrix workspace required")
            guard = DelegationGuard(
                local_source(workspace, self.settings.thread_id), self.settings.runtime
            )
        self.guard = guard

    def _profile(self, task, args, *, initial):
        cfg = self.bridge.config
        worker = cfg.team.workers.get(task.get("principal"))
        if task.get("principal") not in self.workers:
            if worker and worker.routing is not None:
                raise BridgeError("routing_restart_required", "New routing worker requires restart")
            return None
        if (
            fingerprint(cfg.team.routing) != self.configuration
            or worker is None
            or worker.routing is None
            or worker.execution_scope != "separate_managed_session"
            or fingerprint(self.guard.runtime) != fingerprint(self.settings.runtime)
        ):
            raise BridgeError("routing_scope_changed", "Routing configuration changed")
        row = self.bridge.store.db.execute(
            "SELECT id FROM team_work WHERE core_task_id=?", (task.get("id"),)
        ).fetchone()
        if row is None:
            raise BridgeError("routing_seal_required", "Routing requires a sealed team task")
        work = self.bridge.teams._work(row["id"])
        if (
            work["state"] not in {"dispatching", "created", "queued", "accepted", "running"}
            or work["assignee"] != task["principal"]
            or work["core_task_id"] != task["id"]
            or work.get("claimed") is None
        ):
            raise BridgeError("routing_claim_changed", "Sealed claim is no longer executable")
        stored = self.bridge.store.get(task["id"], task["principal"])
        if (
            any(
                task.get(key) != stored.get(key) for key in ("id", "principal", "operation", "args")
            )
            or stored["state"] not in {"accepted", "running"}
            or AgentInput.model_validate(stored["args"]).model_dump() != args.model_dump()
        ):
            raise BridgeError(
                "routing_scope_changed", "Actual request differs from stored Core task"
            )
        if initial and (stored.get("evidence") or {}).get("routing_decision"):
            raise BridgeError("routing_replay_denied", "Original routing decision already exists")
        self.bridge.teams.authorize_execution(stored)
        self.bridge.agents.worktree_guard(stored, args)
        policy = self.bridge.security.principal(task["principal"], "agent.execute")
        agent = cfg.agents.get(worker.agent)
        if not agent or agent.kind not in KINDS or args.agent not in policy.agents:
            raise BridgeError(
                "routing_scope_changed", "Worker or principal no longer permits adapter"
            )
        cli = KINDS[agent.kind]
        access = [item for item in self.guard.runtime.access if item.cli == cli]
        if (
            len(access) != 1
            or not agent.executable
            or not Path(agent.executable).is_absolute()
            or Path(access[0].executable).resolve(strict=True)
            != Path(agent.executable).resolve(strict=True)
        ):
            raise BridgeError(
                "routing_scope_changed", "Runtime must use the fixed worker executable"
            )
        read_only = agent.sandbox_mode == "read-only"
        if (
            agent.bridge_tools
            or args.local_tools
            or (read_only and agent.allow_local_tools)
            or (cli == "grok" and not read_only)
        ):
            raise BridgeError(
                "routing_scope_changed", "Original restricted worker profile required"
            )
        timeout = int(args.timeout)
        if timeout != args.timeout:
            raise BridgeError("routing_config", "Router timeout requires exact whole seconds")
        path = Path(agent.executable).resolve(strict=True)
        st = path.stat()
        seal = self.bridge.store.db.execute(
            "SELECT core_request_hash FROM team_work WHERE id=?", (work["id"],)
        ).fetchone()[0]
        ownership = fingerprint(
            {
                "work_id": work["id"],
                "team_id": work["team_id"],
                "principal": task["principal"],
                "seal": seal,
                "worker": worker.model_dump(),
                "agent": agent.model_dump(),
                "file": [str(path), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns],
                "configuration": self.configuration,
            }
        )
        return Task(
            task_id=task["id"],
            prompt=args.prompt,
            cwd=args.cwd,
            timeout_seconds=timeout,
            ownership_ref="sealed-team:" + ownership,
            allowed_clis=[cli],
            explicit_cli=cli,
            workload=worker.routing.workload,
            explicit_model=args.model if args.model is not None else worker.routing.model,
            explicit_effort=args.effort if args.effort is not None else worker.routing.effort,
            min_effort=worker.routing.min_effort,
            independent_of_provider=worker.routing.independent_of_provider,
            read_only=read_only,
        )

    def profile(self, task, args):
        try:
            return self._profile(task, args, initial=True)
        except (ValueError, OSError) as exc:
            raise BridgeError(
                "routing_scope_invalid", "Sealed routing profile unavailable"
            ) from exc

    def authorize(self, task, args, profile, decision):
        try:
            self._authorize(task, args, profile, decision)
        except (ValueError, OSError) as exc:
            raise BridgeError(
                "routing_preflight_blocked", "Live routing preflight blocked"
            ) from exc

    def _authorize(self, task, args, profile, decision):
        matrix, binding = self.guard.source.load()
        current = select(matrix, self.guard.runtime, profile)
        if (
            binding.get("thread_id") != self.settings.thread_id
            or binding != decision["thread_desk"]
            or any(
                current[key] != decision[key]
                for key in (
                    "cli",
                    "model",
                    "effort",
                    "matrix_sha256",
                    "runtime_sha256",
                    "task_sha256",
                )
            )
        ):
            raise RoutingError("Matrix/runtime decision changed before effect")
        if fingerprint(self._profile(task, args, initial=False)) != fingerprint(profile):
            raise RoutingError("Sealed live profile changed before effect")


class NativeRoutedAdapter(RoutedAdapter):
    def rejected(self, message):
        return BridgeError("routing_preflight_blocked", message)

    def prepare(self, profile):
        try:
            return super().prepare(profile)
        except (ValueError, OSError) as exc:
            raise self.rejected("Routing probes blocked before native effect") from exc

    def matrix(self):
        try:
            return super().matrix()
        except (ValueError, OSError) as exc:
            raise self.rejected("Fresh matrix unavailable before native effect") from exc


def native_routed_manager(bridge, guard=None):
    routing = NativeRouting(bridge, guard)
    manager = new_routed_manager(
        bridge.config,
        bridge.terminal,
        routing.guard,
        routing.profile,
        managed_only=True,
        authorize=routing.authorize,
        adapter_type=NativeRoutedAdapter,
    )
    manager.managed_routing_guard = routing.profile
    return manager
