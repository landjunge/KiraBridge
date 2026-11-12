"""Selection and launch-boundary regressions; no network/model/native sessions."""

import json
import subprocess
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from kirabridge.capability_routing.hook import before_delegation, command_for
from kirabridge.capability_routing.launcher import launch
from kirabridge.capability_routing.router import (
    Access,
    Capability,
    Matrix,
    Model,
    RoutingError,
    Runtime,
    Task,
    select,
)
from kirabridge.capability_routing.source import BEGIN, END, ThreadDeskSource

NOW = datetime(2026, 11, 5, 21, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fixture_clock(monkeypatch):
    # Hook/launcher tests call select without an explicit clock. Bind those
    # calls to the dated synthetic evidence too; production freshness stays real.
    from kirabridge.capability_routing import router

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)

    monkeypatch.setattr(router, "datetime", Clock)


@pytest.fixture
def setup(tmp_path):
    exe = tmp_path / "native-cli"
    exe.write_text(
        '#!/bin/sh\nif [ "$1" = login ]; then\n'
        "printf 'Logged in using ChatGPT\\n'\nelse\nprintf 'native 1.0\\n'\nfi\n"
    )
    exe.chmod(0o700)

    def model(name, provider, cost, routine=5):
        return Model(
            id=name,
            provider=provider,
            efforts=["low", "medium", "high", "xhigh"],
            fit={
                "routine": routine,
                "implementation": 4,
                "debug": 4,
                "architecture": 4,
                "security": 4,
                "review": 4,
                "research": 4,
            },
            cost_rank=cost,
            evidence="test",
        )

    clis = [
        Capability(
            id=cli,
            installed_version="native 1.0",
            capabilities=["headless", "coding"],
            models=models,
            documented_models=[],
            sources=["https://example.test/official"],
            limitations="fixture",
        )
        for cli, models in [
            ("codex", [model("small", "openai", 0), model("large", "openai", 3)]),
            ("grok", [model("grok", "xai", 1)]),
        ]
    ]
    matrix = Matrix(
        schema_version="bigplan.cli-matrix.v1",
        checked_at="2026-11-05T20:00:00Z",
        expires_at="2026-11-06T20:00:00Z",
        clis=clis,
    )
    access = [
        Access(
            cli=c.id,
            executable=str(exe),
            version="native 1.0",
            models=[m.id for m in c.models],
            access_kind="subscription",
            verified_at="2026-11-05T20:00:00Z",
            expires_at="2026-11-06T20:00:00Z",
            evidence="fixture",
        )
        for c in clis
    ]
    runtime = Runtime(
        schema_version="bigplan.cli-runtime.v1",
        access=access,
        allowed_roots=[str(tmp_path)],
        state_dir=str(tmp_path / "state"),
    )
    task = Task(
        task_id="job-1",
        workload="implementation",
        prompt="Review only.",
        cwd=str(tmp_path),
        ownership_ref="owned test workspace",
    )
    return matrix, runtime, task


def source_for(matrix):
    calls = []

    def get(key):
        calls.append(key)
        return {"id": key, "revision": 4, "notes": BEGIN + json.dumps(matrix.model_dump()) + END}

    return ThreadDeskSource(get, "matrix-thread"), calls


def test_economical_routine_and_codex_primary(setup):
    matrix, runtime, task = setup
    decision = select(matrix, runtime, task.model_copy(update={"workload": "routine"}), now=NOW)
    assert (decision["cli"], decision["model"], decision["effort"]) == ("codex", "small", "low")
    assert decision["effective_model"] == "unverified"


@pytest.mark.parametrize(
    "workload,effort", [("implementation", "medium"), ("debug", "high"), ("security", "xhigh")]
)
def test_effort_task_complexity(setup, workload, effort):
    matrix, runtime, task = setup
    assert (
        select(matrix, runtime, task.model_copy(update={"workload": workload}), now=NOW)["effort"]
        == effort
    )


