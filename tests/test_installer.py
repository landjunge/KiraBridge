import importlib.util
import json
import plistlib
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


@pytest.mark.parametrize(
    "timeout_failure", [False, True], ids=["bootstrap-error", "bootstrap-timeout"]
)
def test_launchd_failure_restores_previous_definition_without_config_restore(
    installer, tmp_path, monkeypatch, timeout_failure
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
    with pytest.raises(type(failure), match="SIMULATED"):
        installer.activate(args, release)
    assert launcher.read_bytes() == old_launcher
    assert plist.read_bytes() == old_plist
    assert config.read_bytes() == original_config
    assert not (prefix / "current.json").exists()
    assert operations == ["stop", "start", "stop", "start"]


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
    writes = []

    def bootstrap(args):
        # Models the outgoing daemon's final write needed before launchd can replace it.
        with sqlite3.connect(database, timeout=0) as db:
            db.execute("insert into preserved values ('shutdown completed')")
        writes.append("bootstrap")

    monkeypatch.setattr(installer, "start_service", bootstrap)
    installer.activate(args, release)
    installer.rollback(args)
    assert writes == ["bootstrap", "bootstrap"]
    with sqlite3.connect(database) as db:
        assert db.execute("select count(*) from preserved").fetchone()[0] == 2


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
    with pytest.raises(expected_error):
        installer.start_service(SimpleNamespace(service="launchd", plist=path))
    assert attempts == ([(0.0, 20)] if timeout_failure else [(0.0, 20), (21.0, 9.0)])
    assert elapsed[0] == (20 if timeout_failure else 30)
    assert all(start < 30 and 0 < budget <= min(20, 30 - start) for start, budget in attempts)


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
