"""Actual owned child processes; no service, Terminal or productive profile."""

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def installer():
    spec = importlib.util.spec_from_file_location(
        "output_loop_installer", Path(__file__).parents[1] / "installer/install.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def presenter(events):
    class Presenter:
        begun = False
        done = False

        def begin(self):
            self.begun = True

        def tick(self):
            if not self.done:
                events.append(("frame", None))

        def finish(self):
            events.append(("finish", None))
            if self.begun:
                self.done = True

        def cancel(self):
            events.append(("cancel", None))
            self.done = True

    return Presenter()


def test_real_child_text_releases_graphic_area_before_forwarding(installer):
    events = []

    class Output(io.StringIO):
        def write(self, text):
            events.append(("real", text))
            return super().write(text)

    sink = Output()
    installer.sys = SimpleNamespace(stderr=sink)
    installer.PRESENTER = presenter(events)
    installer.OUTPUT_TARGET = SimpleNamespace(
        encoding="utf-8", write_child=lambda data, *a: sink.write(data.decode("utf-8"))
    )
    installer.run(
        [
            sys.executable,
            "-c",
            "import time,sys;time.sleep(.12);print('out');print('err',file=sys.stderr)",
        ],
        timeout=3,
    )
    assert "out" in sink.getvalue() and "err" in sink.getvalue()
    assert any(kind == "frame" for kind, _ in events)
    for index, event in enumerate(events):
        if event[0] == "real":
            assert events[index - 1][0] == "cancel"
    first_real = next(i for i, event in enumerate(events) if event[0] == "real")
    assert all(kind != "frame" for kind, _ in events[first_real:])


def test_capture_mode_stays_internal_json_without_graphics(installer):
    events = []
    installer.PRESENTER = presenter(events)
    value = installer.run(
        [
            sys.executable,
            "-c",
            "import sys;print('{\"ok\":true}');print('private diagnostic',file=sys.stderr)",
        ],
        capture=True,
        timeout=3,
    )
    assert json.loads(value) == {"ok": True} and events == []


def test_timeout_still_terminates_and_reaps_only_its_owned_process(installer, monkeypatch):
    installer.PRESENTER = presenter([])
    installer.sys = SimpleNamespace(stderr=io.StringIO())
    owned = []
    original = installer.subprocess.Popen

    def record(*args, **kwargs):
        child = original(*args, **kwargs)
        owned.append(child)
        return child

    monkeypatch.setattr(installer.subprocess, "Popen", record)
    with pytest.raises(subprocess.TimeoutExpired):
        installer.run([sys.executable, "-c", "import time;time.sleep(10)"], timeout=0.2)
    pid = owned[0].pid
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_no_late_animation_after_immediate_child_prompt(installer):
    events = []
    installer.PRESENTER = presenter(events)
    installer.OUTPUT_TARGET = SimpleNamespace(
        encoding="utf-8", write_child=lambda data, *a: events.append(("real", data.decode("utf-8")))
    )
    installer.run(
        [sys.executable, "-c", "import time;print('Continue? ',flush=True);time.sleep(.16)"],
        timeout=3,
    )
    first_real = next(i for i, event in enumerate(events) if event[0] == "real")
    assert "Continue?" in events[first_real][1]
    assert all(kind != "frame" for kind, _ in events[first_real:])


def test_full_owned_output_pipe_respects_child_deadline(installer, monkeypatch):
    read_fd, write_fd = os.pipe()
    os.set_blocking(write_fd, False)
    while True:
        try:
            os.write(write_fd, b"x" * 4096)
        except BlockingIOError:
            break
    target = installer.NonBlockingOutput(write_fd)
    installer.OUTPUT_TARGET = target
    installer.PRESENTER = presenter([])
    owned = []
    attempts = []
    original = installer.subprocess.Popen
    write_child = target.write_child

    def record(*args, **kwargs):
        child = original(*args, **kwargs)
        owned.append(child)
        return child

    def attempted(*args):
        attempts.append(True)
        return write_child(*args)

    monkeypatch.setattr(installer.subprocess, "Popen", record)
    monkeypatch.setattr(target, "write_child", attempted)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            installer.run(
                [sys.executable, "-c", "import time;print('actual log',flush=True);time.sleep(10)"],
                timeout=1,
            )
        assert attempts
        with pytest.raises(ProcessLookupError):
            os.kill(owned[0].pid, 0)
    finally:
        target.close()
        os.close(read_fd)


def test_decorative_writer_never_waits_for_full_pipe(installer):
    read_fd, write_fd = os.pipe()
    os.set_blocking(write_fd, False)
    target = installer.NonBlockingOutput(write_fd)
    try:
        while True:
            try:
                os.write(write_fd, b"x" * 4096)
            except BlockingIOError:
                break
        with pytest.raises(BlockingIOError):
            target.write("⣿")
    finally:
        target.close()
        os.close(read_fd)


@pytest.mark.parametrize("accepted", [0, 1, 3])
def test_byte_writer_reports_exact_partial_count_without_character_guessing(installer, accepted):
    installer.os = SimpleNamespace(write=lambda fd, data: accepted)
    assert installer.NonBlockingOutput(17).write_bytes("⣿".encode()) == accepted


def test_byte_writer_yields_zero_on_backpressure_without_waiting(installer):
    def full(*a):
        raise BlockingIOError("owned output full")

    installer.os = SimpleNamespace(write=full)
    assert installer.NonBlockingOutput(17).write_bytes(b"frame") == 0


@pytest.mark.parametrize("write_fails", [False, True])
def test_cancelled_partial_csi_reset_is_sent_before_real_text_and_acknowledged_only_on_success(
    installer, write_fails
):
    events = []
    prefix = "\x18\x1b[0m\x1b[12E\n"

    class Partial:
        output_prefix = prefix

        def cancel(self):
            events.append("cancel")

        def acknowledge_output_prefix(self):
            events.append("ack")
            self.output_prefix = ""

        def begin(self):
            pass

        def tick(self):
            pass

    def output(data, *args):
        events.append(("write", data))
        if write_fails:
            raise TimeoutError("synthetic deadline before prefix completed")

    installer.PRESENTER = Partial()
    installer.OUTPUT_TARGET = SimpleNamespace(encoding="utf-8", write_child=output)
    command = [sys.executable, "-c", "print('FATAL actual diagnostic',flush=True)"]
    if write_fails:
        with pytest.raises(TimeoutError):
            installer.run(command, timeout=3)
        assert "ack" not in events and installer.PRESENTER.output_prefix == prefix
    else:
        installer.run(command, timeout=3)
        assert "ack" in events and installer.PRESENTER.output_prefix == ""
    first_write = next(i for i, event in enumerate(events) if isinstance(event, tuple))
    assert events[first_write - 1] == "cancel"
    assert events[first_write][1].startswith(prefix.encode() + b"FATAL")


def test_status_json_never_uses_human_presenter(installer, tmp_path, capsys):
    installer.PRESENTER = SimpleNamespace(say=lambda _: pytest.fail("No graphic in status JSON"))
    installer.status(SimpleNamespace(prefix=tmp_path))
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"installed_by_versioned_installer": False}
    assert captured.err == ""