def test_insufficient_model_fit_never_used_for_hard_task(setup):
    matrix, runtime, task = setup
    matrix.clis[0].models[0].fit["security"] = 1
    decision = select(
        matrix,
        runtime,
        task.model_copy(update={"workload": "security", "allowed_clis": ["codex"]}),
        now=NOW,
    )
    assert decision["model"] == "large"


def test_independent_review_uses_other_provider(setup):
    matrix, runtime, task = setup
    task = task.model_copy(update={"workload": "review", "independent_of_provider": "openai"})
    assert select(matrix, runtime, task, now=NOW)["cli"] == "grok"


@pytest.mark.parametrize(
    "change",
    [
        {"explicit_model": "invented"},
        {"explicit_effort": "ultra"},
        {"explicit_effort": "none"},
        {"min_effort": "unknown"},
        {"delegation_depth": 1},
        {"minimum_context_tokens": 1000},
        {"required_capabilities": ["audio"]},
        {"allowed_clis": []},
        {"allowed_clis": ["codex"], "explicit_cli": "grok"},
        {"read_only": False},
    ],
)
def test_impossible_or_unauthorized_request_blocks(setup, change):
    matrix, runtime, task = setup
    with pytest.raises(RoutingError):
        select(matrix, runtime, task.model_copy(update=change), now=NOW)


def test_explicit_effort_not_lowered(setup):
    matrix, runtime, task = setup
    assert (
        select(
            matrix,
            runtime,
            task.model_copy(update={"explicit_model": "large", "explicit_effort": "xhigh"}),
            now=NOW,
        )["effort"]
        == "xhigh"
    )


@pytest.mark.parametrize("expiry", ["2026-11-05T20:59:59Z", "2026-11-04T20:00:00Z"])
def test_expired_matrix_blocks(setup, expiry):
    matrix, runtime, task = setup
    matrix.expires_at = expiry
    with pytest.raises(RoutingError):
        select(matrix, runtime, task, now=NOW)


def test_unverified_access_never_inferred_from_installation(setup):
    matrix, runtime, task = setup
    runtime.access = []
    with pytest.raises(RoutingError):
        select(matrix, runtime, task, now=NOW)


def test_access_staleness_and_version_mismatch(setup):
    matrix, runtime, task = setup
    runtime.access[0].version = "another"
    runtime.access[1].verified_at = "2026-11-03T00:00:00Z"
    with pytest.raises(RoutingError):
        select(matrix, runtime, task, now=NOW)


def test_every_preflight_reads_live_thread(setup):
    matrix, runtime, task = setup
    source, calls = source_for(matrix)
    before_delegation(source, runtime, task)
    before_delegation(source, runtime, task)
    assert calls == ["matrix-thread", "matrix-thread"]


def test_public_service_nested_thread_context(setup):
    matrix, _, _ = setup
    source = ThreadDeskSource(
        lambda key: {
            "id": key,
            "revision": 1,
            "context": {"notes": BEGIN + json.dumps(matrix.model_dump()) + END},
        },
        "matrix-thread",
    )
    assert source.load()[0] == matrix


def test_process_output_is_bounded_and_stderr_preserved(tmp_path):
    import sys

    from kirabridge.capability_routing.process import run_bounded

    result = run_bounded(
        [
            sys.executable,
            "-c",
            "import sys;sys.stdout.write('x'*2000000);sys.stderr.write('error')",
        ],
        input=None,
        cwd=tmp_path,
        timeout=5,
        env={},
    )
    assert len(result.stdout) == 1048576
    assert result.stderr == b"error" and result.output_truncated


def test_subscription_environment_removes_api_switches(monkeypatch):
    from kirabridge.capability_routing.hook import subscription_environment

    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unwanted.invalid")
    monkeypatch.setenv("XAI_API_KEY", "test-not-a-secret")
    env = subscription_environment()
    assert not {"OPENAI_API_KEY", "OPENAI_BASE_URL", "XAI_API_KEY"} & set(env)


