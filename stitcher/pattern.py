# SPDX-License-Identifier: MIT
"""Convert the drawing model into a pyembroidery pattern.

Responsibilities:
* Turn drawn objects (strokes, filled regions, text) into machine stitches.
* Export the pattern to any pyembroidery-supported machine format.
* Flatten a pattern into simple line segments for on-screen preview.

Every object contributes one or more *runs* — ordered lists of stitch points
that the needle sews without lifting. ``design_to_pattern`` stitches the runs,
inserting trims/colour-changes between objects and jumps between runs.
"""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple

import pyembroidery as pe

from .model import (
    Design,
    Region,
    Stroke,
    TextItem,
    DEFAULT_HOOP_MM,
    STITCH_BEAN,
    STITCH_SATIN,
)
from .text import text_to_contours

# 1 mm == 10 embroidery units (pyembroidery works in 1/10 mm).
UNITS_PER_MM = 10.0
MIN_STITCH_MM = 0.3

# Tie stitches anchor the thread so the run doesn't unravel at its ends.
TIE_LENGTH_MM = 0.7   # how far each tack stitch reaches from the anchor point
TIE_COUNT = 3         # number of tack stitches at each end of a run

MIN_FILL_SPACING_MM = 0.3

# Underlay: a stabilizing pass sewn before the cover stitches so they don't sink
# into the fabric. Sewn at a longer stitch than the cover pass.
UNDERLAY_STEP_MM = 2.5
UNDERLAY_INSET_MM = 0.5   # pull the satin centre-run in from the very ends

# Curated set of write targets shown in the export dialog: (extension, label).
SUPPORTED_WRITE_FORMATS: List[Tuple[str, str]] = [
    ("dst", "Tajima (*.dst)"),
    ("pes", "Brother (*.pes)"),
    ("exp", "Melco Expanded (*.exp)"),
    ("jef", "Janome (*.jef)"),
    ("vp3", "Pfaff (*.vp3)"),
    ("xxx", "Singer (*.xxx)"),
    ("u01", "Barudan (*.u01)"),
    ("svg", "SVG vector (*.svg)"),
    ("png", "PNG image (*.png)"),
]

# Formats pyembroidery can read back in for import.
SUPPORTED_READ_FORMATS: List[Tuple[str, str]] = [
    ("dst", "Tajima (*.dst)"),
    ("pes", "Brother (*.pes)"),
    ("exp", "Melco Expanded (*.exp)"),
    ("jef", "Janome (*.jef)"),
    ("vp3", "Pfaff (*.vp3)"),
    ("xxx", "Singer (*.xxx)"),
    ("u01", "Barudan (*.u01)"),
]

# Margin left around imported artwork when it's placed on a fresh hoop.
IMPORT_MARGIN_MM = 5.0

Point = Tuple[float, float]
UnitPoint = Tuple[int, int]

# Render segment: (x0, y0, x1, y1, kind, (r, g, b)) in embroidery units.
Segment = Tuple[float, float, float, float, str, Tuple[int, int, int]]


# ---------------------------------------------------------------------------
# Low-level geometry helpers
# ---------------------------------------------------------------------------
def _resample_polyline(points: Sequence[Point], step_mm: float) -> List[Point]:
    """Resample a polyline into points spaced no further apart than ``step_mm``."""
    if len(points) < 2:
        return list(points)

    step = max(step_mm, MIN_STITCH_MM)
    result: List[Point] = [points[0]]
    for i in range(1, len(points)):
        x0, y0 = points[i - 1]
        x1, y1 = points[i]
        dx, dy = x1 - x0, y1 - y0
        dist = math.hypot(dx, dy)
        if dist == 0:
            continue
        segments = max(1, int(math.ceil(dist / step)))
        for k in range(1, segments + 1):
            t = k / segments
            result.append((x0 + dx * t, y0 + dy * t))
    return result


def _to_units(points: Sequence[Point]) -> List[UnitPoint]:
    """Round mm points to integer units and drop consecutive duplicates.

    Some machines reject zero-length stitches, so identical neighbours collapse.
    """
    units: List[UnitPoint] = []
    for x, y in points:
        p = (round(x * UNITS_PER_MM), round(y * UNITS_PER_MM))
        if not units or p != units[-1]:
            units.append(p)
    return units


# ---------------------------------------------------------------------------
# Stroke stitch types
# ---------------------------------------------------------------------------
def _running_run(stroke: Stroke) -> List[Point]:
    return _resample_polyline(stroke.points, stroke.stitch_length_mm)


def _bean_run(stroke: Stroke) -> List[Point]:
    """Triple (bean) stitch: each segment is sewn forward, back, forward."""
    base = _resample_polyline(stroke.points, stroke.stitch_length_mm)
    if len(base) < 2:
        return base
    out: List[Point] = [base[0]]
    for i in range(1, len(base)):
        prev, cur = base[i - 1], base[i]
        out.extend((cur, prev, cur))
    return out


