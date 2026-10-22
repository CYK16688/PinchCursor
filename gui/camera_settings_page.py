"""Stable-device camera configuration page for Precision Desk."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from gui.i18n import tr


class CameraSettingsPage(QWidget):
    """Stages camera selection locally and writes it only on Settings Save."""

    def __init__(self, config, camera_service, parent=None):
        super().__init__(parent)
        self.config = config
        self.camera_service = camera_service
        self.selected_device_id = (config.get("camera") or {}).get("device_id", "")
        self.devices = []
        self.device_buttons = QButtonGroup(self)
        self.device_buttons.setExclusive(True)
        self._build_ui()
        self.refresh_devices()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(16)

        self.title_label = QLabel()
        self.title_label.setObjectName("settingsPageTitle")
        self.description_label = QLabel()
        self.description_label.setObjectName("hintLabel")
        self.description_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.description_label)

        self.selected_status = QLabel()
        self.selected_status.setObjectName("hintLabel")
        layout.addWidget(self.selected_status)

        self.devices_layout = QVBoxLayout()
        self.devices_layout.setSpacing(8)
        layout.addLayout(self.devices_layout)

        self.refresh_button = QPushButton()
        self.refresh_button.clicked.connect(self.refresh_devices)
        layout.addWidget(self.refresh_button, alignment=Qt.AlignLeft)

        self.resolution_title = QLabel()
        self.resolution_title.setObjectName("summaryLabel")
        layout.addWidget(self.resolution_title)
        resolution_layout = QHBoxLayout()
        self.width_input = QSpinBox()
        self.width_input.setRange(320, 1920)
        self.width_input.setSingleStep(160)
        self.height_input = QSpinBox()
        self.height_input.setRange(240, 1080)
        self.height_input.setSingleStep(120)
        self.width_label = QLabel()
        self.height_label = QLabel()
        resolution_layout.addWidget(self.width_label)
        resolution_layout.addWidget(self.width_input)
        resolution_layout.addWidget(self.height_label)
        resolution_layout.addWidget(self.height_input)
        resolution_layout.addStretch()
        layout.addLayout(resolution_layout)
        self.resolution_note = QLabel()
        self.resolution_note.setObjectName("hintLabel")
        layout.addWidget(self.resolution_note)
        layout.addStretch()

        camera = self.config.get("camera") or {}
        self.width_input.setValue(camera.get("width", 640))
        self.height_input.setValue(camera.get("height", 480))
        self.retranslate_ui()

    def retranslate_ui(self):
        """Refresh static copy while preserving the staged stable device selection."""
        self.title_label.setText(tr("camera.title"))
        self.description_label.setText(tr("camera.description"))
        self.refresh_button.setText(tr("camera.refresh"))
        self.resolution_title.setText(tr("camera.resolution"))
        self.width_label.setText(tr("camera.width"))
        self.height_label.setText(tr("camera.height"))
        self.resolution_note.setText(tr("camera.resolution_note"))
        self._refresh_selected_status()
        self._render_devices()

    def refresh_devices(self):
        try:
            devices = self.camera_service.list_devices() if self.camera_service else []
        except Exception:
            devices = []
        self.devices = list(devices)
        self._refresh_selected_status()
        self._render_devices()

    def _render_devices(self):
        """Rebuild labels from cached device metadata without probing hardware."""
        self._clear_devices()
        if not self.devices:
            unavailable = QLabel(tr("camera.none"))
            unavailable.setObjectName("hintLabel")
            self.devices_layout.addWidget(unavailable)
            return

        self.device_rows = {}
        for device in self.devices:
            row = QFrame()
            row.setObjectName("cameraDeviceRow")
            self.device_rows[device.device_id] = row
            row_layout = QHBoxLayout(row)
            select = QPushButton(device.display_name)
            select.setCheckable(True)
            select.setProperty("deviceId", device.device_id)
            select.setChecked(device.device_id == self.selected_device_id)
            select.clicked.connect(lambda checked, device_id=device.device_id: self.select_device(device_id))
            self.device_buttons.addButton(select)
            detail = tr("camera.available" if device.available else "camera.unavailable")
            kind = device.kind.replace("_", " ").title()
            status = QLabel(f"{kind} · {detail}")
            status.setObjectName("hintLabel")
            row_layout.addWidget(select, 1)
            row_layout.addWidget(status)
            self._mark_row_selected(row, device.device_id == self.selected_device_id)
            self.devices_layout.addWidget(row)

    @staticmethod
    def _mark_row_selected(row, selected):
        """Tint the whole row, so "which camera is in use" is one glance."""
        row.setProperty("selected", "on" if selected else "")
        row.style().unpolish(row)
        row.style().polish(row)

    def select_device(self, device_id):
        self.selected_device_id = device_id
        for button in self.device_buttons.buttons():
            button.setChecked(button.property("deviceId") == device_id)
        for row_device_id, row in getattr(self, "device_rows", {}).items():
            self._mark_row_selected(row, row_device_id == device_id)
        self._refresh_selected_status()

    def _refresh_selected_status(self):
        selected = next(
            (device for device in self.devices if device.device_id == self.selected_device_id),
            None,
        )
        if selected is None:
            self.selected_status.setText(
                tr("camera.selected_none")
                if not self.selected_device_id
                else tr("camera.selected_unavailable")
            )
            return
        availability = tr("camera.available" if selected.available else "camera.unavailable")
        self.selected_status.setText(
            tr("camera.selected", name=selected.display_name, availability=availability)
        )

    def apply_to_config(self):
        self.config.set("camera", "device_id", self.selected_device_id)
        self.config.set("camera", "width", self.width_input.value())
        self.config.set("camera", "height", self.height_input.value())

    def _clear_devices(self):
        self.device_buttons = QButtonGroup(self)
        while self.devices_layout.count():
            item = self.devices_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
