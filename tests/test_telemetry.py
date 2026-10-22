"""Telemetry store: local-only, bounded, fail-closed."""

import sqlite3

from core.telemetry import TelemetryStore, default_path


def _store(tmp_path, enabled=True):
    return TelemetryStore(tmp_path / "telemetry.sqlite3", enabled=enabled)


def test_disabled_store_writes_nothing_and_creates_no_file(tmp_path):
    store = _store(tmp_path, enabled=False)
    store.record("action", action="left_click", executed=True)

    assert store.enabled is False
    assert not (tmp_path / "telemetry.sqlite3").exists()
    assert store.summary()["total"] == 0


def test_records_actions_and_summarises_them(tmp_path):
    store = _store(tmp_path)
    store.record("action", action="left_click", executed=True, latency_ms=12.5)
    store.record("action", action="right_click", executed=False, latency_ms=7.5)

    summary = store.summary()

    assert summary["total"] == 2
    assert summary["actions"] == {"left_click": 1, "right_click": 1}
    assert summary["executed_rate"] == 0.5
    assert summary["mean_latency_ms"] == 10.0


def test_unknown_fields_are_dropped_not_stored(tmp_path):
    store = _store(tmp_path)
    store.record("action", action="left_click", executed=True, window_title="Secret", text="hello")

    row = store.recent(1)[0]

    assert "window_title" not in row
    assert "text" not in row
    assert row["action"] == "left_click"


def test_schema_has_no_content_or_image_columns(tmp_path):
    store = _store(tmp_path)
    store.record("action", action="left_click", executed=True)
    store.close()

    connection = sqlite3.connect(tmp_path / "telemetry.sqlite3")
    columns = [row[1] for row in connection.execute("PRAGMA table_info(events)")]
    types = [row[2].upper() for row in connection.execute("PRAGMA table_info(events)")]
    connection.close()

    assert "blob" not in types
    assert not any(name in columns for name in ("image", "frame", "title", "text", "label"))


def test_assist_predictions_are_summarised(tmp_path):
    store = _store(tmp_path)
    store.record("assist", snap_distance=12.0, confidence=0.8)
    store.record("assist", snap_distance=4.0, confidence=0.9)

    summary = store.summary()

    assert summary["snaps"] == 2
    assert summary["mean_snap_distance"] == 8.0


def test_click_misses_count_a_quick_redo_elsewhere(tmp_path):
    store = _store(tmp_path)
    store.record("action", action="left_click", executed=True, x=100, y=100, timestamp=1000.0)
    store.record("action", action="left_click", executed=True, x=160, y=100, timestamp=1000.6)
    store.record("action", action="left_click", executed=True, x=160, y=100, timestamp=1005.0)

    assert store.summary()["click_misses"] == 1


def test_a_second_click_at_the_same_place_is_not_a_miss(tmp_path):
    store = _store(tmp_path)
    store.record("action", action="left_click", executed=True, x=100, y=100, timestamp=1000.0)
    store.record("action", action="left_click", executed=True, x=104, y=102, timestamp=1000.8)

    assert store.summary()["click_misses"] == 0


def test_purge_empties_the_log(tmp_path):
    store = _store(tmp_path)
    store.record("action", action="left_click", executed=True)

    store.purge()

    assert store.summary()["total"] == 0


def test_writes_to_an_unwritable_path_do_not_raise(tmp_path):
    store = TelemetryStore(tmp_path / "missing" / "telemetry.sqlite3", enabled=True)

    store.record("action", action="left_click", executed=True)  # must not raise
    assert store.summary()["total"] == 0


def test_rows_are_pruned_to_the_cap(tmp_path, monkeypatch):
    import core.telemetry as telemetry

    monkeypatch.setattr(telemetry, "_PRUNE_EVERY", 1)
    monkeypatch.setattr(telemetry, "MAX_ROWS", 40)
    store = _store(tmp_path)
    for index in range(45):
        store.record("action", action="move_cursor", executed=True, x=index)

    assert store.summary()["total"] == 40


def test_rows_older_than_the_retention_window_are_dropped_on_open(tmp_path):
    store = _store(tmp_path)
    store.record("action", action="left_click", executed=True, timestamp=1.0)  # 1970
    store.record("action", action="right_click", executed=True)
    store.close()

    reopened = _store(tmp_path)

    assert reopened.summary()["total"] == 1


def test_retention_can_be_shortened_per_store(tmp_path):
    store = TelemetryStore(tmp_path / "t.sqlite3", enabled=True, retention_days=1)
    store.record("action", action="left_click", executed=True, timestamp=1.0)
    store._prune()

    assert store.summary()["total"] == 0


def test_size_is_reported_and_shrinks_after_purge(tmp_path):
    store = _store(tmp_path)
    for index in range(200):
        store.record("action", action="left_click", executed=True, x=index, y=index)
    store.close()

    before = store.size_bytes()
    store = _store(tmp_path)
    store.purge()

    assert before > 0
    assert store.size_bytes() < before


def test_pending_writes_are_flushed_on_close(tmp_path):
    store = _store(tmp_path)
    store.record("action", action="left_click", executed=True)
    store.close()

    reopened = _store(tmp_path)
    assert reopened.summary()["total"] == 1


def test_default_path_sits_beside_the_settings_file(tmp_path):
    assert default_path(tmp_path / "settings.json") == str(tmp_path / "telemetry.sqlite3")


def test_summary_of_an_empty_store_is_well_formed(tmp_path):
    summary = _store(tmp_path).summary()

    assert summary["total"] == 0
    assert summary["executed_rate"] is None
    assert summary["click_misses"] == 0
