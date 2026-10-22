"""手势控制电脑 - 主入口"""

import sys
from PySide6.QtWidgets import QApplication
from gui import icons
from gui.main_window import MainWindow
from gui.native_chrome import apply_dark_titlebar
from gui.theme import apply_dark_palette
from utils.single_instance import SingleInstanceGuard


def main():
    guard = SingleInstanceGuard()
    if not guard.acquire():
        return 1

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # The palette is the floor under the stylesheet: anything Qt draws itself
    # (unstyled containers, spin-box sub-controls, message boxes) would
    # otherwise come out in Fusion's light palette inside a dark window.
    apply_dark_palette(app)
    # Dock, ⌘-Tab and the About panel read this; without it the app shows the
    # generic interpreter icon.
    app.setWindowIcon(icons.app_icon())
    try:
        window = MainWindow()
        window.show()
        # The title bar belongs to AppKit, not the stylesheet; match it to the
        # content instead of leaving a light strip above a dark console.
        apply_dark_titlebar(window)
        return app.exec()
    finally:
        guard.release()


if __name__ == "__main__":
    sys.exit(main())
