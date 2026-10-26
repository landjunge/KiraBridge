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
        self.design, self.motion = design, motion
        self._animation = None
        self._begun = False
        self.exclusive_output = exclusive_output
        self._frame_lines = 0
        self._redraw = False
        self._window_size = None

    def text(self, de, en):
        return de if self.language == "de" else en

    def say(self, de, en=None):
        self.finish()
        value = self.text(de, en or de)
        width = max(24, min(88, shutil.get_terminal_size((80, 24)).columns))
        print(textwrap.fill(value, width=width), file=self.stream, flush=True)

    def _graphic(self, value):
        if not value:
            return
        colored_tty = "\x1b[" in value and self.stream.isatty()
        try:
            written = self.stream.write(value)
            if written is not None and written != len(value):
                raise BlockingIOError("Incomplete decorative write")
            self.stream.flush()
        except BaseException as exc:
            self.cancel()
            if colored_tty:
                try:
                    self.stream.write("\x1b[0m\n")
                    self.stream.flush()
                except BaseException:
                    pass
            # Ordinary decorative I/O failures cannot block installation. User
            # interrupts still propagate after best-effort terminal cleanup.
            if not isinstance(exc, (OSError, UnicodeError)):
                raise

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
        if self._animation is None:
            return
        try:
            self._draw(self._animation.poll())
        except Exception:
            self.cancel()

    def _draw(self, value):
        if not value:
            return
        if self._redraw:
            lines = value.count("\n")
            if self._viewport() != self._window_size or (
                self._frame_lines and lines != self._frame_lines
            ):
                self.cancel()
                return
            if self._frame_lines:
                value = f"\x1b[{self._frame_lines}F" + value
            self._graphic(value)
            if self._redraw:
                self._frame_lines = lines
        else:
            self._graphic(value)

    def finish(self):
        controller, self._animation = self._animation, None
        try:
            if controller is not None:
                self._draw(controller.finish())
        except Exception:
            controller.cancel()
        finally:
            self._frame_lines, self._redraw = 0, False

    def cancel(self):
        controller, self._animation = self._animation, None
        self._frame_lines, self._redraw = 0, False
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
