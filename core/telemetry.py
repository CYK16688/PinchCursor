"""Local, opt-in telemetry for the learning loops.

What this stores, and what it deliberately does not:

* Stored — timestamps, gesture/action names, which accessibility category and
  role was under the pointer, cursor geometry, target geometry, confidence,
  latency, and whether the action executed.
* Never stored — camera frames, screenshots, window titles, control labels,
  typed text, or app content. The schema has no text blob for content and no
  image column at all.

The store is fail-closed: telemetry is diagnostic, so a corrupt database or a
read-only path must never interrupt pointer control.
"""

from __future__ import annotations

from collections.abc import Sequence

import os
import json
import sqlite3
import threading
import time

MAX_ROWS = 20000
# Candidates grow a few rows per click; this caps a long-lived install.
MAX_CANDIDATE_ROWS = 100000
# Old data has no value once the ranking question has been answered, and a
# year-old log only makes the file bigger.
RETENTION_DAYS = 30
_PRUNE_EVERY = 256
# Durability is not worth a disk sync per event; a crash may lose the last
# second of telemetry, which is invisible to every consumer.
_COMMIT_EVERY = 32
_COMMIT_SECONDS = 2.0

# Only these fields are persisted; anything else a caller passes is dropped,
# which keeps accidental content (labels, titles) out of the database.
_FIELDS = (
    "app",
    "category",
    "role",
    "gesture",
    "action",
    "executed",
    "confidence",
    "latency_ms",
    "x",
    "y",
    "target_w",
    "target_h",
    "snap_distance",
)

