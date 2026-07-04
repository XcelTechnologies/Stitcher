# SPDX-License-Identifier: MIT
"""Tests for the main window: toolbar wiring, selection editing, dialogs."""

import pytest

from stitcher.app import (
    MainWindow,
    TraceOptionsDialog,
    ExportOptionsDialog,
    WorksheetDialog,
    MetadataDialog,
    _image_filter,
    _app_icon,
)
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


def test_thread_combo_includes_named_catalog(window):
    # the quick palette plus the full named catalogue (well over the 7 house colours)
    assert window.color_combo.count() > 20


def test_pause_checkbox_edits_selection_and_sets_default(window):
    c = window.canvas
    # with no selection, toggling sets the new-object default
    c._set_selected(None)
    window.pause_check.setChecked(True)
    assert c.current_pause_after is True

    # with a selection, it edits that object and the toolbar reflects its state
    s = Stroke(points=[(0, 0), (10, 0)], pause_after=False)
    c.design.strokes.append(s)
    c._set_selected(s)
    assert window.pause_check.isChecked() is False      # populated from the object
    window.pause_check.setChecked(True)
    assert s.pause_after is True                          # applied to the selection


def test_export_options_dialog_settings(window):
    dlg = ExportOptionsDialog(window)
    assert dlg.settings() is None                        # off by default
    dlg.limit_check.setChecked(True)
    dlg.max_stitch.setValue(6.0)
    assert dlg.settings()["max_stitch"] == 60.0          # mm -> embroidery units


def test_metadata_dialog_reads_and_returns_nonblank(window):
    dlg = MetadataDialog(window, {"name": "Logo", "author": "Paul"})
    # existing values are populated
    assert dlg._fields["name"].text() == "Logo"
    # a blank field is omitted from the result
    dlg._fields["author"].setText("   ")
    dlg._fields["comments"].setPlainText("first draft")
    vals = dlg.values()
    assert vals == {"name": "Logo", "comments": "first draft"}


def test_edit_metadata_applies_and_marks_dirty(window):
    window._set_dirty(False)
    import stitcher.app as A
    # simulate the user filling in the dialog and clicking OK
    orig = A.MetadataDialog

    class _Stub:
        def __init__(self, parent, metadata):
            pass

        def exec(self):
            return A.QDialog.Accepted

        def values(self):
            return {"name": "Stubbed"}

    A.MetadataDialog = _Stub
    try:
        window._edit_metadata()
    finally:
        A.MetadataDialog = orig
    assert window.design.metadata == {"name": "Stubbed"}
    assert window._dirty is True


def test_rotate_whole_design_marks_dirty(window):
    c = window.canvas
    c.design.strokes.append(Stroke(points=[(10, 0), (20, 0)]))
    c.design.texts.append(TextItem(text="Hi", x_mm=5, y_mm=5, height_mm=10))
    c._set_selected(None)
    window._set_dirty(False)
    assert c.rotate_objects(90) is True
    assert c.design.texts[0].rotation_deg == 90.0
    assert window._dirty is True


def test_rotate_by_arbitrary_angle(window):
    c = window.canvas
    text = TextItem(text="Hi", x_mm=5, y_mm=5, height_mm=10)
    c.design.texts.append(text)
    c._set_selected(text)
    import stitcher.app as A
    orig = A.QInputDialog.getDouble
    A.QInputDialog.getDouble = staticmethod(lambda *a, **k: (30.0, True))
    try:
        window._rotate_objects()
    finally:
        A.QInputDialog.getDouble = orig
    assert text.rotation_deg == 30.0        # not just 90° steps


def test_transform_selected_object_only(window):
    c = window.canvas
    keep = Stroke(points=[(0, 0), (5, 0)])
    move = Stroke(points=[(10, 0), (20, 0)])
    c.design.strokes.extend([keep, move])
    c._set_selected(move)
    before_keep = list(keep.points)
    before_move = list(move.points)
    c.flip_objects(True)
    assert keep.points == before_keep        # untouched
    assert move.points != before_move        # transformed


def test_make_applique_adds_two_pausing_outlines(window):
    c = window.canvas
    region = Region(color="#2a9d3a", contours=[[(0, 0), (30, 0), (30, 30), (0, 30)]])
    c.design.regions.append(region)
    c._set_selected(region)
    window._make_applique()
    assert len(c.design.strokes) == 2
    assert all(s.pause_after for s in c.design.strokes)
    # both trace the region outline (closed) and sew before the region cover
    assert all(len(s.points) >= 5 for s in c.design.strokes)


def test_make_applique_needs_a_region(window):
    c = window.canvas
    c.design.strokes.append(Stroke(points=[(0, 0), (10, 0)]))
    c._set_selected(c.design.strokes[0])
    import stitcher.app as A
    calls = []
    orig = A.QMessageBox.information
    A.QMessageBox.information = staticmethod(lambda *a, **k: calls.append(a))
    try:
        window._make_applique()
    finally:
        A.QMessageBox.information = orig
    assert calls                              # told the user to pick a region
    assert len(c.design.strokes) == 1         # nothing added


def test_save_seeds_name_from_filename(window, tmp_path):
    window.canvas.design.strokes.append(Stroke(points=[(0, 0), (10, 0)]))
    assert window.design.metadata.get("name") is None
    window._write_project(str(tmp_path / "My Cool Logo.stitch"))
    assert window.design.metadata.get("name") == "My Cool Logo"


def test_save_does_not_overwrite_existing_name(window, tmp_path):
    window.canvas.design.strokes.append(Stroke(points=[(0, 0), (10, 0)]))
    window.design.metadata = {"name": "Kept"}
    window._write_project(str(tmp_path / "Other.stitch"))
    assert window.design.metadata["name"] == "Kept"


def test_worksheet_dialog_lists_colours(window):
    window.canvas.design.strokes.append(Stroke(color="#d1495b", points=[(0, 0), (20, 5)]))
    window.canvas.design.regions.append(
        Region(color="#2a6fd1", contours=[[(0, 30), (20, 30), (20, 50)]], spacing_mm=2.0)
    )
    from stitcher.pattern import design_to_pattern, color_blocks, pattern_stats
    pat = design_to_pattern(window.canvas.design)
    dlg = WorksheetDialog(window, color_blocks(pat), pattern_stats(pat))
    html = dlg._html(color_blocks(pat), pattern_stats(pat))
    assert "#d1495b" in html and "#2a6fd1" in html
    assert "Totals" in html