@pytest.mark.parametrize("notes", ["", BEGIN + "{}" + BEGIN + END, BEGIN + "{}", "x" * 100001])
def test_malformed_source_blocks(notes):
    source = ThreadDeskSource(
        lambda key: {"id": key, "revision": 1, "notes": notes}, "matrix-thread"
    )
    with pytest.raises(ValueError):
        source.load()


def test_wrong_thread_identity_blocks(setup):
    matrix, _, _ = setup
    source = ThreadDeskSource(
        lambda key: {
            "id": "other",
            "revision": 1,
            "notes": BEGIN + json.dumps(matrix.model_dump()) + END,
        },
        "matrix-thread",
    )
    with pytest.raises(RoutingError):
        source.load()


@pytest.mark.parametrize("context", [None, [], "malformed"])
def test_flat_notes_ignore_malformed_unused_context(setup, context):
    matrix, _, _ = setup
    source = ThreadDeskSource(
        lambda key: {
            "id": key,
            "revision": 1,
            "context": context,
            "notes": BEGIN + json.dumps(matrix.model_dump()) + END,
        },
        "matrix-thread",
    )
    assert source.load()[0] == matrix


@pytest.mark.parametrize("notes", [None, [], {}])
def test_malformed_notes_are_a_typed_block(notes):
    source = ThreadDeskSource(
        lambda key: {"id": key, "revision": 1, "notes": notes}, "matrix-thread"
    )
    with pytest.raises(RoutingError):
        source.load()


def test_duplicate_json_and_reversed_markers_are_rejected():
    for notes in (BEGIN + '{"a":1,"a":2}' + END, END + BEGIN + "{}"):
        source = ThreadDeskSource(
            lambda key, value=notes: {"id": key, "revision": 1, "notes": value}, "matrix-thread"
        )
        with pytest.raises(RoutingError):
            source.load()


def test_native_model_metadata_is_not_prompt_self_report():
    from kirabridge.capability_routing.evidence import native_metadata

    assert native_metadata("grok", b'{"text":"I am model X"}', "grok-4.7") == {}
    data = json.dumps(
        {"sessionId": "session", "requestId": "request", "modelUsage": {"grok-4.7-build": {}}}
    ).encode()
    result = native_metadata("grok", data, "grok-4.7")
    assert result["effective_model"] == "grok-4.7-build"
    assert not result["model_matches_requested_id"]
    assert result["effective_effort"] == "unverified"


def test_binary_upgrade_blocks_before_process(setup):
    matrix, runtime, task = setup
    exe = __import__("pathlib").Path(runtime.access[0].executable)
    exe.write_text("#!/bin/sh\nprintf 'native 1.01\\n'\n")
    source, _ = source_for(matrix)
    with pytest.raises(RoutingError):
        before_delegation(source, runtime, task)


def test_changed_authentication_does_not_enable_api_billing(setup):
    from pathlib import Path

    matrix, runtime, task = setup
    Path(runtime.access[0].executable).write_text(
        '#!/bin/sh\nif [ "$1" = login ]; then\n'
        "printf 'Logged in using an API key\\n'\nelse\nprintf 'native 1.0\\n'\nfi\n"
    )
    source, _ = source_for(matrix)
    with pytest.raises(RoutingError, match="Subscription authentication changed"):
        before_delegation(source, runtime, task)


def test_grok_update_channel_is_not_a_binary_version_change():
    from kirabridge.capability_routing.hook import version_identity

    alpha = version_identity("grok", "grok 1.0.77 (50ca579fa996) [alpha]")
    stable = version_identity("grok", "grok 1.0.77 (50ca579fa996) [stable]")
    assert alpha == stable
    assert alpha != version_identity("grok", "grok 1.0.77 (60ca579fa996) [stable]")
    assert alpha != version_identity("grok", "grok 1.0.78 (50ca579fa996) [stable]")


def test_workspace_escape_blocks(setup, tmp_path):
    matrix, runtime, task = setup
    source, _ = source_for(matrix)
    with pytest.raises(RoutingError):
        before_delegation(source, runtime, task.model_copy(update={"cwd": str(tmp_path.parent)}))


