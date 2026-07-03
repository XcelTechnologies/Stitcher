# SPDX-License-Identifier: MIT
"""Stitch preview.

Renders the *encoded* pattern the way a machine would run it: solid coloured
lines for stitches, thin dashed lines for jumps, and a dot at every needle
penetration. This is generated from the same pyembroidery pattern that gets
exported, so it is an accurate proof of the output.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

import pyembroidery as pe

from .model import Design
from .pattern import design_to_pattern, pattern_to_segments, Segment


class PreviewWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._segments: List[Segment] = []
        self._bounds = None  # (min_x, min_y, max_x, max_y) in units
        self.show_points = True
        self.show_jumps = True
        self.setMinimumSize(360, 360)

    def set_pattern(self, pattern: Optional[pe.EmbPattern]) -> None:
        """Show an already-built pattern (or clear the view when None)."""
        self._segments = pattern_to_segments(pattern) if pattern is not None else []
        self._recompute_bounds()
        self.update()

    def set_design(self, design: Design) -> None:
        self.set_pattern(design_to_pattern(design))

    def _recompute_bounds(self) -> None:
        xs, ys = [], []
        for x0, y0, x1, y1, _kind, _c in self._segments:
            xs.extend((x0, x1))
            ys.extend((y0, y1))
        if xs:
            self._bounds = (min(xs), min(ys), max(xs), max(ys))
        else:
            self._bounds = None

    def _fit(self):
        margin = 24
        if not self._bounds:
            return 1.0, margin, margin
        min_x, min_y, max_x, max_y = self._bounds
        span_x = max(1.0, max_x - min_x)
        span_y = max(1.0, max_y - min_y)
        scale = min(
            (self.width() - 2 * margin) / span_x,
            (self.height() - 2 * margin) / span_y,
        )
        draw_w = span_x * scale
        draw_h = span_y * scale
        ox = (self.width() - draw_w) / 2 - min_x * scale
        oy = (self.height() - draw_h) / 2 - min_y * scale
        return scale, ox, oy

    def _to_px(self, x: float, y: float, scale: float, ox: float, oy: float) -> QPointF:
        return QPointF(ox + x * scale, oy + y * scale)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#1f1f1f"))

        if not self._segments:
            painter.setPen(QColor("#888"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Draw something to preview stitches")
            painter.end()
            return

        scale, ox, oy = self._fit()

        # jumps first (underneath)
        if self.show_jumps:
            jump_pen = QPen(QColor("#f4c542"), 1, Qt.DashLine)
            painter.setPen(jump_pen)
            for x0, y0, x1, y1, kind, _c in self._segments:
                if kind == "jump":
                    painter.drawLine(
                        self._to_px(x0, y0, scale, ox, oy),
                        self._to_px(x1, y1, scale, ox, oy),
                    )

        # stitches
        for x0, y0, x1, y1, kind, color in self._segments:
            if kind != "stitch":
                continue
            pen = QPen(QColor(*color), 1.6)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.drawLine(
                self._to_px(x0, y0, scale, ox, oy),
                self._to_px(x1, y1, scale, ox, oy),
            )

        # needle points
        if self.show_points:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#ffffff"))
            r = 1.4
            for x0, y0, x1, y1, kind, _c in self._segments:
                if kind != "stitch":
                    continue
                p = self._to_px(x1, y1, scale, ox, oy)
                painter.drawEllipse(p, r, r)

        painter.end()
