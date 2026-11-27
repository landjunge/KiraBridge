import contextlib
import importlib.util
import json
import os
import plistlib
import select
import shlex
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import request


@pytest.fixture
def installer():
    path = Path(__file__).parents[1] / "installer/install.py"
    spec = importlib.util.spec_from_file_location("install_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_busy_guard_prevents_switch_without_touching_tasks(installer, bridge, config, tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("data_dir = " + json.dumps(str(config.state_path)))
    value = request("file.list", {"path": config.principals["local"].roots[0]})
    bridge.prepare("local", value)
    with pytest.raises(RuntimeError, match="BUSY"):
        with installer.idle_guard(path):
            pytest.fail("must not enter activation")
    assert bridge.store.get(value.task_id, "local")["state"] == "created"


def _idle_guard_fixture(
    tmp_path,
    *,
    other_task=False,
    other_task_state="queued",
    other_task_operation="file.list",
    receiver=False,
    team_work=False,
):
    state = tmp_path / "state"
    state.mkdir()
    db = sqlite3.connect(state / "bridge.sqlite3")
    db.executescript(
        "CREATE TABLE tasks(id TEXT PRIMARY KEY, principal TEXT, operation TEXT, state TEXT, "
        "args TEXT, evidence TEXT, lease_owner TEXT, lease_until REAL);"
        "CREATE TABLE events(seq INTEGER PRIMARY KEY, task_id TEXT, state TEXT, evidence TEXT);"
        "CREATE TABLE message_jobs(message_id TEXT PRIMARY KEY, state TEXT);"
        "CREATE TABLE queue_holds(queue_id TEXT, item_id TEXT);"
        "CREATE TABLE queue_withdrawals(queue_id TEXT, item_id TEXT);"
        "CREATE TABLE visible_handoffs(id TEXT, message_id TEXT, state TEXT);"
        "CREATE TABLE team_work(id TEXT PRIMARY KEY, state TEXT);"
    )
    task_id = "visible-install-attempt"
    evidence = {
        "execution_route": "visible_terminal",
        "pane_id": "terminal:42:ttys001",
        "expected_pid": 222,
        "tty": "/dev/ttys001",
    }
    db.execute(
        "INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)",
        (
            task_id,
            "codex",
            "terminal.visible",
            "running",
            json.dumps({"pane_id": evidence["pane_id"], "expected_pid": 222}),
            json.dumps(evidence),
            "core-owner",
            4_000_000_000,
        ),
    )
    db.execute(
        "INSERT INTO events(task_id,state,evidence) VALUES(?,?,?)",
        (task_id, "running", json.dumps(evidence)),
    )
    if other_task:
        db.execute(
            "INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)",
            (
                "unrelated-task",
                "codex",
                other_task_operation,
                other_task_state,
                "{}",
                "{}",
                None,
                None,
            ),
        )
    if receiver:
        db.execute("INSERT INTO message_jobs VALUES('receiver-job','queued')")
    if team_work:
        db.execute("INSERT INTO team_work VALUES('team-job','processing_result')")
    db.commit()
    db.close()
    config = tmp_path / "config.toml"
    config.write_text("data_dir = " + json.dumps(str(state)))
    return config, task_id


def _job_guard(
    installer, monkeypatch, tmp_path, job_state, *, handoff=None, withdrawn=False, hold=False
):
    config, task_id = _idle_guard_fixture(tmp_path)
    db = sqlite3.connect(tmp_path / "state" / "bridge.sqlite3")
    db.execute("INSERT INTO message_jobs VALUES('m1',?)", (job_state,))
    if handoff:
        db.execute(
            "INSERT INTO visible_handoffs VALUES('h1','m1',?)",
            ("unknown" if handoff == "unknown+sent" else handoff,),
        )
    if handoff == "unknown+sent":
        db.execute("UPDATE visible_handoffs SET state='unknown'")
        db.execute("INSERT INTO visible_handoffs VALUES('h2','m1','sent')")
    if withdrawn:
        db.execute("INSERT INTO queue_withdrawals VALUES('messages','m1')")
    if hold:
        db.execute("INSERT INTO queue_holds VALUES('messages','m1')")
    db.commit()
    db.close()
    _authorize_current_terminal_task(installer, monkeypatch, task_id)
    return config


def test_unknown_handoff_job_is_reported_not_busy(installer, monkeypatch, tmp_path):
    config = _job_guard(installer, monkeypatch, tmp_path, "queued", handoff="unknown")
    lines = []
    monkeypatch.setattr(installer, "report", lambda kind, msg, **kw: lines.append((kind, msg)))
    with installer.idle_guard(config):
        pass
    assert any(k == "warn" and "m1" in m and "kein Neuversand" in m for k, m in lines)


def test_withdrawn_job_is_not_busy_and_reported(installer, monkeypatch, tmp_path):
    config = _job_guard(installer, monkeypatch, tmp_path, "queued", withdrawn=True)
    lines = []
    monkeypatch.setattr(installer, "report", lambda kind, msg, **kw: lines.append((kind, msg)))
    with installer.idle_guard(config):
        pass
    assert any(k == "warn" and "m1" in m for k, m in lines)


def test_held_job_without_unknown_is_not_busy(installer, monkeypatch, tmp_path):
    config = _job_guard(installer, monkeypatch, tmp_path, "queued", hold=True)
    with installer.idle_guard(config):
        pass


def test_legacy_db_without_new_tables_still_busy(installer, monkeypatch, tmp_path):
    config = _job_guard(installer, monkeypatch, tmp_path, "queued")
    db = sqlite3.connect(tmp_path / "state" / "bridge.sqlite3")
    db.executescript(
        "DROP TABLE queue_holds; DROP TABLE queue_withdrawals; DROP TABLE visible_handoffs;"
    )
    db.close()
    with pytest.raises(RuntimeError, match="BUSY"):
        with installer.idle_guard(config):
            pytest.fail("must block")


def test_many_unknown_ids_are_truncated_in_display_only(installer, monkeypatch, tmp_path):
    config = _job_guard(installer, monkeypatch, tmp_path, "queued", withdrawn=True)
    db = sqlite3.connect(tmp_path / "state" / "bridge.sqlite3")
    for i in range(12):
        db.execute("INSERT INTO message_jobs VALUES(?,'queued')", (f"x{i:02d}",))
        db.execute("INSERT INTO queue_withdrawals VALUES('messages',?)", (f"x{i:02d}",))
    db.commit()
    db.close()
    lines = []
    monkeypatch.setattr(installer, "report", lambda kind, msg, **kw: lines.append((kind, msg)))
    with installer.idle_guard(config):
        pass
    assert any("13 unbekannte" in m and "+3 weitere" in m for _, m in lines)


@pytest.mark.parametrize(
    ("job_state", "handoff"),
    [("queued", None), ("queued", "sent"), ("running", "unknown"), ("queued", "unknown+sent")],
)
def test_real_job_work_still_busy(installer, monkeypatch, tmp_path, job_state, handoff):
    config = _job_guard(installer, monkeypatch, tmp_path, job_state, handoff=handoff)
    with pytest.raises(RuntimeError, match="BUSY"):
        with installer.idle_guard(config):
            pytest.fail("must block")


def _authorize_current_terminal_task(installer, monkeypatch, task_id):
    monkeypatch.setenv(installer.ACTIVE_TERMINAL_TASK_ENV, task_id)
    monkeypatch.setenv(installer.ACTIVE_TERMINAL_PRINCIPAL_ENV, "codex")
    monkeypatch.setattr(installer, "_current_tty", lambda: "/dev/ttys001")
    monkeypatch.setattr(installer, "_process_ancestry", lambda: {111, 222, 333})


def test_idle_guard_excludes_only_the_exact_live_visible_terminal_task(
    installer, monkeypatch, tmp_path
):
    config, task_id = _idle_guard_fixture(tmp_path)
    _authorize_current_terminal_task(installer, monkeypatch, task_id)
    with installer.idle_guard(config):
        pass


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "malformed-env",
        "wrong-principal",
        "wrong-operation",
        "rollback-operation",
        "expired-lease",
        "nan-lease",
        "wrong-tty",
        "wrong-pid",
        "wrong-session",
        "blank-principal",
        "event-mismatch",
    ],
)
def test_idle_guard_never_excludes_unproven_or_stale_terminal_task(
    installer, monkeypatch, tmp_path, mutation
):
    config, task_id = _idle_guard_fixture(tmp_path)
    db_path = tmp_path / "state/bridge.sqlite3"
    db = sqlite3.connect(db_path)
    if mutation == "wrong-operation":
        db.execute("UPDATE tasks SET operation='file.list' WHERE id=?", (task_id,))
    elif mutation == "rollback-operation":
        db.execute("UPDATE tasks SET operation='installer.rollback' WHERE id=?", (task_id,))
    elif mutation == "expired-lease":
        db.execute("UPDATE tasks SET lease_until=1 WHERE id=?", (task_id,))
    elif mutation == "nan-lease":
        db.execute("UPDATE tasks SET lease_until=? WHERE id=?", (float("nan"), task_id))
    elif mutation == "wrong-session":
        args = json.dumps({"pane_id": "terminal:9:ttys009"})
        db.execute("UPDATE tasks SET args=? WHERE id=?", (args, task_id))
    elif mutation == "blank-principal":
        db.execute("UPDATE tasks SET principal='' WHERE id=?", (task_id,))
    elif mutation == "event-mismatch":
        db.execute("UPDATE events SET evidence='{}' WHERE task_id=?", (task_id,))
    db.commit()
    db.close()
    task_env_id = "missing" if mutation == "missing" else task_id
    _authorize_current_terminal_task(installer, monkeypatch, task_env_id)
    if mutation == "malformed-env":
        monkeypatch.setenv(installer.ACTIVE_TERMINAL_TASK_ENV, task_id + "\n")
    if mutation == "wrong-principal":
        monkeypatch.setenv(installer.ACTIVE_TERMINAL_PRINCIPAL_ENV, "grok")
    if mutation == "wrong-tty":
        monkeypatch.setattr(installer, "_current_tty", lambda: "/dev/ttys099")
    elif mutation == "wrong-pid":
        monkeypatch.setattr(installer, "_process_ancestry", lambda: {111, 333})
    with pytest.raises(RuntimeError, match="BUSY: 1 tasks"):
        with installer.idle_guard(config):
            pytest.fail("unverified task must remain busy")