def test_dry_run_no_process_no_receipt(setup):
    matrix, runtime, task = setup
    source, _ = source_for(matrix)
    result = launch(source, runtime, task, runner=lambda *a, **k: pytest.fail("model started"))
    assert result["state"] == "planned"
    assert not __import__("pathlib").Path(runtime.state_dir).exists()


def test_double_dispatch_refused_even_after_success(setup):
    matrix, runtime, task = setup
    source, calls = source_for(matrix)
    spawned = []

    def runner(argv, **kwargs):
        spawned.append(argv)
        assert kwargs["input"] == b"Review only."
        return SimpleNamespace(stdout=b"answer", returncode=0)

    result = launch(source, runtime, task, execute=True, runner=runner)
    assert result["state"] == "process_completed"
    with pytest.raises(RoutingError):
        launch(source, runtime, task, execute=True, runner=runner)
    assert len(spawned) == 1 and len(calls) == 3


def test_lost_final_receipt_does_not_claim_no_model_started(setup, monkeypatch):
    from pathlib import Path

    from kirabridge.capability_routing.launcher import OutcomeUncertain

    matrix, runtime, task = setup
    source, _ = source_for(matrix)
    spawned = []

    def runner(*args, **kwargs):
        spawned.append(True)
        return SimpleNamespace(stdout=b"answer", returncode=0)

    def lost(*args, **kwargs):
        raise OSError("lost receipt")

    monkeypatch.setattr(Path, "replace", lost)
    with pytest.raises(OutcomeUncertain):
        launch(source, runtime, task, execute=True, runner=runner)
    assert spawned == [True]
    assert (
        json.loads((Path(runtime.state_dir) / (task.task_id + ".json")).read_text())["state"]
        == "admitted"
    )


def test_timeout_is_unknown_no_retry(setup):
    matrix, runtime, task = setup
    source, _ = source_for(matrix)

    def runner(*args, **kwargs):
        raise subprocess.TimeoutExpired("owned", 1)

    result = launch(source, runtime, task, execute=True, runner=runner)
    assert result["state"] == "unknown"
    assert result["transport_error"]["category"] == "timeout"
    assert result["transport_error"]["exception_type"] == "TimeoutExpired"
    with pytest.raises(RoutingError):
        launch(source, runtime, task, execute=True, runner=runner)


def test_transport_diagnostic_real_timeout_preserves_partial_output(setup):
    import stat
    import sys
    from pathlib import Path

    from kirabridge.capability_routing.process import run_bounded

    matrix, runtime, task = setup
    source, _ = source_for(matrix)
    calls = []

    def runner(*args, **kwargs):
        calls.append(True)
        return run_bounded(
            [
                sys.executable,
                "-c",
                "import sys,time;print('partial',flush=True);"
                "print('problem',file=sys.stderr,flush=True);time.sleep(5)",
            ],
            input=None,
            cwd=task.cwd,
            timeout=0.4,
            env={},
        )

    result = launch(source, runtime, task, execute=True, runner=runner)
    assert result["state"] == "unknown" and result["automatic_retry"] is False
    assert result["transport_error"]["stage"] == "wait_main"
    assert result["process_evidence"]["pid"] > 0
    assert result["native_exit_code"] == -9
    assert Path(result["output_path"]).read_bytes() == b"partial\n"
    assert Path(result["stderr_path"]).read_bytes() == b"problem\n"
    assert stat.S_IMODE(Path(result["output_path"]).stat().st_mode) == 0o600
    receipt = Path(runtime.state_dir) / (task.task_id + ".json")
    before = receipt.read_bytes()
    with pytest.raises(RoutingError):
        launch(source, runtime, task, execute=True, runner=runner)
    assert calls == [True] and receipt.read_bytes() == before


