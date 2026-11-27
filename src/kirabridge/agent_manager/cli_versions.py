"""Read-only CLI version discovery for configured and well-known agent tools."""

from __future__ import annotations

import asyncio
import os
import re
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
    # A CLI version is an observation only and never a compatibility verdict;
    # adapters check concrete capabilities at runtime instead.
    if kind is None:
        return {"status": "unknown", "reason": "agent_adapter_not_configured"}
    return {"status": "unknown", "reason": "version_policy_not_declared_for_adapter"}


def _signature(executable: str) -> tuple | None:
    """Path, mtime and size: a probe result stays valid while these are unchanged."""
    try:
        stat = Path(executable).stat()
    except OSError:
        return None
    return (executable, stat.st_mtime_ns, stat.st_size)


async def inventory(
    configs: dict,
    allowed: list[str],
    running_process_names: set[str],
    *,
    cache: dict | None = None,
    force: bool = False,
    sequential: bool = False,
) -> list[dict]:
    """Observe every configured/PATH executable without invoking a shell."""
    configured_by_path: dict[str, dict] = {}
    for agent_id, config in configs.items():
        if agent_id not in allowed or not config.executable:
            continue
        executable = str(Path(config.executable).expanduser())
        try:
            resolved = str(Path(executable).resolve(strict=True))
        except OSError:
            resolved = executable
        profile = {"agent_id": agent_id, "kind": config.kind}
        configured_by_path.setdefault(resolved, profile)

    search_path = os.environ.get("PATH", os.defpath).split(os.pathsep)
    pending_by_key: dict[tuple[str, str], tuple[str, str, str, dict, int]] = {}
    for canonical, aliases in CLI_COMMANDS.items():
        for path_index, directory in enumerate(search_path):
            if not directory:
                continue
            for alias_index, alias in enumerate(aliases):
                candidate = Path(directory) / alias
                if not candidate.is_file() or not os.access(candidate, os.X_OK):
                    continue
                try:
                    resolved = str(candidate.resolve(strict=True))
                except OSError:
                    continue
                profile = configured_by_path.get(resolved, {})
                search_order = path_index * max(len(aliases), 1) + alias_index
                _remember_candidate(
                    pending_by_key,
                    canonical,
                    alias,
                    resolved,
                    profile,
                    search_order,
                )

        for agent_id, config in configs.items():
            if agent_id not in allowed or not config.executable:
                continue
            executable = str(Path(config.executable).expanduser())
            if Path(executable).name.lower() not in aliases:
                continue
            try:
                resolved = str(Path(executable).resolve(strict=True))
            except OSError:
                continue
            _remember_candidate(
                pending_by_key,
                canonical,
                Path(executable).name.lower(),
                resolved,
                {"agent_id": agent_id, "kind": config.kind},
                -1,
            )

    for agent_id, config in configs.items():
        if agent_id not in allowed or not config.executable:
            continue
        executable = str(Path(config.executable).expanduser())
        try:
            executable = str(Path(executable).resolve(strict=True))
        except OSError:
            continue
        canonical = KIND_CLI.get(config.kind, agent_id)
        if (canonical, executable) not in pending_by_key:
            _remember_candidate(
                pending_by_key,
                canonical,
                Path(executable).name.lower(),
                executable,
                {"agent_id": agent_id, "kind": config.kind},
                -1,
            )

    pending = sorted(
        pending_by_key.values(),
        key=lambda item: (item[0], item[4], item[2]),
    )
    if cache is None and not sequential:
        probes = await asyncio.gather(*(_probe(executable) for _, _, executable, _, _ in pending))
    else:
        probes = []
        for _, _, executable, _, _ in pending:
            signature = _signature(executable)
            hit = cache.get(executable) if cache is not None and not force else None
            if hit is not None and signature is not None and hit[0] == signature:
                probes.append(hit[1])
                continue
            probe = await _probe(executable)
            # Only a clean observation is reusable; failures are retried next time.
            if cache is not None and signature is not None and probe["status"] == "observed":
                cache[executable] = (signature, probe)
            probes.append(probe)
    candidates = []
    for (canonical, _alias, executable, profile, search_order), probe in zip(
        pending, probes, strict=True
    ):
        aliases = set(CLI_COMMANDS.get(canonical, ()))
        candidates.append(
            {
                "cli": canonical,
                "agent_id": profile.get("agent_id"),
                "adapter": profile.get("kind"),
                "executable": executable,
                "search_order": search_order,
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


def _remember_candidate(pending, canonical, alias, executable, profile, search_order):
    key = (canonical, executable)
    previous = pending.get(key)
    if previous is None:
        pending[key] = (canonical, alias, executable, profile, search_order)
        return
    _canonical, old_alias, _executable, old_profile, old_order = previous
    preferred_profile = profile if search_order == -1 else old_profile
    pending[key] = (
        canonical,
        old_alias if old_order <= search_order else alias,
        executable,
        preferred_profile,
        min(old_order, search_order),
    )
