"""Add routing to NEW managed AgentManagers without editing shared dispatchers.

Existing security, queue admission, ownership guards and ACP/JSON parsers remain
in their existing paths. The caller supplies task profiles from its sealed local
assignment, never from an untrusted model response or freeform board text.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from .router import RoutingError, fingerprint


def effort_shim(decision, state_dir):
    """Immutable per-decision executable supplies effort to existing native adapters."""
    cli, effort = decision["cli"], decision["effort"]
    if cli == "codex":
        prefix = ["-c", 'model_provider="openai"', "-c", f'model_reasoning_effort="{effort}"']
    elif cli == "grok":
        prefix = ["--no-auto-update", "--effort", effort]
    else:
        raise RoutingError("Managed adapter has no verified effort injection")
    directory = Path(state_dir) / "effort-shims"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / (
        fingerprint(
            {k: decision[k] for k in ("cli", "model", "effort", "executable", "expected_version")}
        )
        + ".py"
    )
    content = (
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "env = dict(os.environ)\n"
        "for key in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENAI_BASE_URL', "
        "'OPENAI_ORG_ID', 'OPENAI_PROJECT_ID', 'GROK_API_KEY', 'XAI_API_KEY', 'XAI_BASE_URL'):\n"
        "    env.pop(key, None)\n"
        f"exe = {decision['executable']!r}\n"
        f"os.execve(exe, [exe] + {prefix!r} + sys.argv[1:], env)\n"
    )
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o700)
    except FileExistsError:
        if path.read_text() != content:
            raise RoutingError("Existing effort shim differs from its decision") from None
    else:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    return str(path)


class RoutedAdapter:
    interface_version = "1"

    def __init__(self, adapter, cli, guard, profiles, *, authorize=None, optional=False):
        self.adapter, self.cli, self.guard, self.profiles = adapter, cli, guard, profiles
        self.authorize, self.optional = authorize, optional

    def __getattr__(self, name):
        return getattr(self.adapter, name)

    def rejected(self, message):
        return RoutingError(message)

    def prepare(self, profile):
        return self.guard.prepare(profile)

    def matrix(self):
        return self.guard.source.load()

    async def execute(self, task, args, config, roots, running, progress, **kwargs):
        if kwargs.get("owned_resume_session") and not self.optional:
            raise self.rejected(
                "Resume needs its original pinned decision; no fresh model switching"
            )
        profile = self.profiles(task, args)
        if profile is None and self.optional:
            return await self.adapter.execute(
                task, args, config, roots, running, progress, **kwargs
            )
        if kwargs.get("owned_resume_session"):
            raise self.rejected("Routed resume requires its original decision; no fresh selection")
        if (
            profile.task_id != task["id"]
            or profile.prompt != args.prompt
            or Path(profile.cwd).resolve() != Path(args.cwd).resolve()
            or profile.timeout_seconds != args.timeout
        ):
            raise self.rejected("Sealed task profile differs from actual native request")
        if (
            not profile.read_only
            and not config.allow_local_tools
            and not (
                self.optional
                and config.kind == "codex"
                and config.sandbox_mode == "workspace-write"
            )
        ):
            raise self.rejected("Original agent profile does not allow writing")
        if profile.read_only and (
            config.bridge_tools
            or args.local_tools
            or (self.cli == "codex" and config.sandbox_mode != "read-only")
        ):
            raise self.rejected("Read-only routing needs an already restricted worker profile")
        decision = (
            await asyncio.to_thread(self.prepare, profile)
            if self.authorize is not None
            else self.prepare(profile)
        )
        if decision["cli"] != self.cli:
            raise self.rejected("Selected CLI needs its own authorized worker identity")
        if decision["access_kind"] != "subscription":
            raise self.rejected("Managed routing currently supports existing subscriptions only")
        selected = config.model_copy(
            update={
                "model": decision["model"],
                "executable": effort_shim(decision, self.guard.runtime.state_dir),
                "api_key_env": config.api_key_env
                if self.authorize is not None and config.kind == "grok_structured"
                else "",
            }
        )
        # This event is requested-setting evidence, never effective-model attestation.
        await progress({"routing_decision": decision})
        matrix, binding = self.matrix()
        if binding != decision["thread_desk"] or fingerprint(matrix) != decision["matrix_sha256"]:
            raise self.rejected("Matrix changed before native adapter execution")
        if self.authorize is not None:

            def before_spawn():
                self.authorize(task, args, profile, decision)
                effort_shim(decision, self.guard.runtime.state_dir)

            before_spawn()
            kwargs = {**kwargs, "before_spawn": before_spawn}
        result = await self.adapter.execute(
            task, args, selected, roots, running, progress, **kwargs
        )
        if self.authorize is not None:
            native = result.get("evidence", {})
            observation = {
                key: native[key]
                for key in (
                    "reported_model_ids",
                    "model_evidence_source",
                    "model_matches_requested_id",
                    "effective_model",
                    "effective_model_status",
                    "effective_effort",
                )
                if key in native
            }
            observed = {**decision, **observation}
            await progress({"routing_decision": observed})
            result = {**result, "evidence": {**native, "routing_decision": observed}}
        return result


def new_routed_manager(
    config,
    terminal,
    guard,
    profiles,
    *,
    managed_only=False,
    authorize=None,
    adapter_type=RoutedAdapter,
):
    """Opt-in construction for the parallel coordinator's next safe activation.

    Does not touch a running bridge or manager. Dispatcher identity/ownership and
    security stay with the existing manager. Preserve its worktree_guard as usual.
    """
    from kirabridge.agent_manager import AgentManager

    if config.visible_handoffs.enabled and not managed_only:
        raise RoutingError("Existing visible sessions cannot be reconfigured by the router")
    manager = AgentManager(config, terminal)
    if managed_only:
        if authorize is None:
            raise RoutingError("Managed routing requires live sealed-task authorization")
        # Keep the complete legacy adapter inventory and the manager's visible
        # branch. The trusted profile builder rejects an unsupported routed worker.
        for kind, cli in (("codex", "codex"), ("grok_acp", "grok"), ("grok_structured", "grok")):
            manager.adapters[kind] = adapter_type(
                manager.adapters[kind], cli, guard, profiles, authorize=authorize, optional=True
            )
        return manager
    # Unsupported routes must not bypass routing on this opt-in manager.
    manager.adapters = {kind: manager.adapters[kind] for kind in ("codex", "grok_acp")}
    for kind, cli in (("codex", "codex"), ("grok_acp", "grok")):
        manager.adapters[kind] = RoutedAdapter(manager.adapters[kind], cli, guard, profiles)
    return manager
