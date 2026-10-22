"""Turn one pinch gesture into one labelled episode.

The transition guard has a label problem: when it suppresses a pinch, no click
happens, so there is nothing to learn from — unless the user objects. The one
observable objection is **insisting**: the pinch was dropped and the hand came
back to a pinch within half a second. That retry is the only signal that can
teach a model to disagree with the rule, so the tracker holds every negative
record open for a short window before writing it.

Outcomes and labels:

============  =====  =========================================================
``acted``      1     a click or a drag started while the pinch was held
``retried``    1     dropped, then re-pinched inside the retry window
``reverted``   0     the pinch ended quickly without any action
``rejected``   0     the guard fired and the user did not come back to it
============  =====  =========================================================

A long hold with no action and no rejection is ambiguous (hovering, reading)
and produces no record at all.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

ACTED_ACTIONS = frozenset(
    {"left_click", "right_click", "double_click", "drag_start", "drag"}
)


@dataclass(frozen=True)
class EpisodeRecord:
    """One resolved pinch episode, ready for storage."""

    features: tuple[float, ...]
    label: int
    outcome: str
    rule_rejected: bool
    duration: float
    timestamp: float


class PinchEpisodeTracker:
    """Collects pinch episodes and resolves each to a label exactly once."""

    def __init__(
        self,
        clock=time.monotonic,
        *,
        revert_window: float = 0.30,
        retry_window: float = 0.55,
    ) -> None:
        self.clock = clock
        self.revert_window = max(0.05, float(revert_window))
        self.retry_window = max(0.05, float(retry_window))
        self._episode: dict | None = None
        self._pending: list[tuple[EpisodeRecord, float]] = []

    def reset(self) -> None:
        self._episode = None
        self._pending.clear()

    # -- frames ------------------------------------------------------------
    def observe(self, *, gesture, assessment, now: float) -> list[EpisodeRecord]:
        """Fold one frame in; return every record that just became final."""
        if not isinstance(now, (int, float)) or isinstance(now, bool):
            return self._flush(now=float("inf"))
        emitted = self._flush(now=float(now))

        if gesture == "pinch":
            if self._episode is None:
                # A new pinch right after a dropped one is the user insisting:
                # the previous record flips to label 1 and says why.
                promoted = self._promote_retry(now=float(now))
                if promoted is not None:
                    emitted.append(promoted)
                features = self._features(assessment)
                if features is None:
                    return emitted
                self._episode = {
                    "features": features,
                    "start": float(now),
                    "rejected": bool(getattr(assessment, "transition", False)),
                    "acted": False,
                }
            else:
                if getattr(assessment, "transition", False):
                    self._episode["rejected"] = True
            return emitted

        if self._episode is not None:
            record = self._resolve(now=float(now), gesture=gesture)
            if record is not None:
                if record.label == 0:
                    # Hold it open: the user may still come back to this pinch.
                    self._pending.append((record, float(now) + self.retry_window))
                else:
                    emitted.append(record)
            self._episode = None
        return emitted

    def note_action(self, action, now: float) -> None:
        """Record that an action was dispatched during the open episode."""
        if self._episode is None:
            return
        if isinstance(action, str) and action in ACTED_ACTIONS:
            self._episode["acted"] = True

    @property
    def has_open_episode(self) -> bool:
        return self._episode is not None

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _features(assessment) -> tuple[float, ...] | None:
        from .transition_features import build_features

        return build_features(assessment)

    def _resolve(self, *, now: float, gesture) -> EpisodeRecord | None:
        episode = self._episode
        if episode is None:
            return None
        duration = max(0.0, now - episode["start"])
        if episode["acted"]:
            return EpisodeRecord(
                features=episode["features"],
                label=1,
                outcome="acted",
                rule_rejected=episode["rejected"],
                duration=round(duration, 3),
                timestamp=episode["start"],
            )
        if duration <= self.revert_window:
            return EpisodeRecord(
                features=episode["features"],
                label=0,
                outcome="reverted",
                rule_rejected=episode["rejected"],
                duration=round(duration, 3),
                timestamp=episode["start"],
            )
        if episode["rejected"]:
            return EpisodeRecord(
                features=episode["features"],
                label=0,
                outcome="rejected",
                rule_rejected=True,
                duration=round(duration, 3),
                timestamp=episode["start"],
            )
        # Held, not clicked, not rejected: the user was reading or hovering.
        return None

    def _promote_retry(self, *, now: float) -> EpisodeRecord | None:
        """A pinch right after a drop means the drop was wrong."""
        if not self._pending:
            return None
        record, deadline = self._pending[-1]
        if now > deadline:
            return None
        self._pending.pop()
        return EpisodeRecord(
            features=record.features,
            label=1,
            outcome="retried",
            rule_rejected=record.rule_rejected,
            duration=record.duration,
            timestamp=record.timestamp,
        )

    def _flush(self, *, now: float) -> list[EpisodeRecord]:
        emitted: list[EpisodeRecord] = []
        keep: list[tuple[EpisodeRecord, float]] = []
        for record, deadline in self._pending:
            if now >= deadline:
                emitted.append(record)
            else:
                keep.append((record, deadline))
        self._pending = keep
        return emitted

    def drain(self) -> list[EpisodeRecord]:
        """Return every pending record, for shutdown or session end."""
        records = [record for record, _ in self._pending]
        self._pending.clear()
        return records
