from pathlib import Path
import sys

from core.resource_paths import model_resource_path


def test_model_resource_path_uses_source_root_when_not_frozen(monkeypatch):
    monkeypatch.delattr("sys._MEIPASS", raising=False)

    assert model_resource_path() == Path(__file__).resolve().parents[1] / "core" / "models" / "hand_landmarker.task"


def test_model_resource_path_uses_pyinstaller_resource_root_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert model_resource_path() == tmp_path / "models" / "hand_landmarker.task"


def test_model_resource_path_falls_back_to_packaged_core_data(monkeypatch, tmp_path):
    monkeypatch.delattr("sys._MEIPASS", raising=False)
    monkeypatch.setattr("core.resource_paths.resource_root", lambda: tmp_path)

    assert model_resource_path() == Path(__file__).resolve().parents[1] / "core" / "models" / "hand_landmarker.task"
