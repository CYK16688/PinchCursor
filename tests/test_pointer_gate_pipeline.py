"""Position rejection must not swallow independently qualified pinch endings.

The production pipeline runs against the recording macOS sink. Only the clock,
landmark observations and native OS boundary are simulated; default-gate tests
feed in-frame detector outliers without overriding the gate's decision.
"""
from math import ceil

import pytest

from core.action_state_machine import ActionState
from core.control_engine import HandObservation
from tests.test_joint_pinch_pipeline import Pipeline, hand


@pytest.fixture
def make_pipeline(tmp_path):
    pipelines = []

    def make(fps=30, mode="absolute"):
        pipeline = Pipeline(tmp_path, fps, mode=mode)
        pipelines.append(pipeline)
        return pipeline

    yield make
    for pipeline in pipelines:
        pipeline.coordinator.close()


def observe(pipeline, landmarks):
    pipeline.clock.now += 1 / pipeline.fps
    return pipeline.engine.step(HandObservation(
        pipeline.clock.now, landmarks, (640, 480),
    ))


def record_gate(pipeline, monkeypatch):
    decisions = []
    original = pipeline.engine.jump_gate.accept

    def accept(*args):
        decision = original(*args)
        decisions.append(decision)
        return decision

    monkeypatch.setattr(pipeline.engine.jump_gate, "accept", accept)
    return decisions


def before_release(pipeline, **geometry):
    for _ in range(ceil(.04 * pipeline.fps)):
        assert pipeline.send(**geometry).pinch_phase == "confirmed"


def start_drag(pipeline, *, dx=0, dy=0):
    for _ in range(round(.6 * pipeline.fps)):
        pipeline.send(dx=dx, dy=dy)
    pipeline.hold(.15, 1, dx=dx, dy=dy)
    count = ceil(.7 * pipeline.fps)
    for index in range(count):
        pipeline.send(1, dx=dx + 90 * (index + 1) / count, dy=dy)
    assert pipeline.engine.action_machine.state is ActionState.DRAGGING
    assert len(pipeline.events("left_down")) == 1
    assert not pipeline.events("left_up")


@pytest.mark.parametrize("fps", [15, 30, 60])
@pytest.mark.parametrize("mode", ["absolute", "relative"])
def test_rejected_release_keeps_qualified_click_at_existing_target(make_pipeline, monkeypatch,
                                                                  fps, mode):
    pipeline = make_pipeline(fps, mode)
    pipeline.prime(speed=0)
    pipeline.hold(.15, 1)
    assert pipeline.snapshots[-1].pinch_phase == "confirmed"
    target = pipeline.engine.action_machine.locked_pos
    before_release(pipeline)
    decisions = record_gate(pipeline, monkeypatch)
    landmarks = hand()
    landmarks[8] = (620, 440, 0)

    released = observe(pipeline, landmarks)

    assert decisions == [False]
    assert released.pinch_phase == "released"
    assert pipeline.engine.action_machine.state is ActionState.MOVING
    assert len(pipeline.events("left_down")) == len(pipeline.events("left_up")) == 1
    assert pipeline.events("left_down")[0][1:3] == pytest.approx(
        pipeline.engine.screen_bounds.clamp(*target), abs=1,
    )
    pipeline.hold(.4)
    assert len(pipeline.events("left_down")) == len(pipeline.events("left_up")) == 1
    assert not pipeline.events("left_dragged")


@pytest.mark.parametrize("fps", [15, 30, 60])
@pytest.mark.parametrize("mode", ["absolute", "relative"])
def test_rejected_release_ends_existing_drag_in_the_same_frame(make_pipeline, monkeypatch,
                                                              fps, mode):
    pipeline = make_pipeline(fps, mode)
    start_drag(pipeline)
    before_release(pipeline, dx=90)
    decisions = record_gate(pipeline, monkeypatch)
    landmarks = hand(dx=90)
    landmarks[8] = (0, 479, 0)
    dragged = len(pipeline.events("left_dragged"))

    released = observe(pipeline, landmarks)

    assert decisions == [False]
    assert released.pinch_phase == "released"
    assert pipeline.engine.action_machine.state is ActionState.MOVING
    assert len(pipeline.events("left_down")) == len(pipeline.events("left_up")) == 1
    assert len(pipeline.events("left_dragged")) == dragged


@pytest.mark.parametrize("fps", [15, 30, 60])
@pytest.mark.parametrize("mode", ["absolute", "relative"])
def test_repeated_rejections_cannot_delay_cancelled_drag_release(make_pipeline, monkeypatch,
                                                                fps, mode):
    pipeline = make_pipeline(fps, mode)
    start_drag(pipeline, dx=-246, dy=-120)
    decisions = record_gate(pipeline, monkeypatch)
    dragged = len(pipeline.events("left_dragged"))
    for index in range(6):
        landmarks = hand(dx=-156, dy=-120, fist=1)
        landmarks[8] = (639, 0, 0) if index % 2 == 0 else (0, 479, 0)
        snapshot = observe(pipeline, landmarks)
        if index == 0:
            assert snapshot.pinch_phase == "cancelled"
            assert decisions == [False]
        assert pipeline.engine.action_machine.state is ActionState.MOVING
        assert len(pipeline.events("left_down")) == len(pipeline.events("left_up")) == 1
        assert len(pipeline.events("left_dragged")) == dragged


