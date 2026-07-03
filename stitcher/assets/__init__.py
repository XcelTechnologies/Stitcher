# SPDX-License-Identifier: MIT
"""App icon assets, plus a helper to regenerate the raster icons from the SVG.

The canonical logo is ``icon.svg``. Run :func:`regenerate` after changing it to
refresh the runtime PNG and the packaging icons (macOS ``.icns`` / Windows
``.ico``) that ``build.py`` hands to PyInstaller.
"""

from __future__ import annotations

import os
import sys

ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_SVG = os.path.join(ASSETS_DIR, "icon.svg")
_PACKAGING = os.path.join(os.path.dirname(os.path.dirname(ASSETS_DIR)), "packaging")


def regenerate() -> None:
    """Render icon.svg into the runtime PNG and the macOS/Windows app icons."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtCore import Qt
    from PySide6.QtSvg import QSvgRenderer

    QApplication.instance() or QApplication(sys.argv)

    def render(size: int) -> QImage:
        renderer = QSvgRenderer(ICON_SVG)
        if not renderer.isValid():
            raise RuntimeError(f"Cannot read {ICON_SVG}")
        img = QImage(size, size, QImage.Format_RGBA8888)
        img.fill(Qt.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing, True)
        renderer.render(painter)
        painter.end()
        return img

    targets = [
        (render(256), os.path.join(ASSETS_DIR, "icon.png")),
        (render(1024), os.path.join(_PACKAGING, "Stitcher.icns")),
        (render(256), os.path.join(_PACKAGING, "Stitcher.ico")),
    ]
    for img, path in targets:
        if not img.save(path):
            raise RuntimeError(f"Failed to write {path}")
        print("wrote", path)


if __name__ == "__main__":
    regenerate()
