"""Add routing to NEW managed AgentManagers without editing shared dispatchers.

Existing security, queue admission, ownership guards and ACP/JSON parsers remain
in their existing paths. The caller supplies task profiles from its sealed local
assignment, never from an untrusted model response or freeform board text.
"""

from __future__ import annotations

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

    def __init__(self, adapter, cli, guard, profiles):
        self.adapter, self.cli, self.guard, self.profiles = adapter, cli, guard, profiles

    def __getattr__(self, name):
        return getattr(self.adapter, name)

    async def execute(self, task, args, config, roots, running, progress, **kwargs):
        if kwargs.get("owned_resume_session"):
            raise RoutingError(
                "Resume needs its original pinned decision; no fresh model switching"
            )
        profile = self.profiles(task, args)
        if (
            profile.task_id != task["id"]
            or profile.prompt != args.prompt
            or Path(profile.cwd).resolve() != Path(args.cwd).resolve()
            or profile.timeout_seconds != args.timeout
        ):
            raise RoutingError("Sealed task profile differs from actual native request")
        if not profile.read_only and not config.allow_local_tools:
            raise RoutingError("Original agent profile does not allow writing")
        if profile.read_only and (
            config.bridge_tools
            or args.local_tools
            or (self.cli == "codex" and config.sandbox_mode != "read-only")
        ):
            raise RoutingError("Read-only routing needs an already restricted worker profile")
        decision = self.guard.prepare(profile)
        if decision["cli"] != self.cli:
            raise RoutingError("Selected CLI needs its own authorized worker identity")
        if decision["access_kind"] != "subscription":
            raise RoutingError("Managed routing currently supports existing subscriptions only")
        selected = config.model_copy(
            update={
                "model": decision["model"],
                "executable": effort_shim(decision, self.guard.runtime.state_dir),
                "api_key_env": "",
            }
        )
        # This event is requested-setting evidence, never effective-model attestation.
        await progress({"routing_decision": decision})
        matrix, binding = self.guard.source.load()
        if binding != decision["thread_desk"] or fingerprint(matrix) != decision["matrix_sha256"]:
            raise RoutingError("Matrix changed before native adapter execution")
        return await self.adapter.execute(task, args, selected, roots, running, progress, **kwargs)


def new_routed_manager(config, terminal, guard, profiles):
    """Opt-in construction for the parallel coordinator's next safe activation.

    Does not touch a running bridge or manager. Dispatcher identity/ownership and
    security stay with the existing manager. Preserve its worktree_guard as usual.
    """
    from kirabridge.agent_manager import AgentManager

    if config.visible_handoffs.enabled:
        raise RoutingError("Existing visible sessions cannot be reconfigured by the router")
    manager = AgentManager(config, terminal)
    # Unsupported routes must not bypass routing on this opt-in manager.
    manager.adapters = {kind: manager.adapters[kind] for kind in ("codex", "grok_acp")}
    for kind, cli in (("codex", "codex"), ("grok_acp", "grok")):
        manager.adapters[kind] = RoutedAdapter(manager.adapters[kind], cli, guard, profiles)
    return manager
