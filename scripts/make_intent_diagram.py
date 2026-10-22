#!/usr/bin/env python3
"""Render the intent-resolution figure used by the README.

The overview figure answers "which thread owns what". This one answers the next
question: what has to be true before the pointer moves. Each stage on the spine
is a veto, and the four lanes below it are mutually exclusive — the arbiter hands
the frame to exactly one of them.

    .venv/bin/python scripts/make_intent_diagram.py

Writes docs/intent-pipeline.svg and docs/intent-pipeline.html.
"""

from __future__ import annotations

import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

# One palette, shared with the overview figure so the two cannot drift apart.
from make_architecture_diagram import (  # noqa: E402
    ACCENT, INK, MONO, MUTED, PAPER, SANS, SERIF, SOFT, SURFACE, ZONE_MASK,
)

LINK = "#2E5AA8"
W, H = 1000, 1100

SPINE_X, SPINE_W, SPINE_H = 100, 440, 62
SPINE = [
    (148, "WORKER", "Landmarks", "21 points · worker thread", False),
    (240, "CORE", "Track", "smooth · predict on loss · edge hold", False),
    (332, "CORE", "Classify", "static template · calibrated pinch", True),
    (424, "CORE", "Dynamics", "sticky confidence · transition test", False),
    (516, "CORE", "Session gate", "activation hold 0.3 s · no-hand 2.0 s", False),
    (608, "CORE", "Arbiter", "one owner · neutral rearm 3 frames", False),
]

CHIP_XS = [64, 289, 514, 739]
CHIP_W, CHIP_Y, CHIP_H = 205, 744, 76
CHIPS = [
    ("Pointer", "move · click · drag · snap", True, False),
    ("Combo", "5 stable frames", False, False),
    ("Dynamic", "65-dim DTW · 7.8 ms", False, True),
    ("Contextual", "AX role · 0.3 s dwell", False, False),
]
CHIP_CX = [x + CHIP_W / 2 for x in CHIP_XS]

RES_Y, DISPATCH_Y = 886, 978
BUS_TOP, BUS_BOTTOM = 722, 846


def diamond(x: float, y: float, r: float = 5) -> str:
    return (f'<polygon points="{x},{y - r} {x + r},{y} {x},{y + r} {x - r},{y}" '
            f'fill="{LINK}"/>')


def spine_node(y: int, tag: str, name: str, sub: str, tuned: bool) -> str:
    x, w, h = SPINE_X, SPINE_W, SPINE_H
    cx = x + w / 2
    mark = diamond(x + w - 18, y + 16) if tuned else ""
    return f"""    <g>
      <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{PAPER}"/>
      <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{SURFACE}" stroke="{INK}" stroke-opacity="0.28" stroke-width="1"/>
      <rect x="{x + 10}" y="{y + 8}" width="46" height="12" rx="2" fill="none" stroke="{MUTED}" stroke-opacity="0.45" stroke-width="0.8"/>
      <text x="{x + 33}" y="{y + 17}" fill="{MUTED}" font-family="{MONO}" font-size="8.5" letter-spacing="0.08em" text-anchor="middle">{tag}</text>
      <text x="{cx}" y="{y + 38}" fill="{INK}" font-family="{SANS}" font-size="15" font-weight="600" text-anchor="middle">{name}</text>
      <text x="{cx}" y="{y + 53}" fill="{MUTED}" font-family="{MONO}" font-size="10" text-anchor="middle">{sub}</text>
      {mark}
    </g>"""


def chip(x: int, name: str, sub: str, accent: bool, tuned: bool) -> str:
    cx = x + CHIP_W / 2
    stroke = ACCENT if accent else INK
    opacity = "1" if accent else "0.24"
    fill = ACCENT if accent else SURFACE
    fill_op = "0.06" if accent else "1"
    dash = ' stroke-dasharray="4,3"' if not accent else ""
    mark = diamond(x + CHIP_W - 14, CHIP_Y + 14, 4.5) if tuned else ""
    return f"""    <g>
      <rect x="{x}" y="{CHIP_Y}" width="{CHIP_W}" height="{CHIP_H}" rx="6" fill="{PAPER}"/>
      <rect x="{x}" y="{CHIP_Y}" width="{CHIP_W}" height="{CHIP_H}" rx="6" fill="{fill}" fill-opacity="{fill_op}" stroke="{stroke}" stroke-opacity="{opacity}" stroke-width="1"{dash}/>
      <text x="{cx}" y="{CHIP_Y + 32}" fill="{INK}" font-family="{SANS}" font-size="13" font-weight="600" text-anchor="middle">{name}</text>
      <text x="{cx}" y="{CHIP_Y + 52}" fill="{MUTED}" font-family="{MONO}" font-size="9.5" text-anchor="middle">{sub}</text>
      {mark}
    </g>"""


