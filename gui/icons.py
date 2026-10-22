"""Inline SVG icon set for the app's own chrome.

Drawn on a 24×24 grid with a 1.8 stroke and round joins so a 14–18px render
stays legible. Paths are authored here rather than shipped as files: they must
recolor per state (muted label, accent selection, white on button), and Qt style
sheets cannot tint an SVG image.

Icons here are **navigation and state chrome**, not decoration. Each one replaces
a word the operator would otherwise have to read: a sidebar label, a summary
heading, a gesture identity, a button verb.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_VIEWBOX = 24
_STROKE = 1.8

# Phosphor Icons 'hand-palm' (MIT) — the same glyph the HUD and the gesture
# list use, so the product keeps one hand silhouette everywhere.
_HAND_SOLID = (
    '<path d="M216,64v90.93c0,46.2-36.85,84.55-83,85.06A83.71,83.71,0,0,1,72.6,215.4C50.79,192.33,26.15,136,26.15,136a16,16,0,0,1,6.53-22.23c7.66-4,17.1-.84,21.4,6.62l21,36.44a6.09,6.09,0,0,0,6,3.09l.12,0A8.19,8.19,0,0,0,88,151.74V48a16,16,0,0,1,16.77-16c8.61.4,15.23,7.82,15.23,16.43V112a8,8,0,0,0,8.53,8,8.17,8.17,0,0,0,7.47-8.25V32a16,16,0,0,1,16.77-16c8.61.4,15.23,7.82,15.23,16.43V120a8,8,0,0,0,8.53,8,8.17,8.17,0,0,0,7.47-8.25V64.45c0-8.61,6.62-16,15.23-16.43A16,16,0,0,1,216,64Z"/>'
)


def _gear() -> str:
    """Six teeth set clear of the hub.

    Teeth that touch the hub circle merge into a single ring at 16px — the gap
    is what makes the shape read as a gear rather than a target.
    """
    spokes = []
    for index in range(6):
        angle = math.radians(index * 60)
        x1, y1 = 12 + 6.1 * math.cos(angle), 12 + 6.1 * math.sin(angle)
        x2, y2 = 12 + 9.4 * math.cos(angle), 12 + 9.4 * math.sin(angle)
        spokes.append(f'<path d="M{x1:.2f} {y1:.2f}L{x2:.2f} {y2:.2f}"/>')
    return '<circle cx="12" cy="12" r="4.6"/>' + "".join(spokes)


# Stroke icons: currentColor is supplied at render time.
_STROKED = {
    # Control session: sliders, the universal "settings that change behaviour".
    "sliders": (
        '<path d="M4 6.5h3.2"/><circle cx="9.6" cy="6.5" r="2.4"/><path d="M12 6.5H20"/>'
        '<path d="M4 12h8.4"/><circle cx="15" cy="12" r="2.4"/><path d="M17.4 12H20"/>'
        '<path d="M4 17.5h4.7"/><circle cx="11.1" cy="17.5" r="2.4"/><path d="M13.5 17.5H20"/>'
    ),
    # Gestures: the product's own filled hand glyph. A stroked hand dissolves
    # into a blob at 16px, and this is the one shape the app is about.
    "hand": "HAND_SOLID",
    "camera": (
        '<rect x="3" y="7" width="18" height="12.5" rx="3"/>'
        '<circle cx="12" cy="13.2" r="3.6"/>'
        '<path d="M8.8 7l1.3-2.3h3.8L15.2 7"/>'
    ),
    # Feedback: a level meter, not a bell — the HUD is about signal, not alerts.
    "meter": (
        '<path d="M4 13.5v-3"/><path d="M8 16.5v-9"/><path d="M12 19v-14"/>'
        '<path d="M16 16.5v-9"/><path d="M20 13.5v-3"/>'
    ),
    # Permissions: shield with a check.
    "shield": (
        '<path d="M12 3.4l7 2.6v5.4c0 4.4-2.9 7.4-7 9-4.1-1.6-7-4.6-7-9V6z"/>'
        '<path d="M9.1 12.1l2.1 2.1 3.8-4"/>'
    ),
    "gear": _gear(),
    # Activation: a lightning bolt reads as "this is what starts it".
    "bolt": '<path d="M13.4 3.2L6 13.4h4.7L10.6 20.8 18 10.6h-4.7z"/>',
    # Recent action: clock.
    "history": '<circle cx="12" cy="12" r="8.2"/><path d="M12 7.6v4.9l3.2 1.9"/>',
    "refresh": (
        '<path d="M19.6 12a7.6 7.6 0 1 1-2.2-5.4"/>'
        '<path d="M19.9 4.4v4.2h-4.2"/>'
    ),
    "record": '<circle cx="12" cy="12" r="7.6"/><circle cx="12" cy="12" r="3.4" fill="{c}" stroke="none"/>',
    "check": '<path d="M5.5 12.6l4.2 4.2 8.8-9"/>',
    "close": '<path d="M7 7l10 10"/><path d="M17 7L7 17"/>',
    "plus": '<path d="M12 5.5v13"/><path d="M5.5 12h13"/>',
    "chevron_right": '<path d="M9.5 6l6 6-6 6"/>',
}

# Solid glyphs: button verbs need mass to read at 16px.
_FILLED = {
    "play": '<path d="M8.6 5.2l10.2 6.8-10.2 6.8z"/>',
    "stop": '<rect x="6.6" y="6.6" width="10.8" height="10.8" rx="2.2"/>',
}


def _svg(name: str, color: str) -> str:
    if name == "hand":
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">'
            f'<g fill="{color}">{_HAND_SOLID}</g></svg>'
        )
    if name in _FILLED:
        body = f'<g fill="{color}" stroke="none">{_FILLED[name]}</g>'
        stroke = "none"
    else:
        body = _STROKED[name].replace("{c}", color)
        stroke = color
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_VIEWBOX} {_VIEWBOX}" '
        f'fill="none" stroke="{stroke}" stroke-width="{_STROKE}" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )


def available() -> tuple[str, ...]:
    return tuple(sorted({*_STROKED, *_FILLED}))


def pixmap(name: str, color: str = "#8B93A1", size: int = 16) -> QPixmap:
    """Render one icon at the requested pixel size (HiDPI-aware)."""
    renderer = QSvgRenderer(QByteArray(_svg(name, color).encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


def padded_pixmap(name: str, color: str, size: int, extra_right: int) -> QPixmap:
    """Glyph plus transparent space, so list text is not glued to the icon."""
    base = pixmap(name, color, size)
    padded = QPixmap(size + extra_right, size)
    padded.fill(Qt.transparent)
    painter = QPainter(padded)
    painter.drawPixmap(0, 0, base)
    painter.end()
    return padded


def icon(name: str, color: str = "#8B93A1", size: int = 16) -> QIcon:
    return QIcon(pixmap(name, color, size))


APP_MARK_VIEWBOX = 1024


def app_mark_svg(hand_color: str = "#FFFFFF", tile_color: str = "#5E8CFF") -> str:
    """The product mark: a pointer emerging through a lock ring, on a tile.

    The ring is the same shape the HUD shows at the moment a target locks, and
    the break in it sits exactly where the pointer points, so the mark reads as
    "aim, then lock" instead of as another cursor glyph. ``hand_color`` keeps its
    historical name so callers and the icon script stay unchanged.

    Shared by the in-app header, the window icon, and the .icns the bundle ships
    so the Dock, the header and the About panel cannot drift apart.
    """
    # Classic pointer silhouette, authored in a unit box with the tip at 0,0.
    pointer = "M0 0 L0 15 L4 11 L6.6 16.4 L9.4 15.2 L6.8 9.9 L11.6 9.9 Z"
    # Ring: r=250 around (470,470) with a 64 degree gap facing the pointer tip
    # at 225 degrees. Two round-capped arcs are clearer than a dashed circle.
    ring = "M413.8 226.4 A250 250 0 1 1 226.4 413.8"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {APP_MARK_VIEWBOX} {APP_MARK_VIEWBOX}">'
        f'<defs>'
        f'<linearGradient id="tile" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="#5E8CFF"/>'
        f'<stop offset="1" stop-color="{tile_color}"/>'
        f'</linearGradient>'
        f'</defs>'
        f'<rect width="{APP_MARK_VIEWBOX}" height="{APP_MARK_VIEWBOX}" '
        f'rx="228" fill="url(#tile)"/>'
        f'<path d="{ring}" fill="none" stroke="{hand_color}" '
        f'stroke-width="34" stroke-linecap="round" opacity="0.72"/>'
        f'<g transform="translate(360 280) scale(24)" fill="{hand_color}">'
        f'<path d="{pointer}"/></g>'
        f'</svg>'
    )


def app_icon() -> QIcon:
    """Multi-resolution window/Dock icon built from the same mark."""
    icon = QIcon()
    for size in (16, 32, 64, 128, 256, 512):
        icon.addPixmap(app_mark(size))
    return icon


def app_mark(size: int = 26, hand_color: str = "#FFFFFF") -> QPixmap:
    """Rasterise the product mark at the requested size."""
    renderer = QSvgRenderer(QByteArray(app_mark_svg(hand_color).encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap
