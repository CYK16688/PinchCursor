"""Learning-loop readiness: counts, shadow agreement, and the trainer's gate."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from core.learning_report import (
    TRANSITION_MIN_EPISODES,
    TRANSITION_MIN_PER_CLASS,
    build_status,
    format_status,
)
from core.telemetry import TelemetryStore
from gui.diagnostics_page import DiagnosticsPage
from scripts.learning_status import main as status_main


def _row(label, *, outcome="acted", rejected=None, score=None):
    return {
        "features": [0.2, 0.7, 2.4, -0.3, 0.6, -1.0],
        "label": label,
        "outcome": outcome,
        "rule_rejected": (label == 0) if rejected is None else rejected,
        "duration": 0.4,
        "model_score": score,
    }


def test_an_empty_log_is_not_ready_and_says_what_it_waits_for():
    status = build_status([])

    assert status.episodes == 0
    assert status.ready is False
    assert status.blockers == ("episodes", "positives", "negatives")
    assert "no model loaded" in format_status(status)


def test_outcomes_and_retries_are_counted_separately():
    rows = [
        _row(1, outcome="acted", rejected=False),
        _row(1, outcome="retried", rejected=True),
        _row(0, outcome="reverted", rejected=False),
        _row(0, outcome="rejected", rejected=True),
    ]

    status = build_status(rows)

    assert (status.episodes, status.positives, status.negatives) == (4, 2, 2)
    assert status.outcomes == {"acted": 1, "retried": 1, "reverted": 1, "rejected": 1}
    assert status.rule_rejects == 2
    assert status.retries == 1


def test_shadow_agreement_compares_the_model_to_the_rule():
    # rule rejects A and D; the model agrees on A, disagrees on B, agrees on C,
    # and has no score for D (so D is excluded from the denominator).
    rows = [
        _row(0, rejected=True, score=0.1),   # both reject -> agree
        _row(1, rejected=False, score=0.2),  # model rejects, rule acts -> differ
        _row(1, rejected=False, score=0.9),  # both act -> agree
        _row(0, rejected=True, score=None),
    ]

    status = build_status(rows)

    assert status.shadow_rows == 3
    assert status.shadow_agreement == pytest.approx(2 / 3)


def test_ready_needs_both_classes_and_the_episode_floor():
    rows = [_row(1)] * 40 + [_row(0) for _ in range(TRANSITION_MIN_EPISODES - 40)]

    status = build_status(rows)

    assert status.ready is False
    assert status.blockers == ("positives",)


def test_a_balanced_full_log_is_ready():
    rows = [_row(1)] * 160 + [_row(0)] * 160

    status = build_status(rows)

    assert status.ready is True
    assert status.blockers == ()
    assert "ready to train   yes" in format_status(status)


def _seed_db(path, rows):
    store = TelemetryStore(str(path), enabled=True)
    for row in rows:
        store.record_transition(
            features=row["features"],
            label=row["label"],
            outcome=row["outcome"],
            rule_rejected=row["rule_rejected"],
            duration=row["duration"],
            model_score=row["model_score"],
        )
    store.close()


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_the_cli_reports_json(tmp_path, capsys):
    path = tmp_path / "t.sqlite3"
    _seed_db(path, [_row(1), _row(0)])

    assert status_main(["--db", str(path), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["episodes"] == 2
    assert payload["ready"] is False
    assert payload["blockers"] == ["episodes", "positives", "negatives"]


def test_the_cli_refuses_a_missing_database(tmp_path, capsys):
    assert status_main(["--db", str(tmp_path / "nope.sqlite3")]) == 1
    assert "no telemetry" in capsys.readouterr().err


def test_the_page_shows_episode_progress_and_shadow_agreement(tmp_path, app):
    path = tmp_path / "telemetry.sqlite3"
    store = TelemetryStore(str(path), enabled=True)
    store.record(kind="action", action="left_click", executed=True, x=10, y=20)
    for row in (
        _row(1, score=0.9),
        _row(0, rejected=True, score=0.1),
        _row(1, score=0.2),
    ):
        store.record_transition(
            features=row["features"],
            label=row["label"],
            outcome=row["outcome"],
            rule_rejected=row["rule_rejected"],
            model_score=row["model_score"],
        )
    store.close()

    page = DiagnosticsPage(str(path))
    try:
        assert page.episodes_value.text() == f"3 / {TRANSITION_MIN_EPISODES}"
        assert page.shadow_value.text() == "66.7%"
    finally:
        page.close()