def build_svg() -> str:
    arrows = []
    # the spine: one stage feeds the next, every frame
    for index in range(len(SPINE) - 1):
        y_from = SPINE[index][0] + SPINE_H
        y_to = SPINE[index + 1][0]
        arrows.append(f'    <path d="M320,{y_from} V{y_to}" fill="none" stroke="{MUTED}" stroke-width="1.2" marker-end="url(#arrow)"/>')

    # arbiter fans into one shared bus, then four drops into the lanes
    arrows.append(f'    <path d="M320,{SPINE[-1][0] + SPINE_H} V{BUS_TOP}" fill="none" stroke="{MUTED}" stroke-width="1.2"/>')
    arrows.append(f'    <line x1="{CHIP_CX[0]}" y1="{BUS_TOP}" x2="{CHIP_CX[-1]}" y2="{BUS_TOP}" stroke="{MUTED}" stroke-width="1.2"/>')
    for cx in CHIP_CX:
        arrows.append(f'    <path d="M{cx},{BUS_TOP} V{CHIP_Y}" fill="none" stroke="{MUTED}" stroke-width="1.2" marker-end="url(#arrow)"/>')

    # lanes merge back into one bus: only the winning lane's output continues
    for cx in CHIP_CX:
        arrows.append(f'    <path d="M{cx},{CHIP_Y + CHIP_H} V{BUS_BOTTOM}" fill="none" stroke="{MUTED}" stroke-width="1" stroke-dasharray="4,3"/>')
    arrows.append(f'    <line x1="{CHIP_CX[0]}" y1="{BUS_BOTTOM}" x2="{CHIP_CX[-1]}" y2="{BUS_BOTTOM}" stroke="{MUTED}" stroke-width="1" stroke-dasharray="4,3"/>')
    arrows.append(f'    <path d="M320,{BUS_BOTTOM} V{RES_Y}" fill="none" stroke="{MUTED}" stroke-width="1.2" marker-end="url(#arrow)"/>')

    # resolution hands an action request to the platform layer
    arrows.append(f'    <path d="M320,{RES_Y + SPINE_H} V{DISPATCH_Y}" fill="none" stroke="{ACCENT}" stroke-width="1.2" marker-end="url(#arrow-accent)"/>')

    nodes = "\n".join(spine_node(*stage) for stage in SPINE)
    chips = "\n".join(chip(x, *spec) for x, spec in zip(CHIP_XS, CHIPS))

    def resolution(y: int, tag: str, name: str, sub: str, tuned: bool) -> str:
        x, w, h = SPINE_X, SPINE_W, SPINE_H
        cx = x + w / 2
        mark = diamond(x + w - 18, y + 16) if tuned else ""
        return f"""    <g>
      <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{PAPER}"/>
      <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{SURFACE}" stroke="{INK}" stroke-opacity="0.28" stroke-width="1"/>
      <rect x="{x + 10}" y="{y + 8}" width="72" height="12" rx="2" fill="none" stroke="{MUTED}" stroke-opacity="0.45" stroke-width="0.8"/>
      <text x="{x + 46}" y="{y + 17}" fill="{MUTED}" font-family="{MONO}" font-size="8.5" letter-spacing="0.08em" text-anchor="middle">{tag}</text>
      <text x="{cx}" y="{y + 38}" fill="{INK}" font-family="{SANS}" font-size="15" font-weight="600" text-anchor="middle">{name}</text>
      <text x="{cx}" y="{y + 53}" fill="{MUTED}" font-family="{MONO}" font-size="10" text-anchor="middle">{sub}</text>
      {mark}
    </g>"""

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="pinchcursor-intent-title pinchcursor-intent-desc" font-family="{SANS}">
  <title id="pinchcursor-intent-title">PinchCursor intent resolution</title>
  <desc id="pinchcursor-intent-desc">One camera frame passes through six rejection stages before the arbiter gives it to exactly one lane, which resolves an accessibility target and dispatches a native action.</desc>
  <defs>
    <marker id="arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{MUTED}"/></marker>
    <marker id="arrow-accent" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{ACCENT}"/></marker>
  </defs>

  <rect width="{W}" height="{H}" fill="{PAPER}"/>

  <text x="32" y="40" fill="{SOFT}" font-family="{MONO}" font-size="9" letter-spacing="0.16em">PINCHCURSOR · INTENT RESOLUTION</text>
  <text x="32" y="80" fill="{INK}" font-family="{SERIF}" font-size="27" letter-spacing="-0.01em">Intent is what survives the vetoes.</text>
  <text x="32" y="106" fill="{SOFT}" font-family="{MONO}" font-size="9.5">one frame · landmarks → track → classify → dynamics → gate → arbitration → resolution</text>