_CLICK_ACTIONS = frozenset({"left_click", "right_click", "double_click"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    app TEXT,
    category TEXT,
    role TEXT,
    gesture TEXT,
    action TEXT,
    executed INTEGER,
    confidence REAL,
    latency_ms REAL,
    x INTEGER,
    y INTEGER,
    target_w INTEGER,
    target_h INTEGER,
    snap_distance REAL
);
CREATE INDEX IF NOT EXISTS events_ts ON events (ts);

-- One row per candidate that was on screen at a lock, with the feature vector
-- the ranker would see. Storing the vector (not just geometry) keeps training
-- and inference on exactly the same numbers.
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    lock_id TEXT NOT NULL,
    role TEXT,
    x INTEGER,
    y INTEGER,
    w INTEGER,
    h INTEGER,
    dist REAL,
    inside INTEGER,
    bayes REAL,
    features TEXT,
    chosen_bayes INTEGER,
    chosen_raw INTEGER
);
CREATE INDEX IF NOT EXISTS candidates_lock ON candidates (lock_id);
"""


def default_path(config_path: str) -> str:
    """Place the database beside the settings file it belongs to."""
    directory = os.path.dirname(os.path.abspath(os.fspath(config_path)))
    return os.path.join(directory, "telemetry.sqlite3")


class TelemetryStore:
    """A bounded, local-only event log."""

    def __init__(
        self, path, *, enabled: bool = False, retention_days: int = RETENTION_DAYS
    ) -> None:
        self.path = os.fspath(path)
        self._enabled = bool(enabled)
        self._retention_days = max(1, int(retention_days))
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self._writes = 0
        self._pending = 0
        self._last_commit = time.monotonic()
        if self._enabled:
            self._open()

    # -- lifecycle ---------------------------------------------------------
    def _open(self) -> bool:
        try:
            connection = sqlite3.connect(self.path, check_same_thread=False)
            # DELETE removes the rollback journal after each transaction. WAL
            # would leave a side file that grows on its own, and TRUNCATE keeps
            # an empty one around.
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.executescript(_SCHEMA)
            connection.commit()
        except (OSError, sqlite3.Error):
            self._connection = None
            return False
        self._connection = connection
        # Expired rows should disappear even if the app is only opened briefly.
        self._prune()
        return True

    @property
    def enabled(self) -> bool:
        return self._enabled and self._connection is not None

    def set_enabled(self, enabled: bool) -> None:
        """Turn collection on or off without losing what is already stored."""
        self._enabled = bool(enabled)
        if self._enabled and self._connection is None:
            self._open()
        elif not self._enabled:
            self.close()

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                try:
                    self._connection.commit()
                    self._connection.close()
                except sqlite3.Error:
                    pass
                self._connection = None
            self._pending = 0

    # -- writes ------------------------------------------------------------
    def record(self, kind: str, *, timestamp: float | None = None, **fields) -> None:
        """Append one event; unknown fields and bad values are dropped."""
        if not self.enabled:
            return
        if not isinstance(kind, str) or not kind.strip():
            return
        values = {name: _coerce(name, fields.get(name)) for name in _FIELDS}
        stamp = time.time() if timestamp is None else _float_or_none(timestamp)
        if stamp is None:
            return
        with self._lock:
            if self._connection is None:
                return
            try:
                self._connection.execute(
                    "INSERT INTO events (ts, kind, "
                    + ", ".join(_FIELDS)
                    + ") VALUES (?, ?"
                    + ", ?" * len(_FIELDS)
                    + ")",
                    (stamp, kind.strip()[:40], *[values[name] for name in _FIELDS]),
                )
                self._pending += 1
                if (
                    self._pending >= _COMMIT_EVERY
                    or time.monotonic() - self._last_commit >= _COMMIT_SECONDS
                ):
                    self._connection.commit()
                    self._pending = 0
                    self._last_commit = time.monotonic()
            except sqlite3.Error:
                return
            self._writes += 1
            if self._writes % _PRUNE_EVERY == 0:
                self._prune()

    def record_candidates(self, lock_id: str, rows: Sequence[dict], *, timestamp=None) -> None:
        """Store every candidate seen at one lock, with its feature vector.

        ``chosen_bayes`` records what the current policy picked; ``chosen_raw``
        records the candidate the hand was physically over. Only the latter is
        an unbiased label, which is why both are stored.
        """
        if not self.enabled or not rows or not isinstance(lock_id, str):
            return
        stamp = time.time() if timestamp is None else _float_or_none(timestamp)
        if stamp is None:
            return
        with self._lock:
            if self._connection is None:
                return
            try:
                self._connection.executemany(
                    "INSERT INTO candidates (ts, lock_id, role, x, y, w, h, dist, inside,"
                    " bayes, features, chosen_bayes, chosen_raw)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            stamp,
                            lock_id[:64],
                            str(row.get("role") or "")[:64],
                            int(row.get("x", 0)),
                            int(row.get("y", 0)),
                            int(row.get("w", 0)),
                            int(row.get("h", 0)),
                            _float_or_none(row.get("dist")) or 0.0,
                            1 if row.get("inside") else 0,
                            _float_or_none(row.get("bayes")) or 0.0,
                            json.dumps(
                                [
                                    round(float(value), 6)
                                    for value in (row.get("features") or ())
                                ]
                            ),
                            1 if row.get("chosen_bayes") else 0,
                            1 if row.get("chosen_raw") else 0,
                        )
                        for row in rows
                        if isinstance(row, dict)
                    ],
                )
                self._pending += len(rows)
                if self._pending >= _COMMIT_EVERY:
                    self._connection.commit()
                    self._pending = 0
                    self._last_commit = time.monotonic()
            except (sqlite3.Error, TypeError, ValueError):
                return

    def candidate_groups(self, limit_locks: int = 5000) -> list[dict]:
        """Return candidate rows grouped by lock, oldest first.

        Groups without exactly one ``chosen_raw`` row are dropped: an ambiguous
        or missing physical aim cannot label a training example.
        """
        if self._connection is None:
            return []
        try:
            cursor = self._connection.execute(
                "SELECT lock_id, ts, role, features, bayes, chosen_bayes, chosen_raw"
                " FROM candidates ORDER BY id"
            )
            grouped: dict[str, dict] = {}
            for lock_id, ts, role, features, bayes, chosen_bayes, chosen_raw in cursor.fetchall():
                group = grouped.setdefault(
                    lock_id, {"lock_id": lock_id, "ts": ts, "rows": []}
                )
                try:
                    vector = json.loads(features or "[]")
                except (TypeError, ValueError):
                    continue
                group["rows"].append(
                    {
                        "role": role or "",
                        "features": vector,
                        "bayes": bayes or 0.0,
                        "chosen_bayes": bool(chosen_bayes),
                        "chosen_raw": bool(chosen_raw),
                    }
                )
        except sqlite3.Error:
            return []
        groups = []
        for group in grouped.values():
            raw = [row for row in group["rows"] if row["chosen_raw"]]
            if len(raw) != 1:
                continue
            groups.append(group)
        return groups[-limit_locks:]

    def _prune(self) -> None:
        """Drop expired rows, then enforce the row caps."""
        if self._connection is None:
            return
        cutoff = time.time() - self._retention_days * 86400
        try:
            self._connection.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
            self._connection.execute("DELETE FROM candidates WHERE ts < ?", (cutoff,))
            self._connection.execute(
                "DELETE FROM events WHERE id NOT IN "
                "(SELECT id FROM events ORDER BY id DESC LIMIT ?)",
                (MAX_ROWS,),
            )
            self._connection.execute(
                "DELETE FROM candidates WHERE id NOT IN "
                "(SELECT id FROM candidates ORDER BY id DESC LIMIT ?)",
                (MAX_CANDIDATE_ROWS,),
            )
            self._connection.commit()
            self._pending = 0
            self._last_commit = time.monotonic()
        except sqlite3.Error:
            pass

    # -- reads -------------------------------------------------------------
    def recent(self, limit: int = 50) -> list[dict]:
        """Return the newest events first, for the diagnostics view."""
        if self._connection is None:
            return []
        try:
            cursor = self._connection.execute(
                "SELECT ts, kind, " + ", ".join(_FIELDS) + " FROM events ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            )
            names = ("ts", "kind") + _FIELDS
            return [dict(zip(names, row)) for row in cursor.fetchall()]
        except (sqlite3.Error, TypeError, ValueError):
            return []

    def summary(self) -> dict:
        """Aggregate the log into the metrics the plan promises to move."""
        empty = {
            "total": 0,
            "by_kind": {},
            "actions": {},
            "executed_rate": None,
            "snaps": 0,
            "mean_snap_distance": None,
            "click_misses": 0,
            "mean_latency_ms": None,
        }
        if self._connection is None:
            return empty
        try:
            rows = self._connection.execute(
                "SELECT kind, action, executed, snap_distance, latency_ms, x, y, ts"
                " FROM events ORDER BY id"
            ).fetchall()
        except sqlite3.Error:
            return empty
        if not rows:
            return empty

        by_kind: dict[str, int] = {}
        actions: dict[str, int] = {}
        executed = attempted = 0
        snaps = 0
        snap_total = 0.0
        latencies: list[float] = []
        clicks: list[tuple[float, int | None, int | None]] = []
        for kind, action, was_executed, snap_distance, latency, x, y, ts in rows:
            by_kind[kind] = by_kind.get(kind, 0) + 1
            if action:
                actions[action] = actions.get(action, 0) + 1
            if action and action != "move_cursor":
                attempted += 1
                if was_executed:
                    executed += 1
            if kind == "assist" and snap_distance is not None:
                snaps += 1
                snap_total += float(snap_distance)
            if latency is not None:
                latencies.append(float(latency))
            if action in _CLICK_ACTIONS and was_executed:
                clicks.append((float(ts), x, y))

        return {
            "total": len(rows),
            "by_kind": by_kind,
            "actions": actions,
            "executed_rate": (executed / attempted) if attempted else None,
            "snaps": snaps,
            "mean_snap_distance": (snap_total / snaps) if snaps else None,
            "click_misses": _count_misses(clicks),
            "mean_latency_ms": (sum(latencies) / len(latencies)) if latencies else None,
        }

    def purge(self) -> None:
        """Delete every stored event; the user's one-click erase."""
        if self._connection is None:
            return
        with self._lock:
            try:
                self._connection.execute("DELETE FROM events")
                self._connection.execute("DELETE FROM candidates")
                self._connection.commit()
                # DELETE only frees pages for reuse; the file itself shrinks
                # only after VACUUM, and "clear my data" has to mean the disk.
                self._connection.execute("VACUUM")
                self._pending = 0
            except sqlite3.Error:
                pass

    def size_bytes(self) -> int:
        """Return the on-disk size, so growth is observable rather than assumed."""
        try:
            return os.path.getsize(self.path)
        except OSError:
            return 0


def _count_misses(clicks: list[tuple[float, int | None, int | None]]) -> int:
    """Count clicks immediately followed by another click elsewhere.

    A click the user had to redo is the cheapest honest error signal this app
    can collect without asking them anything.
    """
    misses = 0
    for index, (stamp, x, y) in enumerate(clicks[:-1]):
        next_stamp, next_x, next_y = clicks[index + 1]
        if next_stamp - stamp > 1.5:
            continue
        if x is None or y is None or next_x is None or next_y is None:
            misses += 1
            continue
        if abs(next_x - x) > 24 or abs(next_y - y) > 24:
            misses += 1
    return misses


def _float_or_none(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _coerce(name: str, value):
    if value is None:
        return None
    if name == "executed":
        return 1 if value else 0
    if name in ("app", "category", "role", "gesture", "action"):
        if not isinstance(value, str):
            return None
        return value[:64]
    if name in ("x", "y", "target_w", "target_h"):
        number = _float_or_none(value)
        return None if number is None else int(number)
    return _float_or_none(value)
