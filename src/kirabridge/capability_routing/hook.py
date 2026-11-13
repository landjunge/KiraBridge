"""Mandatory pre-delegation hook for the controlled Big Plan launcher."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from .router import RoutingError, select


def version_identity(cli, text):
    # Grok's same binary/build labels its update channel alpha/stable dynamically.
    # Pin semantic version AND build; retain observed channel separately as evidence.
    if cli == "grok":
        match = re.fullmatch(
            r"(grok \d+\.\d+\.\d+ \([0-9a-f]{12}\))(?: \[(?:alpha|stable)\])?", text
        )
        if match:
            return match[1]
    return text


def subscription_environment():
    """Prevent inherited API keys/endpoints from changing the granted billing route."""
    env = dict(os.environ)
    for key in list(env):
        if key in {
            "OPENAI_API_KEY",
            "CODEX_API_KEY",
            "OPENAI_BASE_URL",
            "OPENAI_ORG_ID",
            "OPENAI_PROJECT_ID",
            "GROK_API_KEY",
            "XAI_API_KEY",
            "XAI_BASE_URL",
        }:
            env.pop(key)
    return env


def _before_delegation(source, runtime, task, *, probe, allow_scoped_qwen):
    matrix, binding = source.load()
    decision = {
        **select(matrix, runtime, task, _allow_scoped_qwen=allow_scoped_qwen),
        "thread_desk": binding,
    }
    cwd = Path(task.cwd).resolve(strict=True)
    if not cwd.is_dir() or not any(
        cwd.is_relative_to(Path(root).resolve(strict=True)) for root in runtime.allowed_roots
    ):
        raise RoutingError("Task cwd is outside granted workspaces")
    exe = Path(decision["executable"])
    if not exe.is_absolute() or not exe.is_file() or not os.access(exe, os.X_OK):
        raise RoutingError("Trusted runtime executable is unavailable")
    if probe:
        argv = [str(exe), "--version"]
        if decision["cli"] == "qwen":
            argv[1:1] = ["--bare", "--safe-mode"]
        if decision["cli"] == "grok":
            argv.insert(1, "--no-auto-update")
        result = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
            env=subscription_environment(),
        )
        # Complete first-line equality, not substring matching (0.166.01 != 0.166.0).
        observed = (result.stdout or result.stderr).strip().splitlines()
        if (
            result.returncode
            or not observed
            or version_identity(decision["cli"], observed[0])
            != version_identity(decision["cli"], decision["expected_version"])
        ):
            raise RoutingError("Installed CLI version changed; reverify matrix/runtime")
        decision["observed_version"] = observed[0]
        if decision["cli"] == "qwen" and decision["access_kind"] == "subscription":
            try:
                public = json.loads((Path.home() / ".qwen/settings.json").read_text())
                selected = public.get("security", {}).get("auth", {}).get("selectedType")
            except (OSError, ValueError):
                raise RoutingError("Qwen subscription selection cannot be confirmed") from None
            if selected != "qwen-subscription":
                raise RoutingError("Qwen subscription selection changed; no account fallback")
            decision["observed_auth_route"] = "qwen-subscription_selection_only"
        # A saved subscription observation must not silently become API billing
        # if somebody changed authentication while parallel work was running.
        if decision["access_kind"] == "subscription" and decision["cli"] in {"codex", "grok"}:
            auth_argv = (
                [str(exe), "login", "status"]
                if decision["cli"] == "codex"
                else [str(exe), "--no-auto-update", "models"]
            )
            auth = subprocess.run(
                auth_argv,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=10,
                env=subscription_environment(),
            )
            text = auth.stdout + auth.stderr
            marker = (
                "Logged in using ChatGPT"
                if decision["cli"] == "codex"
                else "You are logged in with grok.com."
            )
            if auth.returncode or marker not in text.splitlines():
                raise RoutingError("Subscription authentication changed; no API/account fallback")
            if decision["cli"] == "grok" and not re.search(
                r"^\s*[-*]\s+" + re.escape(decision["model"]) + r"(?:\s|$)", text, re.M
            ):
                raise RoutingError("Selected Grok model is no longer listed for this account")
            decision["observed_auth_route"] = (
                "chatgpt" if decision["cli"] == "codex" else "grok.com"
            )
    return decision


def before_delegation(source, runtime, task, *, probe=True):
    """Generic coordinator path; scoped Qwen evidence is deliberately unavailable."""
    return _before_delegation(source, runtime, task, probe=probe, allow_scoped_qwen=False)


def command_for(decision, task):
    """Static adapters only. ThreadDesk cannot provide executable code or flags."""
    exe, model, effort = (decision[k] for k in ("executable", "model", "effort"))
    if decision["cli"] == "codex":
        return [
            exe,
            "exec",
            "--ignore-user-config",
            "--model",
            model,
            "-c",
            'model_provider="openai"',
            "-c",
            "mcp_servers={}",
            "-c",
            f'model_reasoning_effort="{effort}"',
            "-c",
            "features.multi_agent=false",
            "--json",
            "--sandbox",
            "read-only" if task.read_only else "workspace-write",
            "-",
        ], task.prompt.encode()
    if decision["cli"] == "grok":
        if not task.read_only:
            raise RoutingError("Grok write route awaits a verified filesystem-scoped adapter")
        # Only filesystem reads and search; no Bash/Edit/Write/MCP bypass.
        return [
            exe,
            "--no-auto-update",
            "--model",
            model,
            "--effort",
            effort,
            "--no-subagents",
            "--max-turns",
            "8",
            "--permission-mode",
            "plan",
            "--tools",
            "Read,Glob,Grep",
            "--deny",
            "MCPTool",
            "--output-format",
            "json",
            "--single",
            task.prompt,
        ], None
    raise RoutingError("CLI researched but execution adapter not yet verified for this launcher")


class DelegationGuard:
    """Coordinator integration: call for NEW turns only, before sealing the request.

    A fixed existing worker can be checked without changing its identity or defaults.
    Resume/reconcile paths must read their original receipt instead of selecting again.
    """

    def __init__(self, source, runtime):
        self.source, self.runtime = source, runtime

    def prepare(self, task):
        return before_delegation(self.source, self.runtime, task)

    def validate_configured(self, task, *, cli, model, effort):
        decision = self.prepare(task)
        if (cli, model, effort) != tuple(decision[k] for k in ("cli", "model", "effort")):
            raise RoutingError(
                "Configured worker differs from matrix decision; bind a matching per-run profile"
            )
        return decision

    def _validate_scoped_qwen_configured(self, task, *, model, effort):
        decision = _before_delegation(
            self.source,
            self.runtime,
            task,
            probe=True,
            allow_scoped_qwen=True,
        )
        if ("qwen", model, effort) != tuple(decision[k] for k in ("cli", "model", "effort")):
            raise RoutingError(
                "Configured worker differs from matrix decision; bind a matching per-run profile"
            )
        return decision

    def validate_qwen_task(self, task, *, args, config, expected=None):
        """Select for actual Qwen arguments; call again at the native effect boundary.

        This receipt grants no Core execution, claim, tools, resume or retry. The
        caller retains its original sealed Team/Core authority and before_spawn
        lifecycle. A broad historical agent profile cannot widen this read task.
        """
        if (
            task.execution_adapter != "qwen_acp"
            or not task.read_only
            or config.kind != "qwen_acp"
            or config.qwen_auth_type != "qwen-subscription"
            or config.model != task.explicit_model
            or config.qwen_reasoning_effort != task.explicit_effort
            or task.explicit_effort != "medium"
            or args.prompt != task.prompt
            or args.cwd != task.cwd
            or args.timeout != task.timeout_seconds
            or args.local_tools
            or args.resume_session
            or not set(args.mcp_operations) <= {"file.read", "file.list"}
            or not set(args.mcp_operations) <= set(config.qwen_mcp_operations)
            or not set(args.mcp_read_roots) <= set(config.qwen_mcp_read_roots)
            or any(
                g.tool != "read_queries" or g.tool not in config.qwen_mcp_tools
                for g in args.mcp_grants
            )
        ):
            raise RoutingError("Actual Qwen task exceeds the scoped read-only MEDIUM profile")
        from .router import fingerprint

        input_hash, config_hash = fingerprint(args), fingerprint(config)
        decision = self._validate_scoped_qwen_configured(
            task, model=config.model, effort=config.qwen_reasoning_effort
        )
        if Path(config.executable or "").resolve(strict=True) != Path(
            decision["executable"]
        ).resolve(strict=True):
            raise RoutingError("Configured Qwen executable differs from the access evidence")
        matrix, binding = self.source.load()
        current = select(matrix, self.runtime, task, _allow_scoped_qwen=True)
        if (
            binding != decision["thread_desk"]
            or any(
                current[key] != decision[key]
                for key in ("matrix_sha256", "runtime_sha256", "task_sha256", "model", "effort")
            )
            or fingerprint(args) != input_hash
            or fingerprint(config) != config_hash
        ):
            raise RoutingError("Scoped Qwen source or input changed during preflight")
        decision.update(
            {
                "agent_input_sha256": input_hash,
                "configured_agent_sha256": config_hash,
            }
        )
        if expected is not None and any(
            decision[key] != expected.get(key)
            for key in (
                "task_id",
                "cli",
                "model",
                "effort",
                "expected_version",
                "access_kind",
                "matrix_sha256",
                "runtime_sha256",
                "task_sha256",
                "thread_desk",
                "agent_input_sha256",
                "configured_agent_sha256",
            )
        ):
            raise RoutingError("Scoped Qwen source, task or configuration changed before effect")
        return decision
