# SPDX-License-Identifier: MIT
"""Tests for the pure data model (no Qt needed)."""

import pytest

from stitcher.model import (
    Design,
    Region,
    Stroke,
    TextItem,
    STITCH_BEAN,
    STITCH_SATIN,
    STITCH_RUNNING,
    DEFAULT_SATIN_WIDTH_MM,
)


# ---- Stroke ---------------------------------------------------------------
def test_stroke_defaults():
    s = Stroke()
    assert s.stitch_type == STITCH_RUNNING
    assert s.underlay is True
    assert s.width_mm == DEFAULT_SATIN_WIDTH_MM
    assert not s.is_drawable()          # no points
    s.add_point(0, 0)
    s.add_point(1, 1)
    assert s.is_drawable()


def test_stroke_translate():
    s = Stroke(points=[(1.0, 2.0), (3.0, 4.0)])
    s.translate(10, -1)
    assert s.points == [(11.0, 1.0), (13.0, 3.0)]


def test_stroke_roundtrip_preserves_all_fields():
    s = Stroke(color="#abcdef", stitch_length_mm=2.5, points=[(1, 2), (3, 4)],
               stitch_type=STITCH_SATIN, width_mm=3.5, underlay=False,
               pause_after=True)
    back = Stroke.from_dict(s.to_dict())
    assert back == s


def test_pause_after_defaults_off_and_roundtrips():
    # default is off for every object kind, and survives a save/load
    assert Stroke().pause_after is False
    assert Region().pause_after is False
    assert TextItem().pause_after is False
    r = Region(contours=[[(0, 0), (5, 0), (5, 5)]], pause_after=True)
    assert Region.from_dict(r.to_dict()).pause_after is True
    t = TextItem(text="Hi", pause_after=True)
    assert TextItem.from_dict(t.to_dict()).pause_after is True
    # old files without the key load with it off
    assert Stroke.from_dict({"points": [[0, 0], [1, 1]]}).pause_after is False


# ---- Region (multi-contour) ----------------------------------------------
def test_region_points_is_primary_contour():
    r = Region()
    r.add_point(0, 0)
    r.add_point(5, 0)
    assert r.points == [(0.0, 0.0), (5.0, 0.0)]   # points == contours[0]
    assert r.contours[0] == r.points


def test_region_is_drawable_needs_three_points():
    r = Region()
    r.add_point(0, 0)
    r.add_point(1, 0)
    assert not r.is_drawable()
    r.add_point(1, 1)
    assert r.is_drawable()


def test_region_translate_moves_all_contours():
    r = Region(contours=[[(0, 0), (2, 0), (2, 2)], [(0.5, 0.5), (1, 0.5), (1, 1)]])
    r.translate(1, 2)
    assert r.contours[0][0] == (1.0, 2.0)
    assert r.contours[1][0] == (1.5, 2.5)
    assert r.all_points()[0] == (1.0, 2.0)


def test_region_roundtrip_contours():
    r = Region(color="#123456", contours=[[(0, 0), (1, 0), (1, 1)], [(2, 2), (3, 2), (3, 3)]],
               spacing_mm=1.1, angle_deg=30.0, underlay=False)
    assert Region.from_dict(r.to_dict()) == r


def test_region_legacy_points_upgrades_to_contours():
    r = Region.from_dict({"color": "#111111", "points": [[0, 0], [10, 0], [10, 10]]})
    assert r.contours == [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]]
    assert r.is_drawable()


# ---- TextItem -------------------------------------------------------------
def test_text_is_drawable_requires_nonblank():
    assert not TextItem(text="   ").is_drawable()
    assert TextItem(text="Hi").is_drawable()


def test_text_translate_and_roundtrip():
    t = TextItem(text="Ab", x_mm=5, y_mm=6, height_mm=12, font_family="Arial",
                 color="#0000ff", spacing_mm=1.0, angle_deg=15.0, underlay=False)
    t.translate(2, 3)
    assert (t.x_mm, t.y_mm) == (7.0, 9.0)
    assert TextItem.from_dict(t.to_dict()) == t


