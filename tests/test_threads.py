# SPDX-License-Identifier: MIT
"""Tests for the named thread catalogs (no Qt needed)."""

from stitcher import threads


def test_default_catalog_is_first_and_nonempty():
    names = threads.catalog_names()
    assert names[0] == threads.DEFAULT_CATALOG
    assert len(threads.catalog_threads()) > 0


def test_catalog_thread_has_name_number_and_hex():
    info = threads.catalog_threads()[0]
    assert info.description
    assert info.hex.startswith("#") and len(info.hex) == 7
    # label is a compact one-liner mentioning the brand
    assert info.brand in info.label


def test_nearest_returns_an_exact_match_for_a_catalog_colour():
    first = threads.catalog_threads()[0]
    match = threads.nearest(first.hex)
    assert match is not None
    assert match.hex == first.hex           # a catalogue colour maps to itself


def test_nearest_snaps_an_arbitrary_colour_to_a_real_spool():
    match = threads.nearest("#1188cc")
    assert match is not None
    assert match.description                # it has a human name
    assert match.hex.startswith("#")
