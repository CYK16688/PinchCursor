"""Read-only view of the local telemetry log.

The page is a reader only: it never turns recording on and never creates the
database. Everything it shows already exists on disk, so visiting Settings can
not start collecting anything.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.learning_report import TRANSITION_MIN_EPISODES, build_status
from core.telemetry import TelemetryStore

from .i18n import tr

EMPTY_VALUE = "—"

# The store counts actions by name and measures repeat clicks over the click
# actions, but it exposes no click total of its own. Mirroring that set keeps
# "clicks" and "repeat clicks" describing the same population.
_CLICK_ACTIONS = frozenset({"left_click", "right_click", "double_click"})


class DiagnosticsPage(QWidget):
    """Settings page that reports what the telemetry log already contains."""

    def __init__(self, store_path: str, parent=None):
        super().__init__(parent)
        self.store_path = os.fspath(store_path)
        self._build_ui()
        self.refresh()

    # -- construction ------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.addStretch(1)
        self.refresh_button = QPushButton()
        self.refresh_button.setObjectName("quietButton")
        self.refresh_button.clicked.connect(self.refresh)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        self.group = QGroupBox()
        self.form = QFormLayout(self.group)
        # QGroupBox already contributes its own padding through the shared QSS;
        # a second set of margins here would indent the rows twice.
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setHorizontalSpacing(16)
        self.form.setVerticalSpacing(10)
        # Labels stay on the left and values on the right, so a column of
        # figures can be compared at a glance instead of read row by row.
        self.form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.empty_label = QLabel()
        self.empty_label.setObjectName("hintLabel")
        self.empty_label.setWordWrap(True)
        # Row 0 spans the full width, so one form can hold either the empty
        # notice or the figures without moving between layouts.
        self.form.addRow(self.empty_label)

        form = self.form
        self.clicks_label = QLabel()
        self.clicks_value = self._add_row(form, self.clicks_label)
        self.misses_label = QLabel()
        self.misses_value = self._add_row(form, self.misses_label)
        self.snaps_label = QLabel()
        self.snaps_value = self._add_row(form, self.snaps_label)
        self.executed_label = QLabel()
        self.executed_value = self._add_row(form, self.executed_label)
        self.latency_label = QLabel()
        self.latency_value = self._add_row(form, self.latency_label)
        self.episodes_label = QLabel()
        self.episodes_value = self._add_row(form, self.episodes_label)
        self.shadow_label = QLabel()
        self.shadow_value = self._add_row(form, self.shadow_label)
        self.size_label = QLabel()
        self.size_value = self._add_row(form, self.size_label)
        self._value_labels = (
            self.clicks_value,
            self.misses_value,
            self.snaps_value,
            self.executed_value,
            self.latency_value,
            self.episodes_value,
            self.shadow_value,
            self.size_value,
        )

        # Row 0 is the empty notice; everything after it is a figure.
        self._metric_rows = tuple(range(1, self.form.rowCount()))

        layout.addWidget(self.group)
        layout.addStretch(1)

        self.retranslate_ui()

    @staticmethod
    def _add_row(form: QFormLayout, label: QLabel) -> QLabel:
        """Add one label/value pair and return the value label."""
        value = QLabel(EMPTY_VALUE)
        value.setObjectName("summaryValue")
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.addRow(label, value)
        return value

    def retranslate_ui(self):
        """Refresh fixed copy; the figures are locale-neutral and stay put."""
        self.group.setTitle(tr("settings.advanced.diagnostics.title"))
        self.refresh_button.setText(tr("settings.advanced.diagnostics.refresh"))
        self.empty_label.setText(tr("settings.advanced.diagnostics.empty"))
        self.clicks_label.setText(tr("settings.advanced.diagnostics.clicks"))
        self.misses_label.setText(tr("settings.advanced.diagnostics.misses"))
        self.snaps_label.setText(tr("settings.advanced.diagnostics.snaps"))
        self.executed_label.setText(tr("settings.advanced.diagnostics.executed"))
        self.latency_label.setText(tr("settings.advanced.diagnostics.latency"))
        self.episodes_label.setText(tr("settings.advanced.diagnostics.episodes"))
        self.shadow_label.setText(tr("settings.advanced.diagnostics.shadow"))
        self.size_label.setText(tr("settings.advanced.diagnostics.size"))

    # -- data --------------------------------------------------------------
    def refresh(self) -> None:
        """Re-read the log and repaint; an unreadable log shows the empty state."""
        summary, size_bytes, learning = self._load()
        if not summary or not summary.get("total"):
            self._render_empty()
            return
        self.empty_label.hide()
        self._set_metrics_visible(True)
        self.clicks_value.setText(_format_count(_click_total(summary)))
        self.misses_value.setText(_format_count(summary.get("click_misses")))
        self.snaps_value.setText(_format_count(summary.get("snaps")))
        self.executed_value.setText(_format_rate(summary.get("executed_rate")))
        self.latency_value.setText(_format_latency(summary.get("mean_latency_ms")))
        self.episodes_value.setText(_format_episodes(learning))
        self.shadow_value.setText(_format_shadow(learning))
        self.size_value.setText(_format_size(size_bytes))

    def _render_empty(self) -> None:
        """Reset every figure, so a purge can not leave stale numbers behind."""
        self._set_metrics_visible(False)
        self.empty_label.show()
        for value in self._value_labels:
            value.setText(EMPTY_VALUE)

    def _set_metrics_visible(self, visible: bool) -> None:
        """Collapse whole rows; hidden rows keep their indices for later use."""
        for row in self._metric_rows:
            self.form.setRowVisible(row, visible)

    def _load(self):
        """Return ``(summary, size_bytes, learning)``; empty values if unreadable."""
        # TelemetryStore creates the database when it opens one, so a missing
        # file has to be rejected before the store is ever constructed.
        if not os.path.isfile(self.store_path):
            return None, 0, None
        store = None
        try:
            store = TelemetryStore(self.store_path, enabled=True)
            learning = build_status(store.transition_rows())
            return store.summary(), store.size_bytes(), learning
        except Exception:
            # A damaged or unreadable log is exactly when someone opens this
            # page; it must read as "no data" rather than break Settings.
            return None, 0, None
        finally:
            if store is not None:
                try:
                    store.close()
                except Exception:
                    pass


def _click_total(summary: dict) -> int:
    """Sum the click actions; the store reports them individually."""
    actions = summary.get("actions") or {}
    return sum(count for action, count in actions.items() if action in _CLICK_ACTIONS)


def _format_episodes(learning) -> str:
    """Progress toward the trainer's gate, not a bare count."""
    if learning is None:
        return EMPTY_VALUE
    return f"{learning.episodes} / {TRANSITION_MIN_EPISODES}"


def _format_shadow(learning) -> str:
    """Agreement between the shadow model and the rule it would replace."""
    if learning is None or learning.shadow_agreement is None:
        return EMPTY_VALUE
    return f"{learning.shadow_agreement * 100:.1f}%"


def _format_count(value) -> str:
    if value is None:
        return EMPTY_VALUE
    return f"{int(value)}"


def _format_rate(rate) -> str:
    return EMPTY_VALUE if rate is None else f"{float(rate) * 100:.1f}%"


def _format_latency(milliseconds) -> str:
    return EMPTY_VALUE if milliseconds is None else f"{float(milliseconds):.1f} ms"


def _format_size(size_bytes) -> str:
    """Show bytes below 1 KB, so a newly created log is not rounded to 0.0 KB."""
    size = float(size_bytes or 0)
    if size < 1024:
        return f"{size:.1f} B"
    return f"{size / 1024:.1f} KB"
