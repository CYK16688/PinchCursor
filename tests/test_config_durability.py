"""Settings persistence must survive a crash and never live inside the bundle.

A frozen ``.app`` resolves ``utils/config_manager.py`` into ``Contents/Frameworks``;
writing there adds a file to the sealed bundle, which invalidates the code
signature (and with it every TCC grant keyed to it) and loses the settings on the
next build. These tests pin the two guarantees that fix depends on: the writable
path is per-user, and a save cannot truncate the live file.
"""

import json
import os

import pytest

from utils import config_manager
from utils.config_manager import ConfigManager, user_data_dir


def test_user_data_dir_is_per_user_not_the_package(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    directory = user_data_dir()
    package_dir = os.path.dirname(os.path.dirname(os.path.abspath(config_manager.__file__)))
    assert os.path.abspath(directory) != os.path.abspath(package_dir)
    assert directory.startswith(str(tmp_path))


def test_save_leaves_no_temporary_file_behind(tmp_path):
    workspace = tmp_path / "config"
    workspace.mkdir()
    path = workspace / "settings.json"
    manager = ConfigManager(config_path=path)
    manager.set("pointer_assist", "max_snap_distance", 31.0)
    manager.save()
    assert json.loads(path.read_text(encoding="utf-8"))["pointer_assist"]["max_snap_distance"] == 31.0
    assert sorted(entry.name for entry in workspace.iterdir()) == ["settings.json"]


def test_a_failed_save_keeps_the_previous_file_intact(tmp_path, monkeypatch):
    workspace = tmp_path / "config"
    workspace.mkdir()
    path = workspace / "settings.json"
    manager = ConfigManager(config_path=path)
    manager.set("pointer_assist", "max_snap_distance", 24.0)
    manager.save()
    good = path.read_text(encoding="utf-8")

    manager.set("pointer_assist", "max_snap_distance", 99.0)
    monkeypatch.setattr(config_manager.os, "replace", lambda *_a, **_k: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        manager.save()

    # The old document is still readable, and no half-written temp file survives.
    assert path.read_text(encoding="utf-8") == good
    assert sorted(entry.name for entry in workspace.iterdir()) == ["settings.json"]


def test_an_unreadable_file_is_quarantined_and_reported(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"broken": ', encoding="utf-8")
    manager = ConfigManager(config_path=path)

    assert manager.get("pointer_assist", "max_snap_distance") == 24.0
    assert config_manager.last_load_error()
    quarantined = [name for name in os.listdir(tmp_path) if ".corrupt-" in name]
    assert len(quarantined) == 1
    # The unusable bytes are preserved, not replaced by the defaults.
    assert (tmp_path / quarantined[0]).read_text(encoding="utf-8") == '{"broken": '


def test_a_clean_load_reports_no_error(tmp_path):
    path = tmp_path / "settings.json"
    ConfigManager(config_path=path).save()
    ConfigManager(config_path=path)
    assert config_manager.last_load_error() == ""


def test_legacy_settings_next_to_the_package_are_migrated(tmp_path, monkeypatch):
    legacy = tmp_path / "bundle" / "settings.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({"ui": {"language": "en"}}), encoding="utf-8")
    legacy_db = legacy.parent / "telemetry.sqlite3"
    legacy_db.write_text("db", encoding="utf-8")
    monkeypatch.setattr(config_manager, "_legacy_config_path", lambda: str(legacy))

    target = tmp_path / "support" / "settings.json"
    assert config_manager.migrate_legacy_config(str(target)) == str(legacy)

    assert json.loads(target.read_text(encoding="utf-8"))["ui"]["language"] == "en"
    assert not legacy.exists()
    # The event log used to live beside the settings file; it follows them.
    assert (tmp_path / "support" / "telemetry.sqlite3").read_text(encoding="utf-8") == "db"
    assert not legacy_db.exists()


def test_migration_never_overwrites_an_existing_settings_file(tmp_path, monkeypatch):
    legacy = tmp_path / "bundle" / "settings.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({"ui": {"language": "en"}}), encoding="utf-8")
    monkeypatch.setattr(config_manager, "_legacy_config_path", lambda: str(legacy))

    target = tmp_path / "support" / "settings.json"
    target.parent.mkdir()
    target.write_text(json.dumps({"ui": {"language": "zh_CN"}}), encoding="utf-8")

    assert config_manager.migrate_legacy_config(str(target)) is None
    assert json.loads(target.read_text(encoding="utf-8"))["ui"]["language"] == "zh_CN"
    assert legacy.exists()
