import asyncio
import hashlib
import json
import os
import sys
from types import SimpleNamespace

import pytest
from conftest import request, submit

from kirabridge import development_status as status
from kirabridge.bridge_core.config import AgentConfig
from kirabridge.bridge_core.models import BridgeError
from kirabridge.terminal_manager import Session


def test_ps_parser_exact_names_no_arguments_foreign_uid_or_paths():
    raw = b"""501 11 1 /private/personal-path/bin/codex
501 12 1 grok
501 13 1 /Applications/Codex.app/Contents/MacOS/Codex
501 14 1 /Applications/ChatGPT.app/Contents/MacOS/ChatGPT
501 15 1 /Applications/Utilities/Terminal.app/Contents/MacOS/Terminal
502 16 1 codex
501 17 1 my-codex-wrapper
501 18 1 codex --prompt SECRET_ARGUMENT
501 19 1 node
501 20 1 grok-unrelated
bad 21 1 codex
501 notpid 1 codex
501 22 -1 grok
"""
    result = status._parse_processes(raw, 501)
    assert [row["pid"] for row in result["processes"]] == [11, 12, 13, 14, 15]
    serialized = json.dumps(result)
    for hidden in ("SECRET_ARGUMENT", "personal-path", "my-codex-wrapper", "node", "502"):
        assert hidden not in serialized
    for row in result["processes"]:
        assert row["ownership"] == "observed_only"
        assert row["working_status"] == row["session_status"] == "unknown"


def test_ps_parser_caps_bytes_records_and_hides_other_principal_descendants():
    raw = b"501 10 1 codex\n501 11 10 node\n501 12 11 grok\n501 13 1 codex\n"
    assert [row["pid"] for row in status._parse_processes(raw, 501, {10})["processes"]] == [13]
    many = b"".join(f"501 {pid} 1 codex\n".encode() for pid in range(100, 1000))
    result = status._parse_processes(many, 501)
    assert len(result["processes"]) == status.PS_RECORD_LIMIT and result["truncated"]
    assert status._parse_processes(b"x" * (status.PS_BYTE_LIMIT + 1), 501)["truncated"]


async def test_agent_status_filters_owned_tasks_and_terminal_without_reading_outputs(
    bridge, config, monkeypatch
):
    secret = "never-return-prompt-stdout-or-token"
    for principal in ("local", "other"):
        value = request(
            "agent.execute",
            {"agent": "codex", "prompt": secret, "cwd": config.principals[principal].roots[0]},
            task_id="task-" + principal,
        )
        submit(bridge, value, principal)
        bridge.store.db.execute("UPDATE tasks SET state='running' WHERE id=?", (value.task_id,))
        process = SimpleNamespace(pid=11 if principal == "local" else 12, returncode=None)
        bridge.terminal.sessions[value.task_id] = Session(
            value.task_id, principal, process, stdout=bytearray(secret.encode())
        )

    async def observe(excluded):
        assert excluded == {12}
        return {
            "status": "observed",
            **status._parse_processes(
                b"501 11 1 codex\n501 12 1 grok\n501 13 1 grok\n", 501, excluded
            ),
        }

    monkeypatch.setattr(status, "_observe_processes", observe)
    result = await status.agent_status(bridge, "local")
    assert [row["id"] for row in result["managed_tasks"]] == ["task-local"]
    assert [row["task_id"] for row in result["managed_terminal_sessions"]] == ["task-local"]
    assert [row["pid"] for row in result["observed_processes"]] == [11, 13]
    assert result["observed_processes"][0]["ownership"] == "bridge_managed"
    assert result["observed_processes"][1]["ownership"] == "observed_only"
    serialized = json.dumps(result)
    assert secret not in serialized and "task-other" not in serialized
    assert not result["project_completion_verified"]


async def test_agent_status_is_capped_and_capability_gated(bridge, config, monkeypatch):
    async def observe(_):
        return {"status": "observed", "processes": [], "truncated": False}

    monkeypatch.setattr(status, "_observe_processes", observe)
    config.max_waiting_tasks = 200  # listing bound, not the waiting-task cap
    for number in range(105):
        submit(bridge, request("clipboard.info", task_id=f"bounded-{number}"))
    result = await status.agent_status(bridge, "local")
    assert len(result["managed_tasks"]) == 100 and result["tasks_truncated"]
    config.principals["local"].capabilities.remove("agent.inspect")
    with pytest.raises(BridgeError, match="Capability not granted"):
        await status.agent_status(bridge, "local")


async def test_existing_terminal_handles_are_visible_without_reading_or_claiming_ownership(
    bridge, config, monkeypatch
):
    config.principals["local"].capabilities += ["session.inspect"]
    target = {
        "pane_id": "terminal:123:ttys004",
        "expected_pid": 345,
        "window_id": 123,
        "tty": "/dev/ttys004",
        "busy": True,
    }

    async def catalog(principal, *, transport=None):
        assert principal == "local"
        return {"status": "available", "sessions": [target]}

    async def no_read(*args, **kwargs):
        pytest.fail("discovery must not read terminal output")

    monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    monkeypatch.setattr(bridge.sessions, "read", no_read)
    result = await status.agent_status(bridge, "local")
    assert result["interactive_terminal_sessions"] == [target]
    assert result["managed_terminal_sessions"] == []
    assert result["terminal_access"]["availability"] == "available"
    config.principals["local"].capabilities.remove("session.inspect")
    result = await status.agent_status(bridge, "local")
    assert result["interactive_terminal_sessions"] == []
    assert result["terminal_access"]["availability"] == "not_granted"


