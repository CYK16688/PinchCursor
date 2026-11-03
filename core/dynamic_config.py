"""Pure readers that turn persisted shortcut records into runtime objects.

Both the control engine and the main window restore the same recorded shortcuts
from settings. Keeping that conversion in one place means the two cannot drift
apart, and neither needs the other's private methods to do it.

Nothing here touches runtime state: every function takes the persisted mapping
and returns new objects, so the caller decides where they live. Each function
reads the *section mapping* it is handed, never a config object, so a test can
call it with a plain dict.
"""
from __future__ import annotations

from math import isfinite
from numbers import Real

from core.static_gesture_template import StaticGestureTemplate
from utils.dynamic_gesture_template import DynamicGestureTemplate


def restore_static_templates(template_dicts):
    """Convert valid persisted custom-trigger dictionaries into runtime templates."""
    if not isinstance(template_dicts, list):
        return {}

    templates = {}
    for template_dict in template_dicts:
        if not isinstance(template_dict, dict):
            continue
        try:
            feature_vector = tuple(template_dict["feature_vector"])
            raw_threshold = template_dict.get("threshold", 0.18)
        except (KeyError, TypeError):
            continue
        if (
            len(feature_vector) != 63
            or not isinstance(raw_threshold, Real)
            or isinstance(raw_threshold, bool)
            or not all(
                isinstance(value, Real) and not isinstance(value, bool) and isfinite(value)
                for value in feature_vector
            )
            or not isfinite(raw_threshold)
            or raw_threshold <= 0
        ):
            continue
        template = StaticGestureTemplate(
            template_id=str(template_dict.get("template_id", "")),
            name=str(template_dict.get("name", "")),
            feature_vector=tuple(float(value) for value in feature_vector),
            threshold=float(raw_threshold),
        )
        if template.template_id:
            templates[template.template_id] = template
    return templates


def restore_dynamic_templates(template_dicts):
    """Convert persisted, normalized dynamic shortcut records into runtime templates."""
    templates = []
    if not isinstance(template_dicts, list):
        return templates
    for item in template_dicts:
        if not isinstance(item, dict):
            continue
        try:
            samples = tuple(
                tuple(tuple(frame) for frame in sample)
                for sample in item["samples"]
            )
            templates.append(DynamicGestureTemplate(
                template_id=item["template_id"],
                name=item["name"],
                action=item["action"],
                samples=samples,
                threshold=item["threshold"],
                cooldown_seconds=item["cooldown_seconds"],
                min_motion_energy=item["min_motion_energy"],
                context_category=str(item.get("context_category", "")),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return templates
