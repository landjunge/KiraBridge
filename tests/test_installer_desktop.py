"""Desktop upgrade boundaries and recovery must preserve unrelated operator data."""

import contextlib
import hashlib
import importlib.util
import json
import plistlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def desktop():
    path = Path(__file__).parents[1] / "installer/desktop.py"
    spec = importlib.util.spec_from_file_location("desktop_install_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_foreign_companion_is_preserved_before_service_access(desktop, monkeypatch, tmp_path):
    monkeypatch.setattr(desktop.Path, "home", lambda: tmp_path)
    app = tmp_path / "Applications/KiraBridge.app"
    app.mkdir(parents=True)
    (app / "operator.txt").write_text("unrelated app data")
    release = tmp_path / "release"
    release.mkdir()
    (release / "release.json").write_text(json.dumps({"native_app_required": True}))
    api = SimpleNamespace(LABEL="com.kirabridge.bridge", validate_destination=lambda p: None)
    with pytest.raises(RuntimeError, match="differs from recorded"):
        desktop.snapshot(api, SimpleNamespace(service="launchd"), release, {}, tmp_path)
    assert (app / "operator.txt").read_text() == "unrelated app data"


def test_rollback_does_not_overwrite_later_operator_service_changes(desktop, tmp_path):
    plist = tmp_path / "chatgpt.plist"
    plist.write_bytes(plistlib.dumps({"operator": "changed after installation"}))
    old_hash = hashlib.sha256(b"installed plist").hexdigest()
    active = {
        "backup": str(tmp_path),
        "desktop": {
            "services": [
                {
                    "changed": True,
                    "path": str(plist),
                    "installed_sha256": old_hash,
                    "before_sha256": "a" * 64,
                }
            ]
        },
    }
    api = SimpleNamespace(sha=lambda p: hashlib.sha256(p.read_bytes()).hexdigest())
    with pytest.raises(RuntimeError, match="changed after activation"):
        desktop.restore(api, active)
    assert plistlib.loads(plist.read_bytes())["operator"] == "changed after installation"


def test_activation_detects_concurrent_plist_change_before_any_mutation(desktop, tmp_path):
    plist = tmp_path / "approvals.plist"
    plist.write_text("changed")
    app = tmp_path / "absent.app"
    active = {
        "backup": str(tmp_path),
        "desktop": {
            "app": str(app),
            "app_before": None,
            "services": [{"path": str(plist), "before_sha256": "a" * 64}],
        },
    }
    api = SimpleNamespace(sha=lambda p: hashlib.sha256(p.read_bytes()).hexdigest())
    with pytest.raises(RuntimeError, match="service changed during"):
        desktop.activate(api, None, tmp_path, active, tmp_path / "current.json")
    assert not app.exists()
    assert plist.read_text() == "changed"


def test_failed_upgrade_restores_old_companion_and_keeps_failed_build(desktop, tmp_path):
    app = tmp_path / "KiraBridge.app"
    app.mkdir()
    (app / "binary").write_bytes(b"new app")
    backup = tmp_path / "backup"
    previous = backup / "desktop.before.app"
    previous.mkdir(parents=True)
    (previous / "binary").write_bytes(b"previous app")
    active = {
        "backup": str(backup),
        "desktop": {
            "services": [],
            "app_mutating": True,
            "app": str(app),
            "app_installed": desktop.files(app),
            "app_before": {"binary": hashlib.sha256(b"previous app").hexdigest()},
        },
    }
    desktop.restore(SimpleNamespace(), active)
    assert (app / "binary").read_bytes() == b"previous app"
    assert (backup / "desktop.failed.app/binary").read_bytes() == b"new app"


def test_desktop_module_rejects_corruption_before_executing(tmp_path):
    path = Path(__file__).parents[1] / "installer/install.py"
    spec = importlib.util.spec_from_file_location("installer_loader_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "release.json").write_text(
        json.dumps(
            {
                "files": {"installer/desktop.py": "a" * 64},
            }
        )
    )
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        module.desktop_module(SimpleNamespace(bundle=tmp_path))


@pytest.mark.parametrize("difference", ["path", "program", "arguments"])
def test_loaded_job_identity_is_verified_before_unload(desktop, monkeypatch, tmp_path, difference):
    path = tmp_path / "service.plist"
    arguments = ["/trusted/python", "-m", "kirabridge.cli", "approval-server"]
    observed = arguments.copy()
    observed_path = str(path)
    program = arguments[0]
    if difference == "path":
        observed_path = "/other/foreign.plist"
    elif difference == "program":
        program = "/other/program"
    else:
        observed[-1] = "unrelated-service"
    output = (
        f"path = {observed_path}\nprogram = {program}\narguments = {{\n"
        + "\n".join(observed)
        + "\n}\n"
    )
    calls = []

    def inspect(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

    monkeypatch.setattr(desktop.subprocess, "run", inspect)
    with pytest.raises(RuntimeError, match="differs from expected"):
        desktop.stop(
            SimpleNamespace(),
            "com.kirabridge.approvals",
            path=path,
            definition={"ProgramArguments": arguments},
        )
    assert len(calls) == 1
    assert calls[0][1] == "print"


def test_pre_rename_interruption_preserves_untouched_old_app(desktop, tmp_path):
    app = tmp_path / "KiraBridge.app"
    app.mkdir()
    (app / "binary").write_bytes(b"old app remains untouched")
    active = {
        "backup": str(tmp_path / "backup"),
        "desktop": {
            "services": [],
            "app_mutating": True,
            "app": str(app),
            "app_before": desktop.files(app),
            "app_was_running": False,
            "app_expected": {"binary": "a" * 64},
        },
    }
    desktop.restore(SimpleNamespace(), active)
    assert (app / "binary").read_bytes() == b"old app remains untouched"
    assert not (tmp_path / "backup/desktop.failed.app").exists()


def test_missing_old_app_backup_refuses_before_renaming_current_app(desktop, tmp_path):
    app = tmp_path / "KiraBridge.app"
    app.mkdir()
    (app / "binary").write_bytes(b"current installed app")
    active = {
        "backup": str(tmp_path / "backup"),
        "desktop": {
            "services": [],
            "app_mutating": True,
            "app": str(app),
            "app_before": {"binary": "a" * 64},
            "app_installed": desktop.files(app),
        },
    }
    with pytest.raises(RuntimeError, match="backup missing"):
        desktop.restore(SimpleNamespace(), active)
    assert (app / "binary").read_bytes() == b"current installed app"


def test_service_rollback_restores_original_bytes_modes_and_can_resume(
    desktop, monkeypatch, tmp_path
):
    path = tmp_path / "chatgpt.plist"
    path.write_bytes(plistlib.dumps({"Label": "com.kirabridge.chatgpt", "KeepAlive": True}))
    backup = tmp_path / "backup"
    backup.mkdir()
    saved = backup / "chatgpt.before.plist"
    original = plistlib.dumps(
        {"Label": "com.kirabridge.chatgpt", "KeepAlive": {"SuccessfulExit": False}}
    )
    saved.write_bytes(original)
    saved.chmod(0o644)
    row = {
        "name": "chatgpt",
        "label": "com.kirabridge.chatgpt",
        "path": str(path),
        "changed": True,
        "existed": True,
        "was_loaded": True,
        "before_sha256": hashlib.sha256(original).hexdigest(),
        "installed_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    active = {"backup": str(backup), "desktop": {"services": [row]}}
    writes = []
    starts = []
    stops = []

    def atomic(destination, data, mode):
        writes.append(destination)
        destination.write_bytes(data)
        destination.chmod(mode)

    def start(api, destination):
        starts.append(destination)
        if len(starts) == 1:
            raise RuntimeError("simulated bootstrap failure")

    api = SimpleNamespace(sha=lambda p: hashlib.sha256(p.read_bytes()).hexdigest(), atomic=atomic)
    monkeypatch.setattr(desktop, "stop", lambda *a, **kw: stops.append(a[1]))
    monkeypatch.setattr(desktop, "job", lambda *a, **kw: False)
    monkeypatch.setattr(desktop, "start", start)
    with pytest.raises(RuntimeError, match="simulated bootstrap"):
        desktop.restore(api, active)
    assert row["restored"]
    assert path.read_bytes() == original
    assert path.stat().st_mode & 0o777 == 0o644
    desktop.restore(api, active)
    assert writes == [path] and stops == [row["label"]] and starts == [path, path]


def test_partial_desktop_failure_keeps_core_recovery_record_until_resumed(monkeypatch, tmp_path):
    path = Path(__file__).parents[1] / "installer/install.py"
    spec = importlib.util.spec_from_file_location("installer_recovery_review", path)
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    prefix = tmp_path / "install"
    backup = prefix / "backups/transaction"
    backup.mkdir(parents=True)
    launcher = tmp_path / "launcher"
    plist = tmp_path / "service.plist"
    config = tmp_path / "config.toml"
    config.write_text("preserved configuration")
    launcher.write_bytes(b"new launcher")
    plist.write_bytes(b"new plist")
    (backup / "launcher.before").write_bytes(b"previous launcher")
    (backup / "service.before.plist").write_bytes(b"previous plist")
    previous = {"release": str(tmp_path / "old-release"), "commit": "a" * 40}
    active = {
        "previous": previous,
        "release": str(tmp_path / "new-release"),
        "backup": str(backup),
        "had_wrapper": True,
        "had_plist": True,
        "was_loaded": True,
        "previous_version": "0.8.0rc24",
        "config": str(config),
        "launcher": str(launcher),
        "plist": str(plist),
        "service": "launchd",
        "desktop": {"services": []},
        "installed_wrapper_sha256": hashlib.sha256(launcher.read_bytes()).hexdigest(),
        "installed_plist_sha256": hashlib.sha256(plist.read_bytes()).hexdigest(),
    }
    current = prefix / "current.json"
    installer.jwrite(current, active)
    args = SimpleNamespace(
        prefix=prefix, config=config, launcher=launcher, plist=plist, service="launchd"
    )
    monkeypatch.setattr(installer, "require_visible_terminal", lambda *a: None)
    monkeypatch.setattr(installer, "validate_service_owner", lambda *a: None)
    monkeypatch.setattr(installer, "require_queue_compatibility", lambda *a: None)
    monkeypatch.setattr(installer, "idle_guard", lambda *a: contextlib.nullcontext())
    monkeypatch.setattr(installer, "loaded", lambda *a: True)
    core_actions = []
    monkeypatch.setattr(installer, "stop_service", lambda *a: core_actions.append("stop"))
    monkeypatch.setattr(installer, "start_service", lambda *a: core_actions.append("start"))
    monkeypatch.setattr(installer, "wait_health", lambda *a: None)
    attempts = []

    def restore(api, recorded, recorded_current):
        attempts.append(True)
        assert recorded_current == current
        assert json.loads(current.read_text())["rollback_core_restored"]
        if len(attempts) == 1:
            raise RuntimeError("simulated desktop recovery interruption")

    monkeypatch.setattr(installer, "desktop_module", lambda *a: SimpleNamespace(restore=restore))
    with pytest.raises(RuntimeError, match="recovery interruption"):
        installer.rollback(args)
    assert launcher.read_bytes() == b"previous launcher"
    assert plist.read_bytes() == b"previous plist"
    assert config.read_text() == "preserved configuration"
    assert json.loads(current.read_text())["desktop"] == {"services": []}
    installer.rollback(args)
    assert core_actions == ["stop", "start"]
    assert json.loads(current.read_text()) == previous


DEV = "/Users/operator/KiraBridge"


def service_definitions(config):
    return {
        "grok-app": {
            "Label": "com.kirabridge.grok-app",
            "EnvironmentVariables": {"PATH": "/operator/bin"},
            "KeepAlive": True,
            "ProgramArguments": [
                DEV + "/.venv/bin/python",
                *["-m", "kirabridge.cli", "--config", str(config), "grok-connector", "serve"],
            ],
        },
        "chat-events": {
            "Label": "com.kirabridge.chat-events",
            "KeepAlive": False,
            "WorkingDirectory": DEV,
            "ProgramArguments": [
                DEV + "/integrations/chat-events/.venv/bin/python",
                DEV + "/integrations/chat-events/serve.py",
                *["--config", str(config), "--principal", "chatgpt"],
                *["--state", "/operator/event-state", "--sender-only"],
            ],
        },
    }


@pytest.fixture
def services(desktop, monkeypatch, tmp_path):
    """Real installer file helpers; launchd, codesign and the app are simulated."""
    spec = importlib.util.spec_from_file_location(
        "installer_services_test", Path(__file__).parents[1] / "installer/install.py"
    )
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    monkeypatch.setattr(desktop.Path, "home", lambda: tmp_path)
    config = tmp_path / "config.toml"
    agents = tmp_path / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    for name, definition in service_definitions(config).items():
        (agents / f"com.kirabridge.{name}.plist").write_bytes(plistlib.dumps(definition))
    log = []
    monkeypatch.setattr(desktop, "job", lambda api, label, **kw: bool(kw.get("definition")))
    monkeypatch.setattr(desktop, "stop", lambda api, label, **kw: log.append(("stop", label)))
    monkeypatch.setattr(desktop, "start", lambda api, path: log.append(("start", path.name)))
    monkeypatch.setattr(desktop, "app_processes", lambda app: [])
    monkeypatch.setattr(desktop, "start_app", lambda api, app: [])

    def release(name):
        root = tmp_path / name
        (root / "source/integrations/chat-events").mkdir(parents=True)
        (root / "source/integrations/chat-events/serve.py").write_text("sender")
        (root / "release.json").write_text(json.dumps({"native_app_required": True}))
        return root

    def copy_native(source, staged, active):
        (staged / "native/KiraBridge.app").mkdir(parents=True)
        (staged / "native/KiraBridge.app/binary").write_text(source.name)

    def transaction(target, old=None):
        backup = tmp_path / "backups" / target.name
        backup.mkdir(parents=True)
        if old:
            app = tmp_path / "Applications/KiraBridge.app"
            recorded = {"native/KiraBridge.app/" + k: v for k, v in desktop.files(app).items()}
        state = desktop.snapshot(
            api, args, target, {"release": str(old), "files": recorded} if old else None, backup
        )
        return {"backup": str(backup), "desktop": state}

    args = SimpleNamespace(service="launchd", config=config)
    api = SimpleNamespace(
        **{
            **vars(installer),
            "validate_destination": lambda path: None,
            "copy_native": copy_native,
            "run": lambda argv, **kw: log.append(("run", Path(argv[0]).name)),
        }
    )
    return SimpleNamespace(
        api=api, args=args, agents=agents, log=log, release=release, transaction=transaction
    )


def plist(services, name):
    return plistlib.loads((services.agents / f"com.kirabridge.{name}.plist").read_bytes())


def test_install_moves_existing_services_to_release_venv_and_rollback_restores(desktop, services):
    original = {
        name: (services.agents / f"com.kirabridge.{name}.plist").read_bytes()
        for name in ("grok-app", "chat-events")
    }
    release = services.release("rc44")
    active = services.transaction(release)
    assert [row["name"] for row in active["desktop"]["services"]] == [
        "approvals",
        "grok-app",
        "chat-events",
    ]
    desktop.activate(services.api, services.args, release, active, release / "current.json")
    runtime = str(release / "source/.venv/bin/python")
    grok, events = plist(services, "grok-app"), plist(services, "chat-events")
    config = str(services.args.config)
    assert grok["ProgramArguments"] == [
        *[runtime, "-m", "kirabridge.cli", "--config", config, "grok-connector", "serve"]
    ]
    assert grok["EnvironmentVariables"] == {"PATH": "/operator/bin"}
    assert events["ProgramArguments"] == [
        runtime,
        str(release / "source/integrations/chat-events/serve.py"),
        *service_definitions(config)["chat-events"]["ProgramArguments"][2:],
    ]
    assert events["WorkingDirectory"] == str(release / "source")
    assert ("start", "com.kirabridge.chat-events.plist") in services.log
    desktop.restore(services.api, active)
    for name, data in original.items():
        assert (services.agents / f"com.kirabridge.{name}.plist").read_bytes() == data


def test_update_repins_services_from_previous_release(desktop, services):
    first = services.release("rc44")
    active = services.transaction(first)
    desktop.activate(services.api, services.args, first, active, first / "current.json")
    installed = plist(services, "chat-events")
    second = services.release("rc45")
    update = services.transaction(second, old=first)
    desktop.activate(services.api, services.args, second, update, second / "current.json")
    runtime = str(second / "source/.venv/bin/python")
    assert plist(services, "grok-app")["ProgramArguments"][0] == runtime
    assert plist(services, "chat-events")["ProgramArguments"][:2] == [
        runtime,
        str(second / "source/integrations/chat-events/serve.py"),
    ]
    desktop.restore(services.api, update)
    assert plist(services, "chat-events") == installed


def test_unexpected_or_missing_services_are_preserved(desktop, services):
    path = services.agents / "com.kirabridge.grok-app.plist"
    path.unlink()
    events = services.agents / "com.kirabridge.chat-events.plist"
    definition = plist(services, "chat-events")
    definition["ProgramArguments"].remove("--sender-only")  # MCP-2 frontend, not the sender
    events.write_bytes(plistlib.dumps(definition))
    with pytest.raises(RuntimeError, match="chat-events service differs"):
        services.transaction(services.release("rc44"))
    assert not path.exists() and plistlib.loads(events.read_bytes()) == definition
