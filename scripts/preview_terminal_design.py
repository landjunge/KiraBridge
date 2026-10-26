#!/usr/bin/env python3
"""Standalone shared Braille design preview; never starts or changes KiraBridge."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

# Load exactly this checkout's dependency-free presentation module, without
# importing the installed package or initializing any bridge/runtime component.
SOURCE = Path(__file__).resolve().parents[1] / "src/kirabridge/terminal_design.py"
spec = importlib.util.spec_from_file_location("kirabridge_design_preview", SOURCE)
design = importlib.util.module_from_spec(spec)
spec.loader.exec_module(design)


def export(path, content):
    root = Path(__file__).resolve().parents[1]
    target = Path(path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError("Preview exports must stay inside this repository") from None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def emit_frame(stream, text, *, styled=False):
    """The preview owns output; the reusable renderer deliberately does not."""
    try:
        stream.write(text)
        stream.flush()
    except BaseException:
        if styled:
            try:
                stream.write("\033[0m\n")
                stream.flush()
            except BaseException:
                pass  # A closed output cannot confirm cleanup; never print more graphics.
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int)
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    parser.add_argument("--ascii", action="store_true")
    parser.add_argument("--svg", metavar="PATH")
    parser.add_argument("--text", metavar="PATH")
    parser.add_argument(
        "--frames",
        action="store_true",
        help="Print the finite frame sequence without sleeps; opt-in colored TTY only",
    )
    try:
        args = parser.parse_args()
        options = design.options_for(
            sys.stdout,
            width=args.width,
            color=args.color,
            motion="full" if args.frames else "reduced",
        )
        if args.ascii:
            options = options._replace(unicode=False, color="never", motion=False)
        if args.svg:
            if options.width < 30:
                parser.error("SVG Braille preview requires --width >= 30")
            export(args.svg, design.svg(design.render(options.width)))
        if args.text:
            export(args.text, design.static_banner(options._replace(color="never", motion=False)))
        if args.frames and options.motion:
            controller = design.AnimationController(options, clock=lambda: 0.0)
            for index in range(controller.max_frames):
                frame = controller.poll(
                    now=index * controller.duration / (controller.max_frames - 1)
                )
                if frame:
                    emit_frame(sys.stdout, frame, styled=options.color != "never")
        else:
            emit_frame(sys.stdout, design.static_banner(options), styled=options.color != "never")
    except KeyboardInterrupt:
        parser.exit(130, "Preview interrupted.\n")
    except BrokenPipeError:
        parser.exit(1, "Preview output closed.\n")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
