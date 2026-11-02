import json
import os
import plistlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.chatgpt_service import (
    LABEL,
    ensure_chatgpt_service,
    restore_chatgpt_service,
    service_definition,
)
from kirabridge.chatgpt_setup import runtime_status
from kirabridge.operator_control import OperatorControl


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    config_path = tmp_path / ".config/kirabridge/config.toml"
    binary = str(tmp_path / ".local/bin/tunnel-client")
    path = tmp_path / "Library/LaunchAgents" / f"{LABEL}.plist"
    path.parent.mkdir(parents=True)
    definition = service_definition(config_path, binary)
    legacy = {k: v for k, v in definition.items() if k != "ThrottleInterval"}
    legacy["KeepAlive"] = {"SuccessfulExit": False}
    path.write_bytes(plistlib.dumps(legacy))
    path.chmod(0o600)
    return SimpleNamespace(
        path=path, config=config_path, binary=binary, definition=definition, legacy=legacy
    )


def loaded(service, *, pid=42):
    return (
        "state = running\nprogram = "
        + service.binary
        + "\narguments = {\n"
        + "\n".join(service.definition["ProgramArguments"])
        + f"\n}}\npid = {pid}\n"
    )


def test_exact_migration_preflight_backup_and_restore(service):
    old = service.path.read_bytes()
    plan = ensure_chatgpt_service(
        service.config, service.binary, loaded_output=loaded(service), dry_run=True
    )
    assert plan["changed"] and service.path.read_bytes() == old
    assert not Path(plan["backup"]).exists()
    result = ensure_chatgpt_service(service.config, service.binary, loaded_output=loaded(service))
    definition = plistlib.loads(service.path.read_bytes())
    assert definition["KeepAlive"] is True and definition["ThrottleInterval"] == 30
    assert Path(result["backup"]).read_bytes() == old
    assert service.path.stat().st_mode & 0o077 == 0
    assert not ensure_chatgpt_service(service.config, service.binary)["changed"]
    restore_chatgpt_service(result)
    assert service.path.read_bytes() == old


@pytest.mark.parametrize("change", ["argv", "environment", "loaded", "symlink", "unsafe"])
def test_migration_refuses_custom_and_unsafe_jobs_without_mutation(service, tmp_path, change):
    if change in {"argv", "environment"}:
        value = service.legacy.copy()
        if change == "argv":
            value["ProgramArguments"] = ["/bin/echo", "foreign service"]
        else:
            value["EnvironmentVariables"] = {"CUSTOM": "must preserve"}
        service.path.write_bytes(plistlib.dumps(value))
    elif change == "symlink":
        foreign = tmp_path / "foreign.plist"
        service.path.rename(foreign)
        service.path.symlink_to(foreign)
    elif change == "unsafe":
        service.path.chmod(0o666)
    before = service.path.read_bytes()
    with pytest.raises(BridgeError):
        ensure_chatgpt_service(
            service.config,
            service.binary,
            loaded_output=(
                loaded(service).replace("run\n", "foreign\n") if change == "loaded" else None
            ),
        )
    assert service.path.read_bytes() == before
    assert not list(service.path.parent.glob("*.backup-*"))


def test_restore_refuses_intervening_customization(service):
    result = ensure_chatgpt_service(service.config, service.binary)
    value = service.definition.copy()
    value["EnvironmentVariables"] = {"CUSTOM": "preserve"}
    service.path.write_bytes(plistlib.dumps(value))
    before = service.path.read_bytes()
    with pytest.raises(BridgeError, match="changed after migration"):
        restore_chatgpt_service(result)
    assert service.path.read_bytes() == before


@pytest.mark.parametrize("observed,needs_reload", [(False, True), (True, False)])
def test_current_disk_definition_requires_loaded_recovery_evidence(service, observed, needs_reload):
    ensure_chatgpt_service(service.config, service.binary)
    output = loaded(service)
    if observed:
        output += "properties = runatload | keepalive\nminimum runtime = 30\n"
    else:
        output += "properties = runatload\nminimum runtime = 10\n"
    before = service.path.read_bytes()
    result = ensure_chatgpt_service(service.config, service.binary, loaded_output=output)
    assert not result["changed"] and result["reload_required"] is needs_reload
    assert service.path.read_bytes() == before


