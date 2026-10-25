#!/usr/bin/env python3
"""Report whether the learning loop has enough evidence to train.

    .venv/bin/python scripts/learning_status.py --db ~/.../telemetry.sqlite3
    .venv/bin/python scripts/learning_status.py --db ... --json

Read-only: it opens the database, never creates anything, and never writes a
model. The numbers it prints are the same ones `scripts/train_transition.py`
gates on.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.learning_report import build_status, format_status  # noqa: E402
from core.telemetry import TelemetryStore  # noqa: E402


def _last_tuning(store) -> dict | None:
    """The most recent aim-assist decision, if one was ever recorded."""
    try:
        events = store.recent(200)
    except Exception:  # noqa: BLE001
        return None
    for event in events:
        if event.get("kind") == "tune":
            return {
                "reason": event.get("action") or "",
                "distance": event.get("snap_distance"),
                "confidence": event.get("confidence"),
            }
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report learning-loop readiness")
    parser.add_argument("--db", required=True, help="path to telemetry.sqlite3")
    parser.add_argument("--json", action="store_true", help="print machine-readable output")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.db):
        print(f"no telemetry at {args.db}", file=sys.stderr)
        return 1

    store = TelemetryStore(args.db, enabled=True)
    try:
        rows = store.transition_rows()
        tuning = _last_tuning(store)
    finally:
        store.close()

    status = build_status(rows, tuning=tuning)
    if args.json:
        print(
            json.dumps(
                {
                    "episodes": status.episodes,
                    "positives": status.positives,
                    "negatives": status.negatives,
                    "outcomes": status.outcomes,
                    "rule_rejects": status.rule_rejects,
                    "retries": status.retries,
                    "shadow_rows": status.shadow_rows,
                    "shadow_agreement": status.shadow_agreement,
                    "ready": status.ready,
                    "blockers": list(status.blockers),
                    "assist_tuning": status.assist_tuning,
                },
                indent=2,
            )
        )
        return 0
    print(format_status(status))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
