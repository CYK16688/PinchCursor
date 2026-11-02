"""One source for capture power policy: thresholds and per-mode frame spacing.

The GUI applies these seconds between inference passes; the control runtime
decides the mode from processed no-hand frames plus an optional IR sample.
Keeping both here means a tuning change cannot leave the label and the frame
rate disagreeing, and tests can assert the same table production reads.
"""

from __future__ import annotations

LOW_AFTER = 30
SLEEP_AFTER = 150
DEEP_AFTER = 300

FRAME_SECONDS = {
    "normal": 0.0,
    "low": 1.0 / 15.0,
    "sleep": 1.0 / 5.0,
    "deep_sleep": 1.0 / 2.0,
}


def mode_for(hand_frames: int, ir_present=None) -> str:
    """Return the mode for this many consecutive no-hand frames.

    Only an explicit ``False`` IR sample permits deep sleep; ``True`` (a person
    is present) and ``None`` (no usable IR sample) keep the faster wake-up
    cadence so RGB capture can find the hand again.
    """
    if hand_frames > DEEP_AFTER and ir_present is False:
        return "deep_sleep"
    if hand_frames > SLEEP_AFTER:
        return "sleep"
    if hand_frames > LOW_AFTER:
        return "low"
    return "normal"