def test_transport_diagnostic_timeout_runner_does_not_leak_argv(setup):
    from pathlib import Path

    matrix, runtime, task = setup
    source, _ = source_for(matrix)

    def runner(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            "synthetic-private-prompt", 1, output=b"partial", stderr=b"problem"
        )

    result = launch(source, runtime, task, execute=True, runner=runner)
    assert result["state"] == "unknown"
    assert "native_exit_code" not in result
    assert result["transport_error"]["exception_type"] == "TimeoutExpired"
    assert "synthetic-private-prompt" not in json.dumps(result)
    assert Path(result["output_path"]).read_bytes() == b"partial"
    assert Path(result["stderr_path"]).read_bytes() == b"problem"


def test_transport_diagnostic_known_exit_survives_capture_io_failure(setup, monkeypatch):
    import kirabridge.capability_routing.launcher as module

    matrix, runtime, task = setup
    source, _ = source_for(matrix)

    def fail(*args, **kwargs):
        raise PermissionError("synthetic capture failure")

    monkeypatch.setattr(module, "_write_private", fail, raising=False)
    result = launch(
        source,
        runtime,
        task,
        execute=True,
        runner=lambda *a, **k: SimpleNamespace(returncode=7, stdout=b"part", stderr=b"err"),
    )
    assert result["state"] == "unknown"
    assert result["native_exit_code"] == 7
    assert result["transport_error"]["stage"] == "output_persist"
    assert "output_path" not in result


def test_transport_diagnostic_drain_timeout_retains_native_zero(tmp_path, monkeypatch):
    import io
    import threading

    import kirabridge.capability_routing.process as module

    release = threading.Event()

    class Pipe:
        def __init__(self):
            self.closed = threading.Event()

        def read(self, size):
            release.wait(4)
            return b""

        read1 = read

        def close(self):
            self.closed.set()

    child = SimpleNamespace(
        pid=4242,
        returncode=0,
        stdin=io.BytesIO(),
        stdout=Pipe(),
        stderr=Pipe(),
        wait=lambda **kwargs: 0,
        kill=lambda: pytest.fail("already exited child must not be killed"),
    )
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: child)
    try:
        with pytest.raises(subprocess.TimeoutExpired) as caught:
            module.run_bounded(["fake"], input=None, cwd=tmp_path, timeout=0.1, env={})
        assert caught.value.process_evidence["stage"] == "drain_after_exit"
        assert caught.value.process_evidence["native_exit_code"] == 0
    finally:
        release.set()
        assert child.stdout.closed.wait(1) and child.stderr.closed.wait(1)


def test_transport_diagnostic_spawn_error_has_no_fake_native_exit(tmp_path, monkeypatch):
    import kirabridge.capability_routing.process as module

    def missing(*args, **kwargs):
        raise FileNotFoundError(2, "synthetic-private-argument")

    monkeypatch.setattr(module.subprocess, "Popen", missing)
    with pytest.raises(subprocess.SubprocessError) as caught:
        module.run_bounded(["fake"], input=None, cwd=tmp_path, timeout=1, env={})
    evidence = caught.value.process_evidence
    assert evidence["stage"] == "spawn" and evidence["spawn_observed"] is False
    assert evidence["pid"] is None and evidence["native_exit_code"] is None
    assert evidence["exception_type"] == "FileNotFoundError" and evidence["errno"] == 2
    assert "synthetic-private-argument" not in str(caught.value)


def test_transport_diagnostic_partial_capture_bounded_and_private(setup):
    import stat
    from pathlib import Path

    matrix, runtime, task = setup
    source, _ = source_for(matrix)

    def runner(*args, **kwargs):
        raise subprocess.TimeoutExpired("owned", 1, output=b"x" * 1100000, stderr=b"e" * 70000)

    result = launch(source, runtime, task, execute=True, runner=runner)
    assert result["state"] == "unknown" and result["output_truncated"]
    assert Path(result["output_path"]).stat().st_size == 1048576
    assert Path(result["stderr_path"]).stat().st_size == 65536
    assert stat.S_IMODE(Path(result["stderr_path"]).stat().st_mode) == 0o600


