"""Export platform icons from gui/resources/pinchcursor.png.

Run with the project's Python environment. ICO is exported on every platform;
macOS additionally exports ICNS with iconutil. Intermediate files are temporary.
"""

from __future__ import annotations

import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "gui" / "resources" / "pinchcursor.png"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
# iconutil expects this exact naming for a complete iconset.
ICNS_SIZES = {
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


def load_source(path: Path = SOURCE) -> QImage:
    image = QImage(str(path))
    if image.isNull() or image.width() != image.height():
        raise ValueError(f"Expected a valid square app icon: {path}")
    return image


def png_bytes(image: QImage, size: int) -> bytes:
    scaled = image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    if not scaled.save(buffer, "PNG"):
        raise RuntimeError(f"Cannot export {size}px app icon")
    return bytes(buffer.data())


def export_ico(image: QImage, destination: Path) -> None:
    """Package PNG resolutions in the Windows Vista+ ICO container."""
    frames = [png_bytes(image, size) for size in ICO_SIZES]
    offset = 6 + 16 * len(frames)
    directory = bytearray(struct.pack("<HHH", 0, 1, len(frames)))
    for size, frame in zip(ICO_SIZES, frames):
        dimension = 0 if size == 256 else size
        directory.extend(struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(frame), offset))
        offset += len(frame)
    destination.write_bytes(bytes(directory) + b"".join(frames))


def export_icns(image: QImage, destination: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="pinchcursor-icon-") as temporary:
        iconset = Path(temporary) / "AppIcon.iconset"
        iconset.mkdir()
        for name, size in ICNS_SIZES.items():
            (iconset / name).write_bytes(png_bytes(image, size))
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(destination.resolve())],
            check=True,
        )


def main() -> int:
    image = load_source()
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    ico = assets / "app.ico"
    export_ico(image, ico)
    print(f"wrote {ico.relative_to(ROOT)} ({ico.stat().st_size} bytes)")
    if sys.platform == "darwin":
        icns = assets / "app.icns"
        export_icns(image, icns)
        print(f"wrote {icns.relative_to(ROOT)} ({icns.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
