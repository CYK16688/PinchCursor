"""Resolve bundled resources in source and PyInstaller-frozen executions."""

from __future__ import annotations

from pathlib import Path
import sys


def resource_root() -> Path:
    """Return the source root or PyInstaller extraction root for bundled assets."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[1]


def model_resource_path() -> Path:
    """Find the bundled model in frozen, source, and wheel installations."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root) / "models" / "hand_landmarker.task"

    source_model = resource_root() / "models" / "hand_landmarker.task"
    if source_model.is_file():
        return source_model
    return Path(__file__).resolve().parent / "models" / "hand_landmarker.task"
