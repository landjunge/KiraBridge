"""Human setup output is stderr-only; never used by MCP transports."""

from __future__ import annotations

import os
import shutil
import sys
import textwrap


class SetupUI:
    def __init__(
        self, language="de", stream=None, *, design=None, motion="auto", exclusive_output=False
    ):
        self.language = language
        self.stream = stream or sys.stderr
        self.graphic_stream = self.stream
        self.design, self.motion = design, motion
        self._animation = None
        self._begun = False
        self.exclusive_output = exclusive_output
        self._frame_lines = 0
        self._redraw = False
        self._window_size = None
        self._pending = b""
        self._pending_offset = 0
        self._pending_lines = 0
        self._pending_rewind = 0
        self._pending_prefix_length = 0
        self._pending_unknown = False
        self._pending_styled = False
        self._output_prefix = ""
        self._finishing = False
        self._final_pending = False

    def text(self, de, en):
        return de if self.language == "de" else en

    def say(self, de, en=None):
        self.cancel()
        self._priority_prefix()
        value = self.text(de, en or de)
        width = max(24, min(88, shutil.get_terminal_size((80, 24)).columns))
        print(textwrap.fill(value, width=width), file=self.stream, flush=True)

    @property
    def pending_output(self):
        """Only remaining bytes of our single decorative frame, never a timer."""
        return self._pending_offset < len(self._pending)

    @property
    def finalization_pending(self):
        """A requested final banner still needs a later safe caller tick/ack."""
        return self._finishing

    @property
    def output_prefix(self):
        """Opaque abort/reset text; caller must fully send this BEFORE real text."""
        return self._output_prefix

    def acknowledge_output_prefix(self):
        """Clear only after the caller confirms complete transmission of the prefix."""
        self._output_prefix = ""

    def _priority_prefix(self):
        prefix = self.output_prefix
        if not prefix:
            return
        written = self.stream.write(prefix)
        if written is not None and written != len(prefix):
            raise BlockingIOError("Priority cleanup was not fully accepted")
        self.stream.flush()
        self.acknowledge_output_prefix()

    def _clear_pending(self):
        self._pending = b""
        self._pending_offset = self._pending_lines = 0
        self._pending_rewind = self._pending_prefix_length = 0
        self._pending_unknown = self._pending_styled = False

    def _graphic(self, value, *, lines=0, rewind=0, prefix_length=0):
        if not value or self.pending_output or self.output_prefix:
            return
        try:
            encoding = getattr(self.graphic_stream, "encoding", None) or "utf-8"
            data = value.encode(encoding)
            limit = min(getattr(self.design, "MAX_FRAME_BYTES", 131072), 131072)
            if len(data) > limit:
                raise ValueError("Decorative frame exceeds its byte budget")
            self._pending = data
            self._pending_offset = 0
            self._pending_lines, self._pending_rewind = lines, rewind
            self._pending_prefix_length = prefix_length
            self._pending_styled = "\x1b" in value and self.graphic_stream.isatty()
            self._drain_graphic()
        except Exception:
            self.cancel()

    def _drain_graphic(self):
        if not self.pending_output or self.output_prefix:
            return
        if self._redraw and self._viewport() != self._window_size:
            self.cancel()
            return
        sink = self.graphic_stream
        remaining = self._pending[self._pending_offset :]
        raw_writer = getattr(sink, "write_bytes", None)
        try:
            if callable(raw_writer):
                written = raw_writer(remaining)
                if type(written) is not int or not 0 <= written <= len(remaining):
                    raise OSError("Invalid decorative byte acknowledgement")
                self._pending_offset += written
            else:
                encoding = getattr(sink, "encoding", None) or "utf-8"
                text = remaining.decode(encoding)
                written = sink.write(text)
                if written is None:
                    written = len(text)
                if type(written) is not int or not 0 <= written <= len(text):
                    raise OSError("Invalid decorative character acknowledgement")
                self._pending_offset += len(text[:written].encode(encoding))
                if not self.pending_output:
                    sink.flush()
        except BlockingIOError:
            if callable(raw_writer):
                return  # Raw ABI: EAGAIN accepted zero bytes. Retry only on a later tick.
            self._pending_unknown = True
            self.cancel()
            return
        except BaseException as exc:
            self._pending_unknown = True
            self.cancel()
            if not isinstance(exc, (OSError, UnicodeError)):
                raise
            return
        if not self.pending_output:
            lines = self._pending_lines
            self._clear_pending()
            if self._redraw:
                self._frame_lines = lines
            if self._final_pending:
                self._final_pending = self._finishing = False
                self._frame_lines, self._redraw = 0, False

    def _viewport(self):
        try:
            if self.stream.isatty():
                size = os.get_terminal_size(self.stream.fileno())
                if size.columns > 0 and size.lines > 0:
                    return size
        except (AttributeError, OSError, ValueError):
            pass
        return None

    def begin(self):
        self.banner()

    def banner(self):
        if self._begun:
            return
        self._begun = True
        try:
            if self.design is None:
                from kirabridge import terminal_design

                self.design = terminal_design
            self._window_size = self._viewport()
            if self._window_size is not None:
                width = max(1, min(120, self._window_size.columns - 1))
            elif self.stream.isatty():
                width = 29  # Unknown TTY dimensions: short static ASCII, no cursor movement.
            else:
                width = max(1, min(120, shutil.get_terminal_size((80, 24)).columns))
            motion = self.motion if self.exclusive_output and self._window_size else "reduced"
            options = self.design.options_for(self.stream, width=width, motion=motion)
            # Never move into scrollback: only animate a frame fitting entirely
            # inside the current viewport, with a spare line below our own area.
            capacity = max(1, self._window_size.lines - 2) if self._window_size else 1
            if self.design.static_banner(options).count("\n") > capacity:
                options = self.design.options_for(
                    self.stream, width=min(width, 29), motion="reduced"
                )
            self._redraw = bool(
                options.motion and self.exclusive_output and self._window_size is not None
            )
            self._animation = self.design.AnimationController(options)
            self.tick()
        except Exception:
            # Old source checkouts without the optional presentation module keep
            # a plain local banner. No environment/setup work is performed here.
            self.cancel()
            self._graphic("KiraBridge\n")

    def tick(self):
        if self.output_prefix:
            return
        if self.pending_output:
            self._drain_graphic()  # Exactly one write; never poll/queue another frame here.
            return
        if self._animation is None:
            return
        try:
            if self._finishing:
                controller, self._animation = self._animation, None
                value = controller.finish()
                self._final_pending = bool(value)
                self._draw(value)
                if not self.pending_output:
                    self._final_pending = self._finishing = False
                    self._frame_lines, self._redraw = 0, False
            else:
                self._draw(self._animation.poll())
        except Exception:
            self.cancel()

    def _draw(self, value):
        if not value or self.pending_output or self.output_prefix:
            return
        lines, rewind, prefix = value.count("\n"), 0, ""
        if self._redraw:
            if self._viewport() != self._window_size or (
                self._frame_lines and lines != self._frame_lines
            ):
                self.cancel()
                return
            rewind = self._frame_lines
            if rewind:
                prefix = f"\x1b[{rewind}F"
        self._graphic(prefix + value, lines=lines, rewind=rewind, prefix_length=len(prefix))

    def finish(self):
        """Request finalization, without waiting for a partial frame or replacing it."""
        if self._animation is not None:
            self._finishing = True
            if not self.pending_output:
                self.tick()

    def cancel(self):
        controller, self._animation = self._animation, None
        if self._pending and (self._pending_offset or self._pending_unknown):
            if not self._output_prefix:
                tty = self.graphic_stream.isatty()
                complex_frame = self._pending_styled or not self._pending.isascii()
                prefix = "\x18" if tty and complex_frame else ""  # Abort split UTF-8/CSI.
                if self._pending_styled:
                    prefix += "\x1b[0m"
                if (
                    tty
                    and self._pending_rewind
                    and self._viewport() == self._window_size
                    and (
                        self._pending_unknown or self._pending_offset >= self._pending_prefix_length
                    )
                ):
                    body = self._pending[self._pending_prefix_length : self._pending_offset]
                    consumed_lines = 0 if self._pending_unknown else body.count(b"\n")
                    remaining = max(0, self._pending_rewind - consumed_lines)
                    if remaining:
                        prefix += f"\x1b[{remaining}E"  # Forward only, within/below our old frame.
                self._output_prefix = prefix + "\n"
        self._clear_pending()
        self._frame_lines, self._redraw = 0, False
        self._finishing = self._final_pending = False
        if controller is not None:
            controller.cancel()

    def error(self, de, en=None):
        self.cancel()
        self.say(de, en)

    def prompt(self, de, en, default=""):
        return self.ask(de, en, default)

    def step(self, number, de, en):
        self.say(f"[{number}] {de}", f"[{number}] {en}")

    def ask(self, de, en, default=""):
        self.cancel()
        self._priority_prefix()
        print(
            self.text(de, en) + (f" [{default}]" if default else "") + ": ",
            file=self.stream,
            end="",
            flush=True,
        )
        return input().strip() or default

    def confirm(self, de, en, *, default=False):
        answer = self.ask(
            de,
            en,
            "J/n"
            if default and self.language == "de"
            else "Y/n"
            if default
            else "j/N"
            if self.language == "de"
            else "y/N",
        )
        if answer in {"J/n", "Y/n", "j/N", "y/N"}:
            return default
        return answer.lower() in {"y", "yes", "j", "ja"}