def _satin_run(stroke: Stroke) -> List[Point]:
    """Satin column: zig-zag from side to side across a widened spine."""
    spine = _resample_polyline(stroke.points, stroke.stitch_length_mm)
    if len(spine) < 2:
        return spine
    half = max(stroke.width_mm, MIN_STITCH_MM) / 2.0
    out: List[Point] = []
    n = len(spine)
    for i, (x, y) in enumerate(spine):
        if i == 0:
            dx, dy = spine[1][0] - x, spine[1][1] - y
        elif i == n - 1:
            dx, dy = x - spine[i - 1][0], y - spine[i - 1][1]
        else:
            dx, dy = spine[i + 1][0] - spine[i - 1][0], spine[i + 1][1] - spine[i - 1][1]
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length          # unit normal
        side = half if i % 2 == 0 else -half
        out.append((x + nx * side, y + ny * side))
    return out


def _stroke_runs(stroke: Stroke) -> List[List[UnitPoint]]:
    if stroke.stitch_type == STITCH_SATIN:
        runs: List[List[UnitPoint]] = []
        if stroke.underlay:
            under = _to_units(_resample_polyline(stroke.points, UNDERLAY_STEP_MM))
            if under:
                runs.append(under)               # centre run down the spine
        cover = _to_units(_satin_run(stroke))
        if cover:
            runs.append(cover)
        return runs
    if stroke.stitch_type == STITCH_BEAN:
        pts = _bean_run(stroke)
    else:
        pts = _running_run(stroke)
    run = _to_units(pts)
    return [run] if run else []


# ---------------------------------------------------------------------------
# Tatami / parallel-line fill
# ---------------------------------------------------------------------------
def _fill_runs(
    contours: Sequence[Sequence[Point]],
    angle_deg: float,
    spacing_mm: float,
    stitch_length_mm: float,
) -> List[List[Point]]:
    """Fill closed contours with parallel rows, returned as continuous runs.

    Rows are laid at ``angle_deg`` (0° = horizontal) and ``spacing_mm`` apart.
    Each row is split into inside spans by the even-odd rule, so holes (letter
    counters like *o*, *e*, *p* …) leave gaps. Spans are then stitched back and
    forth (boustrophedon), but a row's span only continues the run from the row
    above when their x-ranges overlap — i.e. they belong to the same column of
    the shape. That keeps every join a short step along a wall and guarantees no
    stitch is ever drawn across a counter; each separate column is its own run.
    """
    contours = [list(c) for c in contours if len(c) >= 3]
    if not contours:
        return []

    ang = math.radians(angle_deg)
    ca, sa = math.cos(-ang), math.sin(-ang)      # rotate by -angle -> rows horizontal
    cb, sb = math.cos(ang), math.sin(ang)        # inverse rotation back to mm

    def back(px: float, py: float) -> Point:
        return (px * cb - py * sb, px * sb + py * cb)

    # Edges in rotated space, skipping horizontal ones (no crossing).
    edges: List[Tuple[float, float, float, float]] = []
    ys: List[float] = []
    for contour in contours:
        rot = [(x * ca - y * sa, x * sa + y * ca) for x, y in contour]
        ys.extend(p[1] for p in rot)
        for i in range(len(rot)):
            x0, y0 = rot[i]
            x1, y1 = rot[(i + 1) % len(rot)]
            if y0 != y1:
                edges.append((x0, y0, x1, y1))
    if not edges:
        return []

    spacing = max(spacing_mm, MIN_FILL_SPACING_MM)
    step = max(stitch_length_mm, MIN_STITCH_MM)
    min_y, max_y = min(ys), max(ys)

    runs: List[List[Point]] = []
    # active columns carried down from the previous row:
    #   (run_points, span_lo, span_hi)
    active: List[Tuple[List[Point], float, float]] = []

    y = min_y + spacing / 2.0
    row = 0
    while y < max_y:
        xints: List[float] = []
        for x0, y0, x1, y1 in edges:
            if (y0 > y) != (y1 > y):
                xints.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
        xints.sort()
        spans = [(xints[i], xints[i + 1]) for i in range(0, len(xints) - 1, 2)]

        left_to_right = row % 2 == 0
        ordered = spans if left_to_right else list(reversed(spans))

        next_active: List[Tuple[List[Point], float, float]] = []
        used = set()
        for lo, hi in ordered:
            # continue the overlapping column from the row above, if any
            run: List[Point] | None = None
            for idx, (prev_run, plo, phi) in enumerate(active):
                if idx not in used and phi > lo and plo < hi:
                    run = prev_run
                    used.add(idx)
                    break
            if run is None:
                run = []
                runs.append(run)

            # sew the span in the current sweep direction; the step from the
            # previous row's exit into this entry is the (in-column) join
            entry, exit_ = (lo, hi) if left_to_right else (hi, lo)
            n = max(1, int(math.ceil(abs(hi - lo) / step)))
            for k in range(n + 1):
                t = k / n
                run.append(back(entry + (exit_ - entry) * t, y))
            next_active.append((run, lo, hi))

        active = next_active
        y += spacing
        row += 1

    return [r for r in runs if len(r) >= 1]