def test_new_registration_requires_explicit_create_and_has_no_secret_arguments(service):
    service.path.unlink()
    assert not ensure_chatgpt_service(service.config, service.binary)["changed"]
    assert not service.path.exists()
    result = ensure_chatgpt_service(service.config, service.binary, create=True)
    assert result["changed"] and result["backup"] is None
    definition = plistlib.loads(service.path.read_bytes())
    assert definition == service.definition
    assert not any("key" in arg or "token" in arg for arg in definition["ProgramArguments"])


@pytest.mark.parametrize(
    "healthy,ready,foreign,connected",
    [
        (True, True, False, True),
        (False, True, False, False),
        (True, False, False, False),
        (True, True, True, False),
    ],
)
def test_live_managed_process_replaces_stale_alias_pid_but_not_failed_health(
    service, monkeypatch, healthy, ready, foreign, connected
):
    def run(argv, **kwargs):
        if "runtimes" in argv:
            payload = {
                "process_running": False,
                "healthy": healthy,
                "ready": ready,
                "local": {"process": {"pid": 999999}, "process_running": False},
            }
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload))
        if "print" in argv:
            return SimpleNamespace(returncode=0, stdout=loaded(service))
        assert argv[:4] == ["/bin/ps", "-p", "42", "-o"]
        args = ["/bin/echo", "foreign"] if foreign else service.definition["ProgramArguments"]
        import shlex

        return SimpleNamespace(returncode=0, stdout=f"{os.getuid()} {shlex.join(args)}\n")

    monkeypatch.setattr("kirabridge.chatgpt_setup.subprocess.run", run)
    monkeypatch.setattr("kirabridge.chatgpt_setup.sys.platform", "darwin")
    actual = runtime_status(service.binary, service.config)
    assert actual["connected"] is connected
    assert actual["chatgpt_tool_call"] == "unverified"


@pytest.mark.asyncio
@pytest.mark.parametrize("bootstrap_fails", [False, True])
@pytest.mark.parametrize("action", ["start", "restart"])
async def test_operator_reloads_migrated_job_once_and_restores_on_failure(
    service, monkeypatch, bootstrap_fails, action
):
    original = service.path.read_bytes()
    profile = service.config.parent / "tunnel/kirabridge.yaml"
    profile.parent.mkdir(parents=True)
    profile.write_text("account data stays untouched")
    monkeypatch.setattr("kirabridge.setup_dependencies.local_client", lambda p: service.binary)
    config = SimpleNamespace(_source_path=str(service.config), agents={})
    control = OperatorControl(
        config=lambda: config,
        queries=None,
        daemon=None,
        platform=None,
        actions=None,
        maintenance=None,
        grant_window=None,
        audit=None,
        connectors=None,
    )
    commands = []

    async def command(*args, **kwargs):
        commands.append(args)
        if "print" in args:
            return 0, loaded(service), ""
        if "bootstrap" in args and bootstrap_fails and sum("bootstrap" in c for c in commands) == 1:
            return 1, "", "failed"
        return 0, "", ""

    monkeypatch.setattr(control, "command", command)
    if bootstrap_fails:
        with pytest.raises(BridgeError, match="wiederhergestellt"):
            await control.service_action("chatgpt", action, "one-operation")
        assert service.path.read_bytes() == original
    else:
        result = await control.service_action("chatgpt", action, "one-operation")
        assert result["autostart_updated"]
        assert plistlib.loads(service.path.read_bytes())["KeepAlive"] is True
    assert sum("bootout" in c for c in commands) == 1
    assert sum("bootstrap" in c for c in commands) == (2 if bootstrap_fails else 1)
    assert not any("kickstart" in c for c in commands)
    assert profile.read_text() == "account data stays untouched"


@pytest.mark.asyncio
async def test_operator_waits_only_for_eio_after_teardown(service, monkeypatch):
    profile = service.config.parent / "tunnel/kirabridge.yaml"
    profile.parent.mkdir(parents=True)
    profile.write_text("unchanged")
    monkeypatch.setattr("kirabridge.setup_dependencies.local_client", lambda p: service.binary)
    config = SimpleNamespace(_source_path=str(service.config), agents={})
    control = OperatorControl(
        config=lambda: config,
        queries=None,
        daemon=None,
        platform=None,
        actions=None,
        maintenance=None,
        grant_window=None,
        audit=None,
        connectors=None,
    )
    commands, sleeps = [], []

    async def command(*args, **kwargs):
        commands.append(args)
        if "print" in args:
            return 0, loaded(service), ""
        if "bootstrap" in args and sum("bootstrap" in c for c in commands) == 1:
            return 5, "", "EIO"
        return 0, "", ""

    async def pause(delay):
        sleeps.append(delay)

    monkeypatch.setattr(control, "command", command)
    monkeypatch.setattr("kirabridge.operator_control.asyncio.sleep", pause)
    result = await control.service_action("chatgpt", "restart", "one-operation")
    assert result["autostart_updated"] and len(sleeps) == 1
    assert sum("bootout" in c for c in commands) == 1
    assert sum("bootstrap" in c for c in commands) == 2


