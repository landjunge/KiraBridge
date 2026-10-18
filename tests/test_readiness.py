import json
from pathlib import Path

import pytest
from conftest import request
from pydantic import ValidationError

from kirabridge.bridge_core.config import load_config
from kirabridge.bridge_core.models import BridgeError
from kirabridge.readiness import ReadinessInput, readiness, runtime_snapshot


async def test_project_read_roots_do_not_expand_writes_terminal_or_other_identity(bridge, tmp_path):
    project = tmp_path / "Projects" / "help" / ".worktrees" / "review" / "docs"
    project.mkdir(parents=True)
    file = project / "handoff.md"
    file.write_text("owned handoff")
    bridge.config.principals["local"].read_roots = [str(tmp_path / "Projects" / "help")]
    bridge.config.principals["local"].approval_mode = "automatic"
    bridge.config.principals["other"].approval_mode = "automatic"

    async def run(op, args, key, principal="local"):
        value = request(op, args, task_id=key)
        bridge.prepare(principal, value)
        return await bridge.tasks.wait(principal, key)

    async with bridge:
        result = await run("file.read", {"path": str(file)}, "read")
        assert result["result"]["text"] == "owned handoff"
        assert (await run("file.list", {"path": str(project)}, "list"))["state"] == "completed"
        denied = await run("file.read", {"path": str(file)}, "other", "other")
        assert denied["error"]["code"] == "path_denied" and denied["started"] is None
        write = await run(
            "file.write", {"path": str(file), "text": "bad", "overwrite": True}, "write"
        )
        assert write["error"]["code"] == "path_denied" and file.read_text() == "owned handoff"
        executable = bridge.config.principals["local"].executables[0]
        cwd = await run(
            "terminal.execute", {"argv": [executable, "-V"], "cwd": str(project)}, "cwd"
        )
        assert cwd["error"]["code"] == "path_denied" and cwd["started"] is None


async def test_readiness_reports_specific_denials_without_contents_or_execution(bridge, tmp_path):
    policy = bridge.config.principals["local"]
    root = Path(policy.roots[0])
    file = root / "readable.md"
    file.write_text("PRIVATE_CONTENT_MUST_NOT_APPEAR")
    outside = tmp_path / "outside.md"
    outside.write_text("OUTSIDE")
    (root / "escape").symlink_to(outside)
    policy.executables = ["/missing/allowed-program"]
    async with bridge:
        before = bridge.store.db.total_changes  # The dispatcher has recorded its actual load.
        result = readiness(
            bridge,
            "local",
            ReadinessInput(
                read_paths=[
                    str(file),
                    str(outside),
                    str(root / "escape"),
                    str(root / "missing"),
                    str(bridge.config.state_path / "bridge.sqlite3"),
                ],
                executables=["/bin/cat", "/usr/bin/python3", "/missing/allowed-program"],
            ),
        )
        assert result["dispatcher_active"]
        assert result["requested_prerequisites_ready"] is False
        assert [x["code"] for x in result["read_path_checks"]] == [
            "available",
            "path_denied",
            "path_unavailable",
            "path_missing",
            "path_denied",
        ]
        assert [x["code"] for x in result["executable_checks"]] == [
            "executable_denied",
            "executable_denied",
            "executable_unavailable",
        ]
        assert "PRIVATE_CONTENT" not in json.dumps(result)
        assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
        assert not bridge.terminal.sessions
        assert readiness(bridge, "local", ReadinessInput())["requested_prerequisites_ready"] is None
        good = readiness(bridge, "local", ReadinessInput(read_paths=[str(file)]))
        assert good["requested_prerequisites_ready"] is True
        assert bridge.store.db.total_changes == before


async def test_readiness_preserves_file_capabilities_and_principal_boundary(bridge, tmp_path):
    policy = bridge.config.principals["local"]
    policy.capabilities = ["bridge.health"]
    target = Path(policy.roots[0]) / "file"
    target.write_text("not allowed")
    result = readiness(bridge, "local", ReadinessInput(read_paths=[str(target)]))
    assert result["read_path_checks"][0]["code"] == "forbidden"
    assert all(not x["ok"] for x in result["root_checks"])
    with pytest.raises(BridgeError, match="Capability not granted"):
        readiness(bridge, "unknown", ReadinessInput())
    with pytest.raises(ValidationError):
        ReadinessInput(read_paths=[str(target)] * 17)


def test_config_origin_snapshot_does_not_change_after_file_edit(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('concurrency=1\n[principals.chatgpt]\nread_roots=["/project"]\n')
    config = load_config(str(path))
    snapshot = runtime_snapshot(config)
    assert snapshot["config_path"] == str(path)
    path.write_text(path.read_text().replace("concurrency=1", "concurrency=2"))
    assert runtime_snapshot(config)["config_sha256"] == snapshot["config_sha256"]
    assert runtime_snapshot(load_config(str(path)))["config_sha256"] != snapshot["config_sha256"]
    assert "read_roots" in config.principals["chatgpt"].model_dump()
