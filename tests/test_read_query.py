import sys
from types import SimpleNamespace

import pytest
from conftest import request, submit
from pydantic import ValidationError

from kirabridge.bridge_core.models import BridgeError, State
from kirabridge.read_query import ReadQuery, read_query


def test_direct_file_reads_are_bounded_scoped_and_do_not_create_tasks(bridge, config, tmp_path):
    root = config.principals["local"].roots[0]
    from pathlib import Path

    p = Path(root) / "codex-demo.log"
    p.write_bytes(b"old\n" + b"x" * 100 + b"latest\n")
    result = read_query(
        bridge, "local", ReadQuery(operation="file.read", path=str(p), tail=True, max_bytes=7)
    )
    assert result["text"] == "latest\n" and result["bytes"] == 7
    first = read_query(bridge, "local", ReadQuery(operation="file.read", path=str(p), max_bytes=4))
    assert first["text"] == "old\n" and first["truncated"]
    assert (
        read_query(
            bridge, "local", ReadQuery(operation="file.read", path=str(p), offset=104, max_bytes=7)
        )["text"]
        == "latest\n"
    )
    assert bridge.store.db.execute("select count(*) from tasks").fetchone()[0] == 0
    for denied in [str(tmp_path / "outside"), str(config.state_path / "bridge.sqlite3")]:
        with pytest.raises(BridgeError, match="allowed|available"):
            read_query(bridge, "local", ReadQuery(operation="file.read", path=denied))
    link = Path(root) / "link"
    link.symlink_to(p)
    with pytest.raises(BridgeError):
        read_query(bridge, "local", ReadQuery(operation="file.read", path=str(link)))
    config.principals["local"].capabilities.remove("file.read")
    with pytest.raises(BridgeError, match="Capability"):
        read_query(bridge, "local", ReadQuery(operation="file.read", path=str(p)))


@pytest.mark.parametrize(
    "values",
    [
        {"operation": "file.write", "path": "/tmp/no"},
        {"operation": "file.read", "path": "/tmp/no", "max_bytes": 65537},
        {"operation": "file.read", "path": "/tmp/no", "offset": -1},
        {"operation": "file.read", "path": "/tmp/no", "tail": True, "offset": 1},
        {"operation": "terminal.output", "task_id": "x", "path": "/tmp/no"},
    ],
)
def test_direct_reads_reject_invalid_or_mutating_requests(values):
    with pytest.raises(ValidationError):
        ReadQuery.model_validate(values)


@pytest.mark.parametrize(
    "values",
    [
        {"operation": "session.read", "pane_id": "terminal:123:ttys004"},
        {"operation": "session.read", "pane_id": "terminal:123:ttys004", "expected_pid": 0},
        {"operation": "session.read", "pane_id": "%1", "expected_pid": 1, "text": "must not send"},
        {"operation": "session.catalog", "pane_id": "%1", "expected_pid": 1},
        {"operation": "file.read", "path": "/tmp/file", "pane_id": "%1"},
    ],
)
def test_session_query_requires_exact_read_only_selector(values):
    with pytest.raises(ValidationError):
        ReadQuery.model_validate(values)


async def test_cached_read_tool_discovers_reads_and_rejects_stale_pid(bridge, config, monkeypatch):
    from kirabridge.read_query import read_query_async

    config.principals["local"].capabilities += ["session.inspect"]
    config.principals["local"].permission_level = "medium"
    selected = {"pane_id": "terminal:123:ttys004", "expected_pid": 345}
    reads = []

    async def catalog(principal, *, transport=None):
        bridge.security.principal(principal, "session.inspect")
        return {"sessions": [selected], "status": "available"}

    async def native(source, *, mutation=False):
        assert not mutation
        reads.append(source)
        return "bounded-output"

    monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    monkeypatch.setattr(bridge.sessions.terminal_app, "native", native)
    result = await read_query_async(bridge, "local", ReadQuery(operation="session.catalog"))
    assert result["sessions"] == [selected] and not reads
    with pytest.raises(BridgeError, match="exact current"):
        await read_query_async(
            bridge,
            "local",
            ReadQuery(operation="session.read", **{**selected, "expected_pid": 346}),
        )
    assert not reads
    result = await read_query_async(
        bridge, "local", ReadQuery(operation="session.read", max_bytes=6, **selected)
    )
    assert result["text"] == "output" and len(reads) == 1
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    config.principals["local"].capabilities.remove("session.inspect")
    with pytest.raises(BridgeError, match="Capability"):
        await read_query_async(bridge, "local", ReadQuery(operation="session.read", **selected))


