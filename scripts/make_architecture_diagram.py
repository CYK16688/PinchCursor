#!/usr/bin/env python3
"""Render the runtime-architecture figure used by the README.

The diagram is generated instead of hand-drawn so that a change to the pipeline
is a one-line edit here, and so the standalone SVG and the HTML page can never
drift apart. Everything is inline: no fonts are fetched, no images are linked,
and the figure carries its own background so it reads the same on GitHub, in a
slide deck, and in a print preview.

    .venv/bin/python scripts/make_architecture_diagram.py

Writes docs/architecture.svg and docs/architecture.html.
"""

from __future__ import annotations

import pathlib

BASE = pathlib.Path(__file__).resolve().parents[1]
OUT_SVG = BASE / "docs" / "architecture.svg"
OUT_HTML = BASE / "docs" / "architecture.html"

# Light skin derived from the app's own dark palette (accent #5E8CFF), darkened
# until it clears 4.5:1 as text on paper. System stacks only: GitHub serves SVGs
# without external webfonts, so a downloaded Geist would silently fall back.
PAPER = "#F7F8FB"
ZONE_MASK = "#F2F3F7"  # paper composited under the 2% zone wash
SURFACE = "#FFFFFF"
INK = "#12141A"
MUTED = "#4A5364"
SOFT = "#6C7585"
ACCENT = "#2F5BD0"
ACCENT_TINT = ACCENT
RULE = "#12141A"
RULE_SOLID = "#12141A"
SANS = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "'SF Mono', Menlo, Consolas, monospace"
SERIF = "Georgia, 'Times New Roman', serif"

W, H = 1200, 720

# kind: normal = a component, focal = the deterministic lane, external = outside
# the process, passive = local disk.
NODES = [
    dict(x=68, y=140, w=340, h=64, tag="MAIN", name="Qt shell",
         sub="MainWindow · Settings · HUD · gate", kind="normal"),
    dict(x=828, y=140, w=300, h=64, tag="DISK", name="Local store",
         sub="settings.json · telemetry*", kind="passive"),
    dict(x=68, y=316, w=228, h=84, tag="WORKER", name="Capture &amp; detect",
         sub="camera + MediaPipe · 21 pts", kind="normal"),
    dict(x=348, y=316, w=228, h=84, tag="CORE", name="Track &amp; classify",
         sub="smooth · poses · DTW", kind="normal"),
    dict(x=628, y=316, w=228, h=84, tag="CORE", name="Arbiter",
         sub="combos · context · guard", kind="normal"),
    dict(x=908, y=316, w=228, h=84, tag="CORE", name="State machine",
         sub="move · click · drag", kind="focal"),
    dict(x=952, y=536, w=200, h=64, tag="NATIVE", name="native.py",
         sub="CGEvent · AXUIElement", kind="normal"),
    dict(x=642, y=536, w=200, h=64, tag="OS", name="macOS",
         sub="camera · accessibility", kind="external"),
]

PIPELINE_Y = 358
ARROWS = [
    # frame path
    ("M296,358 H348", "solid", "muted", "FRAMES"),
    ("M576,358 H628", "solid", "muted", "POINTS"),
    ("M856,358 H908", "solid", "muted", "INTENT"),
    # the side effect the whole pipeline exists for
    ("M1022,400 V536", "solid", "accent", "ACTION"),
    # platform boundary
    ("M952,568 H842", "solid", "muted", "CG / AX"),
    # feedback that makes the next click smarter than the last one
    ("M820,536 V470 Q820,462 828,462 H952 Q960,462 960,454 V400", "dashed", "link", "AX TARGETS"),
    # the session gate: nothing runs until the user starts it
    ("M272,204 V316", "dashed", "muted", "START / STOP"),
    # configuration is read, never written by the pipeline
    ("M408,172 H828", "dashed", "muted", "CONFIG"),
]

LABELS = {
    # text: (mask_x, mask_y, mask_w, text_x, text_y, mask_fill)
    "FRAMES": (299, 336, 46, 322, 347, ZONE_MASK),
    "POINTS": (579, 336, 46, 602, 347, ZONE_MASK),
    "INTENT": (859, 336, 46, 882, 347, ZONE_MASK),
    "ACTION": (1032, 476, 56, 1060, 487, ZONE_MASK),
    "CG / AX": (869, 546, 48, 893, 557, ZONE_MASK),
    "AX TARGETS": (854, 440, 72, 890, 451, ZONE_MASK),
    "START / STOP": (279, 234, 86, 322, 245, PAPER),
    "CONFIG": (586, 150, 56, 614, 161, ZONE_MASK),
}