@pytest.mark.parametrize(
    ("other_task", "receiver", "team_work", "expected"),
    [
        (True, False, False, "BUSY: 1 tasks"),
        (False, True, False, "BUSY: 0 tasks, 1 receiver jobs"),
        (False, False, True, "BUSY: 0 tasks, 0 receiver jobs, 1 team jobs"),
    ],
)
def test_idle_guard_still_blocks_every_other_active_work_item(
    installer, monkeypatch, tmp_path, other_task, receiver, team_work, expected
):
    config, task_id = _idle_guard_fixture(
        tmp_path, other_task=other_task, receiver=receiver, team_work=team_work
    )
    _authorize_current_terminal_task(installer, monkeypatch, task_id)
    with pytest.raises(RuntimeError, match=expected):
        with installer.idle_guard(config):
            pytest.fail("other active work must block activation")


async def test_task_manager_running_event_is_accepted_by_installer_idle_guard(
    installer, bridge, config, monkeypatch, tmp_path
):
    task_id = "real-store-visible-installer-task"
    pid = installer.os.getpid()
    pane_id = "terminal:42:ttys001"
    tty = "/dev/ttys001"
    config.principals["local"].capabilities.append("session.inspect")
    request_value = request(
        "terminal.visible",
        {
            "argv": ["python3", "-c", "pass"],
            "cwd": config.principals["local"].roots[0],
            "pane_id": pane_id,
            "expected_pid": pid,
        },
        task_id=task_id,
    )
    bridge.prepare("local", request_value)
    bridge.tasks.approve(task_id)
    claimed = bridge.store.claim_exact(bridge.tasks.owner, 30, task_id)
    assert claimed is not None
    config_path = tmp_path / "installer.toml"
    config_path.write_text("data_dir = " + json.dumps(str(config.state_path)))
    monkeypatch.setenv(installer.ACTIVE_TERMINAL_TASK_ENV, task_id)
    monkeypatch.setenv(installer.ACTIVE_TERMINAL_PRINCIPAL_ENV, "local")
    monkeypatch.setattr(installer, "_current_tty", lambda: tty)
    monkeypatch.setattr(installer, "_process_ancestry", lambda: {pid})

    async def execute(task, running, progress):
        evidence = {
            "execution_route": "visible_terminal",
            "pane_id": pane_id,
            "expected_pid": pid,
            "tty": tty,
        }
        await running(evidence)
        with installer.idle_guard(config_path):
            pass
        return {"success": True}

    bridge.tasks.preflight = None
    bridge.tasks.executor = execute
    await bridge.tasks._execute(claimed)
    assert bridge.store.get(task_id)["state"] == "completed"


@pytest.mark.skipif(os.name != "posix", reason="PTY and process ancestry require POSIX")
def test_process_ancestry_reads_real_pty_and_live_parent_chain(installer):
    import pty

    master, slave = pty.openpty()
    tty = os.ttyname(slave)
    source = Path(installer.__file__).resolve()
    code = (
        "import importlib.util,json,os\n"
        "p=" + repr(str(source)) + "\n"
        "s=importlib.util.spec_from_file_location('install_probe',p)\n"
        "m=importlib.util.module_from_spec(s)\n"
        "s.loader.exec_module(m)\n"
        "print(json.dumps({'pid':os.getpid(),'tty':m._current_tty(),'parents':sorted(m._process_ancestry())}))\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=slave,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    os.close(slave)
    try:
        stdout, stderr = child.communicate(timeout=10)
    finally:
        os.close(master)
    assert child.returncode == 0, stderr
    observed = json.loads(stdout)
    assert observed["tty"] == tty
    assert child.pid == observed["pid"] and child.pid in observed["parents"]
    assert os.getpid() in observed["parents"]


@pytest.mark.skipif(os.name != "posix", reason="PTY process start gate requires POSIX")
async def test_owned_process_start_gate_waits_until_running_evidence_commit(tmp_path):
    import pty

    from kirabridge.platform_adapters import reap_process, spawn_process

    master, slave = pty.openpty()
    directory_fd = os.open(tmp_path, os.O_RDONLY)
    process = None
    try:
        process = await spawn_process(
            [sys.executable, "-c", "print('GATED_EXEC_STARTED')"],
            directory_fd,
            {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)},
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_gated=True,
        )
        os.close(directory_fd)
        directory_fd = -1
        assert process.returncode is None
        assert not select.select([master], [], [], 0.1)[0]
        gate_fd = process._kirabridge_start_gate_fd
        os.close(gate_fd)
        process._kirabridge_start_gate_fd = None
        await process.wait()
        output = bytearray()
        while select.select([master], [], [], 0.05)[0]:
            try:
                output.extend(os.read(master, 4096))
            except OSError:
                break
        assert process.returncode == 0
        assert b"GATED_EXEC_STARTED" in output
    finally:
        if process is not None and process.returncode is None:
            await reap_process(process)
            gate_fd = getattr(process, "_kirabridge_start_gate_fd", None)
            if gate_fd is not None:
                os.close(gate_fd)
        if directory_fd != -1:
            os.close(directory_fd)
        os.close(master)
        os.close(slave)


