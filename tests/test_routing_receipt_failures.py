"""Native-review regressions, isolated files and mocked model runner only."""

import json
import os
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from kirabridge.capability_routing import hook, launcher
from kirabridge.capability_routing.router import (
    Access,
    Capability,
    Matrix,
    Model,
    RoutingError,
    Runtime,
    Task,
)


@pytest.fixture
def writable(tmp_path, monkeypatch):
    exe = tmp_path / "native"
    exe.write_text("fixture")
    exe.chmod(0o700)
    now = datetime.now(timezone.utc)
    start = (now - timedelta(minutes=1)).isoformat()
    end = (now + timedelta(minutes=30)).isoformat()
    matrix = Matrix(
        schema_version="bigplan.cli-matrix.v1",
        checked_at=start,
        expires_at=end,
        clis=[
            Capability(
                id="codex",
                installed_version="fixture1",
                capabilities=["headless", "coding"],
                models=[
                    Model(
                        id="fixture",
                        provider="openai",
                        efforts=["xhigh"],
                        fit={"security": 5},
                        cost_rank=1,
                        evidence="fixture",
                    )
                ],
                documented_models=[],
                sources=["fixture"],
                limitations="fixture",
            )
        ],
    )
    runtime = Runtime(
        schema_version="bigplan.cli-runtime.v1",
        allow_write=True,
        allowed_roots=[str(tmp_path)],
        state_dir=str(tmp_path / "receipts"),
        access=[
            Access(
                cli="codex",
                executable=str(exe),
                version="fixture1",
                models=["fixture"],
                access_kind="subscription",
                verified_at=start,
                expires_at=end,
                evidence="fixture",
            )
        ],
    )
    task = Task(
        task_id="owned-fixture",
        workload="security",
        prompt="fixture",
        cwd=str(tmp_path),
        ownership_ref="fixture",
        allowed_clis=["codex"],
        explicit_cli="codex",
        explicit_model="fixture",
        explicit_effort="xhigh",
        read_only=False,
    )

    class Source:
        calls = 0

        def load(self):
            self.calls += 1
            return matrix, {"thread_id": "fixture", "revision": 1}

    def metadata(argv, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout="fixture1\n" if "--version" in argv else "Logged in using ChatGPT\n",
            stderr="",
        )

    monkeypatch.setattr(hook.subprocess, "run", metadata)
    return Source(), runtime, task, matrix


def receipt(runtime, task):
    return json.loads((Path(runtime.state_dir) / (task.task_id + ".json")).read_text())


def leases(runtime):
    return list(Path(runtime.state_dir).glob("cwd-*.lock"))


def completed(*args, **kwargs):
    return SimpleNamespace(returncode=0, stdout=b"answer", stderr=b"")


def test_execute_cannot_disable_mandatory_probes(writable):
    source, runtime, task, _ = writable
    calls = []
    with pytest.raises(RoutingError):
        launcher.launch(
            source, runtime, task, execute=True, probe=False, runner=lambda *a, **k: calls.append(1)
        )
    assert not calls and not Path(runtime.state_dir).exists()


@pytest.mark.parametrize(
    "failure",
    [
        RoutingError("fixture"),
        launcher.OutcomeUncertain("fixture"),
        FileExistsError("fixture"),
        ValueError("fixture"),
    ],
)
def test_post_boundary_failures_unknown_keep_lease_and_never_replay(writable, failure):
    source, runtime, task, _ = writable

    def runner(*args, **kwargs):
        raise failure

    result = launcher.launch(source, runtime, task, execute=True, runner=runner)
    assert result["state"] == "unknown" and receipt(runtime, task)["state"] == "unknown"
    assert leases(runtime)
    with pytest.raises(RoutingError, match="already admitted"):
        launcher.launch(source, runtime, task, execute=True, runner=runner)


@pytest.mark.parametrize("failure", [KeyboardInterrupt(), SystemExit(3)])
def test_base_exception_persists_unknown_before_propagation(writable, failure):
    source, runtime, task, _ = writable

    def runner(*args, **kwargs):
        raise failure

    with pytest.raises(type(failure)):
        launcher.launch(source, runtime, task, execute=True, runner=runner)
    assert receipt(runtime, task)["state"] == "unknown" and leases(runtime)


def test_pre_spawn_read_error_is_blocked_and_releases_lease(writable):
    source, runtime, task, _ = writable
    original = source.load
    called = []

    def load():
        if source.calls:
            raise OSError("metadata unavailable")
        return original()

    source.load = load
    result = launcher.launch(
        source, runtime, task, execute=True, runner=lambda *a, **k: called.append(1)
    )
    assert result["state"] == "blocked" and not called and not leases(runtime)
    assert receipt(runtime, task)["effect_boundary_crossed"] is False


def test_exit_confirmed_processing_failure_does_not_claim_blocked(writable, monkeypatch):
    source, runtime, task, _ = writable

    def broken(*args):
        raise RoutingError("post-exit decoding failure")

    monkeypatch.setattr(launcher, "native_metadata", broken)
    result = launcher.launch(source, runtime, task, execute=True, runner=completed)
    assert result["state"] == "unknown" and result["process_exit_confirmed"] is True
    assert not leases(runtime)  # confirmed child exit makes another writer safe


