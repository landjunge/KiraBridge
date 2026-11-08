"""Shared Braille presentation, bounded polling and safe capability fallbacks."""

import hashlib
import importlib.util
import math
import re
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest

from kirabridge import terminal_design as design

SGR = re.compile(r"\x1b\[(?:38;2;[0-9]+;[0-9]+;[0-9]+|38;5;[0-9]+|0)m")
SOURCE = Path(design.__file__)


class Stream:
    encoding = "utf-8"

    def __init__(self, tty=True, encoding="utf-8"):
        self.tty, self.encoding = tty, encoding

    def isatty(self):
        return self.tty

    def write(self, text):
        raise AssertionError("Renderer/controller must never own output")


def options(**kwargs):
    return design.options_for(
        Stream(), width=100, env={"TERM": "xterm-256color", "COLORTERM": "truecolor"}, **kwargs
    )


def test_shared_geometry_reuses_entire_pr34_word_and_bridge_with_exact_palette():
    rows = design.render(100)
    assert rows == design.render(100)
    assert hashlib.sha256(design.plain(rows).encode()).hexdigest() == (
        "0c856011697f5592fe0a55a3a9108b0833e5c1025efeda527dc5bbff2c900201"
    )
    assert design.PINK_HEX == "#F06DB0" and design.PINK == (240, 109, 176)
    assert design.color_at(0, 0, 200, 100, False) == design.PINK
    assert all(0x2800 <= ord(char) <= 0x28FF for row in rows for char, _ in row)
    document = ElementTree.fromstring(design.svg(rows))
    text = document.findall(".//{http://www.w3.org/2000/svg}text")
    assert "".join(node.text for node in text) == "".join(char for row in rows for char, _ in row)
    assert "rgb(240, 109, 176)" in design.svg(rows)


@pytest.mark.parametrize(
    "tty,encoding,env,color,motion,expected_color,unicode_ok,animated",
    [
        (
            True,
            "utf-8",
            {"TERM": "xterm", "COLORTERM": "truecolor"},
            "auto",
            "full",
            "rgb",
            True,
            True,
        ),
        (True, "utf-8", {"TERM": "xterm-256color"}, "auto", "full", "256", True, True),
        (True, "utf-8", {"TERM": "vt100"}, "auto", "full", "never", True, False),
        (True, "utf-8", {"TERM": "dumb"}, "always", "full", "never", True, False),
        (True, "utf-8", {"TERM": "xterm", "NO_COLOR": ""}, "always", "full", "never", True, False),
        (False, "utf-8", {"TERM": "xterm"}, "always", "full", "never", True, False),
        (True, "ascii", {"TERM": "xterm-256color"}, "always", "full", "never", False, False),
        (True, "unknown-codec", {"TERM": "xterm"}, "always", "full", "never", False, False),
        (
            True,
            "utf-8",
            {"TERM": "xterm", "COLORTERM": "truecolor"},
            "auto",
            "reduced",
            "rgb",
            True,
            False,
        ),
        (
            True,
            "utf-8",
            {"TERM": "xterm", "COLORTERM": "truecolor", "KIRABRIDGE_MOTION": "full"},
            "auto",
            "auto",
            "rgb",
            True,
            True,
        ),
        (
            True,
            "utf-8",
            {"TERM": "xterm", "COLORTERM": "truecolor", "KIRABRIDGE_MOTION": "reduced"},
            "auto",
            "full",
            "rgb",
            True,
            False,
        ),
    ],
)
def test_capabilities_never_animate_or_escape_in_unsupported_output(
    tty, encoding, env, color, motion, expected_color, unicode_ok, animated
):
    settings = design.options_for(
        Stream(tty, encoding), width=100, env=env, color=color, motion=motion
    )
    assert (settings.color, settings.unicode, settings.motion) == (
        expected_color,
        unicode_ok,
        animated,
    )
    text = design.static_banner(settings)
    if expected_color == "never":
        assert "\x1b" not in text
    else:
        assert "\x1b" not in SGR.sub("", text)
        assert text.endswith("\x1b[0m\n")
    if not unicode_ok:
        assert text.isascii() and "KiraBridge" in text


@pytest.mark.parametrize("width", [1, 9, 29, 30, 100, 160])
def test_width_and_ascii_fallback_are_bounded(width):
    settings = design.options_for(Stream(), width=width, env={}, motion="reduced")
    text = design.static_banner(settings)
    assert all(len(line) <= width for line in text.splitlines())
    if width < 30:
        assert text.isascii()
        assert "KiraBridge" in text.replace("\n", "")
    assert len(text.encode()) <= design.MAX_FRAME_BYTES


@pytest.mark.parametrize("width", [0, -1, 161, True])
def test_invalid_width_cannot_allocate_a_canvas(width):
    with pytest.raises(ValueError):
        design.options_for(Stream(), width=width)
    with pytest.raises(ValueError):
        design.canvas(width)


def lit_dots(rows):
    return [
        (y, x, mask)
        for y, row in enumerate(rows)
        for x, (char, _) in enumerate(row)
        for _, _, mask in design.DOTS
        if (ord(char) - 0x2800) & mask
    ]


def test_point_build_is_ordered_and_pulse_changes_light_only():
    rows = design.render(100)
    original = lit_dots(rows)
    for progress in (0, 0.25, 0.5, 1):
        partial = design.frame_rows(rows, reveal=progress)
        assert lit_dots(partial) == original[: math.floor(len(original) * progress)]
    pulse = design.frame_rows(rows, pulse=0.5)
    assert lit_dots(pulse) == original
    assert pulse != rows
    assert design.plain(pulse) == design.plain(rows)


