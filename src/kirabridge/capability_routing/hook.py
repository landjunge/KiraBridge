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


def subscription_environment(cli=None):
    """Prevent inherited API keys/endpoints from changing the granted billing route."""
    if cli == "claude":
        # Keep the same HOME/keychain subscription; never inherit API/provider,
        # model/effort overrides, plugins or auth-helper environment settings.
        allowed = {
            "HOME",
            "USER",
            "LOGNAME",
            "PATH",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
            "TMPDIR",
            "TERM",
        }
        return {key: value for key, value in os.environ.items() if key in allowed}
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


def before_delegation(source, runtime, task, *, probe=True):
    matrix, binding = source.load()
    decision = {**select(matrix, runtime, task), "thread_desk": binding}
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
        if decision["cli"] == "grok":
            argv.insert(1, "--no-auto-update")
        result = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
            env=subscription_environment(decision["cli"]),
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
                env=subscription_environment(decision["cli"]),
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
        if decision["access_kind"] == "subscription" and decision["cli"] == "claude":
            auth = subprocess.run(
                [str(exe), "auth", "status", "--json"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=10,
                env=subscription_environment("claude"),
            )
            try:
                status = json.loads(auth.stdout)
            except (ValueError, TypeError):
                status = None
            if (
                auth.returncode
                or not isinstance(status, dict)
                or status.get("loggedIn") is not True
                or status.get("authMethod") != "claude.ai"
                or status.get("apiProvider") != "firstParty"
                or status.get("subscriptionType")
                not in {"pro", "max", "ultra", "team", "enterprise"}
            ):
                raise RoutingError(
                    "Claude subscription authentication changed; no API/account fallback"
                )
            # Never expose status identity/token fields or infer model entitlement.
            decision["observed_auth_route"] = "claude.ai"
            decision["requested_model_kind"] = "cli_alias"
            decision["per_model_access_attested"] = False
    return decision


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
    if decision["cli"] == "claude":
        if not task.read_only or model != "opus" or effort != "xhigh":
            raise RoutingError("Claude profile permits only read-only opus/xhigh text review")
        # --bare would disable OAuth/keychain and require API credentials. Keep
        # normal subscription auth; restricted/safe-mode retain managed policy.
        # No builtin tools, MCP, skills, session resume or model fallback.
        return [
            exe,
            "--print",
            "--model",
            model,
            "--effort",
            effort,
            "--restricted",
            "--safe-mode",
            "--permission-mode",
            "plan",
            "--tools",
            "",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--disallowed-tools",
            "mcp__*",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--max-turns",
            "1",
            "--output-format",
            "json",
            "--settings",
            '{"switchModelsOnFlag":false}',
        ], task.prompt.encode()
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