def test_root_change_during_metadata_is_pre_admission_denial(writable, monkeypatch):
    source, runtime, task, _ = writable
    original = hook.subprocess.run
    called = []

    def changed(argv, **kwargs):
        result = original(argv, **kwargs)
        if "status" in argv:
            runtime.allowed_roots = []
        return result

    monkeypatch.setattr(hook.subprocess, "run", changed)
    with pytest.raises(RoutingError):
        launcher.launch(
            source, runtime, task, execute=True, runner=lambda *a, **k: called.append(1)
        )
    assert not called and not (Path(runtime.state_dir) / (task.task_id + ".json")).exists()


def test_expiry_rechecked_at_effect_boundary(writable):
    source, runtime, task, matrix = writable
    original = source.load
    called = []

    def expired():
        if source.calls:
            # The source fingerprint/binding remain exactly the originally checked values;
            # passage of time, not a changed revision, invalidates the access grant.
            runtime.access[0].expires_at = (
                datetime.now(timezone.utc) - timedelta(seconds=1)
            ).isoformat()
        return original()

    source.load = expired
    result = launcher.launch(
        source, runtime, task, execute=True, runner=lambda *a, **k: called.append(1)
    )
    assert result["state"] == "blocked" and not called


def test_output_symlink_is_not_followed_or_chmodded(writable, tmp_path):
    source, runtime, task, _ = writable
    victim = tmp_path / "foreign"
    victim.write_bytes(b"original")
    victim.chmod(0o644)

    def runner(*args, **kwargs):
        (Path(runtime.state_dir) / (task.task_id + ".stdout")).symlink_to(victim)
        return completed()

    result = launcher.launch(source, runtime, task, execute=True, runner=runner)
    assert result["state"] == "unknown" and victim.read_bytes() == b"original"
    assert stat.S_IMODE(victim.stat().st_mode) == 0o644


def test_existing_public_state_directory_is_rejected(writable):
    source, runtime, task, _ = writable
    directory = Path(runtime.state_dir)
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)
    called = []
    with pytest.raises(RoutingError):
        launcher.launch(
            source, runtime, task, execute=True, runner=lambda *a, **k: called.append(1)
        )
    assert not called


def test_final_receipt_fsynced_before_replace_and_files_private(writable, monkeypatch):
    source, runtime, task, _ = writable
    flushed = set()
    fsync = os.fsync
    replace = Path.replace

    def sync(fd):
        flushed.add(os.fstat(fd).st_ino)
        return fsync(fd)

    def replacing(path, target):
        assert path.stat().st_ino in flushed
        return replace(path, target)

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(Path, "replace", replacing)
    result = launcher.launch(source, runtime, task, execute=True, runner=completed)
    assert result["state"] == "process_completed"
    assert all(
        stat.S_IMODE(p.stat().st_mode) == 0o600
        for p in Path(runtime.state_dir).glob("*")
        if p.is_file()
    )


def test_claude_preserves_egress_policy_and_disables_nonessential_traffic(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.fixture:8080")
    monkeypatch.setenv("NODE_EXTRA_CA_CERTS", "/fixture/ca.pem")
    env = hook.subscription_environment("claude")
    assert (
        env["HTTPS_PROXY"] == "http://proxy.fixture:8080"
        and env["NODE_EXTRA_CA_CERTS"] == "/fixture/ca.pem"
    )
    assert all(
        env[key] == "1"
        for key in [
            "DISABLE_TELEMETRY",
            "DISABLE_ERROR_REPORTING",
            "DISABLE_AUTOUPDATER",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
        ]
    )


def test_directory_sync_failure_keeps_no_effect_receipt(writable, monkeypatch):
    source, runtime, task, _ = writable
    original = launcher._sync_directory
    calls = []
    first = True

    def failing_once(path):
        nonlocal first
        if first:
            first = False
            raise OSError("fixture directory sync failure")
        return original(path)

    monkeypatch.setattr(launcher, "_sync_directory", failing_once)
    with pytest.raises(RoutingError, match="Admission persistence failed"):
        launcher.launch(source, runtime, task, execute=True, runner=lambda *a, **k: calls.append(1))
    assert not calls
    assert receipt(runtime, task)["state"] == "blocked"
    assert receipt(runtime, task)["effect_boundary_crossed"] is False


def test_own_python_child_is_reaped_on_interrupt(tmp_path, monkeypatch):
    import sys

    from kirabridge.capability_routing import process

    wait = subprocess.Popen.wait
    first = True
    owned = []

    def interrupted(child, *args, **kwargs):
        nonlocal first
        owned.append(child)
        if first:
            first = False
            raise KeyboardInterrupt()
        return wait(child, *args, **kwargs)

    monkeypatch.setattr(subprocess.Popen, "wait", interrupted)
    with pytest.raises(KeyboardInterrupt) as error:
        process.run_bounded(
            [sys.executable, "-c", "import time;time.sleep(30)"],
            input=None,
            cwd=tmp_path,
            timeout=2,
            env=dict(os.environ),
        )
    assert owned and owned[0].poll() is not None
    assert error.value.owned_process_exit_confirmed is True


@pytest.mark.parametrize("task_id", ["../escape", "/absolute", "x/y", "x\\y", ""])
def test_validated_task_ids_reject_traversal(writable, task_id):
    _, _, task, _ = writable
    with pytest.raises(ValueError):
        Task.model_validate({**task.model_dump(), "task_id": task_id})
