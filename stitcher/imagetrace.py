"""Auto-digitize a raster image (PNG/JPG/…) into fillable regions.

Pipeline for a flat-colour / logo-style image:

1. Load with Qt (:class:`QImage`) and drop fully-transparent pixels.
2. Quantize to a handful of colours with a small k-means.
3. For each colour, trace its mask into closed contours with marching squares
   (holes and separate blobs come out as their own loops).
4. Simplify the staircase contours (collinear collapse + Douglas–Peucker) and
   drop specks below a minimum area.
5. Emit one :class:`~stitcher.model.Region` per colour — every loop of that
   colour in one region, filled with the even-odd tatami engine so holes stay
   open.

Best on flat-colour artwork; photographs need true photo-stitch and are out of
scope here.
"""

from __future__ import annotations

import os
from typing import List, Sequence, Tuple

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from .model import (
    Region,
    DEFAULT_FILL_SPACING_MM,
    DEFAULT_STITCH_LENGTH_MM,
)

Point = Tuple[float, float]

MAX_TRACE_PIXELS = 220     # longest image side is downscaled to this before tracing
ALPHA_THRESHOLD = 128      # pixels more transparent than this are background
SVG_RENDER_PIXELS = 1024   # resolution SVGs are rasterized at before tracing


# ---------------------------------------------------------------------------
# Image loading
# ---------------------------------------------------------------------------
def _render_svg(path: str, max_px: int = SVG_RENDER_PIXELS) -> QImage:
    """Rasterize an SVG at high resolution so flat vector art traces crisply."""
    from PySide6.QtSvg import QSvgRenderer  # optional QtSvg module

    renderer = QSvgRenderer(path)
    if not renderer.isValid():
        raise ValueError("Could not read the SVG file.")
    size = renderer.defaultSize()
    w, h = size.width(), size.height()
    if w <= 0 or h <= 0:
        w = h = max_px
    scale = max_px / max(w, h)
    img = QImage(max(1, round(w * scale)), max(1, round(h * scale)),
                 QImage.Format_RGBA8888)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    renderer.render(painter)
    painter.end()
    return img


def _qimage_to_rgba(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    bpl = img.bytesPerLine()
    buf = bytes(img.constBits())[: bpl * h]
    arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, bpl)
    return arr[:, : w * 4].reshape(h, w, 4).copy()


def load_rgba(path: str) -> np.ndarray:
    """Load an image (any Qt-readable format, or SVG) as an (H, W, 4) RGBA array."""
    if os.path.splitext(path)[1].lower() in (".svg", ".svgz"):
        return _qimage_to_rgba(_render_svg(path))
    img = QImage(path)
    if img.isNull():
        raise ValueError("Could not read the image file.")
    return _qimage_to_rgba(img)


def _downscale(arr: np.ndarray, max_side: int) -> np.ndarray:
    h, w = arr.shape[:2]
    factor = max(1, int(np.ceil(max(h, w) / max_side)))
    return arr[::factor, ::factor]


# ---------------------------------------------------------------------------
# Colour quantization (small k-means)
# ---------------------------------------------------------------------------
def _quantize(rgb: np.ndarray, k: int, iters: int = 15, seed: int = 0):
    """Return (centres kx3 float, labels N) for the given Nx3 pixel colours."""
    rng = np.random.default_rng(seed)
    n = len(rgb)
    k = min(k, n)
    fit = rgb if n <= 12000 else rgb[rng.choice(n, 12000, replace=False)]

    centres = fit[rng.choice(len(fit), k, replace=False)].astype(float)
    for _ in range(iters):
        d = ((fit[:, None, :] - centres[None, :, :]) ** 2).sum(2)
        lbl = d.argmin(1)
        new = np.array(
            [fit[lbl == j].mean(0) if np.any(lbl == j) else centres[j] for j in range(k)]
        )
        if np.allclose(new, centres):
            centres = new
            break
        centres = new

    d = ((rgb[:, None, :] - centres[None, :, :]) ** 2).sum(2)
    return centres, d.argmin(1)