{chr(10).join(arrows)}

{nodes}

    <rect x="48" y="694" width="904" height="148" rx="8" fill="{INK}" fill-opacity="0.02" stroke="{INK}" stroke-opacity="0.12" stroke-width="0.8"/>
    <rect x="62" y="702" width="176" height="15" rx="2" fill="{ZONE_MASK}"/>
    <text x="70" y="714" fill="{SOFT}" font-family="{MONO}" font-size="9.5" letter-spacing="0.14em">LANES · EXACTLY ONE WINS</text>

{chips}

{resolution(RES_Y, "BOUNDARY", "Target resolution", "25-pt AX probe → posteriors → snap 24–60 px", True)}

{resolution(DISPATCH_Y, "NATIVE", "Dispatch", "ActionRequest → CGEvent · AXUIElement", False)}

  <line x1="32" y1="1046" x2="968" y2="1046" stroke="{INK}" stroke-opacity="0.12" stroke-width="0.8"/>
  <text x="32" y="1066" fill="{MUTED}" font-family="{MONO}" font-size="9.5" letter-spacing="0.14em">LEGEND</text>
  <line x1="100" y1="1063" x2="132" y2="1063" stroke="{MUTED}" stroke-width="1.2"/>
  <text x="140" y="1066" fill="{SOFT}" font-family="{MONO}" font-size="9.5">ORDER OF EVALUATION, EVERY FRAME</text>
  <line x1="100" y1="1063" x2="132" y2="1063" stroke="{MUTED}" stroke-width="1" stroke-dasharray="4,3" opacity="0"/>
  {diamond(520, 1062, 5)}
  <text x="532" y="1066" fill="{SOFT}" font-family="{MONO}" font-size="9.5">TUNED FROM YOUR OWN DATA</text>
  <rect x="754" y="1057" width="24" height="12" rx="2" fill="{ACCENT}" fill-opacity="0.06" stroke="{ACCENT}" stroke-width="1"/>
  <text x="786" y="1066" fill="{SOFT}" font-family="{MONO}" font-size="9.5">THE POINTER LANE</text>
</svg>
"""


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PinchCursor intent resolution</title>
<style>
  body {{ margin: 0; padding: 48px 32px; background: {paper}; font-family: {sans}; }}
  .wrap {{ max-width: 1000px; margin: 0 auto; overflow-x: auto; }}
  svg {{ display: block; width: 100%; min-width: 640px; height: auto; }}
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
    out_svg = BASE / "docs" / "intent-pipeline.svg"
    out_html = BASE / "docs" / "intent-pipeline.html"
    out_svg.write_text(svg, encoding="utf-8")
    out_html.write_text(HTML.format(paper=PAPER, sans=SANS, svg=svg), encoding="utf-8")
    print(f"wrote {out_svg.relative_to(BASE)} ({len(svg)} bytes)")
    print(f"wrote {out_html.relative_to(BASE)}")


if __name__ == "__main__":
    main()