@pytest.mark.parametrize("failure", ["history", "mapping", "target"])
def test_rejected_release_without_trusted_clean_mapping_cannot_guess_a_click(
    make_pipeline, monkeypatch, failure,
):
    pipeline = make_pipeline()
    pipeline.prime(speed=0)
    pipeline.hold(.15, 1)
    before_release(pipeline)
    if failure == "history":
        pipeline.engine._pointer_history.clear()
        pipeline.engine._joint_pointer_state = None
    elif failure == "mapping":
        monkeypatch.setattr(pipeline.engine._joint_pointer_state[2], "map", lambda *args: None)
    else:
        pipeline.engine._joint_target = None
    decisions = record_gate(pipeline, monkeypatch)
    landmarks = hand()
    landmarks[8] = (620, 440, 0)

    observe(pipeline, landmarks)

    assert decisions == [False]
    assert pipeline.engine.action_machine.state is ActionState.MOVING
    assert not pipeline.events("left_down")
    pipeline.hold(.4)
    assert not pipeline.events("left_down")


@pytest.mark.parametrize("phase", ["candidate", "confirmed"])
def test_rejected_position_cannot_admit_or_start_a_drag(make_pipeline, monkeypatch, phase):
    pipeline = make_pipeline()
    pipeline.prime(speed=0)
    if phase == "confirmed":
        pipeline.hold(.5, 1)
        assert pipeline.engine.action_machine.state is ActionState.CLICKING
    monkeypatch.setattr(pipeline.engine.jump_gate, "accept", lambda *args: False)

    snapshot = pipeline.send(.4 if phase == "candidate" else 1, dx=90)

    assert snapshot.pinch_phase == phase
    assert pipeline.engine.action_machine.state is (
        ActionState.MOVING if phase == "candidate" else ActionState.CLICKING
    )
    assert not pipeline.events("left_down")
    assert not pipeline.events("left_dragged")


def test_default_gate_still_blocks_ordinary_pointer_outlier(make_pipeline, monkeypatch):
    pipeline = make_pipeline()
    pipeline.prime(speed=0)
    decisions = record_gate(pipeline, monkeypatch)
    before = list(pipeline.native.mouse)
    landmarks = hand()
    landmarks[8] = (620, 440, 0)

    observe(pipeline, landmarks)

    assert decisions == [False]
    assert pipeline.native.mouse == before


def test_rejected_release_cannot_run_optional_combo_or_contextual_commands(
    make_pipeline, monkeypatch,
):
    pipeline = make_pipeline()
    pipeline.prime(speed=0)
    pipeline.hold(.15, 1)
    before_release(pipeline)
    engine = pipeline.engine
    engine.pointer_scroll_enabled = False
    engine.config["gestures"]["peace"] = {
        "enabled": True, "action": "hotkey", "hotkey": "cmd+w",
    }
    original_classify = engine.classifier.classify

    def competing_label(landmarks, *, timestamp):
        original_classify(landmarks, timestamp=timestamp)
        return "peace"

    monkeypatch.setattr(engine.classifier, "classify", competing_label)
    calls = []
    monkeypatch.setattr(engine.combo_detector, "update", lambda *args, **kwargs: calls.append("combo"))
    monkeypatch.setattr(engine.contextual_intent_controller, "observe",
                        lambda *args, **kwargs: calls.append("contextual"))
    landmarks = hand()
    landmarks[8] = (620, 440, 0)

    released = observe(pipeline, landmarks)

    assert released.pinch_phase == "released"
    assert not calls
    assert not pipeline.native.hotkeys
    assert not pipeline.native.scrolls
    assert len(pipeline.events("left_down")) == len(pipeline.events("left_up")) == 1


def test_rejected_release_still_validates_its_physical_timestamps(make_pipeline, monkeypatch):
    from dataclasses import replace

    pipeline = make_pipeline()
    pipeline.prime(speed=0)
    pipeline.hold(.15, 1)
    before_release(pipeline)
    original_update = pipeline.engine.pinch_intent.update

    def invalid_release(*args, **kwargs):
        evidence = original_update(*args, **kwargs)
        if evidence.phase == "released":
            return replace(evidence, opened_at=pipeline.clock.now + 1)
        return evidence

    monkeypatch.setattr(pipeline.engine.pinch_intent, "update", invalid_release)
    landmarks = hand()
    landmarks[8] = (620, 440, 0)

    observe(pipeline, landmarks)

    assert pipeline.engine.action_machine.state is ActionState.MOVING
    assert not pipeline.events("left_down")
    pipeline.hold(.4)
    assert not pipeline.events("left_down")
