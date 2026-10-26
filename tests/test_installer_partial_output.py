"""Private nonblocking pipe writes; no Terminal window, service or user FD is touched."""

import io
import os
from types import SimpleNamespace

import pytest

from kirabridge.install_ui import SetupUI


class BytePipe:
    encoding = "utf-8"

    def __init__(self, *, chunk=17):
        self.read_fd, self.write_fd = os.pipe()
        os.set_blocking(self.read_fd, False)
        os.set_blocking(self.write_fd, False)
        self.chunk, self.attempts = chunk, 0

    def isatty(self):
        return True  # Capability fixture only; the actual resource is our private pipe.

    def fileno(self):
        return self.write_fd

    def flush(self):
        pass

    def write_bytes(self, data):
        self.attempts += 1
        try:
            return os.write(self.write_fd, data[: self.chunk])
        except BlockingIOError:
            return 0

    def write(self, text):
        data = text.encode()
        if self.write_bytes(data) != len(data):
            raise BlockingIOError("Legacy all-or-nothing decorative write")
        return len(text)

    def read(self):
        parts = []
        while True:
            try:
                parts.append(os.read(self.read_fd, 65536))
            except BlockingIOError:
                return b"".join(parts)

    def fill(self):
        while True:
            try:
                os.write(self.write_fd, b"x" * 4096)
            except BlockingIOError:
                return

    def close(self):
        os.close(self.read_fd)
        os.close(self.write_fd)


def fixture_design(*, lines=26, text=None):
    full = (
        text if text is not None else "\x1b[38;2;240;109;176m" + ("⣿" * 120 + "\x1b[0m\n") * lines
    )
    controllers = []

    class Controller:
        def __init__(self, options):
            self.calls, self.done = 0, False
            controllers.append(self)

        def poll(self):
            self.calls += 1
            return None if self.done else full

        def finish(self):
            self.done = True
            return full

        def cancel(self):
            self.done = True

    return SimpleNamespace(
        options_for=lambda *args, **kwargs: SimpleNamespace(motion=True),
        static_banner=lambda options: full,
        AnimationController=Controller,
        MAX_FRAME_BYTES=128 * 1024,
        controllers=controllers,
    ), full


def test_short_write_resumes_one_frame_without_polling_or_duplicating_utf8(monkeypatch):
    monkeypatch.setattr(os, "get_terminal_size", lambda fd: os.terminal_size((131, 35)))
    sink = BytePipe()
    module, frame = fixture_design()
    ui = SetupUI("en", io.StringIO(), design=module, exclusive_output=True)
    ui.stream = sink
    ui.graphic_stream = sink
    try:
        ui.begin()
        assert ui._animation is not None, "A normal short write must not cancel decoration"
        assert ui.pending_output
        received = sink.read()
        for _ in range(1024):
            if not ui.pending_output:
                break
            before = sink.attempts
            ui.tick()
            assert sink.attempts == before + 1
            received += sink.read()
        assert not ui.pending_output and received == frame.encode()
        assert module.controllers[0].calls == 1
        assert ui._frame_lines == frame.count("\n")
    finally:
        sink.close()


def drain_frame(ui, sink, limit=1024):
    result = sink.read()
    for _ in range(limit):
        if not ui.pending_output:
            break
        ui.tick()
        result += sink.read()
    assert not ui.pending_output
    return result


def test_eagain_keeps_exactly_one_bounded_frame_without_poll_or_wait(monkeypatch):
    monkeypatch.setattr(os, "get_terminal_size", lambda fd: os.terminal_size((131, 35)))
    sink = BytePipe(chunk=4096)
    module, frame = fixture_design()
    ui = SetupUI("en", sink, design=module, exclusive_output=True)
    try:
        sink.fill()
        ui.begin()
        assert ui.pending_output and ui._pending_offset == 0
        original = ui._pending
        ui.tick()
        assert ui._pending is original and ui._pending_offset == 0
        assert len(original) <= module.MAX_FRAME_BYTES and module.controllers[0].calls == 1
        assert ui._frame_lines == 0 and not ui.output_prefix
        sink.read()  # Release only our private pipe's filler bytes.
        assert drain_frame(ui, sink) == frame.encode()
        assert module.controllers[0].calls == 1
    finally:
        sink.close()