@pytest.mark.asyncio
async def test_terminal_output_is_real_bounded_and_owner_checked(bridge, config):
    async with bridge:
        value = request(
            "terminal.execute",
            {
                "argv": [sys.executable, "-c", "print('DIRECT_READ_OK')"],
                "cwd": config.principals["local"].roots[0],
            },
            task_id="read-output",
        )
        submit(bridge, value)
        await bridge.tasks.wait("local", value.task_id)
        result = read_query(
            bridge, "local", ReadQuery(operation="terminal.output", task_id=value.task_id)
        )
        assert result["stdout"] == "DIRECT_READ_OK\n" and result["output_available"]
        assert (
            read_query(
                bridge,
                "local",
                ReadQuery(operation="terminal.output", task_id=value.task_id, max_bytes=6),
            )["stdout"]
            == "DIRECT"
        )
        with pytest.raises(BridgeError, match="not found|Not found"):
            read_query(
                bridge, "other", ReadQuery(operation="terminal.output", task_id=value.task_id)
            )
        bridge.terminal.sessions.clear()
        saved = read_query(
            bridge, "local", ReadQuery(operation="terminal.output", task_id=value.task_id)
        )
        assert saved["stdout"] == "DIRECT_READ_OK\n" and saved["source"] == "persisted_task_result"


@pytest.mark.parametrize(
    "operation,visible",
    [
        ("terminal.visible", True),
        ("terminal.execute", True),
        ("admin.execute", True),
        ("admin.execute", False),
    ],
)
def test_owned_visible_and_admin_output_is_available_without_reexecution(
    bridge, config, operation, visible
):
    config.principals["local"].capabilities.append("session.inspect")
    value = request(
        operation,
        {"argv": [sys.executable, "-V"], "cwd": config.principals["local"].roots[0]},
        task_id="saved-visible-output",
    )
    submit(bridge, value)
    bridge.store.claim("fixture", 30)
    bridge.store.transition(value.task_id, State.RUNNING, {"isolated_fixture": True})
    source = (
        {
            "terminal_output": "screen 😀 history",
            "output_scope": "visible screen; includes prompt/history",
        }
        if visible
        else {"stdout": "ADMIN_OUTPUT", "stderr": ""}
    )
    bridge.store.transition(
        value.task_id, State.COMPLETED, {"isolated_fixture": True}, result=source
    )
    before = bridge.store.get(value.task_id)
    result = read_query(
        bridge, "local", ReadQuery(operation="terminal.output", task_id=value.task_id, max_bytes=11)
    )
    key = "terminal_output" if visible else "stdout"
    assert result[key] == ("screen 😀" if visible else "ADMIN_OUTPU")
    assert result["output_available"] and result["truncated"] and result["bytes"] <= 11
    if visible:
        assert result["output_scope"] == source["output_scope"]
        assert result["stdout"] == ""  # A captured viewport is not command stdout.
    with pytest.raises(BridgeError) as error:
        read_query(bridge, "other", ReadQuery(operation="terminal.output", task_id=value.task_id))
    assert error.value.code == "not_found"
    config.principals["local"].capabilities.remove("process.inspect")
    with pytest.raises(BridgeError) as error:
        read_query(bridge, "local", ReadQuery(operation="terminal.output", task_id=value.task_id))
    assert error.value.code == "forbidden"
    assert bridge.store.get(value.task_id) == before


@pytest.mark.parametrize("key", ["stdout", "terminal_output"])
def test_terminal_output_utf8_boundary_does_not_expand_byte_budget(key):
    # Ownership and capability checks are covered using actual stored tasks above.
    # This fixture isolates the response's byte boundary without running a command.
    def no_buffer(*_):
        raise BridgeError("not_found", "No live buffer")

    bridge = SimpleNamespace(
        security=SimpleNamespace(principal=lambda *_: None),
        task=lambda *_: {
            "operation": "terminal.execute",
            "state": "completed",
            "result": {key: "screen 😀"},
        },
        terminal=SimpleNamespace(inspect=no_buffer),
    )
    result = read_query(
        bridge, "local", ReadQuery(operation="terminal.output", task_id="saved", max_bytes=8)
    )
    assert result[key] == "screen "
    assert len(result[key].encode("utf-8")) <= 8
    assert result["truncated"]
