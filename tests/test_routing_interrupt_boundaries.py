"""Exactly the two independent-review interrupt boundaries; no provider calls."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_routing_receipt_failures import writable as fixture_factory

from kirabridge.capability_routing import launcher, process


@pytest.mark.parametrize("partial", [False, True])
def test_final_interrupt_persists_unknown_and_preserves_partial(tmp_path, monkeypatch, partial):
    source, runtime, task, _ = fixture_factory.__wrapped__(tmp_path, monkeypatch)
    write = launcher._write_new
    interrupted = False

    def fails_once(path, payload):
        nonlocal interrupted
        if path.name.endswith(".tmp") and not interrupted:
            interrupted = True
            if partial:
                path.write_bytes(b"original-partial-stage")
            raise KeyboardInterrupt("synthetic final-write interruption")
        return write(path, payload)

    monkeypatch.setattr(launcher, "_write_new", fails_once)
    calls = []

    def completed(*args, **kwargs):
        calls.append(1)
        return SimpleNamespace(
            returncode=0, stdout=b"completed", stderr=b"", owned_process_pid=12345
        )

    with pytest.raises(KeyboardInterrupt):
        launcher.launch(source, runtime, task, execute=True, runner=completed)
    record = json.loads((Path(runtime.state_dir) / (task.task_id + ".json")).read_text())
    assert record["state"] == "unknown" and record["effect_boundary_crossed"] is True
    assert record["process_exit_confirmed"] is True and record["owned_process_pid"] == 12345
    assert record["exit_code"] == 0 and record["failure_phase"] == "final_receipt_persistence"
    if partial:
        assert (
            Path(runtime.state_dir) / (task.task_id + ".tmp")
        ).read_bytes() == b"original-partial-stage"
    with pytest.raises(launcher.RoutingError, match="already admitted"):
        launcher.launch(source, runtime, task, execute=True, runner=completed)
    assert calls == [1]


def test_unconfirmed_failure_journal_raises_explicit_uncertain(tmp_path, monkeypatch):
    source, runtime, task, _ = fixture_factory.__wrapped__(tmp_path, monkeypatch)

    def unavailable(*args, **kwargs):
        raise KeyboardInterrupt("synthetic unavailable final journal")

    monkeypatch.setattr(launcher, "_save_result", unavailable)
    with pytest.raises(launcher.OutcomeUncertain, match="after process boundary"):
        launcher.launch(
            source,
            runtime,
            task,
            execute=True,
            runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout=b"", stderr=b""),
        )


def test_thread_constructor_interrupt_cleans_only_owned_child(monkeypatch):
    class Child:
        pid = 123456
        stdin = stdout = stderr = None
        returncode = None
        killed = waited = 0

        def poll(self):
            return self.returncode

        def kill(self):
            self.killed += 1

        def wait(self, *, timeout):
            assert timeout == 5
            self.waited += 1
            self.returncode = -9

    owned = Child()
    monkeypatch.setattr(process.subprocess, "Popen", lambda *a, **k: owned)

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt("synthetic Thread constructor")

    monkeypatch.setattr(process.threading, "Thread", interrupted)
    with pytest.raises(KeyboardInterrupt) as error:
        process.run_bounded(["fixture"], input=b"", cwd="/", timeout=1, env={})
    assert owned.killed == owned.waited == 1
    assert error.value.owned_process_pid == owned.pid
    assert error.value.owned_process_exit_confirmed is True
