"""Shared pytest fixtures.

The GUI-facing code (canvas, app, text outlines, image tracing) needs a Qt
application, so we force the headless "offscreen" platform *before* PySide6 is
imported and spin up a single QApplication for the whole session.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="session", autouse=True)
def qapp():
    """A process-wide QApplication (created once, offscreen)."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def logo_png(tmp_path):
    """A small flat-colour test image: red disk, green annulus, blue square.

    Returns the file path. The green shape has a transparent hole so tracing has
    a counter to preserve.
    """
    from PySide6.QtGui import QImage, QPainter, QColor, QBrush
    from PySide6.QtCore import Qt

    img = QImage(300, 200, QImage.Format_RGBA8888)
    img.fill(QColor(255, 255, 255, 0))  # transparent background
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, False)
    p.setPen(Qt.NoPen)

    p.setBrush(QBrush(QColor(220, 40, 40)))
    p.drawEllipse(20, 60, 80, 80)                     # red disk

    p.setBrush(QBrush(QColor(40, 180, 60)))
    p.drawEllipse(120, 50, 90, 90)                    # green disk...
    p.setCompositionMode(QPainter.CompositionMode_Clear)
    p.drawEllipse(150, 80, 30, 30)                    # ...with a hole punched out
    p.setCompositionMode(QPainter.CompositionMode_SourceOver)

    p.setBrush(QBrush(QColor(40, 90, 210)))
    p.drawRect(230, 70, 50, 50)                       # blue square
    p.end()

    path = tmp_path / "logo.png"
    assert img.save(str(path))
    return str(path)