@pytest.mark.skipif(os.name != "posix", reason="owned PTY process trees require POSIX")
async def test_owned_process_running_failure_never_releases_start_gate(tmp_path):
    from kirabridge.platform_adapters.linux.owned_terminal import LinuxOwnedTerminal

    marker = tmp_path / "must-not-run"
    directory_fd = os.open(tmp_path, os.O_RDONLY)
    terminal = LinuxOwnedTerminal()

    async def reject_running(_evidence):
        raise RuntimeError("running evidence was not committed")

    try:
        with pytest.raises(RuntimeError, match="running evidence"):
            await terminal.execute_argv(
                [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path(" + repr(str(marker)) + ").write_text('bad')",
                ],
                directory_fd,
                {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)},
                timeout=5,
                max_output=1024,
                running=reject_running,
            )
    finally:
        os.close(directory_fd)
    assert not marker.exists()


def test_installer_with_missing_stdin_tty_reports_busy(installer, tmp_path):
    config, task_id = _idle_guard_fixture(tmp_path)
    code = (
        "import importlib.util,pathlib\n"
        "p=" + repr(str(Path(installer.__file__).resolve())) + "\n"
        "s=importlib.util.spec_from_file_location('install_probe',p)\n"
        "m=importlib.util.module_from_spec(s)\n"
        "s.loader.exec_module(m)\n"
        "with m.idle_guard(pathlib.Path(" + repr(str(config)) + ")): print('UNSAFE')\n"
    )
    environment = os.environ.copy()
    environment[installer.ACTIVE_TERMINAL_TASK_ENV] = task_id
    environment[installer.ACTIVE_TERMINAL_PRINCIPAL_ENV] = "codex"
    result = subprocess.run(
        [sys.executable, "-c", code],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert "BUSY: 1 tasks" in result.stderr


@pytest.mark.skipif(sys.platform != "darwin", reason="visible-terminal pane identity is macOS-only")
def test_missing_ps_command_keeps_real_shell_task_busy(installer, tmp_path):
    import pty

    config, task_id = _idle_guard_fixture(tmp_path)
    master, slave = pty.openpty()
    tty = os.ttyname(slave)
    pane_id = "terminal:42:" + os.path.basename(tty)
    code = (
        "import importlib.util,pathlib,sys,os\n"
        "p=" + repr(str(Path(installer.__file__).resolve())) + "\n"
        "s=importlib.util.spec_from_file_location('install_probe',p)\n"
        "m=importlib.util.module_from_spec(s)\n"
        "s.loader.exec_module(m)\n"
        "print('READY',flush=True)\n"
        "os.read(0,1)\n"
        "try:\n"
        "    with m.idle_guard(pathlib.Path(" + repr(str(config)) + ")): print('UNSAFE')\n"
        "except RuntimeError as e:\n"
        "    print(str(e),flush=True)\n"
        "    sys.exit(4)\n"
    )
    environment = os.environ.copy()
    environment["PATH"] = ""
    environment[installer.ACTIVE_TERMINAL_TASK_ENV] = task_id
    environment[installer.ACTIVE_TERMINAL_PRINCIPAL_ENV] = "codex"
    command = shlex.quote(sys.executable) + " -c " + shlex.quote(code) + "; /bin/sleep 0.1"
    shell = subprocess.Popen(
        ["/bin/sh", "-c", command],
        stdin=slave,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
        cwd=tmp_path,
    )
    try:
        assert shell.stdout.readline().strip() == "READY"
        evidence = {
            "execution_route": "visible_terminal",
            "pane_id": pane_id,
            "expected_pid": shell.pid,
            "tty": tty,
        }
        db = sqlite3.connect(tmp_path / "state/bridge.sqlite3")
        db.execute(
            "UPDATE tasks SET args=?,evidence=?,lease_until=? WHERE id=?",
            (
                json.dumps({"pane_id": pane_id, "expected_pid": shell.pid}),
                json.dumps(evidence),
                4_000_000_000,
                task_id,
            ),
        )
        db.execute(
            "UPDATE events SET evidence=? WHERE task_id=? AND state='running'",
            (json.dumps(evidence), task_id),
        )
        db.commit()
        db.close()
        os.write(master, b"x\n")
        stdout, stderr = shell.communicate(timeout=10)
    finally:
        if shell.poll() is None:
            shell.kill()
            shell.wait(timeout=5)
        os.close(master)
        os.close(slave)
    assert "UNSAFE" not in stdout, (stdout, stderr)
    assert "BUSY: 1 tasks" in stdout


@pytest.mark.parametrize(
    ("state", "operation"),
    [("queued", "terminal.visible"), ("accepted", "terminal.visible"), ("running", "file.list")],
)
def test_second_active_task_always_blocks_even_when_current_task_is_verified(
    installer, monkeypatch, tmp_path, state, operation
):
    config, task_id = _idle_guard_fixture(
        tmp_path,
        other_task=True,
        other_task_state=state,
        other_task_operation=operation,
    )
    _authorize_current_terminal_task(installer, monkeypatch, task_id)
    with pytest.raises(RuntimeError, match="BUSY: 1 tasks"):
        with installer.idle_guard(config):
            pytest.fail("the verified task cannot hide a second active task")


@pytest.mark.parametrize("missing", ["ps", "stdin"])
def test_missing_process_or_tty_proof_keeps_current_task_busy(
    installer, monkeypatch, tmp_path, missing
):
    config, task_id = _idle_guard_fixture(tmp_path)
    monkeypatch.setenv(installer.ACTIVE_TERMINAL_TASK_ENV, task_id)
    monkeypatch.setenv(installer.ACTIVE_TERMINAL_PRINCIPAL_ENV, "codex")
    tty = None if missing == "stdin" else "/dev/ttys001"
    monkeypatch.setattr(installer, "_current_tty", lambda: tty)
    if missing == "ps":
        monkeypatch.setattr(
            installer.subprocess,
            "run",
            lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("ps unavailable")),
        )
    with pytest.raises(RuntimeError, match="BUSY: 1 tasks"):
        with installer.idle_guard(config):
            pytest.fail("missing provenance must fail closed")


