"""Is the learning loop ready? One place that answers it.

A loop that only reports "we are collecting data" is indistinguishable from a
loop that is quietly broken. This module turns the stored episodes into the two
questions a person actually asks: *how close is the boundary to being trainable*
and *does the shadow model agree with the rule it would replace*.

The thresholds live here, and `scripts/train_transition.py` imports them, so the
report and the trainer can never disagree about what "ready" means.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The trainer's gate, in one place.
TRANSITION_MIN_EPISODES = 300
TRANSITION_MIN_PER_CLASS = 60

MODEL_THRESHOLD = 0.5


@dataclass(frozen=True)
class LearningStatus:
    """A read-only snapshot of the transition loop."""

    episodes: int = 0
    positives: int = 0
    negatives: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)
    rule_rejects: int = 0
    retries: int = 0
    shadow_rows: int = 0
    shadow_agreement: float | None = None
    ready: bool = False
    blockers: tuple[str, ...] = ()
    assist_tuning: dict | None = None

    @property
    def balance(self) -> float | None:
        """Share of positive episodes, or None before the first one."""
        if not self.episodes:
            return None
        return self.positives / self.episodes


def build_status(rows, *, tuning: dict | None = None) -> LearningStatus:
    """Summarise stored transition rows (the shape `transition_rows` returns)."""
    episodes = 0
    positives = 0
    rule_rejects = 0
    retries = 0
    shadow_rows = 0
    agreement = 0
    outcomes: dict[str, int] = {}

    for row in rows or ():
        if not isinstance(row, dict):
            continue
        episodes += 1
        label = 1 if row.get("label") else 0
        positives += label
        outcome = str(row.get("outcome") or "")
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        rejected = bool(row.get("rule_rejected"))
        rule_rejects += 1 if rejected else 0
        retries += 1 if outcome == "retried" else 0
        score = row.get("model_score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            shadow_rows += 1
            model_acts = float(score) >= MODEL_THRESHOLD
            if model_acts != rejected:
                agreement += 1

    negatives = episodes - positives
    blockers: list[str] = []
    if episodes < TRANSITION_MIN_EPISODES:
        blockers.append("episodes")
    if positives < TRANSITION_MIN_PER_CLASS:
        blockers.append("positives")
    if negatives < TRANSITION_MIN_PER_CLASS:
        blockers.append("negatives")

    return LearningStatus(
        episodes=episodes,
        positives=positives,
        negatives=negatives,
        outcomes=outcomes,
        rule_rejects=rule_rejects,
        retries=retries,
        shadow_rows=shadow_rows,
        shadow_agreement=(agreement / shadow_rows) if shadow_rows else None,
        ready=not blockers,
        blockers=tuple(blockers),
        assist_tuning=tuning,
    )


def format_status(status: LearningStatus) -> str:
    """A short block of text for the CLI, and a source the UI can wrap."""
    lines = [
        f"pinch episodes   {status.episodes} / {TRANSITION_MIN_EPISODES}",
        f"  acted+retried  {status.positives} (need {TRANSITION_MIN_PER_CLASS})",
        f"  dropped        {status.negatives} (need {TRANSITION_MIN_PER_CLASS})",
        f"  guard rejected {status.rule_rejects}   retried anyway {status.retries}",
    ]
    if status.shadow_rows:
        share = 0.0 if status.shadow_agreement is None else status.shadow_agreement * 100
        lines.append(f"shadow agreement {share:.1f}% over {status.shadow_rows} scored episodes")
    else:
        lines.append("shadow agreement — (no model loaded yet)")
    if status.assist_tuning:
        tuning = status.assist_tuning
        lines.append(
            "aim assist       {distance} px · {confidence}"
            .format(
                distance=tuning.get("distance", "—"),
                confidence=tuning.get("confidence", "—"),
            )
        )
    if status.ready:
        lines.append("ready to train   yes — run scripts/train_transition.py")
    else:
        lines.append("ready to train   no  — waiting on: " + ", ".join(status.blockers))
    return "\n".join(lines)
