"""Shipped marks must load in source/frozen apps and native icon containers."""

from pathlib import Path
import shutil
import struct
import subprocess
import sys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from gui.icons import app_mark, app_mark_path

ROOT = Path(__file__).resolve().parents[1]


def test_source_mark_has_transparent_corners_and_opaque_artwork():
    image = QImage(str(app_mark_path()))
    assert not image.isNull()
    assert image.width() == image.height() >= 1024
    assert image.hasAlphaChannel()
    for x, y in ((0, 0), (image.width() - 1, image.height() - 1)):
        assert image.pixelColor(x, y).alpha() == 0
    assert image.pixelColor(image.width() // 2, image.height() // 2).alpha() >= 250


def test_frozen_mark_loads_without_source_checkout(qapp, tmp_path, monkeypatch):
    destination = tmp_path / 'gui' / 'resources' / 'pinchcursor.png'
    destination.parent.mkdir(parents=True)
    shutil.copyfile(app_mark_path(), destination)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    assert app_mark_path() == destination
    mark = app_mark(26, ratio=2)
    assert not mark.isNull()
    assert mark.deviceIndependentSize().toTuple() == (26, 26)
    assert mark.toImage().pixelColor(0, 0).alpha() == 0


def test_shipped_windows_icon_contains_current_mark_at_every_resolution():
    data = (ROOT / 'assets' / 'app.ico').read_bytes()
    reserved, kind, count = struct.unpack_from('<HHH', data)
    assert (reserved, kind) == (0, 1)
    source = QImage(str(app_mark_path()))
    dimensions = set()
    end = 6 + count * 16
    for index in range(count):
        width, height, colors, reserved, planes, bits, length, offset = struct.unpack_from('<BBBBHHII', data, 6 + index * 16)
        width, height = width or 256, height or 256
        assert offset == end
        assert (width, planes, bits, colors, reserved) == (height, 1, 32, 0, 0)
        frame = QImage.fromData(data[offset:offset + length], 'PNG')
        assert not frame.isNull()
        assert frame.size().toTuple() == (width, height)
        expected = source.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        assert frame.convertToFormat(QImage.Format_RGBA8888) == expected.convertToFormat(QImage.Format_RGBA8888)
        dimensions.add(width)
        end = offset + length
    assert dimensions == {16, 24, 32, 48, 64, 128, 256}
    assert end == len(data)


@pytest.mark.skipif(sys.platform != 'darwin', reason='iconutil is macOS-only')
def test_shipped_macos_icon_decodes_to_current_mark(tmp_path):
    iconset = tmp_path / 'AppIcon.iconset'
    subprocess.run(['iconutil', '-c', 'iconset', str(ROOT / 'assets' / 'app.icns'), '-o', str(iconset)], check=True)
    source = QImage(str(app_mark_path()))
    for name, size in (('icon_16x16.png', 16), ('icon_128x128.png', 128), ('icon_512x512@2x.png', 1024)):
        frame = QImage(str(iconset / name))
        assert not frame.isNull()
        expected = source.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        assert frame.size().toTuple() == (size, size)
        assert frame.pixelColor(0, 0).alpha() == 0
        # iconutil reconstructs legacy 16px entries with its own resampling.
        # Larger entries preserve the pixels, but gain an sRGB metadata tag.
        if size >= 128:
            actual_pixels = frame.convertToFormat(QImage.Format_RGBA8888_Premultiplied)
            expected_pixels = expected.convertToFormat(QImage.Format_RGBA8888_Premultiplied)
            assert bytes(actual_pixels.constBits()) == bytes(expected_pixels.constBits())
