"""A stop during failed reporting must not start additional status subprocesses."""

import asyncio
import importlib.util
import json
import signal
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_stop_during_worker_report_does_not_start_more_reports(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "loop_reporting_stop", Path(__file__).parents[1] / "scripts/bigplan_loop.py"
    )
    runtime = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, runtime)
    spec.loader.exec_module(runtime)
    loop = asyncio.get_running_loop()
    signal_handlers = {}
    monkeypatch.setattr(
        loop, "add_signal_handler", lambda sig, callback: signal_handlers.setdefault(sig, callback)
    )
    profile = {"instance": "fixture", "cwd": str(tmp_path), "workspace": str(tmp_path / "desk")}
    cfg = SimpleNamespace(state_path=tmp_path / "state", port=0, autonext=SimpleNamespace(cards=[]))
    monkeypatch.setattr(runtime, "load_profile", lambda path: profile)
    monkeypatch.setattr(runtime, "configuration", lambda value: cfg)
    workers = [
        {"id": f"work-{i}", "assignee": "codex", "state": "completed", "core_task_id": f"task-{i}"}
        for i in range(3)
    ]

    class FakeDB:
        def execute(self, query):
            if "FROM team_work" in query:
                return SimpleNamespace(fetchall=lambda: workers)
            assert "FROM autonext_items" in query
            return []

    class FakeBridge:
        def __init__(self, config):
            self.store = SimpleNamespace(db=FakeDB())
            self.autonext = SimpleNamespace(
                inspect=lambda: {"state": "disabled", "reason": "fixture"}
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class FakeSocket:
        def bind(self, address):
            pass

        def listen(self, backlog):
            pass

        def getsockname(self):
            return ("127.0.0.1", 12345)

        def close(self):
            pass

    class FakeServer:
        def __init__(self, config):
            self.started = False
            self.closed = asyncio.Event()

        @property
        def should_exit(self):
            return self.closed.is_set()

        @should_exit.setter
        def should_exit(self, value):
            if value:
                self.closed.set()

        async def serve(self, sockets):
            self.started = True
            await self.closed.wait()

    monkeypatch.setattr(runtime, "Bridge", FakeBridge)
    monkeypatch.setattr(runtime, "socket", SimpleNamespace(socket=FakeSocket))
    monkeypatch.setattr(
        runtime, "uvicorn", SimpleNamespace(Server=FakeServer, Config=lambda *a, **k: None)
    )
    monkeypatch.setattr(runtime, "create_http_app", lambda bridge: None)
    monkeypatch.setattr(runtime, "seed", lambda bridge: ("team", "anchor"))

    async def advance(*args):
        return None, None

    monkeypatch.setattr(runtime, "advance", advance)
    monkeypatch.setattr(runtime, "process_completions", lambda *args: {"pending": 0})
    reports = []

    def worker_report(profile, work, report_id=None):
        reports.append(work["id"])
        # Model SIGTERM while the status subprocess is still running. Its timeout
        # returns UNKNOWN, after which the controller must stop scheduling reports.
        loop.call_soon_threadsafe(signal_handlers[signal.SIGTERM])
        return {"report_id": "report-1", "state": "unknown", "error": "report_timeout"}

    def coordinator_report(*args):
        reports.append("coordinator")
        return {"state": "sent", "error": None}

    monkeypatch.setattr(runtime, "report_worker", worker_report)
    monkeypatch.setattr(runtime, "report", coordinator_report)
    await asyncio.wait_for(runtime.serve(tmp_path / "profile.json"), timeout=5)
    assert reports == ["work-0"]
    status = json.loads((cfg.state_path / "status.json").read_text())
    assert status["reporting"]["workers"]["work-0"]["state"] == "unknown"
    assert status["reporting"]["coordinator"] is None


@pytest.fixture
def runtime(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "loop_reporting_hygiene", Path(__file__).parents[1] / "scripts/bigplan_loop.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


async def exercise_loop(
    runtime, tmp_path, monkeypatch, observations, *, result_state="sent", crash=False
):
    """Run actual serve iterations against in-memory work, without agents or transports."""
    loop = asyncio.get_running_loop()
    handlers = {}
    monkeypatch.setattr(
        loop, "add_signal_handler", lambda sig, callback: handlers.setdefault(sig, callback)
    )
    profile = {
        "instance": "fixture",
        "cwd": str(tmp_path),
        "workspace": str(tmp_path / "desk"),
        "completion_target": "fixture",
        "report_cli": "/fixture/reporter",
        "board_id": "fixture-board",
        "threaddesk_source": "/fixture/source",
    }
    cfg = SimpleNamespace(
        state_path=tmp_path / "state",
        port=0,
        autonext=SimpleNamespace(cards=[SimpleNamespace(task_id="fixture")]),
    )
    monkeypatch.setattr(runtime, "load_profile", lambda path: profile)
    monkeypatch.setattr(runtime, "configuration", lambda value: cfg)
    current = {"index": -1}
    reports, snapshots = [], []

    def observation():
        return observations[current["index"]]

    class DB:
        def execute(self, query):
            if "FROM team_work" in query:
                return SimpleNamespace(fetchall=lambda: observation().get("workers", []))
            return [{"task_id": name} for name in observation().get("done", [])]

    class Bridge:
        def __init__(self, config):
            self.store = SimpleNamespace(db=DB())
            self.autonext = SimpleNamespace(inspect=lambda: observation()["state"])
            self.completions = SimpleNamespace(wait=self.wait)

        async def wait(self, *args, **kwargs):
            if current["index"] == len(observations) - 1:
                handlers[signal.SIGTERM]()
            await asyncio.sleep(0)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Socket:
        def bind(self, address):
            pass

        def listen(self, backlog):
            pass

        def getsockname(self):
            return ("127.0.0.1", 12345)

        def close(self):
            pass

    class Server:
        def __init__(self, config):
            self.started = False
            self.closed = asyncio.Event()

        @property
        def should_exit(self):
            return self.closed.is_set()

        @should_exit.setter
        def should_exit(self, value):
            if value:
                self.closed.set()

        async def serve(self, sockets):
            self.started = True
            await self.closed.wait()

    async def advance(*args):
        current["index"] += 1
        return None, observation().get("intake")

    def published_status():
        status = json.loads((cfg.state_path / "status.json").read_text())
        # Readers use existence as the readiness boundary, including while the
        # first reporter is still running. A reservation must never publish a
        # partial status document or a previous iteration's runtime snapshot.
        assert status["autonext"] == observation()["state"]
        assert status["completions"] == {"pending": 0}
        assert status["pid"] == runtime.os.getpid()
        assert status["execution_scope"] == "separate_managed_session"
        assert "continuation" in status
        return status

    def worker_report(profile, work, report_id):
        pending = published_status()["reporting"]["workers"][work["id"]]
        assert pending["report_id"] == report_id
        assert pending["state"] == "unknown"
        reports.append((work["id"], work["state"], report_id))
        if crash:
            raise RuntimeError("simulated crash after effect")
        return {
            "report_id": report_id,
            "state": result_state,
            "error": None if result_state == "sent" else "report_timeout",
            "automatic_retry": False,
        }

    def coordinator_report(profile, done, text, mode, report_id):
        pending = published_status()["reporting"]["coordinator"]
        assert pending["report_id"] == report_id
        assert pending["state"] == "unknown"
        reports.append(("coordinator", mode, report_id))
        if crash:
            raise RuntimeError("simulated crash after effect")
        return {
            "report_id": report_id,
            "state": result_state,
            "error": None if result_state == "sent" else "report_timeout",
            "automatic_retry": False,
        }

    original_save = runtime.save

    def save(path, value, **kwargs):
        original_save(path, value, **kwargs)
        if path.name == "status.json" and not kwargs.get("durable"):
            snapshots.append(json.loads(path.read_text()))

    monkeypatch.setattr(runtime, "Bridge", Bridge)
    monkeypatch.setattr(runtime, "socket", SimpleNamespace(socket=Socket))
    monkeypatch.setattr(
        runtime, "uvicorn", SimpleNamespace(Server=Server, Config=lambda *a, **k: None)
    )
    monkeypatch.setattr(runtime, "create_http_app", lambda bridge: None)
    monkeypatch.setattr(runtime, "seed", lambda bridge: ("team", "anchor"))
    monkeypatch.setattr(runtime, "advance", advance)
    monkeypatch.setattr(runtime, "process_completions", lambda *args: {"pending": 0})
    monkeypatch.setattr(runtime, "report_worker", worker_report)
    monkeypatch.setattr(runtime, "report", coordinator_report)
    monkeypatch.setattr(runtime, "save", save)
    # Huge clock changes exercise liveness independently from semantic reporting.
    monkeypatch.setattr(
        runtime,
        "time",
        SimpleNamespace(
            time=lambda: 1000 + current["index"] * 86400, monotonic=lambda: current["index"] * 86400
        ),
    )
    try:
        await asyncio.wait_for(runtime.serve(tmp_path / "profile.json"), timeout=5)
    except BaseException as error:
        # A real crashed process releases its flock. The in-process traceback
        # intentionally retains the coroutine frame, so release only this fixture's
        # owned lock before simulating restart in the same test process.
        trace = error.__traceback__
        while trace:
            if trace.tb_frame.f_code.co_name == "serve" and "lock" in trace.tb_frame.f_locals:
                trace.tb_frame.f_locals["lock"].close()
            trace = trace.tb_next
        raise
    return reports, snapshots


def work(state="running", assignee="codex", core="task-a"):
    return {"id": "work-a", "assignee": assignee, "state": state, "core_task_id": core}


def state(**extra):
    return {
        "state": "waiting",
        "reason": "work_pending",
        "enabled": True,
        "grant_id": "grant-a",
        **extra,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["sent", "unknown", "failed"])
async def test_unchanged_reports_never_repeat_but_status_stays_current(
    runtime, tmp_path, monkeypatch, outcome
):
    observations = [
        {
            "state": state(observed_at=n, lease_until=n, quota={"observed_at": n}),
            "workers": [work()],
        }
        for n in range(5)
    ]
    reports, snapshots = await exercise_loop(
        runtime, tmp_path, monkeypatch, observations, result_state=outcome
    )
    assert [(r[0], r[1]) for r in reports] == [("work-a", "running"), ("coordinator", "working")]
    assert len(snapshots) == 5
    assert snapshots[-1]["observed_at"] - snapshots[0]["observed_at"] == 4 * 86400
    assert snapshots[-1]["autonext"]["lease_until"] == 4
    assert snapshots[-1]["reporting"]["workers"]["work-a"]["state"] == outcome
    # Restart from the existing valid scope/outcomes creates no retry.
    repeated, _ = await exercise_loop(
        runtime, tmp_path, monkeypatch, observations[:1], result_state=outcome
    )
    assert repeated == []


@pytest.mark.asyncio
async def test_fachliche_worker_and_coordinator_changes_report_once(runtime, tmp_path, monkeypatch):
    observations = [
        {"state": state(), "workers": [work()]},
        {"state": state(), "workers": [work()]},
        {"state": state(), "workers": [work("blocked")]},
        {"state": state(), "workers": [work("blocked", core="task-b")]},
        {"state": state(), "workers": [work("completed", core="task-b")], "done": ["task-b"]},
        {
            "state": state(state="stopped", reason="review_unknown"),
            "workers": [work("completed", core="task-b")],
            "done": ["task-b"],
        },
        {
            "state": state(state="stopped", reason="review_unknown"),
            "workers": [work("completed", core="task-b")],
            "done": ["task-b"],
        },
    ]
    reports, _ = await exercise_loop(runtime, tmp_path, monkeypatch, observations)
    assert [(r[0], r[1]) for r in reports] == [
        ("work-a", "running"),
        ("coordinator", "working"),
        ("work-a", "blocked"),
        ("work-a", "blocked"),
        ("work-a", "completed"),
        ("coordinator", "working"),
        ("coordinator", "blocked"),
    ]
    assert len({r[2] for r in reports}) == len(reports)


@pytest.mark.asyncio
@pytest.mark.parametrize("worker", [False, True])
async def test_crash_after_effect_keeps_reservation_unknown_and_never_replays(
    runtime, tmp_path, monkeypatch, worker
):
    observation = {"state": state(), "workers": [work()] if worker else []}
    with pytest.raises(RuntimeError, match="simulated crash after effect"):
        await exercise_loop(runtime, tmp_path, monkeypatch, [observation], crash=True)
    path = tmp_path / "state/status.json"
    reserved = json.loads(path.read_text())["reporting"]
    row = reserved["workers"]["work-a"] if worker else reserved["coordinator"]
    assert row["state"] == "unknown"
    assert row["error"] == "report_reserved_outcome_unknown"
    reports, _ = await exercise_loop(runtime, tmp_path, monkeypatch, [observation])
    assert all(report[0] != ("work-a" if worker else "coordinator") for report in reports)
    current = json.loads(path.read_text())["reporting"]
    assert (current["workers"]["work-a"] if worker else current["coordinator"]) == row


def test_report_observation_ignores_volatile_intake_but_exposes_new_blockers(runtime):
    intake = {
        "held": [{"task_id": "task-a", "reason": "external_activity", "entry_id": "old"}],
        "selected": {"card": SimpleNamespace(task_id="task-b")},
        "resource_stop": {
            "reason": "quota_unavailable",
            "error_type": "TimeoutError",
            "observed_at": 1,
            "retry_after": 2,
        },
    }
    first = runtime.coordinator_report_observation(state(), ["b", "a"], intake)
    intake["resource_stop"].update(observed_at=999, retry_after=1000)
    intake["held"][0]["entry_id"] = "new"
    assert (
        runtime.coordinator_report_observation(state(lease_until=777), ["a", "b", "a"], intake)
        == first
    )
    assert "task-a:external_activity" in first[2]
    assert "Auswahl task-b" in first[2]
    assert first[3] == "blocked"
    intake["held"][0]["reason"] = "worktree_reserved"
    changed = runtime.coordinator_report_observation(state(), ["b", "a"], intake)
    assert changed[0] != first[0]
    assert "task-a:worktree_reserved" in changed[2]
    intake["selected"]["card"] = SimpleNamespace(task_id="task-c")
    assert runtime.coordinator_report_observation(state(), ["b", "a"], intake)[0] != changed[0]
    assert runtime.worker_report_fingerprint(work()) != runtime.worker_report_fingerprint(
        work(assignee="grok")
    )


@pytest.mark.parametrize(
    "damage",
    [
        "legacy_scope",
        "foreign_scope",
        "no_fingerprint",
        "no_id",
        "bad_fingerprint",
        "bad_state",
        "retry_enabled",
    ],
)
def test_restore_refuses_legacy_foreign_or_malformed_unknown_without_overwrite(
    runtime, tmp_path, damage
):
    path = tmp_path / "status.json"
    row = {
        "report_id": "original-id",
        "instance": "fixture",
        "target": None,
        "fingerprint": "a" * 64,
        "state": "unknown",
        "error": "timeout",
        "automatic_retry": False,
    }
    status = {"reporting_scope": "scope-a", "reporting": {"coordinator": row, "workers": {}}}
    if damage == "legacy_scope":
        status.pop("reporting_scope")
    elif damage == "foreign_scope":
        status["reporting_scope"] = "scope-b"
    elif damage == "no_fingerprint":
        row.pop("fingerprint")
    elif damage == "no_id":
        row.pop("report_id")
    elif damage == "bad_fingerprint":
        row["fingerprint"] = None
    elif damage == "bad_state":
        row["state"] = "success-unproved"
    else:
        row["automatic_retry"] = True
    path.write_text(json.dumps(status))
    original = path.read_bytes()
    with pytest.raises(RuntimeError, match="reconcile before restart"):
        runtime.restore_reporting(path, "scope-a")
    assert path.read_bytes() == original


def test_report_scope_binds_source_cwd_workspace_and_cli(runtime):
    profile = {
        "instance": "same",
        "cwd": "/work",
        "workspace": "/desk",
        "report_cli": "/bin/report",
        "threaddesk_source": "/source",
        "board_id": "board",
    }
    scope = runtime.digest(runtime.fixed_profile(profile))
    for key in ("cwd", "workspace", "report_cli", "threaddesk_source", "board_id"):
        assert runtime.digest(runtime.fixed_profile({**profile, key: "changed"})) != scope


def test_long_held_and_completed_lists_expose_late_changes_in_actual_payload(runtime, monkeypatch):
    held = [
        {"task_id": "task-" + str(n).zfill(4), "reason": "worktree_reserved"} for n in range(100)
    ]
    done = ["completed-task-" + str(n).zfill(4) for n in range(100)]
    intake = {"held": held, "selected": {"card": SimpleNamespace(task_id="selected-task")}}
    first = runtime.coordinator_report_observation(state(), done, intake)
    held[-1]["reason"] = "external_activity"
    second = runtime.coordinator_report_observation(state(), done, intake)
    assert first[2] != second[2]
    assert len(second[2]) <= 600
    assert "Auswahl selected-task" in second[2]
    assert "100 Einträge / Ref " in second[2]
    payloads = []

    def record(command, **kwargs):
        payloads.append(
            {key: command[command.index("--" + key) + 1] for key in ("done", "working")}
        )
        return {"state": "sent"}

    monkeypatch.setattr(runtime, "run_status_report", record)
    runtime.report({"report_cli": "fixture", "instance": "fixture"}, first[1], first[2], first[3])
    runtime.report(
        {"report_cli": "fixture", "instance": "fixture"}, second[1], second[2], second[3]
    )
    assert payloads[0]["working"] != payloads[1]["working"]
    done[-1] = "completed-task-9999"
    third = runtime.coordinator_report_observation(state(), done, intake)
    runtime.report({"report_cli": "fixture", "instance": "fixture"}, third[1], third[2], third[3])
    assert payloads[-1]["done"] != payloads[-2]["done"]
    assert len(payloads[-1]["done"]) <= 500


@pytest.mark.asyncio
async def test_new_semantic_change_preserves_previous_unknown_identity(
    runtime, tmp_path, monkeypatch
):
    reports, snapshots = await exercise_loop(
        runtime,
        tmp_path,
        monkeypatch,
        [
            {"state": state(), "workers": [work()]},
            {"state": state(), "workers": [work("completed")]},
        ],
        result_state="unknown",
    )
    first_worker = reports[0][2]
    unresolved = snapshots[-1]["reporting"]["unresolved"]
    assert unresolved[first_worker]["state"] == "unknown"
    assert unresolved[first_worker]["target"] == "work-a"
    assert unresolved[first_worker]["instance"] == "fixture-work-a"
    assert unresolved[first_worker]["report_id"] == first_worker
    assert unresolved[first_worker]["automatic_retry"] is False
    assert snapshots[-1]["reporting"]["workers"]["work-a"]["report_id"] != first_worker
