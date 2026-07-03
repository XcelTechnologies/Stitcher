"""Freehand drawing canvas.

Tools:

* **Select** — click an object to select it, drag to move it, press Delete to
  remove it.
* **Stroke** — press–drag–release draws one continuous needle run (running,
  bean or satin, per the toolbar).
* **Region** — press–drag–release traces a closed outline that gets filled.
* **Text** — click to place lettering (the window asks for the string).

Coordinates are stored in millimetres inside a fixed hoop area and mapped to
pixels only for display.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple, Union

from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QBrush, QPolygonF
from PySide6.QtWidgets import QWidget

from .model import (
    Design,
    Region,
    Stroke,
    TextItem,
    DEFAULT_STITCH_LENGTH_MM,
    DEFAULT_SATIN_WIDTH_MM,
    DEFAULT_FILL_SPACING_MM,
    DEFAULT_FILL_ANGLE_DEG,
    DEFAULT_TEXT_HEIGHT_MM,
    DEFAULT_FONT_FAMILY,
    STITCH_RUNNING,
)
from .text import text_to_contours, text_size_mm

MIN_POINT_SPACING_MM = 0.8  # don't record points closer than this while drawing
HIT_TOLERANCE_MM = 2.5      # how close a click must be to select a line

TOOL_SELECT = "select"
TOOL_STROKE = "stroke"
TOOL_REGION = "region"
TOOL_TEXT = "text"

Point = Tuple[float, float]
Selectable = Union[Stroke, Region, TextItem]


class DrawingCanvas(QWidget):
    design_changed = Signal()
    text_requested = Signal(float, float)   # (x_mm, y_mm) where the user clicked
    selection_changed = Signal(object)      # the selected object, or None
    text_edit_requested = Signal(object)    # a TextItem to re-edit (double-clicked)

    def __init__(self, design: Design, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.design = design

        self.tool = TOOL_STROKE
        self.current_color = "#1a1a1a"
        self.current_stitch_length = DEFAULT_STITCH_LENGTH_MM
        self.current_stitch_type = STITCH_RUNNING
        self.current_width_mm = DEFAULT_SATIN_WIDTH_MM
        self.current_spacing_mm = DEFAULT_FILL_SPACING_MM
        self.current_angle_deg = DEFAULT_FILL_ANGLE_DEG
        self.current_text_height_mm = DEFAULT_TEXT_HEIGHT_MM
        self.current_font_family = DEFAULT_FONT_FAMILY
        self.current_underlay = True

        self._active: Optional[Union[Stroke, Region]] = None
        self.selected: Optional[Selectable] = None
        self._drag_last: Optional[Point] = None
        self._moved = False

        self.setMinimumSize(360, 360)
        self.setMouseTracking(False)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.CrossCursor)

    # ---- coordinate mapping -------------------------------------------------
    def _fit(self):
        margin = 16
        w = self.width() - 2 * margin
        h = self.height() - 2 * margin
        scale = min(w / self.design.hoop_width_mm, h / self.design.hoop_height_mm)
        draw_w = self.design.hoop_width_mm * scale
        draw_h = self.design.hoop_height_mm * scale
        ox = (self.width() - draw_w) / 2
        oy = (self.height() - draw_h) / 2
        return scale, ox, oy

    def _mm_to_px(self, x_mm: float, y_mm: float) -> QPointF:
        scale, ox, oy = self._fit()
        return QPointF(ox + x_mm * scale, oy + y_mm * scale)

    def _px_to_mm(self, x_px: float, y_px: float):
        scale, ox, oy = self._fit()
        x_mm = (x_px - ox) / scale
        y_mm = (y_px - oy) / scale
        x_mm = max(0.0, min(self.design.hoop_width_mm, x_mm))
        y_mm = max(0.0, min(self.design.hoop_height_mm, y_mm))
        return x_mm, y_mm

    # ---- public API ---------------------------------------------------------
    def set_design(self, design: Design) -> None:
        """Swap in a different design (e.g. after New/Open) and reset drawing state."""
        self.design = design
        self._active = None
        self._drag_last = None
        self._set_selected(None)
        self.update()

    def set_tool(self, tool: str) -> None:
        self.tool = tool
        self._active = None
        self._drag_last = None
        self._set_selected(None)
        self.setCursor(Qt.ArrowCursor if tool == TOOL_SELECT else Qt.CrossCursor)
        self.update()

    def _set_selected(self, obj: Optional[Selectable]) -> None:
        """Change the selection and notify listeners (only on an actual change)."""
        if obj is not self.selected:
            self.selected = obj
            self.selection_changed.emit(obj)

    def set_color(self, hex_color: str) -> None:
        self.current_color = hex_color

    def set_stitch_length(self, mm: float) -> None:
        self.current_stitch_length = mm

    def set_stitch_type(self, stitch_type: str) -> None:
        self.current_stitch_type = stitch_type

    def set_width(self, mm: float) -> None:
        self.current_width_mm = mm

    def set_spacing(self, mm: float) -> None:
        self.current_spacing_mm = mm

    def set_angle(self, deg: float) -> None:
        self.current_angle_deg = deg

    def set_text_height(self, mm: float) -> None:
        self.current_text_height_mm = mm

    def set_font_family(self, family: str) -> None:
        self.current_font_family = family

    def set_underlay(self, on: bool) -> None:
        self.current_underlay = on

    def add_text(self, x_mm: float, y_mm: float, text: str) -> None:
        """Called by the window once the user has typed a string."""
        if not text.strip():
            return
        self.design.add_text(
            TextItem(
                text=text,
                x_mm=x_mm,
                y_mm=y_mm,
                height_mm=self.current_text_height_mm,
                font_family=self.current_font_family,
                color=self.current_color,
                stitch_length_mm=self.current_stitch_length,
                spacing_mm=self.current_spacing_mm,
                angle_deg=self.current_angle_deg,
                underlay=self.current_underlay,
            )
        )
        self.update()
        self.design_changed.emit()

    def undo_last_stroke(self) -> None:
        """Remove the most recently added object (across all kinds)."""
        for coll in (self.design.texts, self.design.regions, self.design.strokes):
            if coll:
                removed = coll.pop()
                if removed is self.selected:
                    self._set_selected(None)
                self.update()
                self.design_changed.emit()
                return

    def clear(self) -> None:
        self.design.clear()
        self._active = None
        self._set_selected(None)
        self.update()
        self.design_changed.emit()

    # ---- mouse --------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        x_mm, y_mm = self._px_to_mm(event.position().x(), event.position().y())

        # Select tool, or Shift+click in any tool, picks the object under the cursor.
        if self.tool == TOOL_SELECT or (event.modifiers() & Qt.ShiftModifier):
            self.setFocus()
            self._set_selected(self._hit_test(x_mm, y_mm))
            self._drag_last = (x_mm, y_mm) if self.selected is not None else None
            self._moved = False
            self.update()
            return

        if self.tool == TOOL_TEXT:
            self.text_requested.emit(x_mm, y_mm)
            return

        if self.tool == TOOL_REGION:
            self._active = self.design.new_region(
                self.current_color,
                self.current_stitch_length,
                self.current_spacing_mm,
                self.current_angle_deg,
                self.current_underlay,
            )
        else:
            self._active = self.design.new_stroke(
                self.current_color,
                self.current_stitch_length,
                self.current_stitch_type,
                self.current_width_mm,
                self.current_underlay,
            )
        self._active.add_point(x_mm, y_mm)
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        x_mm, y_mm = self._px_to_mm(event.position().x(), event.position().y())
        # a text under the cursor can have its string re-edited
        for item in reversed(self.design.texts):
            if item.is_drawable() and self._in_bounds((x_mm, y_mm), self._object_bounds(item)):
                self._set_selected(item)
                self.update()
                self.text_edit_requested.emit(item)
                return
        # a fresh double-click in the empty area drops new text (Text tool feel)
        if self.tool == TOOL_TEXT:
            self.text_requested.emit(x_mm, y_mm)

    def mouseMoveEvent(self, event) -> None:
        x_mm, y_mm = self._px_to_mm(event.position().x(), event.position().y())

        # dragging a selection (Select tool, or after a Shift+click)
        if self._drag_last is not None and self.selected is not None:
            self.selected.translate(x_mm - self._drag_last[0], y_mm - self._drag_last[1])
            self._drag_last = (x_mm, y_mm)
            self._moved = True
            self.update()
            return

        if self.tool == TOOL_SELECT or self._active is None:
            return
        last = self._active.points[-1]
        if math.hypot(x_mm - last[0], y_mm - last[1]) >= MIN_POINT_SPACING_MM:
            self._active.add_point(x_mm, y_mm)
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        # finishing a selection drag
        if self._drag_last is not None:
            if self._moved:
                self.design_changed.emit()
            self._drag_last = None
            self._moved = False
            return

        if self.tool == TOOL_SELECT or self._active is None:
            return
        if not self._active.is_drawable():
            # too small to be useful (a click, or a region with < 3 points)
            self._remove_active()
        self._active = None
        self.update()
        self.design_changed.emit()

    def keyPressEvent(self, event) -> None:
        if self.selected is not None and event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self._delete_selected()
            return
        super().keyPressEvent(event)

    def _remove_active(self) -> None:
        if isinstance(self._active, Region) and self._active in self.design.regions:
            self.design.regions.remove(self._active)
        elif isinstance(self._active, Stroke) and self._active in self.design.strokes:
            self.design.strokes.remove(self._active)

    def delete_selected(self) -> None:
        """Remove the selected object (if any) and clear the selection."""
        if self.selected is None:
            return
        for coll in (self.design.texts, self.design.regions, self.design.strokes):
            if self.selected in coll:
                coll.remove(self.selected)
                break
        self._set_selected(None)
        self.update()
        self.design_changed.emit()

    _delete_selected = delete_selected  # internal alias (keyPress etc.)

    # ---- hit testing --------------------------------------------------------
    def _hit_test(self, x: float, y: float) -> Optional[Selectable]:
        """Topmost object under the point, honouring paint order (strokes on top)."""
        p = (x, y)
        for stroke in reversed(self.design.strokes):
            if self._near_polyline(p, stroke.points, HIT_TOLERANCE_MM):
                return stroke
        for item in reversed(self.design.texts):
            if item.is_drawable() and self._in_bounds(p, self._object_bounds(item)):
                return item
        for region in reversed(self.design.regions):
            if self._in_contours(p, region.contours) or any(
                self._near_polyline(p, c, HIT_TOLERANCE_MM, closed=True)
                for c in region.contours
            ):
                return region
        return None

    def _object_bounds(self, obj: Selectable) -> Tuple[float, float, float, float]:
        if isinstance(obj, TextItem):
            w, h = text_size_mm(obj.text, obj.font_family, obj.height_mm)
            return (obj.x_mm, obj.y_mm, obj.x_mm + w, obj.y_mm + h)
        pts = obj.all_points() if isinstance(obj, Region) else obj.points
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))

    @classmethod
    def _in_contours(cls, p: Point, contours: Sequence[Sequence[Point]]) -> bool:
        """Even-odd point-in-polygon across a set of contours (holes respected)."""
        inside = False
        for contour in contours:
            if len(contour) >= 3 and cls._point_in_poly(p, contour):
                inside = not inside
        return inside

    @staticmethod
    def _in_bounds(p: Point, b: Tuple[float, float, float, float]) -> bool:
        m = 1.0
        return b[0] - m <= p[0] <= b[2] + m and b[1] - m <= p[1] <= b[3] + m

    @staticmethod
    def _point_in_poly(p: Point, pts: Sequence[Point]) -> bool:
        if len(pts) < 3:
            return False
        x, y = p
        inside = False
        n = len(pts)
        j = n - 1
        for i in range(n):
            xi, yi = pts[i]
            xj, yj = pts[j]
            if (yi > y) != (yj > y):
                xint = xi + (y - yi) * (xj - xi) / (yj - yi)
                if x < xint:
                    inside = not inside
            j = i
        return inside

    @staticmethod
    def _dist_point_seg(p: Point, a: Point, b: Point) -> float:
        px, py = p
        ax, ay = a
        bx, by = b
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        if length_sq == 0:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

    def _near_polyline(
        self, p: Point, pts: Sequence[Point], tol: float, closed: bool = False
    ) -> bool:
        if len(pts) < 2:
            return bool(pts) and math.hypot(p[0] - pts[0][0], p[1] - pts[0][1]) <= tol
        edges = list(range(1, len(pts)))
        for i in edges:
            if self._dist_point_seg(p, pts[i - 1], pts[i]) <= tol:
                return True
        if closed and self._dist_point_seg(p, pts[-1], pts[0]) <= tol:
            return True
        return False

    # ---- painting -----------------------------------------------------------
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#2b2b2b"))

        scale, ox, oy = self._fit()
        hoop_w = self.design.hoop_width_mm * scale
        hoop_h = self.design.hoop_height_mm * scale

        # hoop fabric
        painter.setBrush(QBrush(QColor("#fbfbf7")))
        painter.setPen(QPen(QColor("#888"), 1))
        painter.drawRect(ox, oy, hoop_w, hoop_h)

        # 10 mm grid
        painter.setPen(QPen(QColor("#e2e2dc"), 1))
        step_mm = 10
        x = 0
        while x <= self.design.hoop_width_mm:
            px = ox + x * scale
            painter.drawLine(px, oy, px, oy + hoop_h)
            x += step_mm
        y = 0
        while y <= self.design.hoop_height_mm:
            py = oy + y * scale
            painter.drawLine(ox, py, ox + hoop_w, py)
            y += step_mm

        self._paint_regions(painter)
        self._paint_texts(painter)
        self._paint_strokes(painter)
        self._paint_selection(painter)

        painter.end()

    def _paint_regions(self, painter: QPainter) -> None:
        for region in self.design.regions:
            color = QColor(region.color)
            fill = QColor(color)
            fill.setAlpha(70)
            pen = QPen(color, 1.5)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            if region.is_drawable():
                # even-odd path so inner contours (holes) render open
                path = QPainterPath()
                path.setFillRule(Qt.OddEvenFill)
                for contour in region.contours:
                    if len(contour) < 3:
                        continue
                    path.addPolygon(
                        QPolygonF([self._mm_to_px(px, py) for px, py in contour])
                    )
                    path.closeSubpath()
                painter.setBrush(QBrush(fill))
                painter.drawPath(path)
            else:
                # still being drawn — trace the primary contour
                if len(region.points) >= 1:
                    poly = QPolygonF([self._mm_to_px(px, py) for px, py in region.points])
                    painter.setBrush(Qt.NoBrush)
                    painter.drawPolyline(poly)

    def _paint_texts(self, painter: QPainter) -> None:
        for item in self.design.texts:
            if not item.is_drawable():
                continue
            contours = text_to_contours(
                item.text, item.font_family, item.height_mm, item.x_mm, item.y_mm
            )
            # Draw the whole glyph as one even-odd path so counters (the holes in
            # o, e, p, B …) render open instead of being filled over.
            path = QPainterPath()
            path.setFillRule(Qt.OddEvenFill)
            for contour in contours:
                path.addPolygon(
                    QPolygonF([self._mm_to_px(px, py) for px, py in contour])
                )
                path.closeSubpath()
            color = QColor(item.color)
            fill = QColor(color)
            fill.setAlpha(90)
            painter.setBrush(QBrush(fill))
            painter.setPen(QPen(color, 1))
            painter.drawPath(path)

    def _paint_strokes(self, painter: QPainter) -> None:
        for stroke in self.design.strokes:
            if len(stroke.points) < 1:
                continue
            pen = QPen(QColor(stroke.color), 2)
            pen.setJoinStyle(Qt.RoundJoin)
            pen.setCapStyle(Qt.RoundCap)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(pen)
            pts = [self._mm_to_px(px, py) for px, py in stroke.points]
            if len(pts) == 1:
                painter.drawPoint(pts[0])
            else:
                for i in range(1, len(pts)):
                    painter.drawLine(pts[i - 1], pts[i])

    def _paint_selection(self, painter: QPainter) -> None:
        if self.selected is None:
            return
        # the selection may have just been deleted elsewhere
        in_design = (
            self.selected in self.design.strokes
            or self.selected in self.design.regions
            or self.selected in self.design.texts
        )
        if not in_design:
            self.selected = None
            return
        b = self._object_bounds(self.selected)
        tl = self._mm_to_px(b[0], b[1])
        br = self._mm_to_px(b[2], b[3])
        rect = QRectF(tl, br).adjusted(-4, -4, 4, 4)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("#4aa3ff"), 1.5, Qt.DashLine))
        painter.drawRect(rect)
