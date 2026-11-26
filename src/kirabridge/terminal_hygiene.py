"""Find orphaned agent processes and stale terminal bindings, by TTY and process identity.

A Terminal.app tab is identified by the TTY of that single tab and by the process
tree on it, never by the window title (the profile may show the active process and
its arguments, so titles change while an agent runs).

An agent is orphaned when it still runs on a TTY that no open tab owns and has been
re-parented to launchd (ppid 1): its shell or login is gone. Agents without a TTY are
background agents by design and are never touched, and neither is any process that
belongs to a tmux/ssh/other terminal tree (their parent is alive). Everything here is
read-only except `terminate_orphans` (SIGTERM only, identity re-verified first) and
`strip_stale_bindings` (backup first, validated by the caller).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

AGENT_NAMES = frozenset({"claude", "codex", "grok", "gemini", "opencode", "qwen", "copilot"})
BINDING_KEYS = (
    "pane_id",
    "expected_pid",
    "agent_pid",
    "ready_pattern",
    "busy_pattern",
    "codex_thread_id",
    "codex_rollout_path",
)
_ROW = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\S+)\s+(\w+ \w+ +\d+ [\d:]+ \d+)\s+(.*)$")


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    tty: str  # "ttys002" or "??"
    start: str  # ps lstart, with the pid it pins the process identity
    command: str


def parse_ps(output: str) -> list[Proc]:
    rows = []
    for line in output.splitlines():
        match = _ROW.match(line)
        if match:
            pid, ppid, tty, start, command = match.groups()
            rows.append(Proc(int(pid), int(ppid), tty, start, command))
    return rows


def read_processes() -> list[Proc]:
    out = subprocess.run(
        ["/bin/ps", "-axo", "pid=,ppid=,tty=,lstart=,command="],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
        env={**os.environ, "LC_ALL": "C"},  # lstart is locale dependent ("Do 26 Nov" in de)
    ).stdout
    rows = parse_ps(out)
    lines = [line for line in out.splitlines() if line.strip()]
    if not rows or len(rows) != len(lines):  # never decide from a partial process list
        raise RuntimeError("process list not fully readable")
    return rows


def agent_name(command: str) -> str | None:
    first = command.split(None, 1)[0] if command.strip() else ""
    base = Path(first).name.lstrip("-")
    if base in AGENT_NAMES:
        return base
    for name in AGENT_NAMES:  # e.g. ~/.local/share/claude/versions/2.1.332
        if f"/{name}/versions/" in first:
            return name
    return None


def read_live_tabs() -> set[str] | None:
    """TTYs of all open Terminal.app tabs, or None when they cannot be read."""
    script = (
        'const a=Application("Terminal");JSON.stringify(a.running()?'
        "a.windows().flatMap(w=>w.tabs().map(t=>t.tty())):[])"
    )
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-l", "JavaScript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode:
            return None
        return {Path(tty).name for tty in json.loads(result.stdout)}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def protected_pids(procs: list[Proc], me: int | None = None) -> set[int]:
    """This process and all its ancestors: the caller's own session is never a target."""
    by_pid = {p.pid: p for p in procs}
    keep, pid = set(), me or os.getpid()
    while pid in by_pid and pid not in keep:
        keep.add(pid)
        pid = by_pid[pid].ppid
    return keep | {pid}


def find_orphans(procs: list[Proc], live_ttys: set[str], protected: set[int]) -> list[Proc]:
    return [
        p
        for p in procs
        if agent_name(p.command)
        and p.tty.startswith("ttys")
        and p.tty not in live_ttys
        and p.ppid == 1
        and p.pid not in protected
    ]


def background_agents(procs: list[Proc]) -> list[Proc]:
    """Agents without a TTY run in the background on purpose and stay untouched."""
    return [p for p in procs if agent_name(p.command) and not p.tty.startswith("ttys")]


