"""Storage and training contracts for pinch episodes."""

import sqlite3

import numpy as np
import pytest

from core.telemetry import TelemetryStore
from core.transition_features import FEATURE_COUNT
from core.transition_model import TransitionModel
from scripts.train_transition import main as train_main


def _row(label, score=None, outcome="acted"):
    return dict(
        features=[0.2, 0.7, 2.6, -0.4, 0.9, -1.2],
        label=label,
        outcome=outcome,
        rule_rejected=label == 0,
        duration=0.4,
        model_score=score,
    )


def test_episodes_round_trip_with_their_shadow_score(tmp_path):
    store = TelemetryStore(str(tmp_path / "t.sqlite3"), enabled=True)
    store.record_transition(**_row(1, score=0.81))
    store.record_transition(**_row(0, outcome="reverted"))

    rows = store.transition_rows()

    assert len(rows) == 2
    assert rows[0]["label"] == 1
    assert rows[0]["model_score"] == pytest.approx(0.81)
    assert rows[1]["outcome"] == "reverted"
    assert rows[1]["model_score"] is None
    store.close()


def test_a_vector_of_the_wrong_width_is_refused(tmp_path):
    store = TelemetryStore(str(tmp_path / "t.sqlite3"), enabled=True)
    store.record_transition(features=[0.2, 0.7], label=1)

    assert store.transition_rows() == []
    store.close()


def test_purging_clears_episodes_too(tmp_path):
    store = TelemetryStore(str(tmp_path / "t.sqlite3"), enabled=True)
    store.record_transition(**_row(1))
    store.purge()

    assert store.transition_rows() == []
    store.close()


def test_the_episode_table_has_no_content_column(tmp_path):
    path = tmp_path / "t.sqlite3"
    store = TelemetryStore(str(path), enabled=True)
    store.record_transition(**_row(1))
    store.close()

    connection = sqlite3.connect(path)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(transitions)")}
    connection.close()

    assert columns == {
        "id", "ts", "features", "label", "outcome", "rule_rejected", "duration", "model_score"
    }


def _seed(path, count=400, *, noise=0.15, seed=7):
    rng = np.random.default_rng(seed)
    store = TelemetryStore(str(path), enabled=True)
    for index in range(count):
        # The label is driven by the first feature; the rule's verdict is
        # independent of it, which is the situation the model exists to fix.
        ratio = rng.normal(0.5, 0.3)
        label = 1 if ratio < 0.45 else 0
        features = [float(ratio), 0.6, 2.5, -0.4, 0.8, -1.0]
        features = [value + rng.normal(0, noise) for value in features]
        store.record_transition(
            features=features,
            label=label,
            outcome="acted" if label else "reverted",
            rule_rejected=bool(rng.random() < 0.5),
            duration=0.4,
        )
    store.close()


def test_training_refuses_thin_data(tmp_path):
    path = tmp_path / "thin.sqlite3"
    _seed(path, count=120)

    assert train_main(["--db", str(path), "--dry-run"]) == 2


def test_training_writes_a_model_the_runtime_can_load(tmp_path):
    path = tmp_path / "t.sqlite3"
    _seed(path, count=600)
    out = tmp_path / "transition_model.json"

    assert train_main(["--db", str(path), "--out", str(out)]) == 0

    model = TransitionModel.load(str(out))
    assert model is not None
    assert model.metadata["episodes"] == 600


def test_training_refuses_a_model_that_cannot_beat_the_rule(tmp_path):
    path = tmp_path / "t.sqlite3"
    store = TelemetryStore(str(path), enabled=True)
    rng = np.random.default_rng(3)
    for _ in range(400):
        label = int(rng.random() < 0.5)
        # The rule already knows the answer perfectly: a model has nothing to add.
        store.record_transition(
            features=[0.2, 0.7, 2.6, -0.4, 0.9, -1.2],
            label=label,
            outcome="acted" if label else "reverted",
            rule_rejected=label == 0,
        )
    store.close()

    assert train_main(["--db", str(path), "--dry-run"]) == 3
