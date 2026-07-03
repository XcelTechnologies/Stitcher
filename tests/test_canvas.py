# SPDX-License-Identifier: MIT
"""Tests for the drawing canvas: hit-testing, selection, move, delete."""

import pytest

from stitcher.canvas import DrawingCanvas, TOOL_SELECT, TOOL_STROKE
from stitcher.model import Design, Region, Stroke, TextItem


@pytest.fixture
def canvas():
    d = Design()
    d.strokes.append(Stroke(color="#d1495b", points=[(10, 10), (40, 10)]))          # h-line
    d.regions.append(Region(color="#2a9d3a", contours=[[(60, 60), (90, 60), (90, 90), (60, 90)]]))
    d.texts.append(TextItem(text="X", x_mm=20, y_mm=40, height_mm=15, color="#2a6fd1"))
    c = DrawingCanvas(d)
    c.resize(400, 400)
    return c


def test_point_in_poly():
    sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert DrawingCanvas._point_in_poly((5, 5), sq)
    assert not DrawingCanvas._point_in_poly((15, 5), sq)


def test_in_contours_even_odd_hole():
    outer = [(0, 0), (10, 0), (10, 10), (0, 10)]
    inner = [(4, 4), (6, 4), (6, 6), (4, 6)]
    assert DrawingCanvas._in_contours((1, 1), [outer, inner])      # in ring
    assert not DrawingCanvas._in_contours((5, 5), [outer, inner])  # in hole


def test_hit_test_finds_each_kind(canvas):
    assert canvas._hit_test(25, 10) is canvas.design.strokes[0]    # on the line
    assert canvas._hit_test(75, 75) is canvas.design.regions[0]    # inside region
    assert canvas._hit_test(200, 200) is None                      # empty space


def test_selection_signal_emitted(canvas):
    seen = []
    canvas.selection_changed.connect(seen.append)
    canvas._set_selected(canvas.design.regions[0])
    canvas._set_selected(canvas.design.regions[0])  # no change -> no second emit
    canvas._set_selected(None)
    assert seen == [canvas.design.regions[0], None]


def test_translate_moves_object(canvas):
    r = canvas.design.regions[0]
    before = list(r.contours[0])
    r.translate(5, -3)
    assert r.contours[0][0] == (before[0][0] + 5, before[0][1] - 3)


def test_delete_selected_removes_and_clears(canvas):
    canvas._set_selected(canvas.design.regions[0])
    canvas.delete_selected()
    assert canvas.design.regions == []
    assert canvas.selected is None


def test_set_tool_clears_selection(canvas):
    canvas._set_selected(canvas.design.strokes[0])
    canvas.set_tool(TOOL_SELECT)
    assert canvas.selected is None


def test_object_bounds(canvas):
    b = canvas._object_bounds(canvas.design.regions[0])
    assert b == (60.0, 60.0, 90.0, 90.0)
    tb = canvas._object_bounds(canvas.design.texts[0])
    assert tb[0] == 20.0 and tb[1] == 40.0 and tb[2] > 20.0 and tb[3] > 40.0