def test_permissions_snapshot_is_explicit_whitelist_and_checks_disk_drift(
    bridge, config, tmp_path, monkeypatch
):
    secret = "TOKEN_AND_CONFIG_CONTENT_MUST_NOT_ESCAPE"
    config.principals["local"].token_env = secret
    config.credentials_file = secret
    config.tls_key = secret
    config.agents["codex"] = AgentConfig(
        kind="codex",
        executable="/opt/bin/codex",
        sandbox_mode="workspace-write",
        api_key_env=secret,
        model=secret,
    )
    config.agents["not-allowed"] = AgentConfig(kind="private-kind", executable=secret)
    source = tmp_path / "settings.toml"
    source.write_text(secret)
    config._source_path = str(source)
    bridge.runtime["config_sha256"] = hashlib.sha256(secret.encode()).hexdigest()
    bridge.runtime["unknown_sensitive_field"] = secret

    def no_dump(*_, **__):
        raise AssertionError("No generic configuration serialization allowed")

    monkeypatch.setattr(type(config), "model_dump", no_dump)
    first = status.permissions_snapshot(bridge, "local")
    assert first["configuration_file"]["status"] == "matches_loaded"
    assert first["source_files"]["status"] == "matches_loaded"
    assert first["config_path"] == str(source)
    assert first["agent_profiles"] == [
        {
            "name": "codex",
            "kind": "codex",
            "sandbox_mode": "workspace-write",
            "executable": "/opt/bin/codex",
            "local_tools_available": False,
        }
    ]
    assert not first["allow_any_executable"]
    assert first["effective_terminal_roots"] == config.principals["local"].roots
    assert secret not in json.dumps(first)
    source.write_text("changed-secret-do-not-output")
    changed = status.permissions_snapshot(bridge, "local")["configuration_file"]
    assert changed["changed_on_disk"] is True and changed["status"] == "changed_on_disk"
    source.unlink()
    assert (
        status.permissions_snapshot(bridge, "local")["configuration_file"]["status"]
        == "unavailable"
    )


def test_permissions_never_reads_ungranted_configuration(bridge, config, monkeypatch):
    config.principals["local"].capabilities.remove("bridge.health")
    monkeypatch.setattr(status, "_configuration_drift", lambda *_: pytest.fail("must not read"))
    with pytest.raises(BridgeError, match="Capability not granted"):
        status.permissions_snapshot(bridge, "local")


def test_config_hash_rejects_symlink_fifo_and_size_cap(tmp_path):
    file = tmp_path / "actual"
    file.write_text("secret")
    symlink = tmp_path / "link"
    symlink.symlink_to(file)
    with pytest.raises(OSError):
        status._file_hash(symlink, 32)
    with pytest.raises(OSError):
        status._file_hash(file, 2)
    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "fifo"
        os.mkfifo(fifo)
        with pytest.raises(OSError):
            status._file_hash(fifo, 32)


async def test_ps_command_is_absolute_own_uid_metadata_only_and_timeout_is_bounded(monkeypatch):
    captured = {}

    class Process:
        returncode = None
        killed = False

        class Reader:
            async def read(self, _):
                await asyncio.sleep(30)

        stdout = Reader()

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            return self.returncode

    process = Process()

    async def spawn(*argv, **kwargs):
        captured.update(argv=argv, kwargs=kwargs)
        return process

    monkeypatch.setattr(status.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(status, "PS_TIMEOUT", 0.02)
    result = await status._observe_processes(set())
    assert result["status"] == "timeout" and process.killed
    assert captured["argv"][0] in {"/bin/ps", "/usr/bin/ps"}
    columns = "uid=,pid=,ppid=,ucomm=" if sys.platform == "darwin" else "uid=,pid=,ppid=,comm="
    assert captured["argv"][1:] == ("-U", str(os.getuid()), "-o", columns)
    assert "args" not in " ".join(captured["argv"])
    assert set(captured["kwargs"]["env"]) == {"PATH", "LC_ALL"}


async def test_real_ps_metadata_probe_is_read_only_and_bounded():
    result = await status._observe_processes(set())
    assert result["status"] in {"observed", "byte_limit", "unsupported", "unavailable"}
    assert len(result["processes"]) <= 256
    assert all(
        row["comm"] in status.AGENT_NAMES or row["comm"] in status.HOST_NAMES
        for row in result["processes"]
    )
    assert not any(
        "args" in row or "environment" in row or "stdout" in row for row in result["processes"]
    )


def test_permissions_reports_explicit_full_terminal_fields_without_granting_them(bridge, config):
    # model_copy also permits this forward-compatible test on the parent base
    # before its separately implemented PrincipalConfig fields are integrated.
    config.principals["local"] = config.principals["local"].model_copy(
        update={"allow_any_executable": True, "terminal_roots": ["/"]}
    )
    result = status.permissions_snapshot(bridge, "local")
    assert result["allow_any_executable"] is True
    assert result["terminal_roots"] == result["effective_terminal_roots"] == ["/"]
    other = status.permissions_snapshot(bridge, "other")
    assert not other["allow_any_executable"]
    assert other["effective_terminal_roots"] == config.principals["other"].roots


@pytest.mark.parametrize(
    "level,legacy,required", [("full", "manual", False), ("ask", "automatic", True)]
)
def test_policy_inspection_approval_uses_effective_operation_decision(
    bridge, config, level, legacy, required
):
    policy = config.principals["local"]
    policy.permission_level = level
    policy.approval_mode = legacy
    snapshot = status.permissions_snapshot(bridge, "local")
    assert snapshot["approval_mode"] == legacy
    assert snapshot["approval_required"] is required
    assert snapshot["permission_decision"]["operation"] == "policy.inspect"
    assert snapshot["permission_decision"]["approval_required"] is required
