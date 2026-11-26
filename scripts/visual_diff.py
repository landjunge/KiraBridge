#!/usr/bin/env python3
"""Numerischer Bildvergleich zweier PNG-Screenshots (KiraBridge gegen Agent Authority).

Beide Bilder werden auf die gemeinsame Zielgroesse (Maximum aus Breite und Hoehe)
gebracht; die kleinere Aufnahme wird skaliert und die Seitenverhaeltnisse beider
Originale werden im Bericht ausgegeben. Pro Region werden der mittlere absolute
Pixelunterschied in Prozent (0-100) und der Anteil abweichender Pixel (Schwelle:
24 von 255) berichtet, ebenso als Gesamtwert ueber das ganze Bild.

Schwellen sind reine Berichtszahlen: der Exit-Code ist nach erfolgreichem
Vergleich immer 0; nur --max-diff hebt ihn auf 1, wenn die Gesamtabweichung
(mean_diff_pct) groesser ist. 2 bei Benutzerungs- oder Lesefehlern.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

PIXEL_THRESHOLD = 24

# Relative Rechtecke (x0, y0, x1, y1) in Bruchteilen der Bildgroesse.
REGION_DEFS: dict[str, tuple[float, float, float, float]] = {
    "titlebar": (0.0, 0.0, 1.0, 0.04),
    "header": (0.0, 0.04, 1.0, 0.09),
    "sidebar": (0.0, 0.09, 0.11, 1.0),
    "inspector": (0.82, 0.0, 1.0, 1.0),
    "center": (0.11, 0.09, 0.82, 1.0),
}
REGION_ORDER = tuple(REGION_DEFS)


def _region_box(rel: tuple[float, float, float, float], width: int, height: int) -> tuple[int, ...]:
    x0, y0, x1, y1 = rel
    return (round(x0 * width), round(y0 * height), round(x1 * width), round(y1 * height))


def _metrics(diff: np.ndarray) -> dict[str, float]:
    mean_pct = float(diff.mean()) / 255.0 * 100.0
    per_pixel = diff.max(axis=2)
    diff_pct = float((per_pixel > PIXEL_THRESHOLD).mean()) * 100.0
    return {"mean_diff_pct": round(mean_pct, 4), "diff_pixel_pct": round(diff_pct, 4)}


def compare_images(
    path_a: Path | str,
    path_b: Path | str,
    regions: tuple[str, ...] | list[str] | None = None,
) -> tuple[dict, np.ndarray]:
    """Vergleicht beide PNGs und liefert (Bericht, Heatmap) zurueck.

    Heatmap: uint8-Feld (H, W) mit der maximalen Kanaldifferenz je Pixel.
    """
    with Image.open(path_a) as img_a, Image.open(path_b) as img_b:
        img_a = img_a.convert("RGB")
        img_b = img_b.convert("RGB")
        size_a = img_a.size
        size_b = img_b.size
        target = (max(size_a[0], size_b[0]), max(size_a[1], size_b[1]))
        scaled = [name for name, size in (("a", size_a), ("b", size_b)) if size != target]
        if size_a != target:
            img_a = img_a.resize(target)
        if size_b != target:
            img_b = img_b.resize(target)
        a = np.asarray(img_a, dtype=np.int32)
        b = np.asarray(img_b, dtype=np.int32)

    diff = np.abs(a - b)
    heatmap = diff.max(axis=2).astype(np.uint8)
    width, height = target

    names = tuple(regions) if regions else REGION_ORDER
    region_report: dict[str, dict] = {}
    for name in names:
        left, top, right, bottom = _region_box(REGION_DEFS[name], width, height)
        region_report[name] = {
            "box": [left, top, right, bottom],
            **_metrics(diff[top:bottom, left:right]),
        }

    aspect_a = size_a[0] / size_a[1]
    aspect_b = size_b[0] / size_b[1]
    report = {
        "inputs": {
            "a": {
                "path": str(path_a),
                "width": size_a[0],
                "height": size_a[1],
                "aspect_ratio": round(aspect_a, 4),
            },
            "b": {
                "path": str(path_b),
                "width": size_b[0],
                "height": size_b[1],
                "aspect_ratio": round(aspect_b, 4),
            },
        },
        "aspect_ratio_match": abs(aspect_a - aspect_b) <= 0.005,
        "compared_size": {"width": width, "height": height, "scaled": scaled},
        "pixel_threshold": PIXEL_THRESHOLD,
        "total": _metrics(diff),
        "regions": region_report,
    }
    return report, heatmap


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="visual_diff.py",
        description="Numerischer Bildvergleich zweier PNG-Screenshots pro Region.",
    )
    parser.add_argument("a", type=Path, help="PNG A (z. B. KiraBridge)")
    parser.add_argument("b", type=Path, help="PNG B (z. B. Agent Authority)")
    parser.add_argument(
        "--regions",
        default="",
        help="Kommagetrennte Auswahl aus: " + ", ".join(REGION_ORDER) + " (Standard: alle)",
    )
    parser.add_argument(
        "--json", type=Path, default=None, help="Bericht zusaetzlich als JSON-Datei"
    )
    parser.add_argument(
        "--diff", type=Path, default=None, help="Differenzbild (Graustufen-Heatmap) als PNG"
    )
    parser.add_argument(
        "--max-diff",
        type=float,
        default=None,
        help="Exit-Code 1, wenn die Gesamtabweichung (mean_diff_pct) groesser ist",
    )
    args = parser.parse_args(argv)

    for label, path in (("a", args.a), ("b", args.b)):
        if not path.is_file():
            print(f"Fehler: Datei nicht gefunden ({label}): {path}", file=sys.stderr)
            return 2
    names = [item.strip() for item in args.regions.split(",") if item.strip()]
    unknown = [item for item in names if item not in REGION_DEFS]
    if unknown:
        print(f"Fehler: unbekannte Region(en): {', '.join(unknown)}", file=sys.stderr)
        return 2

    report, heatmap = compare_images(args.a, args.b, names or None)
    exceeds = args.max_diff is not None and report["total"]["mean_diff_pct"] > args.max_diff
    report["max_diff"] = args.max_diff
    report["exceeds_max_diff"] = exceeds

    payload = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(payload + "\n", encoding="utf-8")
    if args.diff is not None:
        args.diff.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(heatmap, mode="L").save(args.diff)
    print(payload)
    return 1 if exceeds else 0


if __name__ == "__main__":
    sys.exit(main())