def test_partial_csi_cancel_persists_prefix_through_eagain_before_real_fatal(monkeypatch):
    monkeypatch.setattr(os, "get_terminal_size", lambda fd: os.terminal_size((131, 35)))
    sink = BytePipe(chunk=65536)
    module, frame = fixture_design(lines=20)
    ui = SetupUI("en", sink, design=module, exclusive_output=True)
    try:
        ui.begin()
        assert drain_frame(ui, sink) == frame.encode()
        assert ui._frame_lines == 20
        sink.chunk = 4
        ui.tick()
        prefix_fragment = sink.read()
        assert prefix_fragment == b"\x1b[20"  # Deliberately stop before the cursor-up 'F'.
        assert ui.pending_output and ui._frame_lines == 20
        sink.fill()
        ui.cancel()
        prefix = ui.output_prefix
        assert prefix.startswith("\x18\x1b[0m") and prefix.endswith("\n")
        assert not ui.pending_output
        ui.cancel()
        assert ui.output_prefix == prefix  # Stable until the caller proves full transmission.
        assert sink.write_bytes(prefix.encode()) == 0  # Reset cannot currently be written.
        assert ui.output_prefix == prefix
        before = sink.attempts
        ui.tick()
        assert sink.attempts == before
        sink.read()
        data = prefix.encode() + b"FATAL real output\n"
        accepted = b""
        while data:
            count = sink.write_bytes(data)
            assert count > 0
            data = data[count:]
            accepted += sink.read()
        ui.acknowledge_output_prefix()
        assert ui.output_prefix == ""
        assert b"\x1b[20F" not in prefix_fragment + accepted
        assert accepted == prefix.encode() + b"FATAL real output\n"
        ui.tick()
        assert sink.read() == b""  # No old frame bytes may arrive after real output.
    finally:
        sink.close()


def test_cancel_after_confirmed_rewind_moves_only_forward_before_real_text(monkeypatch):
    monkeypatch.setattr(os, "get_terminal_size", lambda fd: os.terminal_size((131, 35)))
    sink = BytePipe(chunk=65536)
    module, frame = fixture_design(lines=20)
    ui = SetupUI("en", sink, design=module, exclusive_output=True)
    try:
        ui.begin()
        drain_frame(ui, sink)
        sink.chunk = 6  # Full CSI20F plus one new-frame byte.
        ui.tick()
        assert sink.read().startswith(b"\x1b[20F")
        ui.cancel()
        assert "\x1b[20E" in ui.output_prefix and "F" not in ui.output_prefix
        assert ui.output_prefix.startswith("\x18\x1b[0m")
    finally:
        sink.close()


def test_finish_does_not_replace_or_wait_for_an_incomplete_frame(monkeypatch):
    monkeypatch.setattr(os, "get_terminal_size", lambda fd: os.terminal_size((131, 35)))
    sink = BytePipe(chunk=4096)
    module, frame = fixture_design()
    ui = SetupUI("en", sink, design=module, exclusive_output=True)
    try:
        ui.begin()
        original = ui._pending
        ui.finish()
        assert ui.pending_output and ui._pending is original
        assert ui.finalization_pending
        assert drain_frame(ui, sink) == frame.encode()
        assert module.controllers[0].calls == 1 and ui.finalization_pending
        ui.tick()  # A later safe caller tick starts finalization, never a hidden wait.
        final = drain_frame(ui, sink)
        assert final == (f"\x1b[{frame.count(chr(10))}F" + frame).encode()
        assert ui._animation is None and not ui.finalization_pending
    finally:
        sink.close()


