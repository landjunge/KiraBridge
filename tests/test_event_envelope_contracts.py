"""Lifecycle/auth/readiness regressions; synthetic configs and owned child processes only."""

import asyncio
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from kirabridge.event_push import EventJournal
from kirabridge.event_readiness import SenderReadiness
from kirabridge.mcp_gateway.event_envelope import EventEnvelope, serve

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "events_contract_backend", ROOT / "integrations/chat-events/serve.py"
)
backend_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend_module)


@pytest.mark.parametrize(
    "failure",
    [
        {"isError": True},
        {"isError": True, "structuredContent": {"error": {"code": "forbidden"}}},
        {"structuredContent": {"success": False}},
        {"structuredContent": {"ok": False}},
        {"structuredContent": {"error": {"code": "forbidden"}}},
        {"structuredContent": {"value": {"error": {"code": "forbidden"}}}},
        {"content": [{"type": "text", "text": '{"error":{"code":"forbidden"}}'}]},
    ],
)
async def test_failed_mcp_envelope_cannot_authorize_even_with_matching_ids(failure):
    data = {"id": "owned", "recipient": "chatgpt", "principal": "chatgpt"}
    result = {**failure, "structuredContent": {**data, **failure.get("structuredContent", {})}}
    backend = object.__new__(backend_module.Backend)
    backend.principal = "chatgpt"
    backend.call = AsyncMock(return_value=result)
    assert await backend.authorize_message("owned") is False
    assert await backend.authorize("owned") is False


async def test_successful_message_can_describe_a_failed_job_without_being_denied():
    backend = object.__new__(backend_module.Backend)
    backend.principal = "chatgpt"
    backend.call = AsyncMock(
        return_value={
            "isError": False,
            "structuredContent": {
                "id": "owned",
                "recipient": "chatgpt",
                "principal": "chatgpt",
                "body": '{"error":"user-authored data"}',
                "processing": {"error": {"code": "job_failed"}},
            },
        }
    )
    assert await backend.authorize_message("owned") is True
    assert await backend.authorize("owned") is True


def front_command(tmp_path, child):
    config = tmp_path / "config.toml"
    config.write_text(
        f"data_dir={json.dumps(str(tmp_path / 'core'))}\n[principals.chatgpt]\n"
        'token_env="SYNTHETIC_EVENTS_TOKEN"\ncapabilities=["task.read","message.read"]\n'
    )
    return [
        sys.executable,
        str(ROOT / "integrations/chat-events/connect.py"),
        "--config",
        str(config),
        "--state",
        str(tmp_path / "events"),
        "--",
        *child,
    ]


def synthetic_env():
    return {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "SYNTHETIC_EVENTS_TOKEN": "SYNTHETIC-" + "x" * 48,
    }


@pytest.mark.parametrize("code", [0, 23])
def test_exact_child_exit_reaches_wrapper_exit(tmp_path, code):
    result = subprocess.run(
        front_command(tmp_path, [sys.executable, "-c", f"raise SystemExit({code})"]),
        input=b"",
        capture_output=True,
        env=synthetic_env(),
        timeout=10,
    )
    assert result.returncode == code, result.stderr.decode()


async def test_host_eof_stops_and_reaps_only_owned_nonending_child():
    reader = asyncio.StreamReader()
    reader.feed_eof()
    outputs = []

    async def write(line):
        outputs.append(line)

    started = time.monotonic()
    async with asyncio.timeout(2):
        code = await serve(
            EventEnvelope(None),
            [sys.executable, "-c", "import sys,time;sys.stdin.buffer.read();time.sleep(60)"],
            reader,
            write,
            drain_timeout=0.05,
            terminate_timeout=0.2,
            kill_timeout=0.2,
        )
    assert code == -signal.SIGTERM
    assert time.monotonic() - started < 1.5


async def test_eof_escalates_for_owned_child_ignoring_term():
    reader = asyncio.StreamReader()
    ready = asyncio.Event()

    async def write(line):
        assert line == b"READY\n"
        ready.set()

    running = asyncio.create_task(
        serve(
            EventEnvelope(None),
            [
                sys.executable,
                "-c",
                "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                "print('READY',flush=True);time.sleep(60)",
            ],
            reader,
            write,
            drain_timeout=0.05,
            terminate_timeout=0.05,
            kill_timeout=0.2,
        )
    )
    async with asyncio.timeout(3):
        await ready.wait()
        reader.feed_eof()
        assert await running == -signal.SIGKILL