def stale_bindings(bindings: dict[str, dict], procs: list[Proc], live_ttys: set[str]):
    """Names whose tab is gone or whose recorded shell/agent PID no longer exists."""
    alive = {p.pid for p in procs}
    stale = {}
    for name, binding in bindings.items():
        tty = str(binding.get("pane_id", "")).rsplit(":", 1)[-1]
        reasons = []
        if tty not in live_ttys:
            reasons.append("tab_closed")
        for key in ("expected_pid", "agent_pid"):
            if binding.get(key) not in alive:
                reasons.append(f"{key}_gone")
        if reasons:
            stale[name] = reasons
    return stale


def terminate_orphans(orphans, *, read=read_processes, kill=os.kill, wait=5.0, sleep=time.sleep):
    """SIGTERM each orphan after re-checking pid, start time, TTY and parent. No SIGKILL."""
    results = {}
    for orphan in orphans:
        current = {p.pid: p for p in read()}.get(orphan.pid)
        if current != orphan:
            results[orphan.pid] = "identity_changed_not_touched"
            continue
        kill(orphan.pid, signal.SIGTERM)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            sleep(0.25)
            if orphan.pid not in {p.pid for p in read()}:
                results[orphan.pid] = "terminated"
                break
        else:
            results[orphan.pid] = "still_running_after_sigterm"
    return results


def strip_stale_bindings(text: str, names) -> str:
    """Remove `[visible_handoffs.bindings.NAME]` blocks (header + its known keys) from TOML."""
    names, out, skipping = set(names), [], False
    for line in text.splitlines(keepends=True):
        header = re.match(r"^\[visible_handoffs\.bindings\.([A-Za-z0-9_-]+)\]\s*$", line)
        if header:
            skipping = header.group(1) in names
            if skipping:
                continue
        elif skipping:
            key = re.match(r"^([A-Za-z_]+)\s*=", line)
            if key and key.group(1) in BINDING_KEYS:
                continue
            skipping = False
        out.append(line)
    return "".join(out)


def backup(path: Path, label: str) -> Path:
    target = path.with_name(f"{path.name}.bak.{time.strftime('%Y%m%d-%H%M%S')}-{label}")
    shutil.copy2(path, target)
    return target


def report(config_path: str | None, apply: bool = False) -> dict:
    """`kirabridge terminals`: read-only by default; `--apply` cleans up with backups."""
    from kirabridge.bridge_core.config import load_config
    from kirabridge.visible_binding import overlay_path

    config = load_config(config_path)
    procs = read_processes()
    live = read_live_tabs()
    if live is None:  # without the tab list nothing can be called orphaned or stale
        return {"status": "tabs_unavailable", "changed": False}
    orphans = find_orphans(procs, live, protected_pids(procs))
    bindings = {
        name: binding.model_dump() for name, binding in config.visible_handoffs.bindings.items()
    }
    stale = stale_bindings(bindings, procs, live)
    result = {
        "status": "ok",
        "live_tabs": sorted(live),
        "orphan_agents": [
            {"pid": p.pid, "tty": p.tty, "agent": agent_name(p.command), "started": p.start}
            for p in orphans
        ],
        "background_agents_kept": sorted({agent_name(p.command) for p in background_agents(procs)}),
        "stale_bindings": stale,
        "changed": False,
    }
    if not apply:
        return result
    if orphans:
        result["terminated"] = terminate_orphans(orphans)
    if stale:
        source = Path(config._source_path)
        original = source.read_text()
        saved = backup(source, "stale-bindings")
        source.write_text(strip_stale_bindings(original, stale))
        try:
            load_config(str(source))
        except Exception as error:  # an invalid result is never kept
            shutil.copy2(saved, source)
            raise RuntimeError(f"config invalid after cleanup, restored {saved.name}") from error
        overlay = overlay_path(config)
        if overlay.is_file():
            data = json.loads(overlay.read_text())
            backup(overlay, "stale-bindings")
            overlay.write_text(json.dumps({k: v for k, v in data.items() if k not in stale}))
        result["config_backup"] = str(saved)
    result["changed"] = bool(orphans or stale)
    return result
