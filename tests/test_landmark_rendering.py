import os

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow


def test_landmark_rendering_does_not_depend_on_worker_owned_detector():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.detector = None
        frame = np.zeros((160, 160, 3), dtype=np.uint8)
        landmarks = [(20 + index * 3, 40 + index * 2, 0.0) for index in range(21)]

        rendered = window._draw_landmarks(frame, landmarks)

        assert rendered is frame
        assert rendered.any()
    finally:
        window.close()