def test_transport_diagnostic_existing_capture_is_not_workspace_denial(setup):
    from pathlib import Path

    matrix, runtime, task = setup
    source, _ = source_for(matrix)
    state = Path(runtime.state_dir)
    state.mkdir()
    victim = state / "unrelated"
    victim.write_bytes(b"original")
    (state / (task.task_id + ".stdout")).symlink_to(victim)
    result = launch(
        source,
        runtime,
        task,
        execute=True,
        runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout=b"part", stderr=b"err"),
    )
    assert result["state"] == "unknown" and result["native_exit_code"] == 0
    assert result["transport_error"]["stage"] == "output_persist"
    assert result["transport_error"]["exception_type"] == "FileExistsError"
    assert victim.read_bytes() == b"original"
    assert Path(result["stderr_path"]).read_bytes() == b"err"


def test_transport_diagnostic_success_and_invalid_metadata_remain_transport_success(setup):
    matrix, runtime, task = setup
    source, _ = source_for(matrix)
    task = task.model_copy(update={"explicit_cli": "grok", "independent_of_provider": "openai"})
    result = launch(
        source,
        runtime,
        task,
        execute=True,
        probe=False,
        runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout=b"not json", stderr=b""),
    )
    assert result["state"] == "process_completed"
    assert result["exit_code"] == result["native_exit_code"] == 0
    assert "transport_error" not in result
    assert result["effective_model"] == "unverified"


@pytest.mark.parametrize(
    ("stream", "operation"),
    [
        ("stdin", "write"),
        ("stdin", "flush"),
        ("stdin", "close"),
        ("stdout", "close"),
        ("stderr", "close"),
    ],
)
def test_transport_stream_io_failures_keep_native_zero_unknown_and_lease(
    setup, monkeypatch, stream, operation
):
    import errno
    import io
    import threading
    from pathlib import Path

    import kirabridge.capability_routing.process as module

    matrix, runtime, task = setup
    runtime.allow_write = True
    task = task.model_copy(update={"read_only": False})
    source, _ = source_for(matrix)
    injected, calls, thread_errors = [], [], []

    class Faulty(io.BytesIO):
        def inject(self, current):
            if current == operation:
                injected.append(current)
                raise OSError(errno.EIO, "synthetic-private-io-error")

        def write(self, value):
            self.inject("write")
            return super().write(value)

        def flush(self):
            self.inject("flush")
            return super().flush()

        def close(self):
            super().close()
            self.inject("close")

    pipes = {
        "stdin": io.BytesIO(),
        "stdout": io.BytesIO(b"partial"),
        "stderr": io.BytesIO(b"problem"),
    }
    pipes[stream] = Faulty(b"partial" if stream == "stdout" else b"problem")
    child = SimpleNamespace(
        pid=4242,
        returncode=0,
        **pipes,
        wait=lambda **kw: 0,
        kill=lambda: pytest.fail("completed fake child must not be killed"),
    )
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: child)
    monkeypatch.setattr(threading, "excepthook", lambda e: thread_errors.append(e.exc_type))

    def runner(*args, **kwargs):
        calls.append(True)
        return module.run_bounded(
            ["owned-fake"], input=b"assigned prompt", cwd=task.cwd, timeout=0.1, env={}
        )

    result = launch(source, runtime, task, execute=True, probe=False, runner=runner)
    assert injected == [operation]  # The requested error really occurred.
    assert result["native_exit_code"] == 0
    assert result["state"] == "unknown" and result["automatic_retry"] is False
    assert result["transport_error"]["stage"] == "stream_io"
    assert any(
        e["stream_name"] == stream and e["operation"] == operation and e["errno"] == errno.EIO
        for e in result["process_evidence"]["stream_errors"]
    )
    assert not thread_errors
    assert "synthetic-private-io-error" not in json.dumps(result)
    assert Path(result["output_path"]).read_bytes() == b"partial"
    assert Path(result["stderr_path"]).read_bytes() == b"problem"
    state = Path(runtime.state_dir)
    assert len(list(state.glob("cwd-*.lock"))) == 1
    receipt = state / (task.task_id + ".json")
    before = receipt.read_bytes()
    with pytest.raises(RoutingError):
        launch(source, runtime, task, execute=True, probe=False, runner=runner)
    other = task.model_copy(update={"task_id": "other-owned-fixture"})
    assert (
        launch(source, runtime, other, execute=True, probe=False, runner=runner)["state"]
        == "blocked"
    )
    assert calls == [True] and receipt.read_bytes() == before


