# SPDX-License-Identifier: MIT
"""Tests for turning text into glyph contours (needs Qt)."""

from stitcher.text import text_to_contours, text_size_mm


def test_blank_text_has_no_contours():
    assert text_to_contours("", "Arial", 20.0) == []
    assert text_to_contours("   ", "Arial", 20.0) == []


def test_letter_with_counter_has_multiple_contours():
    # "O" -> outer outline plus the inner counter
    contours = text_to_contours("O", "Arial", 40.0)
    assert len(contours) >= 2
    assert all(len(c) >= 3 for c in contours)


def test_text_height_matches_request():
    w, h = text_size_mm("Hg", "Arial", 30.0)
    assert abs(h - 30.0) < 1.0     # bounding box height == requested height
    assert w > 0


def test_contours_positioned_at_origin():
    contours = text_to_contours("A", "Arial", 20.0, x_mm=10.0, y_mm=5.0)
    xs = [x for c in contours for x, _ in c]
    ys = [y for c in contours for _, y in c]
    # top-left of the bounding box sits at (x_mm, y_mm)
    assert min(xs) == max(min(xs), 10.0) and abs(min(xs) - 10.0) < 0.5
    assert abs(min(ys) - 5.0) < 0.5