def test_controller_never_waits_and_skips_stale_frames_with_one_complete_final_banner(monkeypatch):
    import time

    monkeypatch.setattr(time, "sleep", lambda *_: pytest.fail("No decorative waits"))
    settings = options(motion="full")
    controller = design.AnimationController(settings, clock=lambda: 0.0)
    first = controller.poll(now=0)
    assert first and controller.poll(now=0) is None
    final = controller.poll(now=10)  # Slow consumer: skip every obsolete frame.
    assert final == design.static_banner(settings)
    assert controller.poll(now=11) is None and controller.finish() == ""
    assert controller.emitted_bytes <= design.MAX_OUTPUT_BYTES


def test_controller_motion_reduction_prompt_priority_cancellation_and_bad_clock():
    static = design.AnimationController(options(), clock=lambda: 0.0)
    assert static.poll(now=0) == design.static_banner(options())
    assert static.poll(now=1) is None
    active = design.AnimationController(options(motion="full"), clock=lambda: 0.0)
    assert active.poll(now=0).endswith("\x1b[0m\n")
    assert active.poll(now=0.1, urgent=True) is None and active.finish() == ""
    broken = design.AnimationController(options(motion="full"), clock=lambda: 0.0)
    broken.cancel()  # Caller-owned slow/broken output ends decoration immediately.
    assert broken.poll(now=1) is None and broken.finish() == ""
    invalid = design.AnimationController(options(motion="full"), clock=lambda: 0.0)
    assert invalid.poll(now=float("nan")) is None


def test_controller_frame_and_total_budgets_and_sgr_only_at_largest_width():
    settings = options(motion="full")._replace(width=160)
    controller = design.AnimationController(settings, max_frames=8, clock=lambda: 0.0)
    frames = [controller.poll(now=index * controller.duration / 8) for index in range(9)]
    actual = [frame for frame in frames if frame]
    assert len(actual) <= 8 and actual[-1] == design.static_banner(settings)
    assert all(len(frame.encode()) <= design.MAX_FRAME_BYTES for frame in actual)
    assert (
        sum(len(frame.encode()) for frame in actual)
        == controller.emitted_bytes
        <= design.MAX_OUTPUT_BYTES
    )
    for frame in actual:
        assert "\x1b" not in SGR.sub("", frame)
        assert all(char == "\n" or 0x2800 <= ord(char) <= 0x28FF for char in SGR.sub("", frame))


def test_leaf_module_import_needs_no_installed_bridge_and_performs_no_runtime_init():
    code = (
        "import importlib.util,sys;"
        "s=importlib.util.spec_from_file_location('standalone_design',sys.argv[1]);"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        "assert m.API_VERSION==1 and 'kirabridge' not in sys.modules;"
        "assert m.PINK==(240,109,176)"
    )
    subprocess.run([sys.executable, "-I", "-c", code, str(SOURCE)], check=True, timeout=3)


def test_preview_reuses_shared_leaf_and_rejects_exports_outside_checkout(tmp_path):
    preview = SOURCE.parents[2] / "scripts/preview_terminal_design.py"
    spec = importlib.util.spec_from_file_location("isolated_preview", preview)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.design.PINK == design.PINK
    with pytest.raises(ValueError, match="inside this repository"):
        module.export(str(tmp_path / "not-created.svg"), "not written")
    assert not (tmp_path / "not-created.svg").exists()


@pytest.mark.parametrize("error", [KeyboardInterrupt, BrokenPipeError])
@pytest.mark.parametrize("stage", ["write", "flush"])
def test_preview_interrupted_colored_write_resets_without_more_graphics(error, stage):
    preview = SOURCE.parents[2] / "scripts/preview_terminal_design.py"
    spec = importlib.util.spec_from_file_location("interrupted_preview", preview)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    written = []

    class Interrupted:
        def write(self, text):
            written.append(text)
            if stage == "write" and len(written) == 1:
                raise error

        def flush(self):
            if stage == "flush" and len(written) == 1:
                raise error

    with pytest.raises(error):
        module.emit_frame(Interrupted(), "\033[38;2;240;109;176m⣿", styled=True)
    assert written[-1] == "\033[0m\n" and len(written) == 2


@pytest.mark.parametrize("width", [30, 60, 80, 120, 160])
def test_compact_header_is_only_the_left_aligned_wordmark(width):
    rows = design.compact_rows(width)
    full = design.render(min(width, design.COMPACT_MAX_WIDTH))
    assert len(rows) <= 5 and len(rows) < len(full)
    assert all(len(row) <= width for row in rows)
    if width >= 64:
        assert all(char == "⠀" for row in rows for char, _ in row[: design.COMPACT_INDENT])
    assert any(char != "⠀" for row in rows for char, _ in row[design.COMPACT_INDENT :][:1]) or (
        width < 64
    )
    compact = design.options_for(
        Stream(), width=width, env={"TERM": "xterm-256color"}, compact=True
    )
    assert compact.compact and design.static_banner(compact).count("\n") == len(rows)
    # The full PR34 banner keeps its word and bridge for every other caller.
    banner = design.static_banner(compact._replace(compact=False))
    assert banner.count("\n") == len(design.render(width))


def test_compact_header_falls_back_to_plain_name_without_unicode():
    settings = design.options_for(Stream(encoding="ascii"), width=80, env={}, compact=True)
    assert design.static_banner(settings) == "KiraBridge\n"
    assert design.AnimationController(settings).finish() == "KiraBridge\n"
