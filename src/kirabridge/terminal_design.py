"""Bounded Braille presentation, reused from PR34/ada6e37; no runtime or output effects.

Only the caller owns its output stream, progress events and prompt priority. This
module never writes, waits, starts threads/processes or changes a terminal setting.
"""

from __future__ import annotations

import html
import math
import os
import time
from typing import NamedTuple

PINK = (240, 109, 176)
PINK_HEX = "#F06DB0"
API_VERSION = 1
MAX_WIDTH = 160
MAX_FRAMES = 8
MAX_FRAME_BYTES = 128 * 1024
MAX_OUTPUT_BYTES = 256 * 1024
LIGHT = (255, 180, 222)
WHITE = (255, 244, 252)
BACKGROUND = "#100b16"
DOTS = ((0, 0, 1), (0, 1, 2), (0, 2, 4), (1, 0, 8), (1, 1, 16), (1, 2, 32), (0, 3, 64), (1, 3, 128))
# Five-column pixel glyphs, including the lowercase descender in KiraBridge.
FONT = {
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001", "00000", "00000"),
    "i": ("00100", "00000", "01100", "00100", "00100", "00100", "01110", "00000", "00000"),
    "r": ("00000", "00000", "10110", "11001", "10000", "10000", "10000", "00000", "00000"),
    "a": ("00000", "00000", "01110", "00001", "01111", "10001", "01111", "00000", "00000"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110", "00000", "00000"),
    "d": ("00001", "00001", "01101", "10011", "10001", "10011", "01101", "00000", "00000"),
    "g": ("00000", "00000", "01111", "10001", "10001", "01111", "00001", "10001", "01110"),
    "e": ("00000", "00000", "01110", "10001", "11111", "10000", "01110", "00000", "00000"),
}


def color_at(x: int, y: int, width: int, height: int, highlight: bool) -> tuple[int, int, int]:
    if highlight:
        return WHITE
    fraction = min(1.0, 0.65 * x / max(width - 1, 1) + 0.35 * y / max(height - 1, 1))
    return tuple(round(PINK[c] + (LIGHT[c] - PINK[c]) * fraction) for c in range(3))


def canvas(width: int) -> list[list[int]]:
    """Pixel intensity: zero empty, one pink, two white highlight."""
    if type(width) is not int or not 30 <= width <= MAX_WIDTH:
        raise ValueError("Braille canvas width must be between 30 and 160")
    scale = next(s for s in (4, 3, 2, 1) if (59 * s + 1) // 2 <= width)
    word_height = 9 * scale
    bridge_height = max(36, width // 2)
    pixels = [[0] * (width * 2) for _ in range(word_height + 8 + bridge_height)]

    def dot(x, y, intensity=1):
        if 0 <= y < len(pixels) and 0 <= x < len(pixels[0]):
            pixels[y][x] = max(pixels[y][x], intensity)

    def line(x1, y1, x2, y2, intensity=1):
        steps = max(abs(x2 - x1), abs(y2 - y1), 1)
        for step in range(steps + 1):
            dot(
                round(x1 + (x2 - x1) * step / steps),
                round(y1 + (y2 - y1) * step / steps),
                intensity,
            )

    left = (width * 2 - 59 * scale) // 2
    for index, letter in enumerate("KiraBridge"):
        for y, row in enumerate(FONT[letter]):
            for x, value in enumerate(row):
                if value == "1":
                    for dy in range(scale):
                        for dx in range(scale):
                            dot(
                                left + (index * 6 + x) * scale + dx,
                                y * scale + dy,
                                2 if y == 0 and dy == 0 else 1,
                            )

    # A perspective deck, paired towers, suspension cables and lit crossbeams.
    top = word_height + 8
    w, h = width * 2, bridge_height
    near_left, near_right = (w // 12, top + h * 3 // 4), (w * 4 // 5, top + h * 3 // 4)
    depth = (w // 9, -h // 4)
    far_left = (near_left[0] + depth[0], near_left[1] + depth[1])
    far_right = (near_right[0] + depth[0], near_right[1] + depth[1])
    for start, end in (
        (near_left, near_right),
        (far_left, far_right),
        (near_left, far_left),
        (near_right, far_right),
    ):
        line(*start, *end, 2)
    for t in range(0, 11):
        x = round(near_left[0] + (near_right[0] - near_left[0]) * t / 10)
        line(x, near_left[1], x + depth[0], far_left[1])
    for x in (w // 3, w * 3 // 5):
        for offset, bottom in ((0, near_left[1]), (depth[0], far_left[1])):
            peak = top + (3 if offset == 0 else 0)
            line(x + offset, peak, x + offset, top + h - 1, 2)
            line(x + offset + 2, peak, x + offset + 2, top + h - 1)
            for anchor in (near_left[0] + offset, near_right[0] + offset):
                line(x + offset, peak, anchor, bottom)
                for part in range(1, 8):
                    fraction = part / 8
                    cable_x = round(x + offset + (anchor - x - offset) * fraction)
                    cable_y = round(peak + (bottom - peak) * fraction)
                    line(cable_x, cable_y, cable_x, bottom)
        line(x, top + h // 3, x + depth[0], top + h // 3 + depth[1], 2)
    return pixels


def render(width: int) -> list[list[tuple[str, tuple[int, int, int]]]]:
    """One deterministic Braille cell model for terminal, text and SVG exports."""
    pixels = canvas(width)
    rows = []
    for y in range(0, len(pixels), 4):
        row = []
        for x in range(0, width * 2, 2):
            bits, highlight = 0, False
            for dx, dy, mask in DOTS:
                if y + dy < len(pixels) and pixels[y + dy][x + dx]:
                    bits |= mask
                    highlight |= pixels[y + dy][x + dx] == 2
            row.append((chr(0x2800 + bits), color_at(x, y, width * 2, len(pixels), highlight)))
        rows.append(row)
    return rows


COMPACT_MAX_WIDTH = 88  # Keeps the wordmark at scale 2 or less: five Braille rows.
COMPACT_INDENT = 2


def compact_rows(width: int) -> list[list[tuple[str, tuple[int, int, int]]]]:
    """Only the KiraBridge wordmark of the shared geometry, left-aligned, no bridge."""
    if type(width) is not int or not 30 <= width <= MAX_WIDTH:
        raise ValueError("Braille canvas width must be between 30 and 160")
    size = min(width, COMPACT_MAX_WIDTH)
    scale = next(s for s in (4, 3, 2, 1) if (59 * s + 1) // 2 <= size)
    rows = render(size)[: -(-9 * scale // 4)]
    used = [x for row in rows for x, (char, _) in enumerate(row) if char != "⠀"]
    first, last = min(used), max(used)
    blank = ("⠀", PINK)
    indent = [blank] * COMPACT_INDENT if width >= last - first + 1 + COMPACT_INDENT else []
    return [indent + row[first : last + 1] for row in rows]


def plain(rows) -> str:
    return "\n".join("".join(char for char, _ in row) for row in rows) + "\n"


def terminal(rows, color: str) -> str:
    """Complete text/SGR-only frame; blank cells need no foreground color writes."""
    if color == "never":
        return plain(rows)
    if color not in {"rgb", "256"}:
        raise ValueError("Unsupported terminal color mode")
    lines = []
    for row in rows:
        pieces, previous = [], None
        for char, rgb in row:
            if char != "⠀":
                if color == "256":
                    levels = tuple(round(value * 5 / 255) for value in rgb)
                    paint = f"\033[38;5;{16 + 36 * levels[0] + 6 * levels[1] + levels[2]}m"
                else:
                    paint = f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"
                if paint != previous:
                    pieces.append(paint)
                    previous = paint
            pieces.append(char)
        lines.append("".join(pieces) + "\033[0m")
    return "\n".join(lines) + "\n"


def svg(rows) -> str:
    # Exactly the terminal's Braille characters and RGB values; no external fonts.
    width, height = len(rows[0]) * 12 + 32, len(rows) * 22 + 32
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        'aria-label="KiraBridge Braille design preview">',
        "<title>KiraBridge — static terminal preview</title>",
        f'<rect width="{width}" height="{height}" fill="{BACKGROUND}"/>',
    ]
    parts.append(
        '<g font-family="Menlo, DejaVu Sans Mono, monospace" font-size="20" xml:space="preserve">'
    )
    for y, row in enumerate(rows):
        for x, (char, color) in enumerate(row):
            parts.append(
                f'<text x="{16 + x * 12}" y="{32 + y * 22}" '
                f'fill="rgb{color}">{html.escape(char)}</text>'
            )
    parts.append("</g>")
    return "\n".join(parts + ["</svg>"]) + "\n"


def fallback(width: int) -> str:
    if type(width) is not int or not 1 <= width <= MAX_WIDTH:
        raise ValueError("Preview width must be between 1 and 160")
    title = "KiraBridge"
    lines = [title[i : i + width] for i in range(0, len(title), width)]
    if width >= 36:
        lines += [
            "",
            "       |\\             |\\",
            "   ====|=\\============|=\\====",
            "    \\ |  \\            |  \\   \\",
            "     =========================",
            "       |              |",
        ]
    return "\n".join(lines) + "\n"


class RenderOptions(NamedTuple):
    width: int
    unicode: bool
    color: str
    motion: bool
    compact: bool = False


def options_for(stream, *, width=None, env=None, color="auto", motion="reduced", compact=False):
    """Inspect caller-owned capabilities, without emitting output or changing env.

    Unknown capabilities fail to plain/static output. Even explicit color cannot
    introduce escapes into redirected logs, NO_COLOR or TERM=dumb output.
    """
    if color not in {"auto", "always", "never"} or motion not in {"auto", "full", "reduced"}:
        raise ValueError("Unsupported presentation option")
    env = os.environ if env is None else env
    try:
        tty = bool(stream.isatty())
    except (AttributeError, OSError, ValueError):
        tty = False
    if width is None:
        width = 100
        if tty:
            try:
                width = os.get_terminal_size(stream.fileno()).columns
            except (AttributeError, OSError, ValueError):
                pass
        width = max(1, min(width, 120))
    if type(width) is not int or not 1 <= width <= MAX_WIDTH:
        raise ValueError("Preview width must be between 1 and 160")
    try:
        "⣿".encode(getattr(stream, "encoding", None) or "ascii")
        unicode_ok = width >= 30
    except (UnicodeError, LookupError):
        unicode_ok = False
    term = env.get("TERM", "")
    interactive = tty and unicode_ok and term != "dumb" and "NO_COLOR" not in env
    palette = "never"
    if interactive and color != "never":
        if color == "always" or env.get("COLORTERM", "").lower() in {"truecolor", "24bit"}:
            palette = "rgb"
        elif "256color" in term:
            palette = "256"
    requested = env.get("KIRABRIDGE_MOTION", "reduced") if motion == "auto" else motion
    animated = interactive and palette != "never" and requested == "full"
    if env.get("KIRABRIDGE_MOTION") == "reduced":
        animated = False
    return RenderOptions(width, unicode_ok, palette, animated, bool(compact))


def _rows_for(options):
    return compact_rows(options.width) if options.compact else render(options.width)


def static_banner(options):
    """Return one complete final banner, without any protocol/state side effects."""
    if not options.unicode:
        return "KiraBridge\n" if options.compact else fallback(options.width)
    return terminal(_rows_for(options), options.color)


def frame_rows(rows, *, reveal=1.0, pulse=None):
    """Reveal lit Braille dots in stable row/cell/dot order; optional moving light."""
    if not isinstance(reveal, (int, float)) or not math.isfinite(reveal) or not 0 <= reveal <= 1:
        raise ValueError("Reveal must be within 0..1")
    if pulse is not None and (not math.isfinite(pulse) or not 0 <= pulse <= 1):
        raise ValueError("Pulse must be within 0..1")
    total = sum(bin(ord(char) - 0x2800).count("1") for row in rows for char, _ in row)
    remaining = math.floor(total * reveal)
    result = []
    for row in rows:
        current = []
        for x, (char, rgb) in enumerate(row):
            bits, visible = ord(char) - 0x2800, 0
            for _, _, mask in DOTS:
                if bits & mask and remaining > 0:
                    visible |= mask
                    remaining -= 1
            if pulse is not None and abs(x / max(1, len(row) - 1) - pulse) <= 0.08:
                rgb = WHITE
            current.append((chr(0x2800 + visible), rgb))
        result.append(current)
    return result


class AnimationController:
    """Caller-polled bounded frames: no I/O, waits, locks, threads or timed joins.

    The caller polls only at safe presentation points and cancels before a prompt,
    error or slow/broken write. Old frames are skipped rather than queued. Frames
    only append text; there is no cursor motion, clear-screen or terminal control.
    """

    def __init__(
        self, options, *, mode="build-pulse", duration=0.6, max_frames=6, clock=time.monotonic
    ):
        if mode not in {"build-pulse", "build", "pulse"}:
            raise ValueError("Unsupported animation mode")
        if (
            not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or not 0 < duration <= 2
        ):
            raise ValueError("Animation duration must be within 0..2 seconds")
        if type(max_frames) is not int or not 2 <= max_frames <= MAX_FRAMES:
            raise ValueError("Animation frame budget must be within 2..8")
        self.options, self.mode = options, mode
        self.duration, self.max_frames, self.clock = duration, max_frames, clock
        self._start = clock()
        self._last = -1
        self._done = False
        self._bytes = 0
        self._rows = _rows_for(options) if options.unicode else None
        self._static = static_banner(options)
        if len(self._static.encode("utf-8")) > MAX_FRAME_BYTES:
            raise ValueError("Static banner exceeds frame budget")

    @property
    def emitted_bytes(self):
        return self._bytes

    def cancel(self):
        self._done = True

    def finish(self):
        if self._done:
            return ""
        self._done = True
        self._bytes += len(self._static.encode("utf-8"))
        return self._static

    def poll(self, *, now=None, urgent=False):
        if urgent:
            self.cancel()
        if self._done:
            return None
        if not self.options.motion or self._rows is None:
            return self.finish()
        current = self.clock() if now is None else now
        if not isinstance(current, (int, float)) or not math.isfinite(current):
            self.cancel()
            return None
        index = min(
            self.max_frames - 1,
            max(0, int((current - self._start) / self.duration * self.max_frames)),
        )
        if index <= self._last:
            return None
        self._last = index
        if index == self.max_frames - 1:
            return self.finish()
        phase = (index + 1) / (self.max_frames - 1)
        reveal = (
            min(1, phase * 2)
            if self.mode == "build-pulse"
            else phase
            if self.mode == "build"
            else 1
        )
        pulse = (
            (phase - 0.5) * 2
            if self.mode == "build-pulse" and phase >= 0.5
            else phase
            if self.mode == "pulse"
            else None
        )
        text = terminal(frame_rows(self._rows, reveal=reveal, pulse=pulse), self.options.color)
        size = len(text.encode("utf-8"))
        reserved = len(self._static.encode("utf-8"))
        if size > MAX_FRAME_BYTES or self._bytes + size + reserved > MAX_OUTPUT_BYTES:
            return self.finish()
        self._bytes += size
        return text