# ---------------------------------------------------------------------------
# Marching-squares contour tracing of a boolean mask
# ---------------------------------------------------------------------------
def _trace_mask(mask: np.ndarray) -> List[List[Point]]:
    """All closed contours of a boolean mask, in pixel coordinates."""
    h, w = mask.shape
    padded = np.zeros((h + 2, w + 2), dtype=bool)
    padded[1:-1, 1:-1] = mask
    ph, pw = padded.shape

    tl = padded[:-1, :-1]
    tr = padded[:-1, 1:]
    br = padded[1:, 1:]
    bl = padded[1:, :-1]
    active = np.argwhere(~((tl == tr) & (tr == br) & (br == bl)))

    # adjacency between crossing midpoints (undirected)
    adj: dict[Point, List[Point]] = {}
    used_edges: set = set()

    def connect(a: Point, b: Point) -> None:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)

    for r, c in active:
        a, b_, cc, d = (
            bool(padded[r, c]),
            bool(padded[r, c + 1]),
            bool(padded[r + 1, c + 1]),
            bool(padded[r + 1, c]),
        )
        top = (c + 0.5, r)
        right = (c + 1.0, r + 0.5)
        bottom = (c + 0.5, r + 1.0)
        left = (c, r + 0.5)
        crossed = []
        if a != b_:
            crossed.append(top)
        if b_ != cc:
            crossed.append(right)
        if cc != d:
            crossed.append(bottom)
        if d != a:
            crossed.append(left)

        if len(crossed) == 2:
            connect(crossed[0], crossed[1])
        elif len(crossed) == 4:
            # saddle: pair edges so each inside corner is enclosed on its own
            if a and cc:                      # TL & BR inside
                connect(top, left)
                connect(bottom, right)
            else:                             # TR & BL inside
                connect(top, right)
                connect(bottom, left)

    # walk adjacency into closed loops
    loops: List[List[Point]] = []
    for start in list(adj.keys()):
        for first in adj[start]:
            if frozenset((start, first)) in used_edges:
                continue
            loop = [start, first]
            used_edges.add(frozenset((start, first)))
            prev, cur = start, first
            while cur != start:
                nxt = None
                for cand in adj.get(cur, ()):
                    if cand != prev and frozenset((cur, cand)) not in used_edges:
                        nxt = cand
                        break
                if nxt is None:
                    for cand in adj.get(cur, ()):
                        if frozenset((cur, cand)) not in used_edges:
                            nxt = cand
                            break
                if nxt is None:
                    break
                used_edges.add(frozenset((cur, nxt)))
                loop.append(nxt)
                prev, cur = cur, nxt
            if len(loop) >= 4:
                # coords are in padded space; shift back to mask pixels
                loops.append([(x - 1.0, y - 1.0) for x, y in loop])
    return loops


# ---------------------------------------------------------------------------
# Contour simplification
# ---------------------------------------------------------------------------
def _collapse_collinear(pts: Sequence[Point], eps: float = 1e-6) -> List[Point]:
    if len(pts) < 3:
        return list(pts)
    out: List[Point] = []
    n = len(pts)
    for i in range(n):
        a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
        cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if abs(cross) > eps:
            out.append(b)
    return out or list(pts)


