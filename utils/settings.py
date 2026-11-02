"""Typed, read-only view over the persisted settings mapping.

Writes stay where they belong: ``ConfigManager`` owns loading, validation and
persistence. This module is the single *read* path, so every consumer agrees
about what a missing key means.

That agreement is the point. The pointer-mapping gain used to have three
definitions — the schema declared 1.4 while the engine and the window each fell
back to 2.0 — so a settings file without that key silently doubled cursor travel
and the hand jitter that comes with it. The same call syntax also meant two
different things depending on the holder: a section lookup on ``ConfigManager``,
a plain ``dict.get`` on the mapping the engine receives.

Every accessor therefore returns a frozen value object whose fields are
validated once, against the documented default. Anything unusable falls back to
that default rather than propagating into native input, the same fail-closed
shape the rest of the runtime uses.
"""

import math
from dataclasses import dataclass

from utils.config_manager import DEFAULT_CONFIG


def section(config, name):
    """Return one section as a mapping, or an empty mapping when unusable."""
    value = config.get(name) if isinstance(config, dict) else None
    return value if isinstance(value, dict) else {}


def number(source, key, default):
    """Coerce one numeric field, falling back to the default when unusable."""
    value = source.get(key, default) if isinstance(source, dict) else default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return float(default)
    result = float(value)
    return result if math.isfinite(result) else float(default)


def flag(source, key, default=True):
    """Read one boolean field; only a real ``bool`` counts as configured."""
    value = source.get(key, default) if isinstance(source, dict) else default
    return value if isinstance(value, bool) else bool(default)


def text(source, key, default=""):
    """Read one string field, falling back when it is not a usable string."""
    value = source.get(key, default) if isinstance(source, dict) else default
    return value if isinstance(value, str) and value else str(default)


def positive(value):
    """True only for a real, finite, positive number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    number = float(value)
    return math.isfinite(number) and number > 0.0


@dataclass(frozen=True)
class PointerMapping:
    """How a camera position becomes a screen position."""

    mode: str
    gain: float


@dataclass(frozen=True)
class PointerAssist:
    """Parameters of the optional target-snapping assist."""

    enabled: bool
    mode: str
    model_path: str
    max_snap_distance: float
    min_confidence: float
    search_radius: float


@dataclass(frozen=True)
class Sensitivity:
    """User-facing pointer feel."""

    scroll_speed: int
    smoothing: float
    dead_zone: float


@dataclass(frozen=True)
class Stabilization:
    """Gesture label debouncing."""

    confirm_threshold: int
    min_switch_interval: float
    exit_threshold: int
    cooldown_time: float


@dataclass(frozen=True)
class PointerScroll:
    """Continuous wheel control while a thumb pose is held."""

    enabled: bool
    dwell_seconds: float
    repeat_seconds: float
    enter_seconds: float


@dataclass(frozen=True)
class PointerStability:
    """Plausibility gate for the visible pointer lane."""

    enabled: bool


@dataclass(frozen=True)
class SettingsSnapshot:
    """One validated read of the settings, safe to hold across frames."""

    mapping: PointerMapping
    assist: PointerAssist
    sensitivity: Sensitivity
    stabilization: Stabilization
    scroll: PointerScroll
    stability: PointerStability


def read(config, defaults=None):
    """Return one validated snapshot; unusable fields fall back to defaults."""
    base = DEFAULT_CONFIG if defaults is None else defaults

    values = section(config, "pointer_mapping")
    bases = section(base, "pointer_mapping")
    mode = text(values, "mode", text(bases, "mode", "absolute"))
    gain = number(values, "gain", number(bases, "gain", 1.4))
    if mode == "relative" and "gain" in values and not positive(values["gain"]):
        # A relative sweep needs a real positive gain. Degrade to the absolute
        # strategy instead of substituting a default the user never set.
        mode = "absolute"
    mapping = PointerMapping(mode=mode, gain=gain)

    values = section(config, "pointer_assist")
    bases = section(base, "pointer_assist")
    assist = PointerAssist(
        enabled=flag(values, "enabled", flag(bases, "enabled", True)),
        mode=text(values, "mode", text(bases, "mode", "bayesian")),
        model_path=text(values, "model_path", ""),
        max_snap_distance=number(
            values, "max_snap_distance", number(bases, "max_snap_distance", 24.0)
        ),
        min_confidence=number(values, "min_confidence", number(bases, "min_confidence", 0.55)),
        search_radius=number(values, "search_radius", number(bases, "search_radius", 120.0)),
    )

    values = section(config, "global_sensitivity")
    bases = section(base, "global_sensitivity")
    sensitivity = Sensitivity(
        scroll_speed=int(number(values, "scroll_speed", number(bases, "scroll_speed", 50))),
        smoothing=number(values, "smoothing", number(bases, "smoothing", 0.005)),
        dead_zone=number(values, "dead_zone", number(bases, "dead_zone", 8.0)),
    )

    values = section(config, "stabilization")
    bases = section(base, "stabilization")
    stabilization = Stabilization(
        confirm_threshold=int(
            number(values, "confirm_threshold", number(bases, "confirm_threshold", 3))
        ),
        min_switch_interval=number(
            values, "min_switch_interval", number(bases, "min_switch_interval", 0.15)
        ),
        exit_threshold=int(number(values, "exit_threshold", number(bases, "exit_threshold", 4))),
        cooldown_time=number(values, "cooldown_time", number(bases, "cooldown_time", 0.2)),
    )
    values = section(config, "pointer_scroll")
    bases = section(base, "pointer_scroll")
    scroll = PointerScroll(
        enabled=flag(values, "enabled", flag(bases, "enabled", True)),
        dwell_seconds=number(values, "dwell_seconds", number(bases, "dwell_seconds", 0.3)),
        repeat_seconds=number(values, "repeat_seconds", number(bases, "repeat_seconds", 0.12)),
        enter_seconds=number(values, "enter_seconds", number(bases, "enter_seconds", 0.08)),
    )

    values = section(config, "pointer_stability")
    bases = section(base, "pointer_stability")
    stability = PointerStability(
        enabled=flag(values, "enabled", True),
    )

    return SettingsSnapshot(
        mapping=mapping,
        assist=assist,
        sensitivity=sensitivity,
        stabilization=stabilization,
        scroll=scroll,
        stability=stability,
    )

def effective_assist(assist):
    """The snap distance and confidence actually in force for the assist.

    Configured values, overridden by one learned step when that step is present
    and still anchored to the values it started from. Every consumer reads
    through this function, so the model, the diagnostics page and the tuner's
    next input cannot disagree about what is in force.
    """
    values = assist if isinstance(assist, dict) else {}
    learned = values.get("learned")
    learned = learned if isinstance(learned, dict) else {}
    # A learned step is anchored to the values it started from. When the user
    # edits the configured numbers, their choice wins and the stale adaptation
    # is ignored instead of quietly overriding it.
    if learned and (
        learned.get("base_max_snap_distance") != values.get("max_snap_distance")
        or learned.get("base_min_confidence") != values.get("min_confidence")
    ):
        learned = {}

    def pick(key, default):
        for source in (learned, values):
            raw = source.get(key)
            if raw is None or isinstance(raw, bool):
                continue
            try:
                number = float(raw)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(number):
                continue
            return number
        return default

    return pick("max_snap_distance", 24.0), pick("min_confidence", 0.55)

