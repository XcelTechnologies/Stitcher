# SPDX-License-Identifier: MIT
"""Turn text into glyph outline contours (in millimetres).

We reuse Qt's font machinery — which PySide6 already pulls in — to avoid an
extra font dependency. ``QPainterPath.addText`` lays out the string and gives
us the vector outlines; ``toSubpathPolygons`` flattens the curves into
polylines. Each returned contour is a closed polygon; holes in glyphs (the
counter of an 'o', 'a', 'e' …) come back as their own contours and are handled
correctly by the even-odd fill in :mod:`stitcher.pattern`.

The outlines are scaled so the whole string's bounding box is ``height_mm``
tall and its top-left corner sits at ``(x_mm, y_mm)``.
"""

from __future__ import annotations

from typing import List, Tuple

from PySide6.QtGui import QFont, QPainterPath

Point = Tuple[float, float]

# Layout the glyphs at a generous pixel size so the flattened curves are smooth,
# then scale down to millimetres.
_LAYOUT_PIXELS = 512


def text_to_contours(
    text: str,
    font_family: str,
    height_mm: float,
    x_mm: float = 0.0,
    y_mm: float = 0.0,
) -> List[List[Point]]:
    """Flatten ``text`` into a list of closed contours positioned in mm."""
    if not text.strip() or height_mm <= 0:
        return []

    font = QFont(font_family)
    font.setPixelSize(_LAYOUT_PIXELS)

    path = QPainterPath()
    path.addText(0.0, 0.0, font, text)

    polygons = path.toSubpathPolygons()
    if not polygons:
        return []

    rect = path.boundingRect()
    if rect.height() <= 0:
        return []

    scale = height_mm / rect.height()
    left = rect.left()
    top = rect.top()

    contours: List[List[Point]] = []
    for poly in polygons:
        pts = [
            (x_mm + (pt.x() - left) * scale, y_mm + (pt.y() - top) * scale)
            for pt in poly
        ]
        if len(pts) >= 3:
            contours.append(pts)
    return contours


def text_size_mm(text: str, font_family: str, height_mm: float) -> Tuple[float, float]:
    """The (width, height) the laid-out text will occupy, in millimetres."""
    contours = text_to_contours(text, font_family, height_mm)
    if not contours:
        return (0.0, 0.0)
    xs = [x for c in contours for x, _ in c]
    ys = [y for c in contours for _, y in c]
    return (max(xs) - min(xs), max(ys) - min(ys))
