# SPDX-License-Identifier: MIT
"""Tests for the main window: toolbar wiring, selection editing, dialogs."""

import pytest

from stitcher.app import MainWindow, TraceOptionsDialog, _image_filter, _app_icon
from stitcher.canvas import TOOL_SELECT, TOOL_STROKE, TOOL_REGION, TOOL_TEXT
from stitcher.model import Region, Stroke, TextItem


@pytest.fixture
def window():
    w = MainWindow()
    w.show()
    w.canvas.resize(500, 500)
    return w


def _visible(actions):
    return all(a.isVisible() for a in actions)


def test_window_has_icon(window):
    assert not window.windowIcon().isNull()


def test_image_filter_lists_svg():
    f = _image_filter()
    assert "*.svg" in f and "*.png" in f


def test_tool_switch_shows_relevant_controls(window):
    window.tool_combo.setCurrentIndex(window.tool_combo.findData(TOOL_TEXT))
    assert window.canvas.tool == TOOL_TEXT
    assert _visible(window._text_widgets) and _visible(window._fill_widgets)

    window.tool_combo.setCurrentIndex(window.tool_combo.findData(TOOL_SELECT))
    assert not _visible(window._stroke_widgets)
    assert not _visible(window._underlay_widgets)


def test_selecting_object_populates_and_edits_live(window):
    c = window.canvas
    text = TextItem(text="Hi", x_mm=20, y_mm=20, height_mm=15, color="#2a6fd1")
    c.design.texts.append(text)

    c._set_selected(text)                        # emits selection_changed
    assert _visible(window._text_widgets)
    assert abs(window.text_height_spin.value() - 15.0) < 1e-6   # populated

    window.text_height_spin.setValue(24.0)       # edit the toolbar
    assert text.height_mm == 24.0                # applied to the selection

    window.color_combo.setCurrentIndex(0)        # palette Black
    assert text.color == "#1a1a1a"


def test_editing_with_no_selection_sets_defaults(window):
    window.canvas._set_selected(None)
    window.length_spin.setValue(4.5)
    assert window.canvas.current_stitch_length == 4.5


def test_stroke_selection_enables_satin_width(window):
    c = window.canvas
    s = Stroke(points=[(0, 0), (10, 0)])
    c.design.strokes.append(s)
    c._set_selected(s)
    i = window.type_combo.findData("satin")
    window.type_combo.setCurrentIndex(i)
    assert s.stitch_type == "satin"
    assert window.width_spin.isEnabled()


def test_deselect_reverts_toolbar_to_tool(window):
    c = window.canvas
    t = TextItem(text="A", x_mm=10, y_mm=10, height_mm=12)
    c.design.texts.append(t)
    c._set_selected(t)
    c._set_selected(None)
    # back to the active tool (Stroke by default)
    assert _visible(window._stroke_widgets)
    assert not _visible(window._text_widgets)


def test_text_edit_request_renames(window):
    c = window.canvas
    t = TextItem(text="Old", x_mm=10, y_mm=10, height_mm=12)
    c.design.texts.append(t)
    c._set_selected(t)

    # patch the input dialog to simulate the user typing a new string
    import stitcher.app as A
    orig = A.QInputDialog.getText
    A.QInputDialog.getText = staticmethod(lambda *a, **k: ("New", True))
    try:
        window._on_text_edit_requested(t)
    finally:
        A.QInputDialog.getText = orig
    assert t.text == "New"


def test_text_edit_clear_deletes(window):
    c = window.canvas
    t = TextItem(text="Bye", x_mm=10, y_mm=10, height_mm=12)
    c.design.texts.append(t)
    c._set_selected(t)

    import stitcher.app as A
    orig = A.QInputDialog.getText
    A.QInputDialog.getText = staticmethod(lambda *a, **k: ("   ", True))
    try:
        window._on_text_edit_requested(t)
    finally:
        A.QInputDialog.getText = orig
    assert t not in c.design.texts
    assert c.selected is None


def test_trace_options_dialog_values(window):
    dlg = TraceOptionsDialog(window, default_width_mm=90.0)
    v = dlg.values()
    assert v["target_width_mm"] == 90.0
    assert set(v) == {"num_colors", "target_width_mm", "angle_deg", "min_area_mm2"}
    dlg.colors.setValue(5)
    dlg.angle.setValue(30.0)
    assert dlg.values()["num_colors"] == 5
    assert dlg.values()["angle_deg"] == 30.0


def test_app_icon_not_null():
    assert not _app_icon().isNull()