# ---- Design ---------------------------------------------------------------
def test_design_queries_and_clear():
    d = Design()
    assert d.is_empty() and not d.has_content()
    d.strokes.append(Stroke(points=[(0, 0), (1, 1)]))
    d.strokes.append(Stroke(points=[(0, 0)]))          # not drawable
    d.regions.append(Region(contours=[[(0, 0), (1, 0), (1, 1)]]))
    d.texts.append(TextItem(text="X", height_mm=5))
    assert d.has_content()
    assert len(d.drawable_strokes()) == 1
    assert len(d.drawable_regions()) == 1
    assert len(d.drawable_texts()) == 1
    d.clear()
    assert d.is_empty()


def test_design_full_roundtrip():
    d = Design(hoop_width_mm=120, hoop_height_mm=80)
    d.strokes.append(Stroke(color="#d1495b", points=[(1, 2), (3, 4)], stitch_type=STITCH_BEAN))
    d.regions.append(Region(color="#2a9d3a", contours=[[(0, 0), (5, 0), (5, 5)]]))
    d.texts.append(TextItem(text="Hi", x_mm=1, y_mm=1, height_mm=10))
    assert Design.from_dict(d.to_dict()).to_dict() == d.to_dict()


def test_design_from_minimal_dict_backward_compat():
    # old files had no regions/texts keys at all
    d = Design.from_dict({"strokes": [{"points": [[0, 0], [1, 1]]}]})
    assert len(d.strokes) == 1
    assert d.regions == [] and d.texts == []
    assert d.hoop_width_mm > 0


def test_design_trim_jump_roundtrips_and_defaults():
    d = Design()
    d.trim_jump_mm = 3.5
    assert Design.from_dict(d.to_dict()).trim_jump_mm == 3.5
    # old files without the key fall back to the default (1 mm)
    assert Design.from_dict({}).trim_jump_mm == 1.0


def test_stroke_rotate_scale_flip():
    s = Stroke(points=[(10, 0), (0, 0)])
    s.rotate(90, 0, 0)
    assert s.points[0][0] == pytest.approx(0.0) and s.points[0][1] == pytest.approx(10.0)
    s2 = Stroke(points=[(0, 0), (10, 10)])
    s2.scale(2.0, 0, 0)
    assert s2.points[1] == (20.0, 20.0)
    s3 = Stroke(points=[(2, 3)])
    s3.flip_h(0)
    s3.flip_v(0)
    assert s3.points[0] == (-2, -3)


def test_region_transforms_all_contours():
    r = Region(contours=[[(0, 0), (10, 0), (10, 10)], [(2, 2), (4, 2), (4, 4)]])
    r.scale(2.0, 0, 0)
    assert r.contours[0][1] == (20.0, 0.0)
    assert r.contours[1][1] == (8.0, 4.0)


def test_text_rotation_field_and_transform_roundtrip():
    t = TextItem(text="Hi", x_mm=0, y_mm=0, height_mm=10)
    assert t.rotation_deg == 0.0
    t.rotate(90, 0, 0, box_w=20, box_h=10)
    assert t.rotation_deg == 90.0
    assert TextItem.from_dict(t.to_dict()).rotation_deg == 90.0
    # a horizontal flip negates the spin
    t.flip_h(0, box_w=20)
    assert t.rotation_deg == pytest.approx(270.0)


def test_design_metadata_roundtrips_and_drops_blanks():
    d = Design()
    assert d.metadata == {}                      # empty by default
    d.metadata = {"name": "Logo", "author": "Paul", "comments": ""}
    back = Design.from_dict(d.to_dict())
    # non-empty fields survive; blank ones are dropped
    assert back.metadata == {"name": "Logo", "author": "Paul"}
    # old files without the key load with empty metadata
    assert Design.from_dict({}).metadata == {}