def _rdp(pts: List[Point], tol: float) -> List[Point]:
    """Douglas–Peucker simplification of an open polyline."""
    if len(pts) < 3:
        return pts
    a, b = pts[0], pts[-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = (dx * dx + dy * dy) ** 0.5 or 1.0
    dmax, idx = 0.0, 0
    for i in range(1, len(pts) - 1):
        px, py = pts[i]
        dist = abs((px - a[0]) * dy - (py - a[1]) * dx) / length
        if dist > dmax:
            dmax, idx = dist, i
    if dmax <= tol:
        return [a, b]
    left = _rdp(pts[: idx + 1], tol)
    right = _rdp(pts[idx:], tol)
    return left[:-1] + right


def _simplify(loop: List[Point], tol: float) -> List[Point]:
    if len(loop) >= 2 and loop[0] == loop[-1]:
        loop = loop[:-1]                       # drop the closing duplicate
    loop = _collapse_collinear(loop)
    if len(loop) < 3:
        return loop
    # RDP a closed ring by splitting it into two open arcs at the point farthest
    # from the start — a single open segment start→start would be degenerate.
    a = loop[0]
    far = max(
        range(len(loop)),
        key=lambda i: (loop[i][0] - a[0]) ** 2 + (loop[i][1] - a[1]) ** 2,
    )
    if far == 0:
        return loop
    first_arc = _rdp(loop[: far + 1], tol)
    second_arc = _rdp(loop[far:] + [loop[0]], tol)
    result = first_arc[:-1] + second_arc[:-1]  # drop the shared/closing endpoints
    return result if len(result) >= 3 else loop


def _area(loop: Sequence[Point]) -> float:
    s = 0.0
    n = len(loop)
    for i in range(n):
        x0, y0 = loop[i]
        x1, y1 = loop[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return abs(s) / 2.0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def trace_image(
    path: str,
    *,
    num_colors: int = 6,
    hoop_w_mm: float = 100.0,
    hoop_h_mm: float = 100.0,
    margin_mm: float = 5.0,
    min_area_mm2: float = 3.0,
    simplify_tol_mm: float = 0.4,
    spacing_mm: float = DEFAULT_FILL_SPACING_MM,
    stitch_length_mm: float = DEFAULT_STITCH_LENGTH_MM,
    angle_deg: float = 0.0,
    target_width_mm: float | None = None,
    underlay: bool = True,
) -> List[Region]:
    """Trace an image into editable :class:`Region` fills positioned on the hoop.

    ``target_width_mm`` sets how wide the traced art should be (height follows
    the aspect ratio); when ``None`` the art is scaled to fit inside the hoop.
    """
    arr = _downscale(load_rgba(path), MAX_TRACE_PIXELS)
    h, w = arr.shape[:2]
    rgb = arr[:, :, :3].astype(np.int16)
    opaque = arr[:, :, 3] >= ALPHA_THRESHOLD
    if not opaque.any():
        return []

    centres, labels_flat = _quantize(rgb[opaque].reshape(-1, 3), num_colors)
    labels = np.full((h, w), -1, dtype=int)
    labels[opaque] = labels_flat

    # bounding box of the actual (opaque) artwork — ignore transparent margins
    ys_op, xs_op = np.where(opaque)
    bx0, by0 = int(xs_op.min()), int(ys_op.min())
    bw = int(xs_op.max()) - bx0 + 1
    bh = int(ys_op.max()) - by0 + 1

    # size the art: a chosen target width, else fit inside the hoop
    if target_width_mm and target_width_mm > 0:
        scale = target_width_mm / bw
    else:
        avail_w = max(1.0, hoop_w_mm - 2 * margin_mm)
        avail_h = max(1.0, hoop_h_mm - 2 * margin_mm)
        scale = min(avail_w / bw, avail_h / bh)
    # centre the art's bounding box in the hoop
    ox = (hoop_w_mm - bw * scale) / 2.0 - bx0 * scale
    oy = (hoop_h_mm - bh * scale) / 2.0 - by0 * scale

    def to_mm(pt: Point) -> Point:
        return (ox + pt[0] * scale, oy + pt[1] * scale)

    regions: List[Region] = []
    for j in range(len(centres)):
        mask = labels == j
        if not mask.any():
            continue
        contours: List[List[Point]] = []
        for loop in _trace_mask(mask):
            loop = _simplify(loop, simplify_tol_mm / scale)  # tol back to px
            if len(loop) < 3:
                continue
            mm_loop = [to_mm(p) for p in loop]
            if _area(mm_loop) < min_area_mm2:
                continue
            contours.append(mm_loop)
        if not contours:
            continue
        r, g, b = (int(v) for v in np.clip(centres[j], 0, 255))
        regions.append(
            Region(
                color="#%02x%02x%02x" % (r, g, b),
                contours=contours,
                stitch_length_mm=stitch_length_mm,
                spacing_mm=spacing_mm,
                angle_deg=angle_deg,
                underlay=underlay,
            )
        )
    return regions