def test_outer_presentation_loader_compiles_only_verified_bytes(installer, tmp_path, monkeypatch):
    directory = tmp_path / "installer"
    directory.mkdir()
    path = directory / "presentation.py"
    verified = b'def create_presentation(*args,**kwargs): return {"verified":True}\n'
    path.write_bytes(verified)
    (tmp_path / "release.json").write_text(
        json.dumps({"files": {"installer/presentation.py": hashlib.sha256(verified).hexdigest()}})
    )
    original = installer.hashlib.sha256

    def replace(data):
        path.write_text('raise RuntimeError("unverified replacement")')
        return original(data)

    monkeypatch.setattr(installer.hashlib, "sha256", replace)
    installer.begin_presentation(tmp_path)
    assert installer.PRESENTER == {"verified": True}


def test_tampered_helper_is_not_executed(installer, tmp_path):
    directory = tmp_path / "installer"
    directory.mkdir()
    (directory / "presentation.py").write_text('raise SystemExit("Unverified code executed")')
    (tmp_path / "release.json").write_text(
        json.dumps({"files": {"installer/presentation.py": "0" * 64}})
    )
    installer.begin_presentation(tmp_path)
    assert installer.PRESENTER is None


@pytest.mark.parametrize("failure", [False, True])
def test_main_closes_owned_fd_after_success_or_error_without_final_graphic(
    installer, monkeypatch, failure
):
    read_fd, write_fd = os.pipe()
    events = []
    installer.PRESENTER = SimpleNamespace(
        cancel=lambda: events.append("cancel"),
        error=lambda message: events.append("error"),
        finish=lambda: pytest.fail("Error cleanup must not render a finishing banner"),
    )
    installer.OUTPUT_TARGET = installer.NonBlockingOutput(write_fd)

    def work():
        if failure:
            raise RuntimeError("synthetic before lock open")

    monkeypatch.setattr(installer, "_main", work)
    try:
        assert installer.main() == (1 if failure else 0)
        assert events == (["error", "cancel"] if failure else ["cancel"])
        with pytest.raises(OSError):
            os.fstat(write_fd)
        assert installer.OUTPUT_TARGET is None and installer.PRESENTER is None
    finally:
        os.close(read_fd)