def node_svg(n: dict) -> str:
    x, y, w, h = n["x"], n["y"], n["w"], n["h"]
    cx = x + w / 2
    kind = n["kind"]
    if kind == "focal":
        fill, fill_op, stroke, stroke_op, sw, dash = ACCENT, "0.07", ACCENT, "1", "1.4", ""
        tag_stroke, tag_fill, name_fill = ACCENT, ACCENT, INK
    elif kind == "external":
        fill, fill_op, stroke, stroke_op, sw, dash = INK, "0.03", INK, "0.28", "1", ' stroke-dasharray="5,4"'
        tag_stroke, tag_fill, name_fill = MUTED, MUTED, INK
    elif kind == "passive":
        fill, fill_op, stroke, stroke_op, sw, dash = INK, "0.02", INK, "0.28", "1", ' stroke-dasharray="5,4"'
        tag_stroke, tag_fill, name_fill = MUTED, MUTED, INK
    else:
        fill, fill_op, stroke, stroke_op, sw, dash = SURFACE, "1", INK, "0.28", "1", ""
        tag_stroke, tag_fill, name_fill = MUTED, MUTED, INK

    name_y = y + (40 if h > 70 else 34)
    sub_y = name_y + 18
    return f"""    <g>
      <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{PAPER}"/>
      <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" fill-opacity="{fill_op}" stroke="{stroke}" stroke-opacity="{stroke_op}" stroke-width="{sw}"{dash}/>
      <rect x="{x + 10}" y="{y + 8}" width="46" height="12" rx="2" fill="none" stroke="{tag_stroke}" stroke-opacity="0.45" stroke-width="0.8"/>
      <text x="{x + 33}" y="{y + 17}" fill="{tag_fill}" font-family="{MONO}" font-size="8.5" letter-spacing="0.08em" text-anchor="middle">{n['tag']}</text>
      <text x="{cx}" y="{name_y}" fill="{name_fill}" font-family="{SANS}" font-size="15" font-weight="600" text-anchor="middle">{n['name']}</text>
      <text x="{cx}" y="{sub_y}" fill="{MUTED}" font-family="{MONO}" font-size="10" text-anchor="middle">{n['sub']}</text>
    </g>"""


def arrow_svg(path: str, style: str, color: str, label: str) -> tuple[str, str]:
    stroke = {"muted": MUTED, "accent": ACCENT, "link": "#2E5AA8"}[color]
    marker = {"muted": "arrow", "accent": "arrow-accent", "link": "arrow-link"}[color]
    dash = ' stroke-dasharray="5,4"' if style == "dashed" else ""
    weight = "1" if style == "dashed" else "1.2"
    line = (f'    <path d="{path}" fill="none" stroke="{stroke}" stroke-width="{weight}"'
            f'{dash} marker-end="url(#{marker})"/>')
    mx, my, mw, tx, ty, mask = LABELS[label]
    text = (f'    <rect x="{mx}" y="{my}" width="{mw}" height="13" rx="2" fill="{mask}"/>\n'
            f'    <text x="{tx}" y="{ty}" fill="{MUTED}" font-family="{MONO}" font-size="9"'
            f' letter-spacing="0.06em" text-anchor="middle">{label}</text>')
    return line, text


