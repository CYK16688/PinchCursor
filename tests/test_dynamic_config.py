"""The pure shortcut readers: what a saved record becomes at runtime."""

from core.dynamic_config import restore_dynamic_templates, restore_static_templates


def _static(**overrides):
    record = {
        "template_id": "saved",
        "name": "Saved",
        "feature_vector": [0.05] * 63,
        "threshold": 0.2,
    }
    record.update(overrides)
    return record


def test_a_valid_static_record_becomes_a_template():
    templates = restore_static_templates([_static()])
    assert list(templates) == ["saved"]
    assert templates["saved"].threshold == 0.2


def test_static_records_with_a_bad_shape_are_dropped():
    bad = [
        _static(feature_vector=[0.05] * 62),
        _static(feature_vector=[0.05] * 62 + [float("nan")]),
        _static(threshold=0),
        _static(threshold=-1),
        _static(template_id=""),
        "not a dict",
    ]
    assert restore_static_templates(bad) == {}


def test_non_list_input_reads_as_empty():
    assert restore_static_templates(None) == {}
    assert restore_static_templates({"not": "a list"}) == {}


def _dynamic(**overrides):
    record = {
        "template_id": "dyn",
        "name": "Dyn",
        "action": "scroll_up",
        "samples": [[[0.0] * 63, [0.1] * 63]],
        "threshold": 0.18,
        "cooldown_seconds": 0.75,
        "min_motion_energy": 0.05,
    }
    record.update(overrides)
    return record


def test_a_valid_dynamic_record_becomes_a_template():
    templates = restore_dynamic_templates([_dynamic()])
    assert len(templates) == 1
    assert templates[0].template_id == "dyn"
    assert templates[0].context_category == ""


def test_dynamic_records_missing_a_field_are_dropped():
    missing = _dynamic()
    del missing["samples"]
    assert restore_dynamic_templates([missing, "junk"]) == []


def test_dynamic_non_list_input_reads_as_empty():
    assert restore_dynamic_templates(None) == []
