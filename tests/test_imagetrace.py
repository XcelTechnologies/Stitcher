"""Tests for image auto-digitizing (needs Qt + numpy)."""

from stitcher.model import Design
from stitcher.pattern import design_to_pattern, pattern_to_segments, UNITS_PER_MM
from stitcher.imagetrace import trace_image, load_rgba, _area


def test_load_rgba_shape(logo_png):
    arr = load_rgba(logo_png)
    assert arr.ndim == 3 and arr.shape[2] == 4
    assert arr.shape[0] == 200 and arr.shape[1] == 300


def test_trace_returns_regions(logo_png):
    regions = trace_image(logo_png, num_colors=4, hoop_w_mm=100, hoop_h_mm=100)
    assert regions                       # red disk, green ring, blue square
    assert all(r.contours for r in regions)
    # every region carries a hex colour
    assert all(r.color.startswith("#") and len(r.color) == 7 for r in regions)


def test_traced_annulus_keeps_hole_open(logo_png):
    regions = trace_image(logo_png, num_colors=4, hoop_w_mm=100, hoop_h_mm=100)
    ring = [r for r in regions if len(r.contours) >= 2]
    assert ring, "expected the green annulus to trace as a holed region"
    inner = min(ring[0].contours, key=_area)

    def inside(poly, px, py):
        c = False
        n = len(poly)
        j = n - 1
        for i in range(n):
            xi, yi = poly[i]
            xj, yj = poly[j]
            if (yi > py) != (yj > py):
                if px < xi + (py - yi) * (xj - xi) / (yj - yi):
                    c = not c
            j = i
        return c

    segs = pattern_to_segments(design_to_pattern(Design(regions=[ring[0]])))
    for x0, y0, x1, y1, kind, _c in segs:
        if kind != "stitch":
            continue
        mx, my = (x0 + x1) / 2 / UNITS_PER_MM, (y0 + y1) / 2 / UNITS_PER_MM
        if inside(inner, mx, my):
            # tolerate the boundary band; only fail for stitches deep in the hole
            dmin = min(
                _seg_dist((mx, my), inner[i - 1], inner[i]) for i in range(len(inner))
            )
            assert dmin <= 1.5, "stitch found deep inside the counter"


def test_target_width_sets_content_width(logo_png):
    regions = trace_image(logo_png, num_colors=4, target_width_mm=60.0,
                          hoop_w_mm=100, hoop_h_mm=100)
    xs = [x for r in regions for c in r.contours for x, _ in c]
    assert abs((max(xs) - min(xs)) - 60.0) < 1.5


def test_trace_angle_applied(logo_png):
    regions = trace_image(logo_png, num_colors=4, angle_deg=45.0,
                          hoop_w_mm=100, hoop_h_mm=100)
    assert regions and all(abs(r.angle_deg - 45.0) < 1e-9 for r in regions)


def test_huge_min_area_drops_everything(logo_png):
    regions = trace_image(logo_png, num_colors=4, min_area_mm2=1e6,
                          hoop_w_mm=100, hoop_h_mm=100)
    assert regions == []


def _seg_dist(p, a, b):
    import math
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    ll = dx * dx + dy * dy
    if ll == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / ll))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
