"""Main application window: drawing canvas + live stitch preview + file I/O."""

from __future__ import annotations

import json
import os
import sys
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QIcon,
    QImageReader,
    QKeySequence,
    QPixmap,
)

# App icon assets live in stitcher/assets/ (bundled into frozen builds).
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _app_icon() -> QIcon:
    """The window / dock / taskbar icon, preferring the crisp SVG."""
    icon = QIcon()
    for name in ("icon.svg", "icon.png"):
        path = os.path.join(ASSETS_DIR, name)
        if os.path.exists(path):
            icon.addFile(path)
    return icon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSpinBox,
    QSplitter,
    QToolBar,
)

from .model import (
    Design,
    Region,
    Stroke,
    TextItem,
    PALETTE,
    STITCH_TYPES,
    STITCH_SATIN,
)
from .canvas import (
    DrawingCanvas,
    TOOL_SELECT,
    TOOL_STROKE,
    TOOL_REGION,
    TOOL_TEXT,
)
from .preview import PreviewWidget
from .imagetrace import trace_image
from .pattern import (
    design_to_pattern,
    export_design,
    import_design,
    pattern_stats,
    SUPPORTED_WRITE_FORMATS,
    SUPPORTED_READ_FORMATS,
)

PROJECT_EXT = ".stitch"
PROJECT_FILTER = "Stitcher project (*.stitch);;All files (*)"
OPEN_FILTER = "Stitcher project (*.stitch *.json);;All files (*)"


def _color_icon(hex_color: str) -> QIcon:
    pix = QPixmap(16, 16)
    pix.fill(QColor(hex_color))
    return QIcon(pix)


def _image_filter() -> str:
    """A file filter covering every image format this Qt build can read."""
    exts = {bytes(f).decode().lower() for f in QImageReader.supportedImageFormats()}
    exts.update({"svg", "svgz"})  # traced via the SVG renderer
    patterns = " ".join(f"*.{e}" for e in sorted(exts))
    return f"Images ({patterns});;All files (*)"


