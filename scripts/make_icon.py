"""Generate the macOS .icns and the PNG previews from one SVG mark.

The mark lives in `gui/icons.py` so the in-app header, the window icon and the
bundle icon cannot drift apart. Re-run after changing `app_mark_svg()`.

    python scripts/make_icon.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QByteArray, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QPainter, QPixmap  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

from gui.icons import app_mark_svg  # noqa: E402

# iconutil expects this exact naming for a complete iconset.
SIZES = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


def render(size: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(app_mark_svg().encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


def main() -> int:
    app = QGuiApplication([])  # required before rendering QPixmaps offscreen
    assets = ROOT / "assets"
    iconset = assets / "AppIcon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)

    for name, size in SIZES.items():
        if not render(size).save(str(iconset / name), "PNG"):
            print(f"failed to write {name}", file=sys.stderr)
            return 1

    icns = assets / "app.icns"
    result = subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(icns)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(result.stderr or result.stdout, file=sys.stderr)
        return result.returncode

    # The iconset is a build input, not a shipped asset.
    shutil.rmtree(iconset)
    print(f"wrote {icns.relative_to(ROOT)} ({icns.stat().st_size} bytes)")
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
