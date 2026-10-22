"""Feedback preferences for the pointer-adjacent HUD."""

from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLabel, QSpinBox, QVBoxLayout, QWidget

from gui.i18n import tr


class FeedbackSettingsPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.title_label = QLabel()
        self.title_label.setObjectName("settingsPageTitle")
        self.description_label = QLabel()
        self.description_label.setObjectName("hintLabel")
        self.description_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.description_label)
        self.group = QGroupBox()
        form = QFormLayout(self.group)
        feedback = self.config.get("feedback") or {}
        self.mode_combo = QComboBox()
        for key, mode in (
            ("feedback.quiet", "quiet"),
            ("feedback.standard", "standard"),
            ("feedback.learn", "learn"),
        ):
            self.mode_combo.addItem(tr(key), mode)
        self.mode_combo.setCurrentIndex(max(self.mode_combo.findData(feedback.get("mode", "standard")), 0))
        self.opacity_input = QSpinBox(); self.opacity_input.setRange(40, 100); self.opacity_input.setSuffix(" %")
        self.opacity_input.setValue(round(feedback.get("opacity", 0.92) * 100))
        self.scale_input = QSpinBox(); self.scale_input.setRange(80, 160); self.scale_input.setSuffix(" %")
        self.scale_input.setValue(round(feedback.get("scale", 1.0) * 100))
        self.feedback_level_label = QLabel()
        self.opacity_label = QLabel()
        self.scale_label = QLabel()
        form.addRow(self.feedback_level_label, self.mode_combo)
        form.addRow(self.opacity_label, self.opacity_input)
        form.addRow(self.scale_label, self.scale_input)
        layout.addWidget(self.group)
        layout.addStretch()
        self.retranslate_ui()

    def retranslate_ui(self):
        """Refresh fixed labels while retaining the staged feedback values."""
        selected_mode = self.mode_combo.currentData()
        self.title_label.setText(tr("feedback.title"))
        self.description_label.setText(tr("feedback.description"))
        self.group.setTitle(tr("feedback.group"))
        self.feedback_level_label.setText(tr("feedback.level"))
        self.opacity_label.setText(tr("feedback.opacity"))
        self.scale_label.setText(tr("feedback.scale"))
        for key, mode in (
            ("feedback.quiet", "quiet"),
            ("feedback.standard", "standard"),
            ("feedback.learn", "learn"),
        ):
            index = self.mode_combo.findData(mode)
            self.mode_combo.setItemText(index, tr(key))
        self.mode_combo.setCurrentIndex(max(self.mode_combo.findData(selected_mode), 0))

    def apply_to_config(self):
        self.config.set("feedback", "mode", self.mode_combo.currentData())
        self.config.set("feedback", "opacity", self.opacity_input.value() / 100)
        self.config.set("feedback", "scale", self.scale_input.value() / 100)
