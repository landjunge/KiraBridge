"""Tab identity by TTY and process, orphaned agents, stale bindings, message routing."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

from kirabridge import terminal_hygiene as th
from kirabridge.session_manager import SessionManager

PS = """\
17135 17134 ttys000 Thu Nov 26 16:01:20 2026 -zsh
12418 12140 ttys002 Thu Nov 26 15:34:21 2026 claude
 9001     1 ttys007 Tue Nov 24 10:00:00 2026 /Users/x/.local/share/claude/versions/2.1.332 --resume
 9002     1 ttys008 Tue Nov 24 10:00:00 2026 codex
 9003   500 ttys009 Tue Nov 24 10:00:00 2026 codex
 9004     1 ??      Tue Nov 24 10:00:00 2026 codex app-server
 9715     1 ttys013 Tue Nov 24 21:56:14 2026 /bin/zsh -i
12140 12139 ttys002 Thu Nov 26 15:33:27 2026 -zsh
  500     1 ttys009 Tue Nov 24 09:59:00 2026 tmux: server
"""


def test_orphans_are_agents_on_tty_without_tab_whose_parent_is_launchd():
    procs = th.parse_ps(PS)
    orphans = th.find_orphans(procs, {"ttys000", "ttys002"}, th.protected_pids(procs, 12418))
    # 9001 (claude) and 9002 (codex) lost their tab; the codex in a live tmux tree (parent
    # 500 alive), the TTY-less background agent, the orphan shell and this session stay.
    assert sorted(p.pid for p in orphans) == [9001, 9002]
    assert [p.pid for p in th.background_agents(procs)] == [9004]


def test_own_session_and_ancestors_are_never_targets():
    procs = th.parse_ps(PS)
    protected = th.protected_pids(procs, 12418)
    assert {12418, 12140, 12139} <= protected
    assert th.find_orphans(procs, set(), protected) != []  # no tab list: still skips protected
    assert 12418 not in {p.pid for p in th.find_orphans(procs, set(), protected)}


def test_terminate_rechecks_identity_and_uses_sigterm_only():
    procs = th.parse_ps(PS)
    orphans = [p for p in procs if p.pid in (9001, 9002)]
    sent, gone = [], set()
    # 9002 was replaced by another process with the same pid (different start time).
    live = [
        p if p.pid != 9002 else th.Proc(9002, 1, "ttys008", "other start", "codex") for p in procs
    ]

    def kill(pid, sig):
        sent.append((pid, sig))
        gone.add(pid)

    def read_now():
        return [p for p in live if p.pid not in gone]

    result = th.terminate_orphans(orphans, read=read_now, kill=kill, wait=1, sleep=lambda s: None)
    assert result == {9001: "terminated", 9002: "identity_changed_not_touched"}
    assert [pid for pid, _ in sent] == [9001]
    assert sent[0][1].name == "SIGTERM"


def test_stale_bindings_by_tab_and_pid_and_strip_keeps_everything_else():
    procs = th.parse_ps(PS)
    bindings = {
        "claude": {"pane_id": "terminal:8514:ttys000", "expected_pid": 850, "agent_pid": 891},
        "live": {"pane_id": "terminal:1:ttys002", "expected_pid": 12140, "agent_pid": 12418},
    }
    assert th.stale_bindings(bindings, procs, {"ttys002"}) == {
        "claude": ["tab_closed", "expected_pid_gone", "agent_pid_gone"]
    }
    text = (
        '[visible_handoffs.bindings.claude]\npane_id = "terminal:8514:ttys000"\n'
        'expected_pid = 850\nagent_pid = 891\nready_pattern = "❯"\n\n'
        '[visible_handoffs.bindings.live]\npane_id = "terminal:1:ttys002"\n'
        'expected_pid = 12140\nagent_pid = 12418\n\n[agents.x]\nkind = "y"\n'
    )
    out = th.strip_stale_bindings(text, ["claude"])
    assert "bindings.claude" not in out and "8514" not in out
    assert "bindings.live" in out and "[agents.x]" in out


async def test_message_routing_uses_the_tty_of_each_tab_not_the_window_title(bridge, monkeypatch):
    # One window, two tabs: ttys000 free shell (selected, so the window title shows it) and
    # ttys002 running the agent. The row for the agent addresses its own tab by TTY and PID.
    monkeypatch.setattr(
        "kirabridge.platform_adapters.terminal_app.sys", SimpleNamespace(platform="darwin")
    )
    manager = SessionManager(bridge.sessions.ports)
    uid = os.getuid()

    async def native(*args, **kwargs):
        return [
            {
                "window_id": 7,
                "tty": "/dev/ttys000",
                "busy": False,
                "selected": True,
                "script_tab_count": 2,
                "tab_index_in_script_window": 1,
                "frontmost": True,
            },
            {
                "window_id": 7,
                "tty": "/dev/ttys002",
                "busy": True,
                "selected": False,
                "script_tab_count": 2,
                "tab_index_in_script_window": 2,
                "frontmost": True,
            },
        ]

    async def communicate():
        return (
            f"{uid} 100 1 ttys000 /usr/bin/login\n{uid} 101 100 ttys000 /bin/zsh\n"
            f"{uid} 200 1 ttys002 /usr/bin/login\n{uid} 201 200 ttys002 /bin/zsh\n"
            f"{uid} 202 201 ttys002 /usr/local/bin/claude\n"
        ).encode(), b""

    async def process(*args, **kwargs):
        return SimpleNamespace(
            communicate=communicate, returncode=0, wait=AsyncMock(return_value=0)
        )

    monkeypatch.setattr(manager.terminal_app, "native", native)
    monkeypatch.setattr(
        "kirabridge.platform_adapters.terminal_app.asyncio.create_subprocess_exec", process
    )
    rows = {row["tty"]: row for row in await manager.terminal_app.catalog()}
    assert set(rows) == {"/dev/ttys000", "/dev/ttys002"}
    agent = rows["/dev/ttys002"]
    assert agent["pane_id"] == "terminal:7:ttys002" and agent["expected_pid"] == 200
    assert agent["processes"][-1]["name"] == "claude"
    assert not agent["identity_ambiguous"] and agent["tab_count"] == 2
    assert "title" not in agent


def test_unreadable_process_list_fails_closed(monkeypatch):
    german = "17135 17134 ttys000 Do 26 Nov 16:01:20 2026 -zsh\n"
    monkeypatch.setattr(
        th.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=german, returncode=0)
    )
    with __import__("pytest").raises(RuntimeError):
        th.read_processes()
