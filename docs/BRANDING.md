# Branding

PinchCursor’s mark combines a white thumb–index pinch with a mint pointer on a cobalt tile. The pointer sits between the fingertips to express continuous hand control becoming mouse input.

## Assets

- Canonical source: `gui/resources/pinchcursor.png` (1254 × 1254, RGBA).
- macOS bundle: `assets/app.icns`.
- Windows executable: `assets/app.ico`.

The application header, window icon and README use the canonical PNG. Platform icons are resolution exports of that same image; do not redraw them separately.

Regenerate exports with `.venv/bin/python scripts/make_icon.py`. ICO exports on every platform; ICNS also exports on macOS. Temporary iconsets are automatically removed. Update the source and exports together, then regenerate UI screenshots with `QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/make_screenshots.py`.

## Generation record

Generated on 2026-10-28 using built-in `image_gen`, with transparent background enabled. No CLI or external-provider fallback. The generated image was copied unchanged; platform exports only scale and package it.

Final prompt:

```text
Use case: logo-brand. Asset type: final desktop app icon for PinchCursor, a local webcam-based continuous hand gesture mouse. Primary request: a distinctive, immediately understandable pinch-to-control-cursor logo, suitable for both a macOS Dock icon and a 24px in-app mark. A single bold white geometric hand pictogram in a thumb-and-index pinching pose, with a small mint cursor arrow exactly at the gap between the converging fingertips. The fingertips and arrow must feel like one integrated symbol: hand gesture becomes mouse input. Use a simple recognizable silhouette, generous negative space, thick smooth shapes and minimal detail, no thin finger anatomy, no extra fingers, no decorative gesture rays or circles. Center the symbol on a deep cobalt blue rounded square tile consistent with a precise calm desktop utility; white hand, mint #47D7A1 pointer accent, cobalt around #3658B6. Flat polished vector-like design, crisp edges, no 3D, no shadows, no texture, no gradients. Square canvas; tile fills 92% of canvas with equal safe margins, logo fills roughly 70% of tile. Truly transparent outside the rounded-square tile. Produce exactly one finished icon, no alternatives grid, no mockup, no words, no letters, no watermark.
```