def test_rollback_function_keeps_its_idle_guard(installer, monkeypatch, tmp_path):
    state_root = tmp_path / "state-root"
    state_root.mkdir()
    config, _ = _idle_guard_fixture(state_root, other_task=True)
    root = tmp_path / "install-root"
    root.mkdir()
    current = root / "current.json"
    previous = {
        "config": str(config),
        "launcher": str(root / "launcher"),
        "plist": str(root / "plist"),
        "service": "none",
        "backup": str(root / "unused-backup"),
        "had_wrapper": False,
        "had_plist": False,
        "was_loaded": False,
        "rollback_core_restored": False,
    }
    current.write_text(json.dumps(previous))
    original = current.read_bytes()
    args = SimpleNamespace(
        prefix=root,
        config=config,
        launcher=root / "launcher",
        plist=root / "plist",
        service="none",
    )
    monkeypatch.setattr(installer, "validate_service_owner", lambda _args: None)
    with pytest.raises(RuntimeError, match="BUSY: 2 tasks"):
        installer.rollback(args, _compensating=True)
    assert current.read_bytes() == original


def test_private_atomic_write_rejects_symlink_and_preserves_original(installer, tmp_path):
    target = tmp_path / "real"
    target.write_text("preserve")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(RuntimeError, match="symlink"):
        installer.atomic(link, "replace")
    assert target.read_text() == "preserve"
    p = tmp_path / "private"
    installer.atomic(p, "private", 0o600)
    assert p.stat().st_mode & 0o777 == 0o600


def test_upgrade_never_replaces_saved_terminal_grant_or_voice_policy(installer, tmp_path):
    path = tmp_path / "config.toml"
    policy = (
        '[principals.chatgpt]\npermission_level="full"\n'
        'automatic_operations=["session.input"]\n'
        "[session_input_policy]\nenabled=false\nprincipals=[]\n"
        "[voice_messaging]\ntimeout_seconds=60\n"
    )
    path.write_text(policy)
    installer.fresh_config(SimpleNamespace(config=path, full_access=True), tmp_path / "release")
    assert path.read_text() == policy


def test_update_rejects_silent_switch_to_another_config(installer, tmp_path):
    path = tmp_path / "service.plist"
    definition = {
        "Label": installer.LABEL,
        "ProgramArguments": [
            "python",
            "-m",
            "kirabridge.cli",
            "--config",
            str(tmp_path / "original.toml"),
            "serve",
        ],
    }
    original = plistlib.dumps(definition)
    path.write_bytes(original)
    with pytest.raises(RuntimeError, match="expected KiraBridge config"):
        installer.validate_service_owner(
            SimpleNamespace(service="launchd", plist=path, config=tmp_path / "other.toml")
        )
    assert path.read_bytes() == original


def test_previous_health_waits_for_read_only_status_after_transient_timeout(
    installer, monkeypatch, tmp_path
):
    now = 0.0
    calls = []

    def status(release, config, *args, timeout):
        calls.append(timeout)
        if len(calls) == 1:
            raise installer.subprocess.TimeoutExpired("status", timeout)
        return {"version": "0.8.0rc58", "dispatcher_active": True}

    monkeypatch.setattr(installer, "cli", status)
    monkeypatch.setattr(installer.time, "monotonic", lambda: now)

    def sleep(duration):
        nonlocal now
        now += duration

    monkeypatch.setattr(installer.time, "sleep", sleep)
    health = installer.wait_previous_health(tmp_path / "release", tmp_path / "config", seconds=5)
    assert health["version"] == "0.8.0rc58"
    assert calls == [5, 4.5]


def test_previous_health_default_allows_slow_status_under_load(installer, monkeypatch, tmp_path):
    seen = []

    def status(release, config, *args, timeout):
        seen.append(timeout)
        return {"version": "0.8.0rc58"}  # answers after >8s in real life; 30s budget applies

    monkeypatch.setattr(installer, "cli", status)
    health = installer.wait_previous_health(tmp_path / "release", tmp_path / "config")
    assert health["version"] == "0.8.0rc58"
    assert seen == [30]


def test_previous_health_timeout_is_bounded_and_does_not_switch(installer, monkeypatch, tmp_path):
    now = 0.0
    calls = []

    def status(release, config, *args, timeout):
        calls.append(timeout)
        raise installer.subprocess.TimeoutExpired("status", timeout)

    monkeypatch.setattr(installer, "cli", status)
    monkeypatch.setattr(installer.time, "monotonic", lambda: now)

    def sleep(duration):
        nonlocal now
        now += duration

    monkeypatch.setattr(installer.time, "sleep", sleep)
    with pytest.raises(RuntimeError, match="Existing service health unavailable; no switch"):
        installer.wait_previous_health(tmp_path / "release", tmp_path / "config", seconds=1)
    assert len(calls) == 2
    assert calls[-1] == pytest.approx(0.5)


@pytest.mark.parametrize(
    "timeout_failure", [False, True], ids=["bootstrap-error", "bootstrap-timeout"]
)
@pytest.mark.parametrize("rollback_failure", [False, True], ids=["rollback-ok", "rollback-fails"])
def test_launchd_failure_restores_previous_definition_without_config_restore(
    installer, tmp_path, monkeypatch, timeout_failure, rollback_failure
):
    prefix = tmp_path / "install"
    prefix.mkdir(mode=0o700)
    config = tmp_path / "config.toml"
    config.write_text("data_dir = " + json.dumps(str(tmp_path / "state")))
    original_config = config.read_bytes()
    launcher = tmp_path / "bin/kirabridge"
    launcher.parent.mkdir()
    old_launcher = (
        "#!/bin/sh\nexec old-python -m kirabridge.cli --config " + str(config) + ' "$@"\n'
    ).encode()
    launcher.write_bytes(old_launcher)
    plist = tmp_path / "service.plist"
    old_plist = plistlib.dumps(
        {
            "Label": installer.LABEL,
            "ProgramArguments": [
                "old-python",
                "-m",
                "kirabridge.cli",
                "--config",
                str(config),
                "serve",
                "--transport",
                "http",
            ],
        }
    )
    plist.write_bytes(old_plist)
    release = prefix / "releases/new"
    release.mkdir(parents=True)
    (release / "release.json").write_text(json.dumps({"version": "0.6.0", "commit": "a" * 40}))
    args = SimpleNamespace(
        prefix=prefix,
        config=config,
        launcher=launcher,
        plist=plist,
        service="launchd",
        full_access=True,
    )
    monkeypatch.setattr(installer, "loaded", lambda args: True)
    monkeypatch.setattr(installer, "cli", lambda *a, **kw: {"version": "0.5.2"})
    monkeypatch.setattr(installer, "wait_health", lambda *a, **kw: {"version": "0.5.2"})
    operations = []
    monkeypatch.setattr(installer, "stop_service", lambda args: operations.append("stop"))

    failure = (
        installer.subprocess.TimeoutExpired(["SIMULATED launchd bootstrap"], 30)
        if timeout_failure
        else RuntimeError("SIMULATED launchd bootstrap failure")
    )

    def start(args):
        operations.append("start")
        if operations.count("start") == 1:
            raise failure

    monkeypatch.setattr(installer, "start_service", start)
    if rollback_failure:

        def fail_rollback(*args, **kwargs):
            raise RuntimeError("ROLLBACK guard mismatch token=do-not-print-this")

        monkeypatch.setattr(installer, "rollback", fail_rollback)
        with pytest.raises(RuntimeError, match="Aktivierung fehlgeschlagen") as raised:
            installer.activate(args, release)
        message = str(raised.value)
        assert "SIMULATED launchd bootstrap" in message
        assert "ROLLBACK guard mismatch token=[redacted]" in message
        assert "do-not-print-this" not in message
    else:
        with pytest.raises(type(failure), match="SIMULATED"):
            installer.activate(args, release)
    assert config.read_bytes() == original_config
    if rollback_failure:
        assert (prefix / "current.json").exists()
        assert operations == ["stop", "start"]
    else:
        assert launcher.read_bytes() == old_launcher
        assert plist.read_bytes() == old_plist
        assert not (prefix / "current.json").exists()
        assert operations == ["stop", "start", "stop", "start"]


