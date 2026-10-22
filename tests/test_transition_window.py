"""Window wiring: episodes reach the log, the shadow score never acts."""

import json

from core.telemetry import TelemetryStore
from core.transition_episodes import PinchEpisodeTracker
from core.transition_features import FEATURE_NAMES
from core.transition_model import TransitionModel
from gui.main_window import MainWindow


class _Assessment:
    pinch_ratio = 0.2
    pinch_confidence = 0.7
    transition = False
    others_rate = -0.3
    wrist_speed = 0.6
    others_distance = 2.4
    pinch_slope = -1.0


def _window(tmp_path, model=None):
    window = MainWindow.__new__(MainWindow)
    window.telemetry = TelemetryStore(str(tmp_path / "t.sqlite3"), enabled=True)
    window.pinch_episodes = PinchEpisodeTracker()
    window.transition_model = model
    return window


def test_an_acted_episode_reaches_the_log(tmp_path):
    window = _window(tmp_path)

    window._observe_pinch_episode("pinch", _Assessment(), 1.0)
    window._note_episode_action("left_click", 1.1)
    window._observe_pinch_episode("point", _Assessment(), 1.3)

    rows = window.telemetry.transition_rows()
    assert len(rows) == 1
    assert rows[0]["label"] == 1
    assert rows[0]["outcome"] == "acted"
    assert rows[0]["model_score"] is None
    window.telemetry.close()


def test_a_shadow_model_only_adds_a_score(tmp_path):
    path = tmp_path / "transition_model.json"
    path.write_text(
        json.dumps(
            {
                "feature_names": list(FEATURE_NAMES),
                "mean": [0.0] * 6,
                "scale": [1.0] * 6,
                "weights": [3.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                "intercept": 0.0,
            }
        ),
        encoding="utf-8",
    )
    window = _window(tmp_path, model=TransitionModel.load(str(path)))

    window._observe_pinch_episode("pinch", _Assessment(), 1.0)
    window._note_episode_action("left_click", 1.1)
    window._observe_pinch_episode("point", _Assessment(), 1.3)

    row = window.telemetry.transition_rows()[0]
    assert row["label"] == 1  # the outcome, not the model, decides the label
    assert row["model_score"] is not None and row["model_score"] > 0.5
    window.telemetry.close()


def test_nothing_is_recorded_and_nothing_breaks_without_telemetry(tmp_path):
    window = MainWindow.__new__(MainWindow)
    window.telemetry = None
    window.pinch_episodes = PinchEpisodeTracker()
    window.transition_model = None

    window._observe_pinch_episode("pinch", _Assessment(), 1.0)
    window._note_episode_action("left_click", 1.1)
    window._observe_pinch_episode("point", _Assessment(), 1.3)

    assert window.pinch_episodes.has_open_episode is False
