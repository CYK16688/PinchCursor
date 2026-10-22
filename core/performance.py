"""Two resource profiles: standard and performance.

The profiles exist because the honest cost of accuracy here is *pixels on the
hand* and a *second inference backend*, not a different algorithm. Everything
the profiles change is a number the pipeline already reads, so switching modes
needs no new code path in the control loop.

``standard``
    CPU inference at 640x480, 15 fps preview. The default: roughly 16 % of one
    core, no GPU context, lowest memory.

``performance``
    Metal-accelerated inference (which needs RGBA input), 1280x720 capture for
    finer landmark quantisation, 30 fps preview, and slightly longer smoothing.
    Faster per frame on Apple Silicon because the work leaves the CPU, at the
    cost of a GPU context, more memory, and more camera bandwidth.
"""

from __future__ import annotations

from dataclasses import dataclass

MODES = ("standard", "performance")
DEFAULT_MODE = "standard"


@dataclass(frozen=True)
class PerformancePreset:
    mode: str
    camera_width: int
    camera_height: int
    preview_fps: float
    detection_confidence: float
    tracking_confidence: float
    smoothing_mincutoff: float
    delegate: str
    color_format: str

    @property
    def is_performance(self) -> bool:
        return self.mode == "performance"


STANDARD = PerformancePreset(
    mode="standard",
    camera_width=640,
    camera_height=480,
    preview_fps=15.0,
    detection_confidence=0.7,
    tracking_confidence=0.5,
    smoothing_mincutoff=1.5,
    delegate="cpu",
    color_format="rgb",
)

PERFORMANCE = PerformancePreset(
    mode="performance",
    camera_width=1280,
    camera_height=720,
    preview_fps=30.0,
    # A lower detection floor keeps the hand tracked through motion blur; a
    # higher tracking floor stops the tracker from latching onto a different
    # hand or a background object.
    detection_confidence=0.5,
    tracking_confidence=0.6,
    # A lower cutoff trades a little latency for a steadier cursor, which is
    # the point of the mode.
    smoothing_mincutoff=1.2,
    delegate="gpu",
    color_format="rgba",
)


def preset_for(mode: object) -> PerformancePreset:
    """Return the preset for ``mode``, defaulting to standard on anything odd."""
    return PERFORMANCE if mode == "performance" else STANDARD