def test_desktop_chatgpt_rollback_does_not_kickstart_same_service_twice(
    installer, monkeypatch, tmp_path
):
    prefix = tmp_path / "install"
    backup = prefix / "backups/transaction"
    backup.mkdir(parents=True)
    config = tmp_path / "config.toml"
    config.write_text("")
    launcher = tmp_path / "launcher"
    launcher.write_text("new launcher")
    plist = tmp_path / "service.plist"
    plist.write_text("new plist")
    (backup / "launcher.before").write_text("old launcher")
    (backup / "service.before.plist").write_text("old plist")
    args = SimpleNamespace(
        prefix=prefix,
        config=config,
        launcher=launcher,
        plist=plist,
        service="launchd",
    )
    active = {
        "backup": str(backup),
        "config": str(config),
        "launcher": str(launcher),
        "plist": str(plist),
        "service": "launchd",
        "installed_wrapper_sha256": installer.sha(launcher),
        "installed_plist_sha256": installer.sha(plist),
        "had_wrapper": True,
        "had_plist": True,
        "was_loaded": False,
        "previous": None,
        "aux_services": [],
        "desktop": {"services": [{"name": "chatgpt", "changed": True}]},
    }
    current = prefix / "current.json"
    installer.jwrite(current, active)
    kicks, desktop_restores = [], []

    def restore_desktop(api, transaction, journal):
        desktop_restores.append(transaction["desktop"]["services"][0]["name"])

    monkeypatch.setattr(installer, "require_visible_terminal", lambda args: None)
    monkeypatch.setattr(installer, "validate_service_owner", lambda args: None)
    monkeypatch.setattr(installer, "require_queue_compatibility", lambda *args: None)
    monkeypatch.setattr(installer, "idle_guard", lambda config: contextlib.nullcontext())
    monkeypatch.setattr(installer, "stop_service", lambda args: None)
    monkeypatch.setattr(installer, "loaded", lambda args: False)
    monkeypatch.setattr(installer, "_restart_owned_tunnel", lambda agents: kicks.append(agents))
    monkeypatch.setattr(
        installer,
        "desktop_module",
        lambda args: SimpleNamespace(restore=restore_desktop),
    )
    monkeypatch.setattr(installer, "report", lambda *args, **kwargs: None)
    monkeypatch.setattr(installer, "report_summary", lambda *args, **kwargs: None)

    installer.rollback(args)

    assert desktop_restores == ["chatgpt"]
    assert kicks == []
    assert not current.exists()


def test_desktop_chatgpt_activation_disables_followup_aux_tunnel_restart(
    installer, monkeypatch, tmp_path
):
    prefix = tmp_path / "install"
    prefix.mkdir()
    config = tmp_path / "config.toml"
    config.write_text("data_dir = " + json.dumps(str(tmp_path / "data")))
    launcher = tmp_path / "bin/kirabridge"
    plist = tmp_path / "service.plist"
    release = tmp_path / "release"
    release.mkdir()
    (release / "release.json").write_text(json.dumps({"version": "0.8.0rc1", "commit": "a" * 40}))
    args = SimpleNamespace(
        prefix=prefix,
        config=config,
        launcher=launcher,
        plist=plist,
        service="none",
        desktop=True,
    )
    services = [{"name": "chatgpt", "changed": False}]
    observed = []

    def snapshot(*args):
        return {"services": services}

    def activate_desktop(api, args, release, active, current):
        services[0]["changed"] = True

    monkeypatch.setattr(installer, "require_visible_terminal", lambda *args: None)
    monkeypatch.setattr(installer, "validate_service_owner", lambda *args: None)
    monkeypatch.setattr(installer, "validate_launcher_owner", lambda *args: None)
    monkeypatch.setattr(installer, "fresh_config", lambda *args: None)
    monkeypatch.setattr(installer, "loaded", lambda args: False)
    monkeypatch.setattr(installer, "require_queue_compatibility", lambda *args: None)
    monkeypatch.setattr(installer, "idle_guard", lambda config: contextlib.nullcontext())
    monkeypatch.setattr(installer, "start_service", lambda args: None)
    monkeypatch.setattr(
        installer,
        "desktop_module",
        lambda args: SimpleNamespace(snapshot=snapshot, activate=activate_desktop),
    )

    def sync_aux_services(*args, **kwargs):
        observed.append(kwargs["restart_tunnel"])
        return [], []

    monkeypatch.setattr(installer, "sync_aux_services", sync_aux_services)
    monkeypatch.setattr(installer, "report", lambda *args, **kwargs: None)
    monkeypatch.setattr(installer, "report_summary", lambda *args, **kwargs: None)

    installer.activate(args, release)

    assert observed == [False]


@pytest.mark.parametrize("interrupted_path", ["launcher", "plist"])
def test_persisted_checkpoint_rolls_back_after_partial_core_switch(
    installer, tmp_path, monkeypatch, interrupted_path
):
    """A fresh rollback invocation can recover after either definition was replaced."""
    prefix = tmp_path / "install"
    prefix.mkdir(mode=0o700)
    state = tmp_path / "empty-state"
    state.mkdir()
    config = tmp_path / "config.toml"
    config.write_text("data_dir = " + json.dumps(str(state)))
    launcher = tmp_path / "bin/kirabridge"
    launcher.parent.mkdir()
    old_launcher = (
        "#!/bin/sh\nexec old-python -m kirabridge.cli --config " + str(config) + ' "$@"\n'
    ).encode()
    launcher.write_bytes(old_launcher)
    plist = tmp_path / "service.plist"
    old_plist = plistlib.dumps(
        {
            "Label": installer.LABEL,
            "ProgramArguments": [
                "old-python",
                "-m",
                "kirabridge.cli",
                "--config",
                str(config),
                "serve",
                "--transport",
                "http",
            ],
        }
    )
    plist.write_bytes(old_plist)
    release = prefix / "releases/new"
    release.mkdir(parents=True)
    (release / "release.json").write_text(json.dumps({"version": "0.6.0", "commit": "a" * 40}))
    args = SimpleNamespace(
        prefix=prefix,
        config=config,
        launcher=launcher,
        plist=plist,
        service="launchd",
        full_access=True,
    )
    monkeypatch.setattr(installer, "loaded", lambda args: True)
    monkeypatch.setattr(installer, "cli", lambda *a, **kw: {"version": "0.5.2"})
    monkeypatch.setattr(installer, "wait_health", lambda *a, **kw: None)
    monkeypatch.setattr(installer, "require_visible_terminal", lambda *a: None)
    monkeypatch.setattr(installer, "validate_service_owner", lambda *a: None)
    monkeypatch.setattr(installer, "validate_launcher_owner", lambda *a: None)
    monkeypatch.setattr(installer, "require_queue_compatibility", lambda *a: None)
    monkeypatch.setattr(installer, "idle_guard", lambda *a: contextlib.nullcontext())
    monkeypatch.setattr(installer, "stop_service", lambda *a: None)
    monkeypatch.setattr(installer, "start_service", lambda *a: None)
    monkeypatch.setattr(installer, "_restart_owned_tunnel", lambda *a: None)
    monkeypatch.setattr(installer, "report", lambda *a, **kw: None)
    monkeypatch.setattr(installer, "report_summary", lambda *a, **kw: None)

    real_atomic = installer.atomic
    target = launcher if interrupted_path == "launcher" else plist

    def interrupt_after_replace(path, data, mode=0o600, *, exact_mode=False):
        real_atomic(path, data, mode, exact_mode=exact_mode)
        if Path(path) == target:
            raise KeyboardInterrupt("simulated process interruption")

    monkeypatch.setattr(installer, "atomic", interrupt_after_replace)
    with pytest.raises(KeyboardInterrupt, match="simulated process interruption"):
        installer.activate(args, release)

    current = prefix / "current.json"
    checkpoint = json.loads(current.read_text())
    backup = Path(checkpoint["backup"])
    assert (backup / "transaction.json").is_file()
    assert (backup / "launcher.before").read_bytes() == old_launcher
    assert (backup / "service.before.plist").read_bytes() == old_plist
    assert checkpoint["launcher"] == str(launcher)
    assert checkpoint["plist"] == str(plist)
    # The fixture has no bridge.sqlite3, so the test cannot copy production state.
    assert not (backup / "bridge.before.sqlite3").exists()

    monkeypatch.setattr(installer, "atomic", real_atomic)
    # Simulate the next installer process by re-reading the persisted checkpoint.
    assert json.loads(current.read_text()) == checkpoint
    installer.rollback(args)
    assert launcher.read_bytes() == old_launcher
    assert plist.read_bytes() == old_plist
    assert not current.exists()