class TraceOptionsDialog(QDialog):
    """Settings gathered before auto-digitizing an image."""

    def __init__(self, parent, default_width_mm: float) -> None:
        super().__init__(parent)
        self.setWindowTitle("Trace image options")
        form = QFormLayout(self)

        self.colors = QSpinBox()
        self.colors.setRange(2, 16)
        self.colors.setValue(6)

        self.width = QDoubleSpinBox()
        self.width.setRange(10.0, 400.0)
        self.width.setSingleStep(5.0)
        self.width.setValue(default_width_mm)
        self.width.setSuffix(" mm")

        self.angle = QDoubleSpinBox()
        self.angle.setRange(0.0, 180.0)
        self.angle.setSingleStep(15.0)
        self.angle.setWrapping(True)
        self.angle.setSuffix(" °")

        self.min_area = QDoubleSpinBox()
        self.min_area.setRange(0.0, 200.0)
        self.min_area.setSingleStep(0.5)
        self.min_area.setValue(3.0)
        self.min_area.setSuffix(" mm²")

        form.addRow("Thread colours:", self.colors)
        form.addRow("Target width:", self.width)
        form.addRow("Fill angle:", self.angle)
        form.addRow("Min region size:", self.min_area)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict:
        return {
            "num_colors": self.colors.value(),
            "target_width_mm": self.width.value(),
            "angle_deg": self.angle.value(),
            "min_area_mm2": self.min_area.value(),
        }


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.resize(1100, 640)
        self.setWindowIcon(_app_icon())

        self.design = Design()
        self.project_path: Optional[str] = None
        self._dirty = False
        self._custom_index = -1  # combo slot reused for a custom-picked colour

        self.canvas = DrawingCanvas(self.design)
        self.preview = PreviewWidget()

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.canvas)
        splitter.addWidget(self.preview)
        splitter.setSizes([550, 550])
        self.setCentralWidget(splitter)

        self._build_actions()
        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()

        self.canvas.design_changed.connect(self._on_design_changed)
        self.canvas.text_requested.connect(self._on_text_requested)
        self.canvas.text_edit_requested.connect(self._on_text_edit_requested)
        self.canvas.selection_changed.connect(self._on_selection_changed)
        self._update_title()
        self._refresh()

    # ---- UI construction ----------------------------------------------------
    def _build_actions(self) -> None:
        self.act_new = QAction("&New", self, shortcut=QKeySequence.New)
        self.act_new.triggered.connect(self._new_project)

        self.act_open = QAction("&Open…", self, shortcut=QKeySequence.Open)
        self.act_open.triggered.connect(self._open_project)

        self.act_save = QAction("&Save", self, shortcut=QKeySequence.Save)
        self.act_save.triggered.connect(self._save)

        self.act_save_as = QAction("Save &As…", self, shortcut=QKeySequence.SaveAs)
        self.act_save_as.triggered.connect(self._save_as)

        self.act_import = QAction("&Import…", self, shortcut="Ctrl+I")
        self.act_import.triggered.connect(self._import)

        self.act_trace = QAction("&Trace image…", self, shortcut="Ctrl+T")
        self.act_trace.triggered.connect(self._trace_image)

        self.act_export = QAction("&Export…", self, shortcut="Ctrl+E")
        self.act_export.triggered.connect(self._export)

        self.act_quit = QAction("&Quit", self, shortcut=QKeySequence.Quit)
        self.act_quit.triggered.connect(self.close)

        self.act_undo = QAction("&Undo stroke", self, shortcut=QKeySequence.Undo)
        self.act_undo.triggered.connect(self.canvas.undo_last_stroke)

        self.act_clear = QAction("&Clear", self)
        self.act_clear.triggered.connect(self._confirm_clear)

        self.act_about = QAction("&About Stitcher", self)
        self.act_about.triggered.connect(self._about)

    def _build_menu(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("&File")
        file_menu.addAction(self.act_new)
        file_menu.addAction(self.act_open)
        file_menu.addSeparator()
        file_menu.addAction(self.act_save)
        file_menu.addAction(self.act_save_as)
        file_menu.addSeparator()
        file_menu.addAction(self.act_import)
        file_menu.addAction(self.act_trace)
        file_menu.addAction(self.act_export)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        edit_menu = bar.addMenu("&Edit")
        edit_menu.addAction(self.act_undo)
        edit_menu.addAction(self.act_clear)

        help_menu = bar.addMenu("&Help")
        help_menu.addAction(self.act_about)

    def _build_toolbar(self) -> None:
        tb = QToolBar("Tools")
        tb.setMovable(False)
        self.addToolBar(tb)

        # tool: what a press-drag-release (or click) creates
        tb.addWidget(QLabel(" Tool: "))
        self.tool_combo = QComboBox()
        self.tool_combo.addItem("Select / move", TOOL_SELECT)
        self.tool_combo.addItem("Stroke", TOOL_STROKE)
        self.tool_combo.addItem("Fill region", TOOL_REGION)
        self.tool_combo.addItem("Text", TOOL_TEXT)
        self.tool_combo.setCurrentIndex(1)  # start on Stroke
        self.tool_combo.currentIndexChanged.connect(self._on_tool_changed)
        tb.addWidget(self.tool_combo)

        tb.addSeparator()

        # colour palette
        tb.addWidget(QLabel(" Thread: "))
        self.color_combo = QComboBox()
        for name, hex_color in PALETTE:
            self.color_combo.addItem(_color_icon(hex_color), name, hex_color)
        self.color_combo.currentIndexChanged.connect(self._on_color_changed)
        tb.addWidget(self.color_combo)

        custom = QAction("Custom…", self)
        custom.triggered.connect(self._pick_custom_color)
        tb.addAction(custom)

        tb.addSeparator()

        # stitch length (all tools)
        tb.addWidget(QLabel(" Stitch mm: "))
        self.length_spin = QDoubleSpinBox()
        self.length_spin.setRange(0.5, 12.0)
        self.length_spin.setSingleStep(0.5)
        self.length_spin.setValue(self.canvas.current_stitch_length)
        self.length_spin.valueChanged.connect(self._on_length_changed)
        tb.addWidget(self.length_spin)

        # ---- stroke-only controls ------------------------------------------
        self._stroke_widgets = []
        self._stroke_widgets.append(tb.addSeparator())
        self._stroke_widgets.append(tb.addWidget(QLabel(" Stitch: ")))
        self.type_combo = QComboBox()
        for value, label in STITCH_TYPES:
            self.type_combo.addItem(label, value)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        self._stroke_widgets.append(tb.addWidget(self.type_combo))

        self._stroke_widgets.append(tb.addWidget(QLabel(" Width mm: ")))
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(0.5, 12.0)
        self.width_spin.setSingleStep(0.5)
        self.width_spin.setValue(self.canvas.current_width_mm)
        self.width_spin.valueChanged.connect(self._on_width_changed)
        self._stroke_widgets.append(tb.addWidget(self.width_spin))

        # ---- fill controls (region + text) ---------------------------------
        self._fill_widgets = []
        self._fill_widgets.append(tb.addSeparator())
        self._fill_widgets.append(tb.addWidget(QLabel(" Row mm: ")))
        self.spacing_spin = QDoubleSpinBox()
        self.spacing_spin.setRange(0.3, 6.0)
        self.spacing_spin.setSingleStep(0.1)
        self.spacing_spin.setValue(self.canvas.current_spacing_mm)
        self.spacing_spin.valueChanged.connect(self._on_spacing_changed)
        self._fill_widgets.append(tb.addWidget(self.spacing_spin))

        self._fill_widgets.append(tb.addWidget(QLabel(" Angle°: ")))
        self.angle_spin = QDoubleSpinBox()
        self.angle_spin.setRange(0.0, 180.0)
        self.angle_spin.setSingleStep(15.0)
        self.angle_spin.setWrapping(True)
        self.angle_spin.setValue(self.canvas.current_angle_deg)
        self.angle_spin.valueChanged.connect(self._on_angle_changed)
        self._fill_widgets.append(tb.addWidget(self.angle_spin))

        # ---- text-only controls --------------------------------------------
        self._text_widgets = []
        self._text_widgets.append(tb.addSeparator())
        self._text_widgets.append(tb.addWidget(QLabel(" Font: ")))
        self.font_combo = QFontComboBox()
        self.font_combo.currentFontChanged.connect(self._on_font_changed)
        self._text_widgets.append(tb.addWidget(self.font_combo))

        self._text_widgets.append(tb.addWidget(QLabel(" Height mm: ")))
        self.text_height_spin = QDoubleSpinBox()
        self.text_height_spin.setRange(3.0, 80.0)
        self.text_height_spin.setSingleStep(1.0)
        self.text_height_spin.setValue(self.canvas.current_text_height_mm)
        self.text_height_spin.valueChanged.connect(self._on_text_height_changed)
        self._text_widgets.append(tb.addWidget(self.text_height_spin))

        # ---- underlay (satin + fills) --------------------------------------
        self._underlay_widgets = [tb.addSeparator()]
        self.underlay_check = QCheckBox("Underlay")
        self.underlay_check.setToolTip("Sew a stabilizing pass under satin and fills")
        self.underlay_check.setChecked(self.canvas.current_underlay)
        self.underlay_check.toggled.connect(self._on_underlay_changed)
        self._underlay_widgets.append(tb.addWidget(self.underlay_check))

        tb.addSeparator()
        tb.addAction(self.act_undo)
        tb.addAction(self.act_clear)

        # sync initial selections to the canvas
        self._on_color_changed(0)
        self.canvas.set_font_family(self.font_combo.currentFont().family())
        self._update_tool_widgets(TOOL_STROKE)

    def _build_statusbar(self) -> None:
        self.stats_label = QLabel()
        self.statusBar().addWidget(self.stats_label)

    # ---- dirty / title bookkeeping ------------------------------------------
    def _set_dirty(self, value: bool) -> None:
        self._dirty = value
        self.setWindowModified(value)

    def _update_title(self) -> None:
        name = os.path.basename(self.project_path) if self.project_path else "Untitled"
        self.setWindowTitle(f"{name}[*] — Stitcher")

    def _set_design(self, design: Design) -> None:
        """Single point of truth for swapping the active design (New/Open)."""
        self.design = design
        self.canvas.set_design(design)

    # ---- slots --------------------------------------------------------------
    def _on_design_changed(self) -> None:
        self._set_dirty(True)
        self._refresh()

    # ---- toolbar controls: edit the selected object, else set new-object defaults
    def _after_edit(self) -> None:
        """Repaint, mark dirty, and rebuild the preview after editing a selection."""
        self.canvas.update()
        self._set_dirty(True)
        self._refresh()

    def _on_color_changed(self, index: int) -> None:
        hex_color = self.color_combo.itemData(index)
        if not hex_color:
            return
        if self.canvas.selected is not None:
            self.canvas.selected.color = hex_color
            self._after_edit()
        else:
            self.canvas.set_color(hex_color)

    def _on_length_changed(self, value: float) -> None:
        if self.canvas.selected is not None:
            self.canvas.selected.stitch_length_mm = value
            self._after_edit()
        else:
            self.canvas.set_stitch_length(value)

    def _on_width_changed(self, value: float) -> None:
        if isinstance(self.canvas.selected, Stroke):
            self.canvas.selected.width_mm = value
            self._after_edit()
        else:
            self.canvas.set_width(value)

    def _on_spacing_changed(self, value: float) -> None:
        if isinstance(self.canvas.selected, (Region, TextItem)):
            self.canvas.selected.spacing_mm = value
            self._after_edit()
        else:
            self.canvas.set_spacing(value)

    def _on_angle_changed(self, value: float) -> None:
        if isinstance(self.canvas.selected, (Region, TextItem)):
            self.canvas.selected.angle_deg = value
            self._after_edit()
        else:
            self.canvas.set_angle(value)

    def _on_font_changed(self, font: QFont) -> None:
        if isinstance(self.canvas.selected, TextItem):
            self.canvas.selected.font_family = font.family()
            self._after_edit()
        else:
            self.canvas.set_font_family(font.family())

    def _on_text_height_changed(self, value: float) -> None:
        if isinstance(self.canvas.selected, TextItem):
            self.canvas.selected.height_mm = value
            self._after_edit()
        else:
            self.canvas.set_text_height(value)

    def _on_underlay_changed(self, on: bool) -> None:
        if self.canvas.selected is not None:
            self.canvas.selected.underlay = on
            self._after_edit()
        else:
            self.canvas.set_underlay(on)

    def _on_type_changed(self, index: int) -> None:
        stitch_type = self.type_combo.itemData(index)
        if isinstance(self.canvas.selected, Stroke):
            self.canvas.selected.stitch_type = stitch_type
            self._after_edit()
        else:
            self.canvas.set_stitch_type(stitch_type)
        self.width_spin.setEnabled(stitch_type == STITCH_SATIN)  # satin uses width

    def _on_tool_changed(self, index: int) -> None:
        tool = self.tool_combo.itemData(index)
        self.canvas.set_tool(tool)
        self._update_tool_widgets(tool)

    def _update_tool_widgets(self, tool: str) -> None:
        """Show only the controls relevant to the active tool (or selection kind)."""
        for w in self._stroke_widgets:
            w.setVisible(tool == TOOL_STROKE)
        for w in self._fill_widgets:
            w.setVisible(tool in (TOOL_REGION, TOOL_TEXT))
        for w in self._text_widgets:
            w.setVisible(tool == TOOL_TEXT)
        for w in self._underlay_widgets:
            w.setVisible(tool != TOOL_SELECT)   # underlay applies to satin + fills
        if tool == TOOL_STROKE:
            self.width_spin.setEnabled(self.type_combo.currentData() == STITCH_SATIN)

    # ---- selection -> contextual toolbar ------------------------------------
    def _on_selection_changed(self, obj) -> None:
        """When an object is selected, show and populate its editing controls."""
        if obj is None:
            self._update_tool_widgets(self.canvas.tool)
            return
        if isinstance(obj, Stroke):
            kind = TOOL_STROKE
        elif isinstance(obj, Region):
            kind = TOOL_REGION
        else:
            kind = TOOL_TEXT
        self._sync_controls_to(obj)
        self._update_tool_widgets(kind)

    def _sync_controls_to(self, obj) -> None:
        """Load the selected object's properties into the toolbar (no re-edit)."""
        widgets = [
            self.color_combo, self.length_spin, self.type_combo, self.width_spin,
            self.spacing_spin, self.angle_spin, self.font_combo,
            self.text_height_spin, self.underlay_check,
        ]
        for w in widgets:
            w.blockSignals(True)
        try:
            self._set_color_combo(obj.color)
            self.length_spin.setValue(obj.stitch_length_mm)
            if isinstance(obj, Stroke):
                i = self.type_combo.findData(obj.stitch_type)
                if i >= 0:
                    self.type_combo.setCurrentIndex(i)
                self.width_spin.setValue(obj.width_mm)
                self.width_spin.setEnabled(obj.stitch_type == STITCH_SATIN)
            if isinstance(obj, (Region, TextItem)):
                self.spacing_spin.setValue(obj.spacing_mm)
                self.angle_spin.setValue(obj.angle_deg)
            if isinstance(obj, TextItem):
                self.font_combo.setCurrentFont(QFont(obj.font_family))
                self.text_height_spin.setValue(obj.height_mm)
            self.underlay_check.setChecked(getattr(obj, "underlay", True))
        finally:
            for w in widgets:
                w.blockSignals(False)

    def _set_color_combo(self, hex_color: str) -> None:
        """Select the palette entry matching hex_color, or park it in the custom slot."""
        target = hex_color.lower()
        for i in range(self.color_combo.count()):
            data = self.color_combo.itemData(i)
            if data and data.lower() == target:
                self.color_combo.setCurrentIndex(i)
                return
        label = f"Custom ({hex_color})"
        if self._custom_index < 0:
            self.color_combo.addItem(_color_icon(hex_color), label, hex_color)
            self._custom_index = self.color_combo.count() - 1
        else:
            self.color_combo.setItemIcon(self._custom_index, _color_icon(hex_color))
            self.color_combo.setItemText(self._custom_index, label)
            self.color_combo.setItemData(self._custom_index, hex_color)
        self.color_combo.setCurrentIndex(self._custom_index)

    def _on_text_requested(self, x_mm: float, y_mm: float) -> None:
        text, ok = QInputDialog.getText(self, "Add text", "Text to stitch:")
        if ok and text.strip():
            self.canvas.add_text(x_mm, y_mm, text)

    def _on_text_edit_requested(self, item: TextItem) -> None:
        text, ok = QInputDialog.getText(
            self, "Edit text", "Text to stitch:", text=item.text
        )
        if not ok:
            return
        if text.strip():
            item.text = text
            self._after_edit()
        else:  # cleared -> remove the text object
            self.canvas.delete_selected()

    def _pick_custom_color(self) -> None:
        seed = self.canvas.selected.color if self.canvas.selected else self.canvas.current_color
        color = QColorDialog.getColor(QColor(seed), self, "Pick thread colour")
        if not color.isValid():
            return
        hex_color = color.name()
        label = f"Custom ({hex_color})"
        if self._custom_index < 0:
            self.color_combo.addItem(_color_icon(hex_color), label, hex_color)
            self._custom_index = self.color_combo.count() - 1
        else:
            self.color_combo.setItemIcon(self._custom_index, _color_icon(hex_color))
            self.color_combo.setItemText(self._custom_index, label)
            self.color_combo.setItemData(self._custom_index, hex_color)
        self.color_combo.setCurrentIndex(self._custom_index)

    def _confirm_clear(self) -> None:
        if self.design.is_empty():
            return
        if QMessageBox.question(self, "Clear", "Remove everything?") == QMessageBox.Yes:
            self.canvas.clear()

    def _about(self) -> None:
        QMessageBox.about(
            self,
            "About Stitcher",
            "Stitcher — a small embroidery designer.\n\n"
            "Draw freehand strokes and export machine files via pyembroidery.",
        )

    def _refresh(self) -> None:
        if self.design.has_content():
            pattern = design_to_pattern(self.design)  # build once, reuse for stats
            self.preview.set_pattern(pattern)
            stats = pattern_stats(pattern)
            self.stats_label.setText(
                f"  Stitches: {stats['stitches']}   "
                f"Colours: {stats['colors']}   "
                f"Size: {stats['width_mm']:.1f} × {stats['height_mm']:.1f} mm"
            )
        else:
            self.preview.set_pattern(None)
            self.stats_label.setText(
                "  Pick a tool and draw on the hoop (press–drag for strokes/regions, "
                "click for text)."
            )

    # ---- unsaved-changes guard ----------------------------------------------
    def _maybe_save(self) -> bool:
        """Ask before discarding unsaved work. Return True if it's safe to proceed."""
        if not self._dirty:
            return True
        resp = QMessageBox.warning(
            self,
            "Unsaved changes",
            "Save changes to the current design?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        )
        if resp == QMessageBox.Save:
            return self._save()
        return resp == QMessageBox.Discard

    def closeEvent(self, event) -> None:
        if self._maybe_save():
            event.accept()
        else:
            event.ignore()

    # ---- project I/O --------------------------------------------------------
    def _new_project(self) -> None:
        if not self._maybe_save():
            return
        self._set_design(Design())
        self.project_path = None
        self._set_dirty(False)
        self._update_title()
        self._refresh()

    def _open_project(self) -> None:
        if not self._maybe_save():
            return
        filename, _ = QFileDialog.getOpenFileName(self, "Open project", "", OPEN_FILTER)
        if not filename:
            return
        try:
            with open(filename, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            design = Design.from_dict(data)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Open failed", f"Could not read project:\n{exc}")
            return
        self._set_design(design)
        self.project_path = filename
        self._set_dirty(False)
        self._update_title()
        self._refresh()

    def _save(self) -> bool:
        if not self.project_path:
            return self._save_as()
        return self._write_project(self.project_path)

    def _save_as(self) -> bool:
        start = self.project_path or f"design{PROJECT_EXT}"
        filename, _ = QFileDialog.getSaveFileName(self, "Save project", start, PROJECT_FILTER)
        if not filename:
            return False
        if not filename.lower().endswith(PROJECT_EXT):
            filename += PROJECT_EXT
        return self._write_project(filename)

    def _write_project(self, filename: str) -> bool:
        try:
            with open(filename, "w", encoding="utf-8") as fh:
                json.dump(self.design.to_dict(), fh, indent=2)
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", f"Could not save project:\n{exc}")
            return False
        self.project_path = filename
        self._set_dirty(False)
        self._update_title()
        self.statusBar().showMessage(f"Saved {os.path.basename(filename)}", 4000)
        return True

    # ---- import -------------------------------------------------------------
    def _import(self) -> None:
        if not self._maybe_save():
            return
        exts = " ".join(f"*.{e}" for e, _label in SUPPORTED_READ_FORMATS)
        filters = f"Embroidery files ({exts});;All files (*)"
        filename, _ = QFileDialog.getOpenFileName(
            self, "Import embroidery file", "", filters
        )
        if not filename:
            return
        try:
            design = import_design(filename)
        except Exception as exc:  # pyembroidery raises plain exceptions
            QMessageBox.critical(self, "Import failed", f"Could not read file:\n{exc}")
            return
        if not design.has_content():
            QMessageBox.information(
                self, "Nothing imported", "No stitches were found in that file."
            )
            return
        self._set_design(design)
        self.project_path = None  # imported art isn't a .stitch project yet
        self._set_dirty(True)
        self._update_title()
        self._refresh()
        self.statusBar().showMessage(
            f"Imported {os.path.basename(filename)} as editable strokes", 5000
        )

    # ---- trace image --------------------------------------------------------
    def _trace_image(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Trace image", "", _image_filter()
        )
        if not filename:
            return
        dialog = TraceOptionsDialog(
            self, default_width_mm=max(10.0, self.design.hoop_width_mm - 10.0)
        )
        if dialog.exec() != QDialog.Accepted:
            return
        opts = dialog.values()

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            regions = trace_image(
                filename,
                hoop_w_mm=self.design.hoop_width_mm,
                hoop_h_mm=self.design.hoop_height_mm,
                spacing_mm=self.canvas.current_spacing_mm,
                stitch_length_mm=self.canvas.current_stitch_length,
                underlay=self.canvas.current_underlay,
                **opts,
            )
        except Exception as exc:  # QImage / numpy raise plain exceptions
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Trace failed", f"Could not trace image:\n{exc}")
            return
        QApplication.restoreOverrideCursor()

        if not regions:
            QMessageBox.information(
                self, "Nothing traced", "No fillable colour areas were found."
            )
            return
        self.design.regions.extend(regions)
        self._set_dirty(True)
        self.canvas.update()
        self._refresh()
        self.statusBar().showMessage(
            f"Traced {len(regions)} colour region(s) from "
            f"{os.path.basename(filename)} — edit or delete them with the Select tool",
            6000,
        )

    # ---- export -------------------------------------------------------------
    def _export(self) -> None:
        if not self.design.has_content():
            QMessageBox.information(self, "Nothing to export", "Draw something first.")
            return

        filters = ";;".join(label for _ext, label in SUPPORTED_WRITE_FORMATS)
        filename, selected = QFileDialog.getSaveFileName(
            self, "Export embroidery file", "design.dst", filters
        )
        if not filename:
            return

        # ensure the chosen extension is present
        ext = next(
            (e for e, label in SUPPORTED_WRITE_FORMATS if label == selected),
            SUPPORTED_WRITE_FORMATS[0][0],
        )
        if not os.path.splitext(filename)[1]:
            filename = f"{filename}.{ext}"

        try:
            export_design(self.design, filename)
        except Exception as exc:  # pyembroidery raises plain exceptions
            QMessageBox.critical(self, "Export failed", f"{exc}")
            return
        self.statusBar().showMessage(f"Exported {os.path.basename(filename)}", 5000)


def run() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Stitcher")
    app.setWindowIcon(_app_icon())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
