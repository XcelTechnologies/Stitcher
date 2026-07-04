# SPDX-License-Identifier: MIT
"""Named thread catalogs, backed by pyembroidery's built-in colour charts.

pyembroidery ships real manufacturer palettes (Brother/Pec, Janome/Jef, Husqvarna,
Pfaff, …), each entry carrying a colour plus a human name and catalogue number.
This module exposes those as light-weight :class:`ThreadInfo` records and offers a
nearest-colour lookup so any ``#rrggbb`` used in a design can be named against a
real spool — used by the palette picker and the thread worksheet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import pyembroidery as pe


@dataclass(frozen=True)
class ThreadInfo:
    """One catalogue thread: a colour with a name, number and brand."""

    description: str
    catalog_number: str
    brand: str
    hex: str          # "#rrggbb" of the catalogue colour itself

    @property
    def label(self) -> str:
        """A compact one-line name, e.g. ``"Sky Blue (Brother 32)"``."""
        num = f" {self.catalog_number}".rstrip()
        return f"{self.description} ({self.brand}{num})"


# Brand -> the pyembroidery thread class holding that chart.
_CATALOG_CLASSES = {
    "Brother": pe.EmbThreadPec,
    "Janome": pe.EmbThreadJef,
    "Husqvarna": pe.EmbThreadHus,
    "Husqvarna Viking": pe.EmbThreadShv,
    "Janome (Sew)": pe.EmbThreadSew,
}

DEFAULT_CATALOG = "Brother"


def _hex(thread: pe.EmbThread) -> str:
    return "#%02x%02x%02x" % (thread.get_red(), thread.get_green(), thread.get_blue())


def _load(brand: str) -> List[pe.EmbThread]:
    cls = _CATALOG_CLASSES.get(brand, _CATALOG_CLASSES[DEFAULT_CATALOG])
    return [t for t in cls.get_thread_set() if t is not None]


# Threads are static data — build each chart once and reuse it.
_THREADS: Dict[str, List[pe.EmbThread]] = {}


def _threads(brand: str) -> List[pe.EmbThread]:
    if brand not in _THREADS:
        _THREADS[brand] = _load(brand)
    return _THREADS[brand]


def catalog_names() -> List[str]:
    """The brands available as thread charts, default first."""
    names = list(_CATALOG_CLASSES)
    names.remove(DEFAULT_CATALOG)
    return [DEFAULT_CATALOG] + names


def _info(thread: pe.EmbThread, brand: str) -> ThreadInfo:
    return ThreadInfo(
        description=thread.description or "Thread",
        catalog_number=str(thread.catalog_number or "").strip(),
        brand=thread.brand or brand,
        hex=_hex(thread),
    )


def catalog_threads(brand: str = DEFAULT_CATALOG) -> List[ThreadInfo]:
    """Every thread in a brand's chart as :class:`ThreadInfo` records."""
    return [_info(t, brand) for t in _threads(brand)]


def nearest(hex_color: str, brand: str = DEFAULT_CATALOG) -> Optional[ThreadInfo]:
    """The catalogue thread closest in colour to ``hex_color`` (or None if empty)."""
    threads = _threads(brand)
    if not threads:
        return None
    probe = pe.EmbThread()
    probe.set_hex_color(hex_color)
    idx = probe.find_nearest_color_index(threads)
    if idx is None or not (0 <= idx < len(threads)):
        return None
    return _info(threads[idx], brand)
