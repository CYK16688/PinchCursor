#!/usr/bin/env python3
"""Train the pinch-transition boundary from recorded episodes.

The rule in `core.hand_dynamics` is one inequality: are the other three fingers
closing faster than 0.8 palm/s while the pinch crosses its threshold? It is
cheap and it works, but the threshold is the same for every hand. This script
fits a small logistic boundary over the six features in
`core.transition_features`, and reports it against the rule on a held-out slice
that the rule was not tuned on.

    .venv/bin/python scripts/train_transition.py --db ~/path/to/telemetry.sqlite3 --dry-run

It refuses to write a model on thin or one-sided data, and it always prints the
rule's own accuracy next to the model's, because a model that cannot beat the
rule is not worth shipping.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.learning_report import (  # noqa: E402
    TRANSITION_MIN_EPISODES as MIN_EPISODES,
    TRANSITION_MIN_PER_CLASS as MIN_PER_CLASS,
)
from core.telemetry import TelemetryStore  # noqa: E402
from core.transition_features import FEATURE_COUNT, FEATURE_NAMES  # noqa: E402
EPOCHS = 500
LEARNING_RATE = 0.2
L2 = 0.01
VALIDATION_FRACTION = 0.25


def load_dataset(db_path: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """Return (features, labels, rule_rejected, outcomes)."""
    store = TelemetryStore(db_path, enabled=True)
    try:
        rows = store.transition_rows()
    finally:
        store.close()
    features = []
    labels = []
    rejected = []
    outcomes = []
    for row in rows:
        vector = row.get("features") or []
        if len(vector) != FEATURE_COUNT:
            continue
        features.append([float(value) for value in vector])
        labels.append(1.0 if row["label"] else 0.0)
        rejected.append(1.0 if row["rule_rejected"] else 0.0)
        outcomes.append(row.get("outcome", ""))
    if not features:
        return np.zeros((0, FEATURE_COUNT)), np.zeros(0), np.zeros(0), []
    return (
        np.asarray(features, dtype=np.float64),
        np.asarray(labels, dtype=np.float64),
        np.asarray(rejected, dtype=np.float64),
        outcomes,
    )


def standardise(features: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = features.mean(axis=0)
    scale = features.std(axis=0)
    scale[scale < 1e-9] = 1.0
    return (features - mean) / scale, mean, scale


def train_logistic(
    features: np.ndarray,
    labels: np.ndarray,
    *,
    epochs: int = EPOCHS,
    lr: float = LEARNING_RATE,
    l2: float = L2,
) -> tuple[np.ndarray, float]:
    weights = np.zeros(features.shape[1], dtype=np.float64)
    intercept = 0.0
    for _ in range(epochs):
        logits = features @ weights + intercept
        predictions = 1.0 / (1.0 + np.exp(-np.clip(logits, -40.0, 40.0)))
        error = predictions - labels
        weights -= lr * (features.T @ error / len(labels) + l2 * weights)
        intercept -= lr * float(error.mean())
    return weights, intercept


def accuracy(scores: np.ndarray, labels: np.ndarray, threshold: float) -> float | None:
    if len(labels) == 0:
        return None
    predicted = (scores >= threshold).astype(np.float64)
    return float((predicted == labels).mean())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the pinch-transition boundary")
    parser.add_argument("--db", required=True, help="path to telemetry.sqlite3")
    parser.add_argument("--out", default=None, help="output model path (default: beside the db)")
    parser.add_argument("--dry-run", action="store_true", help="train and report without writing")
    args = parser.parse_args(argv)

    features, labels, rejected, outcomes = load_dataset(args.db)
    positives = int(labels.sum())
    negatives = int(len(labels) - positives)
    print(f"episodes: {len(labels)}   acted/retried: {positives}   dropped: {negatives}")

    if len(labels) < MIN_EPISODES:
        print(
            f"refusing to train: {len(labels)} episodes, need at least {MIN_EPISODES}",
            file=sys.stderr,
        )
        return 2
    if positives < MIN_PER_CLASS or negatives < MIN_PER_CLASS:
        print(
            f"refusing to train: one class is too thin ({positives} positive, {negatives} negative,"
            f" need {MIN_PER_CLASS} each)",
            file=sys.stderr,
        )
        return 2

    # Time-ordered split: the model must generalise forward, not memorise the
    # same session it was trained on.
    cut = max(1, int(len(labels) * (1.0 - VALIDATION_FRACTION)))
    train_x, train_y = features[:cut], labels[:cut]
    valid_x, valid_y = features[cut:], labels[cut:]
    if train_y.min() == train_y.max() or valid_y.min() == valid_y.max():
        print("refusing to train: the time split left one side with a single class", file=sys.stderr)
        return 2

    scaled_train, mean, scale = standardise(train_x)
    scaled_valid = (valid_x - mean) / scale
    weights, intercept = train_logistic(scaled_train, train_y)
    scores = scaled_valid @ weights + intercept

    model_accuracy = accuracy(scores, valid_y, 0.5)
    rule_scores = 1.0 - rejected[cut:]  # the rule says "act" unless it rejected
    rule_accuracy = accuracy(rule_scores, valid_y, 0.5)

    print(f"validation accuracy: model={model_accuracy}  rule={rule_accuracy}")
    print("weights (standardised inputs):")
    for name, weight in zip(FEATURE_NAMES, weights):
        print(f"  {name:18s} {weight:+.4f}")

    if model_accuracy is not None and rule_accuracy is not None and model_accuracy <= rule_accuracy:
        print(
            "the model does not beat the rule on held-out data; not writing it",
            file=sys.stderr,
        )
        return 3

    if args.dry_run:
        return 0

    out = Path(args.out) if args.out else Path(args.db).with_name("transition_model.json")
    payload = {
        "version": 1,
        "feature_names": list(FEATURE_NAMES),
        "mean": [round(float(value), 6) for value in mean],
        "scale": [round(float(value), 6) for value in scale],
        "weights": [round(float(value), 6) for value in weights],
        "intercept": round(float(intercept), 6),
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "episodes": int(len(labels)),
        "validation_accuracy": None if model_accuracy is None else round(model_accuracy, 4),
        "rule_accuracy": None if rule_accuracy is None else round(rule_accuracy, 4),
        "outcomes": {name: outcomes.count(name) for name in sorted(set(outcomes))},
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