def _fill_underlay_runs(contours: Sequence[Sequence[Point]]) -> List[List[Point]]:
    """A running stitch around each closed contour, to anchor the fill."""
    runs: List[List[Point]] = []
    for contour in contours:
        if len(contour) < 3:
            continue
        closed = list(contour) + [contour[0]]
        runs.append(_resample_polyline(closed, UNDERLAY_STEP_MM))
    return runs


def _filled_object_runs(
    contours: Sequence[Sequence[Point]],
    angle_deg: float,
    spacing_mm: float,
    stitch_length_mm: float,
    underlay: bool,
) -> List[List[UnitPoint]]:
    runs_mm: List[List[Point]] = []
    if underlay:
        runs_mm.extend(_fill_underlay_runs(contours))
    runs_mm.extend(_fill_runs(contours, angle_deg, spacing_mm, stitch_length_mm))
    return [u for u in (_to_units(r) for r in runs_mm) if u]


def _region_runs(region: Region) -> List[List[UnitPoint]]:
    return _filled_object_runs(
        region.contours,
        region.angle_deg,
        region.spacing_mm,
        region.stitch_length_mm,
        region.underlay,
    )


def _text_runs(item: TextItem) -> List[List[UnitPoint]]:
    contours = text_to_contours(
        item.text, item.font_family, item.height_mm, item.x_mm, item.y_mm
    )
    return _filled_object_runs(
        contours, item.angle_deg, item.spacing_mm, item.stitch_length_mm, item.underlay
    )


# ---------------------------------------------------------------------------
# Tie-off tacks
# ---------------------------------------------------------------------------
def _tie_offset(anchor: UnitPoint, toward: UnitPoint) -> UnitPoint:
    """A point ~TIE_LENGTH_MM from `anchor` in the direction of `toward` (units)."""
    ax, ay = anchor
    tx, ty = toward
    dx, dy = tx - ax, ty - ay
    dist = math.hypot(dx, dy)
    if dist == 0:
        return anchor
    step = min(dist, TIE_LENGTH_MM * UNITS_PER_MM)
    return (round(ax + dx * step / dist), round(ay + dy * step / dist))


def _tack(pattern: pe.EmbPattern, anchor: UnitPoint, neighbour: UnitPoint) -> None:
    """Stitch back and forth between `anchor` and a nearby point to lock the thread."""
    tie = _tie_offset(anchor, neighbour)
    if tie == anchor:  # neighbour coincides with the anchor — nothing to tack to
        return
    for _ in range(TIE_COUNT):
        pattern.stitch_abs(tie[0], tie[1])
        pattern.stitch_abs(anchor[0], anchor[1])


def _add_thread(pattern: pe.EmbPattern, hex_color: str) -> None:
    thread = pe.EmbThread()
    thread.set_hex_color(hex_color)
    pattern.add_thread(thread)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def _design_objects(design: Design) -> List[Tuple[str, List[List[UnitPoint]]]]:
    """Every drawable object as (colour, runs), in stitch order."""
    objects: List[Tuple[str, List[List[UnitPoint]]]] = []
    for stroke in design.drawable_strokes():
        runs = _stroke_runs(stroke)
        if runs:
            objects.append((stroke.color, runs))
    for region in design.drawable_regions():
        runs = _region_runs(region)
        if runs:
            objects.append((region.color, runs))
    for item in design.drawable_texts():
        runs = _text_runs(item)
        if runs:
            objects.append((item.color, runs))
    return objects


def _stitch_object(pattern: pe.EmbPattern, runs: List[List[UnitPoint]]) -> None:
    """Sew one object's runs, tying in at the very start and off at the very end."""
    last = len(runs) - 1
    for ri, run in enumerate(runs):
        if not run:
            continue
        pattern.move_abs(run[0][0], run[0][1])   # jump to the run start (needle up)
        if ri == 0 and len(run) >= 2:
            _tack(pattern, run[0], run[1])        # tie-in ends on run[0]...
            body = run[1:]                        # ...so stitching continues from run[1]
        else:
            body = run                            # later runs penetrate their start too
        for x, y in body:
            pattern.stitch_abs(x, y)
        if ri == last and len(run) >= 2:
            _tack(pattern, run[-1], run[-2])      # tie-off after the final run