def test_revision_change_prevents_spawn(setup):
    matrix, runtime, task = setup
    count = 0

    def get(key):
        nonlocal count
        count += 1
        return {
            "id": key,
            "revision": count,
            "notes": BEGIN + json.dumps(matrix.model_dump()) + END,
        }

    result = launch(
        ThreadDeskSource(get, "matrix-thread"),
        runtime,
        task,
        execute=True,
        runner=lambda *a, **k: pytest.fail("stale decision launched"),
    )
    assert result["state"] == "blocked"


def test_grok_write_not_implicitly_enabled(setup):
    _, _, task = setup
    with pytest.raises(RoutingError):
        command_for(
            {"cli": "grok", "executable": "/grok", "model": "grok", "effort": "high"},
            task.model_copy(update={"read_only": False}),
        )


def test_documentation_cannot_supply_shell_flags(setup):
    matrix, _, _ = setup
    data = matrix.model_dump()
    data["clis"][0]["models"][0]["id"] = "model; touch /tmp/no"
    with pytest.raises(ValueError):
        Matrix.model_validate(data)


def test_threaddesk_unavailable_never_uses_cached_matrix(setup):
    _, runtime, task = setup

    def offline(key):
        raise OSError("offline")

    with pytest.raises(OSError):
        launch(ThreadDeskSource(offline, "matrix-thread"), runtime, task)