def test_command_timeout_is_bounded_and_does_not_leave_parent_running(installer):
    import subprocess
    import sys

    with pytest.raises(subprocess.TimeoutExpired):
        installer.run([sys.executable, "-c", "import time;time.sleep(20)"], timeout=0.05)


def test_launchctl_bootstrap_retries_transient_failure(installer, monkeypatch, tmp_path):
    from subprocess import CompletedProcess

    calls = []
    sleeps = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        code = 5 if len(calls) < 3 else 0
        return CompletedProcess(argv, code, stdout="", stderr="Input/output error" if code else "")

    monkeypatch.setattr(installer.subprocess, "run", fake_run)
    monkeypatch.setattr(installer.time, "sleep", sleeps.append)
    installer.start_service(SimpleNamespace(service="launchd", plist=tmp_path / "test.plist"))
    assert calls == []  # Nonexistent definition must not bootstrap

    (tmp_path / "test.plist").write_text("placeholder")
    installer.start_service(SimpleNamespace(service="launchd", plist=tmp_path / "test.plist"))
    assert len(calls) == 3
    assert sleeps == [1, 1]


def test_launchctl_bootstrap_errors_are_bounded(installer, monkeypatch, tmp_path):
    from subprocess import CompletedProcess

    path = tmp_path / "test.plist"
    path.write_text("placeholder")
    attempts = []
    monkeypatch.setattr(installer.time, "sleep", lambda n: None)

    def transient(argv, **kwargs):
        attempts.append(argv)
        return CompletedProcess(argv, 5, stdout="", stderr="Input/output error")

    monkeypatch.setattr(installer.subprocess, "run", transient)
    with pytest.raises(RuntimeError, match=r"bootstrap failed \(5\)"):
        installer.start_service(SimpleNamespace(service="launchd", plist=path))
    assert len(attempts) == 30

    attempts.clear()

    def permanent(argv, **kwargs):
        attempts.append(argv)
        return CompletedProcess(argv, 13, stdout="", stderr="Not permitted")

    monkeypatch.setattr(installer.subprocess, "run", permanent)
    with pytest.raises(RuntimeError, match="Not permitted"):
        installer.start_service(SimpleNamespace(service="launchd", plist=path))
    assert len(attempts) == 1


def test_foreign_launcher_refused_before_fresh_config_is_created(installer, tmp_path):
    launcher = tmp_path / "kirabridge"
    launcher.write_text('#!/bin/sh\necho "foreign service"\n')
    config = tmp_path / "config/config.toml"
    args = SimpleNamespace(
        launcher=launcher, config=config, prefix=tmp_path / "install", service="none"
    )
    with pytest.raises(RuntimeError, match="Unrecognized existing launcher"):
        installer.activate(args, tmp_path / "missing-release")
    assert launcher.read_text() == '#!/bin/sh\necho "foreign service"\n'
    assert not config.exists()


def test_bundle_tampering_fails_before_runtime_preparation(installer, tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "payload").mkdir()
    (bundle / "payload/uv.lock").write_text("tampered")
    (bundle / "release.json").write_text(
        json.dumps(
            {
                "version": "0.8.0rc15",
                "commit": "a" * 40,
                "files": {"payload/uv.lock": "0" * 64},
            }
        )
    )
    prefix = tmp_path / "installation"
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        installer.prepare_bundle(SimpleNamespace(bundle=bundle, prefix=prefix))
    assert not prefix.exists()