def build_svg() -> str:
    arrows = [arrow_svg(*a) for a in ARROWS]
    arrow_paths = "\n".join(a for a, _ in arrows)
    arrow_labels = "\n".join(b for _, b in arrows)
    nodes = "\n".join(node_svg(n) for n in NODES)

    def zone(y: int, h: int, label: str, label_w: int) -> str:
        return f"""    <rect x="32" y="{y}" width="1136" height="{h}" rx="8" fill="{RULE}" fill-opacity="0.02" stroke="{RULE}" stroke-opacity="0.12" stroke-width="0.8"/>
    <rect x="46" y="{y + 7}" width="{label_w}" height="15" rx="2" fill="{ZONE_MASK}"/>
    <text x="54" y="{y + 19}" fill="{SOFT}" font-family="{MONO}" font-size="9.5" letter-spacing="0.14em">{label}</text>"""

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="pinchcursor-arch-title pinchcursor-arch-desc" font-family="{SANS}">
  <title id="pinchcursor-arch-title">PinchCursor runtime architecture</title>
  <desc id="pinchcursor-arch-desc">Camera frames are captured and turned into hand landmarks on a worker thread, classified and arbitrated on the main thread, and executed as native pointer events, with accessibility targets feeding back into the arbiter.</desc>
  <defs>
    <marker id="arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{MUTED}"/></marker>
    <marker id="arrow-accent" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{ACCENT}"/></marker>
    <marker id="arrow-link" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="#2E5AA8"/></marker>
  </defs>

  <rect width="{W}" height="{H}" fill="{PAPER}"/>

  <text x="32" y="40" fill="{SOFT}" font-family="{MONO}" font-size="9" letter-spacing="0.16em">PINCHCURSOR · RUNTIME ARCHITECTURE</text>
  <text x="32" y="78" fill="{INK}" font-family="{SERIF}" font-size="31" letter-spacing="-0.01em">Camera in, OS events out, deterministic in between.</text>

{zone(100, 128, "UI · MAIN THREAD", 118)}
{zone(260, 196, "DECISION CORE · QT-FREE PYTHON", 216)}
{zone(488, 140, "PLATFORM · CTYPES BOUNDARY", 178)}

{arrow_paths}

{arrow_labels}

{nodes}

  <line x1="32" y1="654" x2="1168" y2="654" stroke="{RULE}" stroke-opacity="0.12" stroke-width="0.8"/>
  <text x="32" y="674" fill="{MUTED}" font-family="{MONO}" font-size="9.5" letter-spacing="0.14em">LEGEND</text>
  <line x1="96" y1="672" x2="128" y2="672" stroke="{MUTED}" stroke-width="1.2"/>
  <text x="138" y="675" fill="{SOFT}" font-family="{MONO}" font-size="8.5" letter-spacing="0.06em">FRAME PATH</text>
  <line x1="240" y1="672" x2="272" y2="672" stroke="{MUTED}" stroke-width="1" stroke-dasharray="5,4"/>
  <text x="280" y="675" fill="{SOFT}" font-family="{MONO}" font-size="8.5" letter-spacing="0.06em">CONTROL / FEEDBACK</text>
  <line x1="452" y1="672" x2="484" y2="672" stroke="{ACCENT}" stroke-width="1.2"/>
  <text x="492" y="675" fill="{SOFT}" font-family="{MONO}" font-size="8.5" letter-spacing="0.06em">DETERMINISTIC LANE</text>
  <rect x="660" y="666" width="24" height="12" rx="2" fill="none" stroke="{RULE_SOLID}" stroke-opacity="0.28" stroke-width="1" stroke-dasharray="5,4"/>
  <text x="692" y="675" fill="{SOFT}" font-family="{MONO}" font-size="8.5" letter-spacing="0.06em">OUTSIDE THE PROCESS</text>
  <text x="1168" y="675" fill="{SOFT}" font-family="{MONO}" font-size="8.5" text-anchor="end">* telemetry is opt-in; no frames or titles are stored</text>
</svg>
"""


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PinchCursor runtime architecture</title>
<style>
  body {{ margin: 0; padding: 48px 32px; background: {paper}; font-family: {sans}; }}
  .wrap {{ max-width: 1200px; margin: 0 auto; overflow-x: auto; }}
  svg {{ display: block; width: 100%; min-width: 720px; height: auto; }}
  @media print {{ .wrap {{ overflow: visible; }} svg {{ min-width: 0; }} }}
</style>
</head>
<body>
<div class="wrap">
{svg}
</div>
</body>
</html>
"""


def main() -> None:
    svg = build_svg()
    OUT_SVG.parent.mkdir(parents=True, exist_ok=True)
    OUT_SVG.write_text(svg, encoding="utf-8")
    OUT_HTML.write_text(HTML.format(paper=PAPER, sans=SANS, svg=svg), encoding="utf-8")
    print(f"wrote {OUT_SVG.relative_to(BASE)} ({len(svg)} bytes)")
    print(f"wrote {OUT_HTML.relative_to(BASE)}")


if __name__ == "__main__":
    main()
