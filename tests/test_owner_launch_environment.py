"""Owner-launched Claude starts with its session-local suggestion setting disabled.

Only the typed launch line of a fresh, owner-created window changes; existing
sessions, other principals, other CLIs and the draft guard are untouched.
"""

import shlex
import sys
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_session_open_ambiguity import manager_for_open, row

from kirabridge.cli_adapters import adapter_for
from kirabridge.session_manager import RECEIVER_OWNER, SessionOpen, launch_command

ARGV = ["/opt/claude/bin/claude", "--session-id", "6f1c2a9e-0000-4000-8000-00000000000a"]


def test_owner_claude_launch_gets_only_its_literal_process_local_environment():
    assert RECEIVER_OWNER == "local"
    assert launch_command("local", "claude", ARGV) == (
        "CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION=false " + shlex.join(ARGV)
    )


@pytest.mark.parametrize(
    ("principal", "agent"),
    [("chatgpt", "claude"), ("local", "codex"), ("local", None), ("local", "unknown-cli")],
)
def test_other_principals_and_clis_keep_the_exact_argv_line(principal, agent):
    assert launch_command(principal, agent, ARGV) == shlex.join(ARGV)


def test_non_literal_adapter_environment_is_refused(monkeypatch):
    from kirabridge.bridge_core.models import BridgeError

    adapter = adapter_for("claude")
    monkeypatch.setattr(adapter, "launch_environment", {"X": "$(touch /tmp/x)"})
    with pytest.raises(BridgeError) as error:
        launch_command("local", "claude", ARGV)
    assert error.value.code == "invalid_arguments"


def test_draft_guard_is_unchanged_by_the_launch_setting():
    from test_claude_visible_adapter import BINDING, screen

    placeholder = adapter_for("claude").observe(screen(['❯ Try "fix lint errors"']), BINDING)
    assert placeholder["state"] == "input_not_empty" and not placeholder["ready"]


@pytest.mark.parametrize("principal", ["local", "chatgpt"])
async def test_open_types_the_owner_environment_only_for_the_owner(
    tmp_path, native_session_platform, principal
):
    shell = row()
    agent = {**shell, "processes": [{"pid": 901, "ppid": shell["expected_pid"], "name": "claude"}]}
    manager, native, _ = manager_for_open(tmp_path, [shell])
    native.catalog = AsyncMock(side_effect=[[shell], [agent]])
    profile = SimpleNamespace(executable=sys.executable)
    manager.ports = replace(
        manager.ports,
        agent_registry=lambda: ({"claude": profile}, {}),
        agent_started=AsyncMock(return_value={"state": "bound"}),
    )
    manager.agent_registry = manager.ports.agent_registry

    result = await manager.open(
        principal, SessionOpen(cwd=str(tmp_path), argv=[sys.executable]), task_id="claude-start"
    )

    assert result["lifecycle"]["agent_process"] == "started"
    parts = shlex.split(native.send_confirmed.await_args.args[1])
    if principal == "local":
        assert parts[0] == "CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION=false" and len(parts) == 2
    else:
        assert len(parts) == 1 and "=" not in parts[0]
    native.send_confirmed.assert_awaited_once()  # one launch, never resent
