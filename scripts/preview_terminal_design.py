#!/usr/bin/env python3
"""Static, dependency-free terminal design preview; never starts KiraBridge."""

from __future__ import annotations

import argparse
import html
import os
import shutil
import sys
from pathlib import Path

PINK = (242, 61, 160)
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


def plain(rows) -> str:
    return "\n".join("".join(char for char, _ in row) for row in rows) + "\n"


def terminal(rows, color: str) -> str:
    if color == "never":
        return plain(rows)

    def paint(char, rgb):
        r, g, b = rgb
        if color == "256":
            levels = [round(value * 5 / 255) for value in rgb]
            index = 16 + 36 * levels[0] + 6 * levels[1] + levels[2]
            return f"\033[38;5;{index}m{char}"
        return f"\033[38;2;{r};{g};{b}m{char}"

    return (
        "\n".join("".join(paint(char, rgb) for char, rgb in row) + "\033[0m" for row in rows) + "\n"
    )


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


def export(path: str, content: str) -> None:
    root = Path(__file__).resolve().parents[1]
    target = Path(path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError("Preview exports must stay inside this repository") from None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--width", type=int, default=min(shutil.get_terminal_size((100, 24)).columns, 120)
    )
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    parser.add_argument("--ascii", action="store_true", help="Plain ASCII fallback")
    parser.add_argument("--svg", metavar="PATH", help="Export dot geometry inside this repository")
    parser.add_argument(
        "--text", metavar="PATH", help="Export plain UTF-8 preview inside this repository"
    )
    args = parser.parse_args()
    if not 1 <= args.width <= 160:
        parser.error("--width must be between 1 and 160")
    encoding = sys.stdout.encoding or "ascii"
    try:
        "⣿".encode(encoding)
        unicode_ok = True
    except (UnicodeError, LookupError):
        unicode_ok = False
    rows = render(args.width) if args.width >= 30 else None
    use_ascii = args.ascii or not unicode_ok or rows is None
    color = "never"
    term = os.environ.get("TERM", "")
    if not use_ascii:
        if args.color == "always":
            color = "rgb"
        elif (
            args.color == "auto"
            and sys.stdout.isatty()
            and "NO_COLOR" not in os.environ
            and term != "dumb"
        ):
            if os.environ.get("COLORTERM", "").lower() in {"truecolor", "24bit"}:
                color = "rgb"
            elif "256color" in term:
                color = "256"
    try:
        if args.svg:
            if rows is None:
                parser.error("SVG Braille preview requires --width >= 30")
            export(args.svg, svg(rows))
        if args.text:
            export(args.text, fallback(args.width) if use_ascii else plain(rows))
        sys.stdout.write(fallback(args.width) if use_ascii else terminal(rows, color))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