@pytest.mark.parametrize("number", [signal.SIGINT, signal.SIGTERM])
def test_wrapper_signal_cleans_up_owned_child_and_reports_signal(tmp_path, number):
    child_pid_file = tmp_path / "child.pid"
    child = [
        sys.executable,
        "-c",
        f"import os,time;open({str(child_pid_file)!r},'w').write(str(os.getpid()));time.sleep(60)",
    ]
    process = subprocess.Popen(
        front_command(tmp_path, child),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=synthetic_env(),
    )
    child_pid = None
    try:
        deadline = time.monotonic() + 5
        while not child_pid_file.exists():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.01)
        child_pid = int(child_pid_file.read_text())
        process.send_signal(number)
        _, stderr = process.communicate(timeout=8)
        assert process.returncode == 128 + number, stderr.decode()
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
        if child_pid is not None:
            try:
                os.kill(
                    child_pid, signal.SIGKILL
                )  # Only the child PID captured from our unique fixture.
            except ProcessLookupError:
                pass


def test_readiness_requires_held_lock_matching_route_and_fresh_marker(config, tmp_path):
    import fcntl

    journal = EventJournal(tmp_path / "events")
    state = tmp_path / "events"
    ready = SenderReadiness(journal, config, "local", ["callbacks.example.test"])
    assert not ready.is_ready()
    fd = os.open(state / "sender.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert not ready.is_ready()
        ready.publish("ready")
        assert ready.is_ready()
        assert not SenderReadiness(journal, config, "other", ["callbacks.example.test"]).is_ready()
        assert not SenderReadiness(journal, config, "local", ["other.example.test"]).is_ready()
        ready.publish("unready")
        assert not ready.is_ready()
        ready.publish("ready")
        row = json.loads(
            journal.db.execute(
                "SELECT value FROM settings WHERE key='sender_readiness'"
            ).fetchone()[0]
        )
        row["heartbeat"] -= 60
        journal.db.execute(
            "UPDATE settings SET value=? WHERE key='sender_readiness'", (json.dumps(row),)
        )
        assert not ready.is_ready()
        ready.publish("ready")
        assert ready.is_ready()
        fcntl.flock(fd, fcntl.LOCK_UN)
        assert not ready.is_ready()
    finally:
        os.close(fd)
        journal.db.close()


async def test_unready_envelope_withholds_capability_but_preserves_existing_wire():
    class Push:
        def event_list(self):
            raise AssertionError("unready handler must not inspect event data")

    envelope = EventEnvelope(Push(), ready=lambda: False)
    request = b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
    assert await envelope.from_host(request) == (None, request)
    result = b'{"jsonrpc":"2.0","id":1,"result":{"capabilities":{"tools":{}}}}\n'
    assert envelope.from_child(result) == result
    response, forwarded = await envelope.from_host(
        b'{"jsonrpc":"2.0","id":2,"method":"events/list"}\n'
    )
    assert forwarded is None
    assert json.loads(response)["error"]["data"]["reason"] == "event_sender_unavailable"
    request = b'{"jsonrpc":"2.0","id":3,"method":"tools/list"}\n'
    assert await envelope.from_host(request) == (None, request)


async def test_owned_failed_task_record_is_authorized_without_accepting_failed_envelope():
    backend = object.__new__(backend_module.Backend)
    backend.principal = "chatgpt"
    record = {
        "id": "owned",
        "principal": "chatgpt",
        "api_version": "1",
        "state": "failed",
        "operation": "file.list",
        "request_sha256": "a" * 64,
        "error": {"code": "execution_failed"},
        "result": {"success": False},
    }
    backend.call = AsyncMock(
        return_value={
            "isError": False,
            "structuredContent": record,
            "content": [{"type": "text", "text": json.dumps(record)}],
        }
    )
    assert await backend.authorize("owned") is True
    backend.call = AsyncMock(return_value={"isError": True, "structuredContent": record})
    assert await backend.authorize("owned") is False