def test_unsafe_destination_rejected_without_permission_changes(installer, tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("preserve")
    path.chmod(0o644)
    with pytest.raises(RuntimeError, match="Unsafe ownership/permissions"):
        installer.validate_destination(path, private=True)
    assert path.stat().st_mode & 0o777 == 0o644
    assert path.read_text() == "preserve"


def test_loaded_foreign_plist_is_never_stopped(installer, monkeypatch, tmp_path):
    from subprocess import CompletedProcess

    monkeypatch.setattr(
        installer.subprocess,
        "run",
        lambda argv, **kw: CompletedProcess(
            argv, 0, stdout="service = {\n path = /foreign/service.plist\n}", stderr=""
        ),
    )
    with pytest.raises(RuntimeError, match="another plist"):
        installer.loaded(SimpleNamespace(service="launchd", plist=tmp_path / "ours.plist"))


def test_guided_setup_can_prepare_without_writing_launcher(monkeypatch, tmp_path):
    from kirabridge.local_runtime import setup

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = setup(str(tmp_path / "project"), install_wrapper=False)
    assert Path(result["config"]).exists()
    assert not (tmp_path / ".local/bin/kirabridge").exists()


def test_guided_service_supports_the_recorded_launcher(monkeypatch, tmp_path):
    from subprocess import CompletedProcess

    from kirabridge.local_runtime import install_service

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("kirabridge.local_runtime.sys.platform", "darwin")
    monkeypatch.setattr(
        "kirabridge.local_runtime.subprocess.run", lambda argv, **kw: CompletedProcess(argv, 0)
    )
    launcher = str(tmp_path / "bin/kirabridge")
    result = install_service(tmp_path / "config.toml", command=launcher)
    definition = plistlib.loads(Path(result["plist"]).read_bytes())
    assert definition["ProgramArguments"] == [launcher, "serve", "--transport", "http"]
    assert definition["RunAtLoad"] and definition["KeepAlive"] == {"SuccessfulExit": False}


def test_activate_and_rollback_release_sqlite_before_bootstrap(installer, monkeypatch, tmp_path):
    import sqlite3

    prefix = tmp_path / "install"
    prefix.mkdir(mode=0o700)
    state = tmp_path / "data"
    state.mkdir()
    database = state / "bridge.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("create table preserved(value text)")
    config = tmp_path / "config.toml"
    config.write_text("data_dir = " + json.dumps(str(state)))
    release = tmp_path / "runtime"
    release.mkdir()
    (release / "release.json").write_text(json.dumps({"version": "0.8.0rc15", "commit": "a" * 40}))
    args = SimpleNamespace(
        prefix=prefix,
        config=config,
        launcher=tmp_path / "bin/kirabridge",
        plist=tmp_path / "service.plist",
        service="launchd",
        full_access=False,
    )
    monkeypatch.setattr(installer, "loaded", lambda args: True)
    monkeypatch.setattr(installer, "cli", lambda *a, **kw: {"version": "0.8.0rc14"})
    monkeypatch.setattr(
        installer, "wait_health", lambda *a, **kw: {"version": "0.8.0rc15", "runtime": {"pid": 1}}
    )
    monkeypatch.setattr(installer, "stop_service", lambda args: None)
    tunnel_restarts = []
    monkeypatch.setattr(
        installer, "_restart_owned_tunnel", lambda agents: tunnel_restarts.append(agents)
    )
    writes = []

    def bootstrap(args):
        # Models the outgoing daemon's final write needed before launchd can replace it.
        with sqlite3.connect(database, timeout=0) as db:
            db.execute("insert into preserved values ('shutdown completed')")
        writes.append("bootstrap")

    monkeypatch.setattr(installer, "start_service", bootstrap)
    installer.activate(args, release)
    assert tunnel_restarts == [args.plist.parent]
    installer.rollback(args)
    assert tunnel_restarts == [args.plist.parent, args.plist.parent]
    assert writes == ["bootstrap", "bootstrap"]
    with sqlite3.connect(database) as db:
        assert db.execute("select count(*) from preserved").fetchone()[0] == 2


def test_rollback_retains_core_checkpoint_until_tunnel_restart_succeeds(
    installer, monkeypatch, tmp_path
):
    from contextlib import nullcontext

    prefix = tmp_path / "install"
    backup = prefix / "backups/b1"
    backup.mkdir(parents=True)
    config = tmp_path / "config.toml"
    config.write_text("")
    launcher = tmp_path / "bin/kirabridge"
    launcher.parent.mkdir()
    launcher.write_text("new launcher")
    plist = tmp_path / "service.plist"
    plist.write_text("new plist")
    (backup / "launcher.before").write_text("old launcher")
    (backup / "service.before.plist").write_text("old plist")
    args = SimpleNamespace(
        prefix=prefix,
        config=config,
        launcher=launcher,
        plist=plist,
        service="launchd",
    )
    active = {
        "backup": str(backup),
        "config": str(config),
        "launcher": str(launcher),
        "plist": str(plist),
        "service": "launchd",
        "installed_wrapper_sha256": installer.sha(launcher),
        "installed_plist_sha256": installer.sha(plist),
        "had_wrapper": True,
        "had_plist": True,
        "was_loaded": False,
        "previous": None,
        "aux_services": [],
    }
    current = prefix / "current.json"
    installer.jwrite(current, active)
    tunnel_results = iter(["Neustart fehlgeschlagen", None])
    monkeypatch.setattr(installer, "require_visible_terminal", lambda args: None)
    monkeypatch.setattr(installer, "validate_service_owner", lambda args: None)
    monkeypatch.setattr(installer, "require_queue_compatibility", lambda *args: None)
    monkeypatch.setattr(installer, "idle_guard", lambda config: nullcontext())
    monkeypatch.setattr(installer, "stop_service", lambda args: None)
    monkeypatch.setattr(installer, "start_service", lambda args: None)
    monkeypatch.setattr(installer, "loaded", lambda args: False)
    monkeypatch.setattr(installer, "_restart_owned_tunnel", lambda agents: next(tunnel_results))
    monkeypatch.setattr(installer, "report", lambda *args, **kwargs: None)
    monkeypatch.setattr(installer, "report_summary", lambda *args, **kwargs: None)

    installer.rollback(args)

    checkpoint = json.loads(current.read_text())
    assert checkpoint["rollback_core_restored"] is True
    assert checkpoint["restored_installed_wrapper_sha256"] == installer.sha(launcher)
    assert checkpoint["restored_installed_plist_sha256"] == installer.sha(plist)
    assert launcher.read_text() == "old launcher"
    assert plist.read_text() == "old plist"

    installer.rollback(args)

    assert not current.exists()


def test_queue_holds_block_unsafe_downgrade_before_service_switch(
    installer, bridge, config, tmp_path, monkeypatch
):
    policy_path = tmp_path / "config.toml"
    policy_path.write_text("data_dir = " + json.dumps(str(config.state_path)))
    bridge.store.db.execute(
        "INSERT INTO queue_holds VALUES('messages','one','local',1,'withdrawn')"
    )

    def unsupported(*args, **kwargs):
        raise RuntimeError("old runtime has no queue module")

    monkeypatch.setattr(installer, "run", unsupported)
    with pytest.raises(RuntimeError, match="QUEUE COMPATIBILITY"):
        installer.require_queue_compatibility(policy_path, tmp_path / "old-release")
    assert bridge.store.db.execute("SELECT count(*) FROM queue_holds").fetchone()[0] == 1
    monkeypatch.setattr(installer, "run", lambda *args, **kwargs: b"")
    installer.require_queue_compatibility(policy_path, tmp_path / "queue-aware-release")


def test_launchctl_bootstrap_waits_for_delayed_job_removal(installer, monkeypatch, tmp_path):
    from subprocess import CompletedProcess

    path = tmp_path / "service.plist"
    path.write_text("placeholder")
    elapsed = [0.0]
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(kwargs["timeout"])
        code = 5 if elapsed[0] < 8 else 0
        return CompletedProcess(argv, code, stdout="", stderr="Input/output error" if code else "")

    monkeypatch.setattr(installer.subprocess, "run", fake_run)
    monkeypatch.setattr(installer.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(
        installer.time, "sleep", lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds)
    )
    installer.start_service(SimpleNamespace(service="launchd", plist=path))
    assert elapsed[0] == 8 and len(calls) == 9
    assert all(0 < value <= 20 for value in calls)


@pytest.mark.parametrize("timeout_failure", [False, True], ids=["slow-eio", "command-timeout"])
def test_launchctl_bootstrap_command_runtime_consumes_deadline(
    installer, monkeypatch, tmp_path, timeout_failure
):
    from subprocess import CompletedProcess, TimeoutExpired

    path = tmp_path / "service.plist"
    path.write_text("placeholder")
    elapsed, attempts = [0.0], []

    def slow_run(argv, **kwargs):
        attempts.append((elapsed[0], kwargs["timeout"]))
        elapsed[0] += kwargs["timeout"]
        if timeout_failure:
            raise TimeoutExpired(argv, kwargs["timeout"])
        return CompletedProcess(argv, 5, stdout="", stderr="Input/output error")

    monkeypatch.setattr(installer.subprocess, "run", slow_run)
    monkeypatch.setattr(installer.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(
        installer.time, "sleep", lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds)
    )
    expected_error = TimeoutExpired if timeout_failure else RuntimeError
    with pytest.raises(expected_error) as failure:
        installer.start_service(SimpleNamespace(service="launchd", plist=path))
    if not timeout_failure:
        # The final message must carry launchctl's last error, not only "did not settle".
        assert "did not settle within 30 seconds" in str(failure.value)
        assert "last error: Input/output error" in str(failure.value)
    assert attempts == ([(0.0, 20)] if timeout_failure else [(0.0, 20), (21.0, 9.0)])
    assert elapsed[0] == (20 if timeout_failure else 30)
    assert all(start < 30 and 0 < budget <= min(20, 30 - start) for start, budget in attempts)


@pytest.mark.parametrize("lingers", [False, True], ids=["unloads-after-drain", "never-unloads"])
def test_stop_service_waits_until_launchd_drops_the_label(
    installer, monkeypatch, tmp_path, lingers
):
    """bootout may return while the old process drains; bootstrap would then hit EALREADY."""
    path = tmp_path / "service.plist"
    path.write_text("placeholder")
    elapsed, state = [0.0], {"polls": 0, "bootout": 0}

    def fake_loaded(args):
        state["polls"] += 1
        # polls: 1 = initial check in stop_service, then one per second after bootout
        return True if lingers else state["polls"] <= 6

    monkeypatch.setattr(installer, "loaded", fake_loaded)
    monkeypatch.setattr(
        installer, "run", lambda argv, **kwargs: state.__setitem__("bootout", state["bootout"] + 1)
    )
    monkeypatch.setattr(installer.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(
        installer.time, "sleep", lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds)
    )
    args = SimpleNamespace(service="launchd", plist=path)
    if lingers:
        with pytest.raises(RuntimeError, match="90 seconds after bootout"):
            installer.stop_service(args)
        assert elapsed[0] >= 90
    else:
        installer.stop_service(args)
        assert elapsed[0] == 5  # polled once per second until the label was gone
    assert state["bootout"] == 1


def test_status_lines_fall_back_to_plain_text_without_presenter(installer, capsys, monkeypatch):
    monkeypatch.setattr(installer, "PRESENTER", None)
    monkeypatch.setattr(installer.Path, "home", classmethod(lambda cls: Path("/Users/example")))
    installer.report("phase", "Paket prüfen")
    installer.report("ok", "Rückweg gesichert", detail=installer.short("/Users/example/b/1"))
    installer.report_summary("KiraBridge 1.0 ist installiert", [("Quellstand", "abc")])
    assert capsys.readouterr().err == (
        "== Paket prüfen\n"
        "OK Rückweg gesichert (~/b/1)\n"
        "KiraBridge 1.0 ist installiert\n   Quellstand: abc\n"
    )
    assert installer.short("/Users/examplefoo/x") == "/Users/examplefoo/x"


def test_final_check_is_compact_and_never_fails_the_installation(installer, capsys, monkeypatch):
    monkeypatch.setattr(installer, "PRESENTER", None)
    live = {
        "sections": [
            {
                "title": "KiraBridge",
                "items": [
                    {"status": "ok", "label": "Dienst läuft", "detail": "", "hint": ""},
                    {"status": "info", "label": "Version", "detail": "1.0", "hint": ""},
                ],
            },
            {
                "title": "Dienste",
                "items": [
                    {
                        "status": "warn",
                        "label": "Antwortzustellung",
                        "detail": "aus",
                        "hint": "Start",
                    }
                ],
            },
        ]
    }
    calls = []

    def fake_cli(release, config, *argv, timeout=30):
        calls.append(argv)
        return {"live": live}

    monkeypatch.setattr(installer, "cli", fake_cli)
    installer.final_check(SimpleNamespace(config="c"), "r")
    assert calls == [("doctor", "--live", "--json")]
    assert capsys.readouterr().err == (
        "== Abschlussprüfung\n"
        "OK KiraBridge (1 Prüfungen in Ordnung)\n"
        "!! Dienste: Antwortzustellung (aus)\n   -> Start\n"
    )

    def broken(*args, **kwargs):
        raise RuntimeError("daemon unreachable")

    monkeypatch.setattr(installer, "cli", broken)
    installer.final_check(SimpleNamespace(config="c"), "r")
    assert "-- Abschlussprüfung nicht möglich (daemon unreachable)" in capsys.readouterr().err


def _evidence_linked_job(installer, monkeypatch, tmp_path, *, extra_active=False):
    config, task_id = _idle_guard_fixture(tmp_path)
    db = sqlite3.connect(tmp_path / "state" / "bridge.sqlite3")
    db.execute("ALTER TABLE message_jobs ADD COLUMN evidence TEXT NOT NULL DEFAULT '{}'")
    db.execute(
        "INSERT INTO message_jobs VALUES('job-msg','queued',?)",
        (json.dumps({"observation": {"handoff_id": "h-ev", "message_id": "other-msg"}}),),
    )
    db.execute("INSERT INTO visible_handoffs VALUES('h-ev','other-msg','unknown')")
    if extra_active:
        db.execute("INSERT INTO visible_handoffs VALUES('h-2','other-msg','sent')")
    db.commit()
    db.close()
    _authorize_current_terminal_task(installer, monkeypatch, task_id)
    return config


def test_job_linked_to_unknown_handoff_only_via_evidence_is_not_busy(
    installer, monkeypatch, tmp_path
):
    config = _evidence_linked_job(installer, monkeypatch, tmp_path)
    lines = []
    monkeypatch.setattr(installer, "report", lambda kind, msg, **kw: lines.append((kind, msg)))
    with installer.idle_guard(config):
        pass
    assert any(k == "warn" and "job-msg" in m for k, m in lines)


def test_evidence_linked_unknown_handoff_with_active_sibling_is_busy(
    installer, monkeypatch, tmp_path
):
    config = _evidence_linked_job(installer, monkeypatch, tmp_path, extra_active=True)
    with pytest.raises(RuntimeError, match="BUSY"):
        with installer.idle_guard(config):
            pytest.fail("must block")


def _retry_job(installer, monkeypatch, tmp_path, *, deadline_offset, attempted=False):
    config, task_id = _idle_guard_fixture(tmp_path)
    db = sqlite3.connect(tmp_path / "state" / "bridge.sqlite3")
    db.execute("ALTER TABLE message_jobs ADD COLUMN evidence TEXT NOT NULL DEFAULT '{}'")
    evidence = {
        "phase": "receiver_connect",
        "terminal_input_attempted": attempted,
        "waiting_for_receiver": True,
        "receiver_retry": {"deadline": time.time() + deadline_offset},
    }
    db.execute("INSERT INTO message_jobs VALUES('retry-job','queued',?)", (json.dumps(evidence),))
    db.commit()
    db.close()
    _authorize_current_terminal_task(installer, monkeypatch, task_id)
    return config


def test_expired_receiver_retry_without_input_is_reported_not_busy(
    installer, monkeypatch, tmp_path
):
    config = _retry_job(installer, monkeypatch, tmp_path, deadline_offset=-60)
    lines = []
    monkeypatch.setattr(installer, "report", lambda kind, msg, **kw: lines.append((kind, msg)))
    with installer.idle_guard(config):
        pass
    assert any(k == "warn" and "retry-job" in m for k, m in lines)


@pytest.mark.parametrize(("offset", "attempted"), [(300, False), (-60, True)])
def test_open_retry_or_attempted_input_is_still_busy(
    installer, monkeypatch, tmp_path, offset, attempted
):
    config = _retry_job(
        installer, monkeypatch, tmp_path, deadline_offset=offset, attempted=attempted
    )
    with pytest.raises(RuntimeError, match="BUSY"):
        with installer.idle_guard(config):
            pytest.fail("must block")