@pytest.mark.parametrize("event", ["say", "error", "prompt"])
def test_real_status_error_prompt_take_prefix_then_never_resume_frame(monkeypatch, event):
    monkeypatch.setattr(os, "get_terminal_size", lambda fd: os.terminal_size((131, 35)))
    monkeypatch.setattr("builtins.input", lambda: "yes")
    sink, human = BytePipe(chunk=7), io.StringIO()
    module, _ = fixture_design()
    ui = SetupUI("en", sink, design=module, exclusive_output=True)
    try:
        ui.begin()
        sink.read()
        ui.stream = human  # Caller-owned human stream, separate from the raw graphic writer.
        if event == "prompt":
            assert ui.prompt("Frage", "Continue") == "yes"
        else:
            getattr(ui, event)("Status", "FATAL real output")
        output = human.getvalue()
        assert output.startswith("\x18\x1b[0m\n")
        assert "Continue" in output if event == "prompt" else "FATAL real output" in output
        assert not ui.output_prefix and not ui.pending_output
        ui.tick()
        assert sink.read() == b""
    finally:
        sink.close()


def test_ascii_partial_cancel_has_no_unnecessary_ansi_and_resize_never_resumes(monkeypatch):
    size = [os.terminal_size((131, 35))]
    monkeypatch.setattr(os, "get_terminal_size", lambda fd: size[0])
    sink = BytePipe(chunk=2)
    module, _ = fixture_design(text="KiraBridge\n")
    ui = SetupUI("en", sink, design=module, exclusive_output=False)
    try:
        ui.begin()
        sink.read()
        ui.cancel()
        assert ui.output_prefix == "\n"
    finally:
        sink.close()
    sink = BytePipe(chunk=4)
    module, _ = fixture_design()
    ui = SetupUI("en", sink, design=module, exclusive_output=True)
    try:
        ui.begin()
        sink.read()
        size[0] = os.terminal_size((60, 20))
        before = sink.attempts
        ui.tick()
        assert sink.attempts == before and not ui.pending_output
        assert "F" not in ui.output_prefix and "E" not in ui.output_prefix
        assert ui.output_prefix.startswith("\x18")
    finally:
        sink.close()


def test_generic_buffered_flush_failure_retains_cleanup_until_real_output():
    class Buffered(io.StringIO):
        def __init__(self):
            super().__init__()
            self.flushes = 0

        def isatty(self):
            return True

        def flush(self):
            self.flushes += 1
            if self.flushes == 1:
                raise BrokenPipeError("Buffered output was not confirmed")

    stream = Buffered()
    ui = SetupUI("en", stream, design=fixture_design()[0])
    frame = "\x1b[35mUNCONFIRMED\x1b[0m\n"
    ui._graphic(frame)
    assert not ui.pending_output and ui.output_prefix.startswith("\x18\x1b[0m")
    before = ui.output_prefix
    ui.cancel()
    assert ui.output_prefix == before
    ui.error("Fehler", "FATAL real output")
    assert not ui.output_prefix and stream.getvalue().count("UNCONFIRMED") == 1
    assert stream.getvalue().endswith(before + "FATAL real output\n")


def test_unconfirmed_priority_cleanup_is_never_acknowledged_or_followed_by_real_text(monkeypatch):
    monkeypatch.setattr(os, "get_terminal_size", lambda fd: os.terminal_size((131, 35)))
    sink = BytePipe(chunk=4)
    module, _ = fixture_design()
    ui = SetupUI("en", sink, design=module, exclusive_output=True)

    class FailingPriority(io.StringIO):
        def flush(self):
            raise BrokenPipeError("Cleanup flush unconfirmed")

    human = FailingPriority()
    try:
        ui.begin()
        sink.read()
        ui.stream = human
        with pytest.raises(BrokenPipeError):
            ui.say("Status", "FATAL real output")
        assert ui.output_prefix and "FATAL" not in human.getvalue()
        before = sink.attempts
        ui.tick()
        assert sink.attempts == before and not ui.pending_output
    finally:
        sink.close()
