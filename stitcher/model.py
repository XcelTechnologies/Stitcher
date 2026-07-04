# SPDX-License-Identifier: MIT
"""Drawing data model.

The model is stored in millimetres so it stays independent of the on-screen
zoom level and maps cleanly onto embroidery units (pyembroidery works in
1/10 mm, i.e. 1 mm == 10 units).

A design holds three kinds of object:

* ``Stroke``  — a freehand needle run, rendered as running / bean / satin.
* ``Region``  — a closed shape filled with parallel (tatami) rows.
* ``TextItem`` — lettering whose glyph outlines are filled like regions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

Point = Tuple[float, float]  # (x_mm, y_mm)

DEFAULT_STITCH_LENGTH_MM = 3.0
DEFAULT_HOOP_MM = (100.0, 100.0)

DEFAULT_SATIN_WIDTH_MM = 2.5
DEFAULT_FILL_SPACING_MM = 1.5
DEFAULT_FILL_ANGLE_DEG = 0.0
DEFAULT_TEXT_HEIGHT_MM = 14.0
DEFAULT_FONT_FAMILY = "Arial"

# Travel longer than this between two runs cuts the thread instead of leaving a
# jump thread connecting them (see pattern._stitch_object).
DEFAULT_TRIM_JUMP_MM = 1.0

# Stitch types available for a Stroke.
STITCH_RUNNING = "running"
STITCH_BEAN = "bean"
STITCH_SATIN = "satin"
STITCH_TYPES = [
    (STITCH_RUNNING, "Running"),
    (STITCH_BEAN, "Bean (triple)"),
    (STITCH_SATIN, "Satin"),
]

# A small palette of thread colours (name, "#rrggbb").
PALETTE = [
    ("Black", "#1a1a1a"),
    ("Red", "#d1495b"),
    ("Green", "#2a9d3a"),
    ("Blue", "#2a6fd1"),
    ("Gold", "#e0a800"),
    ("Purple", "#7b3fa0"),
    ("White", "#f5f5f5"),
]


@dataclass
class Stroke:
    """A single continuous run of the needle in one thread colour."""

    color: str = "#1a1a1a"          # "#rrggbb"
    stitch_length_mm: float = DEFAULT_STITCH_LENGTH_MM
    points: List[Point] = field(default_factory=list)
    stitch_type: str = STITCH_RUNNING
    width_mm: float = DEFAULT_SATIN_WIDTH_MM   # satin column width
    underlay: bool = True                      # satin: sew a stabilizing pass first

    def add_point(self, x_mm: float, y_mm: float) -> None:
        self.points.append((x_mm, y_mm))

    def translate(self, dx_mm: float, dy_mm: float) -> None:
        self.points = [(x + dx_mm, y + dy_mm) for x, y in self.points]

    def is_drawable(self) -> bool:
        return len(self.points) >= 2

    def to_dict(self) -> dict:
        return {
            "color": self.color,
            "stitch_length_mm": self.stitch_length_mm,
            "points": [list(p) for p in self.points],
            "stitch_type": self.stitch_type,
            "width_mm": self.width_mm,
            "underlay": self.underlay,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Stroke":
        return cls(
            color=data.get("color", "#1a1a1a"),
            stitch_length_mm=float(data.get("stitch_length_mm", DEFAULT_STITCH_LENGTH_MM)),
            points=[tuple(p) for p in data.get("points", [])],
            stitch_type=data.get("stitch_type", STITCH_RUNNING),
            width_mm=float(data.get("width_mm", DEFAULT_SATIN_WIDTH_MM)),
            underlay=bool(data.get("underlay", True)),
        )


@dataclass
class Region:
    """One or more closed contours filled with parallel (tatami) rows.

    A hand-drawn region has a single contour; a traced image colour can have
    many (separate blobs, plus inner contours for holes). The fill uses the
    even-odd rule across all of a region's contours, so holes are left open —
    the same way glyph counters work in :class:`TextItem`.
    """

    color: str = "#1a1a1a"
    contours: List[List[Point]] = field(default_factory=lambda: [[]])
    stitch_length_mm: float = DEFAULT_STITCH_LENGTH_MM   # stitch length along a row
    spacing_mm: float = DEFAULT_FILL_SPACING_MM          # gap between rows
    angle_deg: float = DEFAULT_FILL_ANGLE_DEG            # row direction
    underlay: bool = True                                # run the boundary first

    @property
    def points(self) -> List[Point]:
        """The primary contour — the buffer freehand drawing appends to."""
        return self.contours[0] if self.contours else []

    def add_point(self, x_mm: float, y_mm: float) -> None:
        if not self.contours:
            self.contours.append([])
        self.contours[-1].append((x_mm, y_mm))

    def all_points(self) -> List[Point]:
        return [p for contour in self.contours for p in contour]

    def translate(self, dx_mm: float, dy_mm: float) -> None:
        self.contours = [
            [(x + dx_mm, y + dy_mm) for x, y in contour] for contour in self.contours
        ]

    def is_drawable(self) -> bool:
        return any(len(contour) >= 3 for contour in self.contours)

    def to_dict(self) -> dict:
        return {
            "color": self.color,
            "contours": [[list(p) for p in c] for c in self.contours],
            "stitch_length_mm": self.stitch_length_mm,
            "spacing_mm": self.spacing_mm,
            "angle_deg": self.angle_deg,
            "underlay": self.underlay,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Region":
        if "contours" in data:
            contours = [[tuple(p) for p in c] for c in data["contours"]]
        else:  # legacy single-contour format
            contours = [[tuple(p) for p in data.get("points", [])]]
        return cls(
            color=data.get("color", "#1a1a1a"),
            contours=contours,
            stitch_length_mm=float(data.get("stitch_length_mm", DEFAULT_STITCH_LENGTH_MM)),
            spacing_mm=float(data.get("spacing_mm", DEFAULT_FILL_SPACING_MM)),
            angle_deg=float(data.get("angle_deg", DEFAULT_FILL_ANGLE_DEG)),
            underlay=bool(data.get("underlay", True)),
        )


@dataclass
class TextItem:
    """Lettering placed on the hoop, filled like a region from font outlines."""

    text: str = ""
    x_mm: float = 0.0                # top-left of the text's bounding box
    y_mm: float = 0.0
    height_mm: float = DEFAULT_TEXT_HEIGHT_MM
    font_family: str = DEFAULT_FONT_FAMILY
    color: str = "#1a1a1a"
    stitch_length_mm: float = DEFAULT_STITCH_LENGTH_MM
    spacing_mm: float = DEFAULT_FILL_SPACING_MM
    angle_deg: float = DEFAULT_FILL_ANGLE_DEG
    underlay: bool = True

    def translate(self, dx_mm: float, dy_mm: float) -> None:
        self.x_mm += dx_mm
        self.y_mm += dy_mm

    def is_drawable(self) -> bool:
        return bool(self.text.strip())

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "height_mm": self.height_mm,
            "font_family": self.font_family,
            "color": self.color,
            "stitch_length_mm": self.stitch_length_mm,
            "spacing_mm": self.spacing_mm,
            "angle_deg": self.angle_deg,
            "underlay": self.underlay,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TextItem":
        return cls(
            text=data.get("text", ""),
            x_mm=float(data.get("x_mm", 0.0)),
            y_mm=float(data.get("y_mm", 0.0)),
            height_mm=float(data.get("height_mm", DEFAULT_TEXT_HEIGHT_MM)),
            font_family=data.get("font_family", DEFAULT_FONT_FAMILY),
            color=data.get("color", "#1a1a1a"),
            stitch_length_mm=float(data.get("stitch_length_mm", DEFAULT_STITCH_LENGTH_MM)),
            spacing_mm=float(data.get("spacing_mm", DEFAULT_FILL_SPACING_MM)),
            angle_deg=float(data.get("angle_deg", DEFAULT_FILL_ANGLE_DEG)),
            underlay=bool(data.get("underlay", True)),
        )


@dataclass
class Design:
    """A whole embroidery design: a hoop area plus the objects drawn in it."""

    hoop_width_mm: float = DEFAULT_HOOP_MM[0]
    hoop_height_mm: float = DEFAULT_HOOP_MM[1]
    # Travel longer than this between runs is cut (trimmed) rather than leaving a
    # connector thread strung across the design.
    trim_jump_mm: float = DEFAULT_TRIM_JUMP_MM
    strokes: List[Stroke] = field(default_factory=list)
    regions: List[Region] = field(default_factory=list)
    texts: List[TextItem] = field(default_factory=list)

    # ---- construction helpers ----------------------------------------------
    def new_stroke(
        self,
        color: str,
        stitch_length_mm: float,
        stitch_type: str = STITCH_RUNNING,
        width_mm: float = DEFAULT_SATIN_WIDTH_MM,
        underlay: bool = True,
    ) -> Stroke:
        stroke = Stroke(
            color=color,
            stitch_length_mm=stitch_length_mm,
            stitch_type=stitch_type,
            width_mm=width_mm,
            underlay=underlay,
        )
        self.strokes.append(stroke)
        return stroke

    def new_region(
        self,
        color: str,
        stitch_length_mm: float,
        spacing_mm: float,
        angle_deg: float,
        underlay: bool = True,
    ) -> Region:
        region = Region(
            color=color,
            stitch_length_mm=stitch_length_mm,
            spacing_mm=spacing_mm,
            angle_deg=angle_deg,
            underlay=underlay,
        )
        self.regions.append(region)
        return region

    def add_text(self, item: TextItem) -> TextItem:
        self.texts.append(item)
        return item

    # ---- queries ------------------------------------------------------------
    def drawable_strokes(self) -> List[Stroke]:
        return [s for s in self.strokes if s.is_drawable()]

    def drawable_regions(self) -> List[Region]:
        return [r for r in self.regions if r.is_drawable()]

    def drawable_texts(self) -> List[TextItem]:
        return [t for t in self.texts if t.is_drawable()]

    def has_content(self) -> bool:
        return bool(
            self.drawable_strokes() or self.drawable_regions() or self.drawable_texts()
        )

    def is_empty(self) -> bool:
        return not (self.strokes or self.regions or self.texts)

    def clear(self) -> None:
        self.strokes.clear()
        self.regions.clear()
        self.texts.clear()

    # ---- serialization ------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "hoop_width_mm": self.hoop_width_mm,
            "hoop_height_mm": self.hoop_height_mm,
            "trim_jump_mm": self.trim_jump_mm,
            "strokes": [s.to_dict() for s in self.strokes],
            "regions": [r.to_dict() for r in self.regions],
            "texts": [t.to_dict() for t in self.texts],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Design":
        return cls(
            hoop_width_mm=float(data.get("hoop_width_mm", DEFAULT_HOOP_MM[0])),
            hoop_height_mm=float(data.get("hoop_height_mm", DEFAULT_HOOP_MM[1])),
            trim_jump_mm=float(data.get("trim_jump_mm", DEFAULT_TRIM_JUMP_MM)),
            strokes=[Stroke.from_dict(s) for s in data.get("strokes", [])],
            regions=[Region.from_dict(r) for r in data.get("regions", [])],
            texts=[TextItem.from_dict(t) for t in data.get("texts", [])],
        )