def design_to_pattern(design: Design) -> pe.EmbPattern:
    """Build a stitch-ready EmbPattern from a Design."""
    pattern = pe.EmbPattern()

    prev_color: str | None = None
    for color, runs in _design_objects(design):
        if prev_color is None:
            _add_thread(pattern, color)
        else:
            pattern.trim()  # cut thread before travelling to the next object
            if color != prev_color:
                pattern.color_change()
                _add_thread(pattern, color)

        _stitch_object(pattern, runs)
        prev_color = color

    pattern.end()
    return pattern


def export_design(design: Design, filepath: str) -> None:
    """Encode and write the design; format is chosen from the file extension."""
    pattern = design_to_pattern(design)
    pattern.write(filepath)


def _thread_hex(pattern: pe.EmbPattern, index: int) -> str:
    threads = pattern.threadlist
    if threads and 0 <= index < len(threads):
        th = threads[index]
        return "#%02x%02x%02x" % (th.get_red(), th.get_green(), th.get_blue())
    return "#1a1a1a"


def pattern_to_design(pattern: pe.EmbPattern) -> Design:
    """Convert a read-in machine pattern into an editable Design.

    A machine file is just stitches, so this is necessarily lossy: each block of
    stitches between jumps/trims/colour-changes becomes one running Stroke in the
    block's thread colour. The artwork is shifted onto a positive hoop so it
    lands fully on the canvas.
    """
    design = Design()
    color_index = 0
    current: Stroke | None = None

    for x, y, command in pattern.stitches:
        code = command & pe.COMMAND_MASK
        if code == pe.STITCH:
            if current is None:
                current = Stroke(color=_thread_hex(pattern, color_index))
                design.strokes.append(current)
            current.add_point(x / UNITS_PER_MM, y / UNITS_PER_MM)
        elif code in (pe.COLOR_CHANGE, pe.NEEDLE_SET):
            color_index += 1
            current = None
        elif code == pe.END:
            break
        else:  # JUMP, TRIM, STOP, … — end the current run
            current = None

    design.strokes = [s for s in design.strokes if s.is_drawable()]

    # Shift artwork to positive coordinates and size the hoop to fit.
    pts = [p for s in design.strokes for p in s.points]
    if pts:
        min_x = min(p[0] for p in pts)
        min_y = min(p[1] for p in pts)
        dx, dy = IMPORT_MARGIN_MM - min_x, IMPORT_MARGIN_MM - min_y
        for stroke in design.strokes:
            stroke.translate(dx, dy)
        max_x = max(p[0] + dx for p in pts)
        max_y = max(p[1] + dy for p in pts)
        design.hoop_width_mm = max(DEFAULT_HOOP_MM[0], max_x + IMPORT_MARGIN_MM)
        design.hoop_height_mm = max(DEFAULT_HOOP_MM[1], max_y + IMPORT_MARGIN_MM)

    return design


def import_design(filepath: str) -> Design:
    """Read a machine embroidery file and convert it to an editable Design."""
    pattern = pe.read(filepath)
    if pattern is None:
        raise ValueError("Unrecognised or unreadable embroidery file.")
    return pattern_to_design(pattern)


def pattern_to_segments(pattern: pe.EmbPattern) -> List[Segment]:
    """Flatten a pattern into drawable stitch/jump segments for the preview."""
    segments: List[Segment] = []
    threads = pattern.threadlist
    color_index = 0

    def current_color() -> Tuple[int, int, int]:
        if threads and 0 <= color_index < len(threads):
            th = threads[color_index]
            return (th.get_red(), th.get_green(), th.get_blue())
        return (26, 26, 26)

    prev: Tuple[float, float] | None = None
    for x, y, command in pattern.stitches:
        code = command & pe.COMMAND_MASK
        if code == pe.STITCH:
            if prev is not None:
                segments.append((prev[0], prev[1], x, y, "stitch", current_color()))
            prev = (x, y)
        elif code == pe.JUMP:
            if prev is not None:
                segments.append((prev[0], prev[1], x, y, "jump", current_color()))
            prev = (x, y)
        elif code in (pe.COLOR_CHANGE, pe.NEEDLE_SET):
            color_index += 1
            prev = (x, y)
        elif code == pe.END:
            break
        else:  # TRIM, STOP, etc. — keep the needle position, draw nothing.
            prev = (x, y)

    return segments


def pattern_stats(pattern: pe.EmbPattern) -> dict:
    """Summary numbers for the status bar."""
    bounds = pattern.bounds()  # (min_x, min_y, max_x, max_y) in units
    width_mm = (bounds[2] - bounds[0]) / UNITS_PER_MM
    height_mm = (bounds[3] - bounds[1]) / UNITS_PER_MM
    return {
        "stitches": pattern.count_stitches(),
        "colors": pattern.count_color_changes() + 1,
        "width_mm": width_mm,
        "height_mm": height_mm,
    }
