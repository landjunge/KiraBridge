"""Read-only CLI version discovery for configured and well-known agent tools."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from pathlib import Path

VERSION = re.compile(r"(?<![0-9])v?(\d+\.\d+(?:\.\d+)?(?:[-+][A-Za-z0-9.-]+)?)(?![0-9])")

# Canonical command names are intentionally separate from configured agent IDs:
# one installation may back several profiles, while a CLI may be installed but
# not yet configured as a worker.
CLI_COMMANDS = {
    "aider": ("aider",),
    "claude": ("claude",),
    "codex": ("codex",),
    "copilot": ("copilot", "gh-copilot"),
    "cursor": ("cursor",),
    "gemini": ("gemini",),
    "opencode": ("opencode",),
    "qwen": ("qwen", "qwen-code"),
    "grok": ("grok",),
}
KIND_CLI = {
    "codex": "codex",
    "grok_acp": "grok",
    "grok_api": "grok",
    "grok_structured": "grok",
    "qwen_acp": "qwen",
    "claude_code": "claude",
    "opencode": "opencode",
    "opencode_acp": "opencode",
    "opencode_http": "opencode",
    "opencode_http_v2": "opencode",
    "gemini_cli": "gemini",
    "copilot_cli": "copilot",
}


def _version_text(output: bytes) -> str | None:
    text = output.decode("utf-8", errors="replace")[:4096]
    match = VERSION.search(text)
    return match.group(1) if match else None


async def _probe(executable: str) -> dict:
    path = Path(executable)
    if not path.is_file() or not os.access(path, os.X_OK):
        return {"status": "not_runnable", "version": None}
    try:
        process = await asyncio.create_subprocess_exec(
            str(path),
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={"PATH": os.environ.get("PATH", os.defpath), "HOME": str(Path.home())},
        )
        output = await asyncio.wait_for(process.stdout.read(4097), timeout=3)
        try:
            await asyncio.wait_for(process.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return {"status": "probe_timeout", "version": _version_text(output)}
    except (OSError, asyncio.TimeoutError):
        if "process" in locals() and process.returncode is None:
            process.kill()
            await process.wait()
        return {"status": "probe_failed", "version": None}
    version = _version_text(output[:4096])
    return {
        "status": "observed" if process.returncode == 0 and version else "version_unknown",
        "version": version,
    }


def compatibility(kind: str | None, version: str | None, *, cli: str | None = None) -> dict:
    if not version:
        return {"status": "unknown", "reason": "version_not_observed"}
    if kind == "qwen_acp" or cli == "qwen":
        if version in {"0.27.2", "0.27.3"}:
            return {"status": "compatible", "reason": "qwen_acp_supported_version"}
        return {"status": "unsupported", "reason": "qwen_acp_version_not_in_supported_set"}
    if kind is None:
        return {"status": "unknown", "reason": "agent_adapter_not_configured"}
    return {"status": "unknown", "reason": "version_policy_not_declared_for_adapter"}


async def inventory(
    configs: dict, allowed: list[str], running_process_names: set[str]
) -> list[dict]:
    """Observe configured executables and known CLI names on PATH; never use a shell."""
    configured: dict[str, dict] = {}
    for agent_id, config in configs.items():
        if agent_id not in allowed or not config.executable:
            continue
        name = Path(config.executable).name.lower()
        configured.setdefault(name, {"agent_id": agent_id, "kind": config.kind})

    pending = []
    seen = set()
    for canonical, aliases in CLI_COMMANDS.items():
        paths = [(alias, shutil.which(alias)) for alias in aliases]
        paths.extend(
            (Path(config.executable).name.lower(), config.executable)
            for agent_id, config in configs.items()
            if (
                agent_id in allowed
                and config.executable
                and Path(config.executable).name.lower() in aliases
            )
        )
        for alias, executable in paths:
            if not executable:
                continue
            resolved = str(Path(executable).expanduser())
            try:
                resolved = str(Path(resolved).resolve(strict=True))
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            profile = configured.get(Path(executable).name.lower(), {})
            pending.append((canonical, alias, resolved, profile))
    for agent_id, config in configs.items():
        if agent_id not in allowed or not config.executable:
            continue
        executable = str(Path(config.executable).expanduser())
        try:
            executable = str(Path(executable).resolve(strict=True))
        except OSError:
            continue
        if executable in seen:
            continue
        seen.add(executable)
        canonical = KIND_CLI.get(config.kind, agent_id)
        pending.append(
            (
                canonical,
                Path(executable).name.lower(),
                executable,
                {"agent_id": agent_id, "kind": config.kind},
            )
        )
    probes = await asyncio.gather(*(_probe(executable) for _, _, executable, _ in pending))
    candidates = []
    for (canonical, _alias, executable, profile), probe in zip(pending, probes, strict=True):
        aliases = set(CLI_COMMANDS.get(canonical, ()))
        candidates.append(
            {
                "cli": canonical,
                "agent_id": profile.get("agent_id"),
                "adapter": profile.get("kind"),
                "executable": executable,
                "version": probe["version"],
                "probe_status": probe["status"],
                "running": bool(aliases.intersection(running_process_names))
                or Path(executable).name.lower() in running_process_names,
                "compatibility": compatibility(
                    profile.get("kind"), probe["version"], cli=canonical
                ),
            }
        )
    return candidates
