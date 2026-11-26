"""Tests für scripts/visual_diff.py — synthetische PNGs, keine echten Screenshots."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("PIL")
pytest.importorskip("numpy")

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "visual_diff.py"
_spec = importlib.util.spec_from_file_location("visual_diff", _SCRIPT)
assert _spec is not None and _spec.loader is not None
visual_diff = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(visual_diff)

SIZE = (800, 500)


def _solid(color: tuple[int, int, int]) -> np.ndarray:
    return np.zeros((SIZE[1], SIZE[0], 3), dtype=np.uint8) + np.array(color, dtype=np.uint8)


def _png(tmp_path: Path, name: str, array: np.ndarray) -> Path:
    path = tmp_path / name
    Image.fromarray(array, mode="RGB").save(path)
    return path


def test_identical_images_zero(tmp_path):
    a = _png(tmp_path, "a.png", _solid((30, 60, 90)))
    b = _png(tmp_path, "b.png", _solid((30, 60, 90)))
    report, heatmap = visual_diff.compare_images(a, b)
    assert report["total"]["mean_diff_pct"] == 0.0
    assert report["total"]["diff_pixel_pct"] == 0.0
    for region in report["regions"].values():
        assert region["mean_diff_pct"] == 0.0
        assert region["diff_pixel_pct"] == 0.0
    assert heatmap.shape == (SIZE[1], SIZE[0])


def test_completely_different_images_high(tmp_path):
    a = _png(tmp_path, "a.png", _solid((255, 0, 0)))
    b = _png(tmp_path, "b.png", _solid((0, 0, 255)))
    report, _ = visual_diff.compare_images(a, b)
    assert report["total"]["mean_diff_pct"] > 50.0
    assert report["total"]["diff_pixel_pct"] == 100.0


def test_only_sidebar_change_raises_only_sidebar(tmp_path):
    base = _solid((40, 40, 40))
    changed = base.copy()
    changed[60:400, 10:80] = (240, 30, 30)  # liegt eindeutig innerhalb der Sidebar-Region
    a = _png(tmp_path, "a.png", base)
    b = _png(tmp_path, "b.png", changed)
    report, _ = visual_diff.compare_images(a, b)
    assert report["regions"]["sidebar"]["mean_diff_pct"] > 0.0
    assert report["regions"]["sidebar"]["diff_pixel_pct"] > 0.0
    for name in ("titlebar", "header", "inspector", "center"):
        assert report["regions"][name]["mean_diff_pct"] == 0.0, name
        assert report["regions"][name]["diff_pixel_pct"] == 0.0, name


def test_subthreshold_change_counts_only_in_mean(tmp_path):
    base = _solid((100, 100, 100))
    a = _png(tmp_path, "a.png", base)
    b = _png(tmp_path, "b.png", base + 20)  # unter der Schwelle von 24
    report, _ = visual_diff.compare_images(a, b)
    assert report["total"]["mean_diff_pct"] > 0.0
    assert report["total"]["diff_pixel_pct"] == 0.0


def test_smaller_image_scaled_and_aspect_reported(tmp_path):
    small = np.zeros((100, 100, 3), dtype=np.uint8) + np.array((10, 200, 30), dtype=np.uint8)
    big = np.zeros((200, 200, 3), dtype=np.uint8) + np.array((10, 200, 30), dtype=np.uint8)
    a = _png(tmp_path, "a.png", small)
    b = _png(tmp_path, "b.png", big)
    report, _ = visual_diff.compare_images(a, b)
    assert report["compared_size"] == {"width": 200, "height": 200, "scaled": ["a"]}
    assert report["inputs"]["a"]["aspect_ratio"] == 1.0
    assert report["inputs"]["b"]["aspect_ratio"] == 1.0
    assert report["aspect_ratio_match"] is True
    assert report["total"]["mean_diff_pct"] == 0.0


def test_regions_subset_json_and_diff_files(tmp_path, capsys):
    a = _png(tmp_path, "a.png", _solid((5, 5, 5)))
    b = _png(tmp_path, "b.png", _solid((5, 5, 5)))
    out_json = tmp_path / "sub" / "report.json"
    out_png = tmp_path / "sub" / "diff.png"
    code = visual_diff.main(
        [
            str(a),
            str(b),
            "--regions",
            "sidebar,center",
            "--json",
            str(out_json),
            "--diff",
            str(out_png),
        ]
    )
    assert code == 0
    report = json.loads(out_json.read_text(encoding="utf-8"))
    assert list(report["regions"]) == ["sidebar", "center"]
    assert "titlebar" not in report["regions"]
    assert Image.open(out_png).size == SIZE
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["total"]["mean_diff_pct"] == 0.0


def test_max_diff_exit_codes(tmp_path):
    a = _png(tmp_path, "a.png", _solid((255, 0, 0)))
    b = _png(tmp_path, "b.png", _solid((0, 0, 255)))
    assert visual_diff.main([str(a), str(b), "--max-diff", "10"]) == 1
    assert visual_diff.main([str(a), str(b), "--max-diff", "99"]) == 0
    assert visual_diff.main([str(a), str(a)]) == 0


def test_unknown_region_and_missing_file_exit_2(tmp_path, capsys):
    a = _png(tmp_path, "a.png", _solid((1, 2, 3)))
    assert visual_diff.main([str(a), str(a), "--regions", "footer"]) == 2
    assert "footer" in capsys.readouterr().err
    assert visual_diff.main([str(a), str(tmp_path / "fehlt.png")]) == 2