@pytest.mark.asyncio
async def test_unmanaged_live_tunnel_registers_recovery_without_duplicate(service, monkeypatch):
    profile = service.config.parent / "tunnel/kirabridge.yaml"
    profile.parent.mkdir(parents=True)
    profile.write_text("unchanged")
    monkeypatch.setattr("kirabridge.setup_dependencies.local_client", lambda p: service.binary)
    config = SimpleNamespace(_source_path=str(service.config), agents={})
    control = OperatorControl(
        config=lambda: config,
        queries=None,
        daemon=None,
        platform=None,
        actions=None,
        maintenance=None,
        grant_window=None,
        audit=None,
        connectors=None,
    )
    commands = []

    async def command(*args, **kwargs):
        commands.append(args)
        assert "print" in args
        return 1, "", "not loaded"

    async def snapshot(**kwargs):
        return {"services": [{"id": "chatgpt", "active": True}]}

    monkeypatch.setattr(control, "command", command)
    monkeypatch.setattr(control, "snapshot", snapshot)
    result = await control.service_action("chatgpt", "start", "preserve-live")
    assert result["existing_runtime_preserved"] and result["autostart_updated"]
    assert len(commands) == 1
    assert plistlib.loads(service.path.read_bytes())["KeepAlive"] is True


@pytest.mark.asyncio
async def test_bootstrap_timeout_remains_unknown_without_restore_or_replay(service, monkeypatch):
    profile = service.config.parent / "tunnel/kirabridge.yaml"
    profile.parent.mkdir(parents=True)
    profile.write_text("unchanged")
    monkeypatch.setattr("kirabridge.setup_dependencies.local_client", lambda p: service.binary)
    config = SimpleNamespace(_source_path=str(service.config), agents={})
    control = OperatorControl(
        config=lambda: config,
        queries=None,
        daemon=None,
        platform=None,
        actions=None,
        maintenance=None,
        grant_window=None,
        audit=None,
        connectors=None,
    )
    commands = []

    async def command(*args, **kwargs):
        commands.append(args)
        if "print" in args:
            return 0, loaded(service), ""
        if "bootstrap" in args:
            raise TimeoutError("receipt unknown")
        return 0, "", ""

    monkeypatch.setattr(control, "command", command)
    with pytest.raises(BridgeError) as error:
        await control.service_action("chatgpt", "start", "unknown-start")
    assert error.value.code == "service_start_unknown"
    assert sum("bootstrap" in c for c in commands) == 1
    assert plistlib.loads(service.path.read_bytes())["KeepAlive"] is True


@pytest.mark.asyncio
async def test_partial_migration_reloads_stale_loaded_policy(service, monkeypatch):
    ensure_chatgpt_service(service.config, service.binary)
    profile = service.config.parent / "tunnel/kirabridge.yaml"
    profile.parent.mkdir(parents=True)
    profile.write_text("unchanged")
    monkeypatch.setattr("kirabridge.setup_dependencies.local_client", lambda p: service.binary)
    config = SimpleNamespace(_source_path=str(service.config), agents={})
    control = OperatorControl(
        config=lambda: config,
        queries=None,
        daemon=None,
        platform=None,
        actions=None,
        maintenance=None,
        grant_window=None,
        audit=None,
        connectors=None,
    )
    commands = []

    async def command(*args, **kwargs):
        commands.append(args)
        if "print" in args:
            return 0, loaded(service) + "properties = runatload\nminimum runtime = 10\n", ""
        return 0, "", ""

    monkeypatch.setattr(control, "command", command)
    result = await control.service_action("chatgpt", "start", "finish-reload")
    assert result["autostart_updated"]
    assert sum("bootout" in c for c in commands) == 1
    assert sum("bootstrap" in c for c in commands) == 1
