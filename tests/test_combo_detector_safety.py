from core.combo_detector import ComboDetector


def test_runtime_combo_detector_rejects_pointer_lifecycle_nodes():
    detector = ComboDetector()

    detector.set_combos([
        {"id": "unsafe-first", "gesture1": "point", "gesture2": "peace", "action": "scroll_up"},
        {"id": "unsafe-second", "gesture1": "peace", "gesture2": "pinch", "action": "scroll_up"},
        {"id": "safe", "gesture1": "peace", "gesture2": "thumb_up", "action": "scroll_up"},
        {"id": "unsupported", "gesture1": "peace", "gesture2": "thumb_down", "action": "screenshot"},
    ])

    assert detector.combos == [
        {"id": "safe", "gesture1": "peace", "gesture2": "thumb_up", "action": "scroll_up"}
    ]
