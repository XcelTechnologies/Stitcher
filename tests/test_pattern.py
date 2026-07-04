# SPDX-License-Identifier: MIT
"""Tests for stitch generation, fills, and machine-file I/O."""

import math

import pyembroidery as pe
import pytest

from stitcher.model import Design, Region, Stroke, STITCH_BEAN, STITCH_SATIN
from stitcher import pattern as P
from stitcher.pattern import (
    UNITS_PER_MM,
    design_to_pattern,
    export_design,
    import_design,
    pattern_stats,
    pattern_to_segments,
)


# ---- geometry helpers -----------------------------------------------------
def test_resample_polyline_respects_step():
    pts = P._resample_polyline([(0, 0), (10, 0)], 2.0)
    # consecutive points never more than the step apart
    for a, b in zip(pts, pts[1:]):
        assert math.hypot(b[0] - a[0], b[1] - a[1]) <= 2.0 + 1e-9
    assert pts[0] == (0, 0) and pts[-1] == (10, 0)


def test_to_units_scales_and_dedups():
    units = P._to_units([(0.0, 0.0), (0.0, 0.0), (1.0, 2.0)])
    assert units == [(0, 0), (10, 20)]        # x10, duplicates dropped


# ---- stitch types ---------------------------------------------------------
def test_bean_triples_the_segments():
    s = Stroke(points=[(0, 0), (10, 0)], stitch_length_mm=5.0)
    running = len(P._running_run(s))
    bean = len(P._bean_run(s))
    assert bean == running + 2 * (running - 1)   # each segment forward-back-forward


def test_satin_alternates_sides_of_the_spine():
    s = Stroke(points=[(0, 0), (10, 0)], stitch_length_mm=2.0,
               stitch_type=STITCH_SATIN, width_mm=4.0)
    pts = P._satin_run(s)
    ys = [p[1] for p in pts]
    assert max(ys) > 1.5 and min(ys) < -1.5        # zig-zags ~ +/- width/2
    assert any(a * b < 0 for a, b in zip(ys, ys[1:]))  # sign flips


def test_satin_underlay_adds_a_run():
    base = Stroke(points=[(0, 0), (10, 0), (20, 5)], stitch_type=STITCH_SATIN,
                  width_mm=4.0, underlay=False)
    with_u = Stroke(points=[(0, 0), (10, 0), (20, 5)], stitch_type=STITCH_SATIN,
                    width_mm=4.0, underlay=True)
    assert len(P._stroke_runs(with_u)) == len(P._stroke_runs(base)) + 1


# ---- fill -----------------------------------------------------------------
def _square(size=20.0, x=0.0, y=0.0):
    return [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]


def test_fill_runs_stay_within_the_shape():
    runs = P._fill_runs([_square(20)], angle_deg=0.0, spacing_mm=2.0, stitch_length_mm=3.0)
    assert runs
    for run in runs:
        for x, y in run:
            assert -0.01 <= x <= 20.01 and -0.01 <= y <= 20.01


def test_fill_leaves_holes_open():
    # a 40mm square with a 12mm square hole in the middle
    outer = _square(40)
    inner = _square(12, x=14, y=14)
    runs = P._fill_runs([outer, inner], angle_deg=0.0, spacing_mm=1.5, stitch_length_mm=3.0)
    pts = [p for r in runs for p in r]
    # no stitch point should land well inside the hole
    deep = [p for p in pts if 16 < p[0] < 24 and 16 < p[1] < 24]
    assert deep == []


def test_fill_angle_changes_the_result():
    sq = [_square(20)]
    a = P._fill_runs(sq, 0.0, 2.0, 3.0)
    b = P._fill_runs(sq, 90.0, 2.0, 3.0)
    assert a and b and a != b


# ---- assembly, stats, export ---------------------------------------------
def test_design_to_pattern_counts_colours_and_stitches():
    d = Design()
    d.strokes.append(Stroke(color="#111111", points=[(0, 0), (10, 0)]))
    d.strokes.append(Stroke(color="#222222", points=[(0, 5), (10, 5)]))
    d.regions.append(Region(color="#333333", contours=[_square(15)]))
    stats = pattern_stats(design_to_pattern(d))
    assert stats["stitches"] > 0
    # three distinct colours -> two colour changes -> 3 thread blocks
    assert stats["colors"] == 3


def test_design_to_pattern_same_colour_no_extra_change():
    d = Design()
    d.strokes.append(Stroke(color="#222222", points=[(0, 0), (10, 0)]))
    d.strokes.append(Stroke(color="#222222", points=[(0, 5), (10, 5)]))
    # same colour across objects: a trim but no colour change
    assert pattern_stats(design_to_pattern(d))["colors"] == 1


def test_fill_underlay_adds_stitches():
    def count(underlay):
        d = Design()
        d.regions.append(Region(contours=[_square(30)], spacing_mm=2.0, underlay=underlay))
        return pattern_stats(design_to_pattern(d))["stitches"]
    assert count(True) > count(False)


def test_pattern_to_segments_has_stitch_kinds():
    d = Design()
    d.strokes.append(Stroke(points=[(0, 0), (10, 0), (10, 10)]))
    segs = pattern_to_segments(design_to_pattern(d))
    kinds = {s[4] for s in segs}
    assert "stitch" in kinds


def _count_trims(pattern):
    return sum(1 for _x, _y, c in pattern.stitches if (c & pe.COMMAND_MASK) == pe.TRIM)


def test_trim_jump_cuts_long_travels_between_columns():
    # one region of two separated blobs -> two fill columns (runs) within a
    # single object, with a long travel between them
    d = Design()
    d.regions.append(
        Region(contours=[_square(10, x=0), _square(10, x=60)],
               spacing_mm=2.0, underlay=False)
    )

    d.trim_jump_mm = 100.0                 # far enough that nothing is cut
    loose = design_to_pattern(d)
    d.trim_jump_mm = 1.0                    # cut anything but the shortest hops
    tight = design_to_pattern(d)

    # a smaller trim distance means more thread cuts...
    assert _count_trims(tight) > _count_trims(loose)
    # ...and no long connector is drawn in the preview once travels are cut
    tight_jumps = [s for s in pattern_to_segments(tight) if s[4] == "jump"]
    long_jumps = [
        s for s in tight_jumps
        if math.hypot(s[2] - s[0], s[3] - s[1]) > 1.0 * UNITS_PER_MM
    ]
    assert long_jumps == []


@pytest.mark.parametrize("ext", ["dst", "pes", "exp", "jef", "svg"])
def test_export_writes_nonempty_file(tmp_path, ext):
    d = Design()
    d.strokes.append(Stroke(color="#d1495b", points=[(2, 2), (30, 5), (40, 30)]))
    out = tmp_path / f"design.{ext}"
    export_design(d, str(out))
    assert out.exists() and out.stat().st_size > 0


def test_import_roundtrip_positions_on_positive_hoop(tmp_path):
    d = Design()
    d.strokes.append(Stroke(color="#2a6fd1", points=[(-10, -5), (20, 3), (40, 30)]))
    src = tmp_path / "rt.dst"
    export_design(d, str(src))
    imported = import_design(str(src))
    assert imported.strokes
    for s in imported.strokes:
        for x, y in s.points:
            assert x >= 0 and y >= 0
    assert pattern_stats(design_to_pattern(imported))["stitches"] > 0


def test_import_unrecognised_format_raises(tmp_path):
    # an extension pyembroidery has no reader for -> pe.read returns None
    bad = tmp_path / "mystery.zzz"
    bad.write_bytes(b"not a real embroidery file")
    with pytest.raises(ValueError):
        import_design(str(bad))