@pytest.mark.parametrize(
    "cli,prefix",
    [
        ("codex", ["-c", 'model_provider="openai"', "-c", 'model_reasoning_effort="high"']),
        ("grok", ["--no-auto-update", "--effort", "high"]),
    ],
)
def test_managed_shim_passes_real_effort_and_keeps_arguments(tmp_path, cli, prefix):
    import sys

    from kirabridge.capability_routing.integration import effort_shim

    exe = tmp_path / "argv-cli"
    exe.write_text(f"#!{sys.executable}\nimport sys,json\nprint(json.dumps(sys.argv[1:]))\n")
    exe.chmod(0o700)
    decision = {
        "cli": cli,
        "model": "model",
        "effort": "high",
        "executable": str(exe),
        "expected_version": "test",
    }
    shim = effort_shim(decision, tmp_path / "state")
    result = subprocess.run([shim, "agent", "stdio"], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == prefix + ["agent", "stdio"]
    assert effort_shim(decision, tmp_path / "state") == shim


@pytest.mark.parametrize(
    "arguments,expected",
    [
        (["agent", "stdio"], ["--no-auto-update", "--effort", "high", "agent", "stdio"]),
        (
            ["--no-auto-update", "--json-schema", "{}"],
            ["--effort", "high", "--no-auto-update", "--json-schema", "{}"],
        ),
        (
            ["--", "--no-auto-update"],
            ["--no-auto-update", "--effort", "high", "--", "--no-auto-update"],
        ),
        (
            ["--no-auto-update", "--no-auto-update"],
            ["--effort", "high", "--no-auto-update", "--no-auto-update"],
        ),
    ],
)
def test_grok_shim_adds_update_guard_only_when_not_supplied(tmp_path, arguments, expected):
    import sys

    from kirabridge.capability_routing.integration import effort_shim

    exe = tmp_path / "argv-grok"
    exe.write_text(f"#!{sys.executable}\nimport sys,json\nprint(json.dumps(sys.argv[1:]))\n")
    exe.chmod(0o700)
    decision = {
        "cli": "grok",
        "model": "model",
        "effort": "high",
        "executable": str(exe),
        "expected_version": "fixture",
    }
    state = tmp_path / "state"
    old_identity = {
        k: decision[k] for k in ("cli", "model", "effort", "executable", "expected_version")
    }
    from kirabridge.capability_routing.router import fingerprint

    old = state / "effort-shims" / (fingerprint(old_identity) + ".py")
    old.parent.mkdir(parents=True)
    old.write_text("historical immutable shim")
    shim = effort_shim(decision, state)
    assert shim != str(old) and old.read_text() == "historical immutable shim"
    result = subprocess.run([shim, *arguments], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == expected
    assert effort_shim(decision, state) == shim


@pytest.mark.asyncio
async def test_managed_adapter_keeps_config_immutable(setup):
    from kirabridge.bridge_core.config import AgentConfig
    from kirabridge.capability_routing.hook import DelegationGuard
    from kirabridge.capability_routing.integration import RoutedAdapter

    matrix, runtime, profile = setup
    source, _ = source_for(matrix)
    profile = profile.model_copy(update={"allowed_clis": ["codex"]})
    config = AgentConfig(kind="codex", executable=runtime.access[0].executable, model="original")
    seen, events = [], []

    class Native:
        async def execute(self, task, args, cfg, *others, **kwargs):
            seen.append(cfg)
            return {"native": True}

    async def progress(event):
        events.append(event)

    routed = RoutedAdapter(
        Native(), "codex", DelegationGuard(source, runtime), lambda t, a: profile
    )
    args = SimpleNamespace(
        prompt=profile.prompt, cwd=profile.cwd, local_tools=False, timeout=profile.timeout_seconds
    )
    result = await routed.execute({"id": profile.task_id}, args, config, [], None, progress)
    assert result == {"native": True} and events[0]["routing_decision"]["effort"] == "medium"
    assert config.model == "original" and seen[0].model == "small"
    assert seen[0].executable != config.executable


@pytest.mark.asyncio
async def test_managed_adapter_refuses_wrong_task_and_resume(setup):
    from kirabridge.bridge_core.config import AgentConfig
    from kirabridge.capability_routing.hook import DelegationGuard
    from kirabridge.capability_routing.integration import RoutedAdapter

    matrix, runtime, profile = setup
    source, _ = source_for(matrix)
    routed = RoutedAdapter(None, "codex", DelegationGuard(source, runtime), lambda t, a: profile)
    args = SimpleNamespace(prompt="other prompt", cwd=profile.cwd, local_tools=False)
    with pytest.raises(RoutingError):
        await routed.execute(
            {"id": profile.task_id}, args, AgentConfig(kind="codex"), [], None, None
        )
    with pytest.raises(RoutingError):
        await routed.execute(
            {"id": profile.task_id},
            args,
            AgentConfig(kind="codex"),
            [],
            None,
            None,
            owned_resume_session="existing-session",
        )


def test_new_manager_has_no_unrouted_provider_bypass():
    from kirabridge.capability_routing.integration import new_routed_manager

    config = SimpleNamespace(visible_handoffs=SimpleNamespace(enabled=False))
    manager = new_routed_manager(config, None, None, None)
    assert set(manager.adapters) == {"codex", "grok_acp", "qwen_acp"}
    from kirabridge.capability_routing.integration import RoutedAdapter

    assert all(isinstance(adapter, RoutedAdapter) for adapter in manager.adapters.values())
    assert manager.adapters["qwen_acp"].cli == "qwen"


def test_unknown_writer_keeps_root_lease_and_blocks_subdirectory(setup, tmp_path):
    matrix, runtime, task = setup
    runtime.allow_write = True
    task = task.model_copy(update={"read_only": False})
    source, _ = source_for(matrix)
    count = 0

    def timeout(*args, **kwargs):
        nonlocal count
        count += 1
        raise subprocess.TimeoutExpired("owned", 1)

    assert launch(source, runtime, task, execute=True, runner=timeout)["state"] == "unknown"
    child = tmp_path / "subdirectory"
    child.mkdir()
    second = task.model_copy(update={"cwd": str(child), "task_id": "job-2"})
    assert launch(source, runtime, second, execute=True, runner=timeout)["state"] == "blocked"
    assert count == 1
