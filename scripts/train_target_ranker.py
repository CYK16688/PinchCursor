"""Train the candidate ranker from the local telemetry log.

This is an offline tool: it reads ``telemetry.sqlite3``, learns which
accessibility element the hand was physically over at each lock, and writes a
small JSON model beside the settings file. Nothing here runs inside the app.

Deliberate choices:

* **The label is ``chosen_raw``** — the rectangle the cursor was actually over,
  not the one the current snap policy picked. Training on the policy's own
  output would just teach the model to imitate the thing it is supposed to
  improve.
* **Time-based split.** Adjacent locks are highly correlated, so a random split
  would report an accuracy the model cannot reproduce in use.
* **It refuses to train on thin data.** Below ``MIN_LOCKS`` the output is a
  clear error, not a model that happens to fit 40 examples.

Usage:
    .venv/bin/python scripts/train_target_ranker.py --db settings-dir/telemetry.sqlite3
    .venv/bin/python scripts/train_target_ranker.py --db ... --dry-run
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.assist.features import FEATURE_COUNT, FEATURE_NAMES  # noqa: E402
from core.telemetry import TelemetryStore  # noqa: E402

MIN_LOCKS = 200
EPOCHS = 400
LEARNING_RATE = 0.15
L2 = 0.01


def load_dataset(db_path: str) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Return (features, labels, lock_ids) with one row per candidate."""
    store = TelemetryStore(db_path, enabled=True)
    try:
        groups = store.candidate_groups()
    finally:
        store.close()
    rows: list[list[float]] = []
    labels: list[int] = []
    lock_ids: list[str] = []
    for group in groups:
        for row in group["rows"]:
            vector = row.get("features") or []
            if len(vector) != FEATURE_COUNT:
                continue
            if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in vector):
                continue
            rows.append([float(value) for value in vector])
            labels.append(1 if row["chosen_raw"] else 0)
            lock_ids.append(group["lock_id"])
    if not rows:
        return np.zeros((0, FEATURE_COUNT)), np.zeros(0), []
    return np.asarray(rows, dtype=np.float64), np.asarray(labels, dtype=np.float64), lock_ids


def train_logistic(
    features: np.ndarray, labels: np.ndarray, *, epochs: int = EPOCHS, lr: float = LEARNING_RATE, l2: float = L2
) -> tuple[np.ndarray, float]:
    """Full-batch logistic regression; deterministic for a fixed input."""
    weights = np.zeros(features.shape[1], dtype=np.float64)
    intercept = 0.0
    for _ in range(epochs):
        logits = features @ weights + intercept
        predictions = 1.0 / (1.0 + np.exp(-np.clip(logits, -40.0, 40.0)))
        error = predictions - labels
        gradient = features.T @ error / len(labels) + l2 * weights
        weights -= lr * gradient
        intercept -= lr * float(error.mean())
    return weights, intercept


def top1_accuracy(
    features: np.ndarray, labels: np.ndarray, lock_ids: list[str], scores: np.ndarray
) -> float | None:
    """Score per lock: did the best-scoring candidate carry the label?"""
    correct = 0
    total = 0
    current = None
    best_score = -math.inf
    best_label = 0.0
    for index, lock_id in enumerate(lock_ids):
        if current is not None and lock_id != current:
            correct += 1 if best_label == 1.0 else 0
            total += 1
            best_score = -math.inf
        if lock_id != current or scores[index] > best_score:
            best_score = float(scores[index])
            best_label = float(labels[index])
        current = lock_id
    if current is not None:
        correct += 1 if best_label == 1.0 else 0
        total += 1
    return (correct / total) if total else None


def split_index(lock_ids: list[str], fraction: float = 0.8) -> int:
    """Index of the time-based split, never inside a lock."""
    if not lock_ids:
        return 0
    unique = sorted({lock_id for lock_id in lock_ids}, key=lock_ids.index)
    cut = max(1, int(len(unique) * fraction))
    boundary = unique[min(cut, len(unique) - 1)]
    return lock_ids.index(boundary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the target ranker from telemetry")
    parser.add_argument("--db", required=True, help="path to telemetry.sqlite3")
    parser.add_argument("--out", default=None, help="output model path (default: beside the db)")
    parser.add_argument("--dry-run", action="store_true", help="train and report without writing")
    args = parser.parse_args(argv)

    features, labels, lock_ids = load_dataset(args.db)
    locks = len({lock_id for lock_id in lock_ids})
    if locks < MIN_LOCKS:
        print(
            f"refusing to train: {locks} labelled locks, need at least {MIN_LOCKS}",
            file=sys.stderr,
        )
        return 2

    cut = split_index(lock_ids)
    train_x, train_y = features[:cut], labels[:cut]
    valid_x, valid_y = features[cut:], labels[cut:]
    if len(train_y) == 0 or len(valid_y) == 0 or train_y.sum() == 0:
        print("refusing to train: the split left one side without positives", file=sys.stderr)
        return 2

    weights, intercept = train_logistic(train_x, train_y)
    valid_scores = valid_x @ weights + intercept
    accuracy = top1_accuracy(valid_x, valid_y, lock_ids[cut:], valid_scores)
    baseline = top1_accuracy(
        valid_x, valid_y, lock_ids[cut:], np.asarray([row[FEATURE_NAMES.index("bayes")] for row in valid_x])
    )

    print(f"locks: {locks}   candidate rows: {len(labels)}")
    print(f"validation top-1: model={accuracy}  bayesian-baseline={baseline}")
    print("weights:")
    for name, weight in zip(FEATURE_NAMES, weights):
        print(f"  {name:14s} {weight:+.4f}")

    if args.dry_run:
        return 0

    out = Path(args.out) if args.out else Path(args.db).with_name("target_ranker.json")
    payload = {
        "version": 1,
        "feature_names": list(FEATURE_NAMES),
        "weights": [round(float(value), 6) for value in weights],
        "intercept": round(float(intercept), 6),
        "trained_locks": locks,
        "accuracy": None if accuracy is None else round(float(accuracy), 4),
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
