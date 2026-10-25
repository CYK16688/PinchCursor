"""Precision Desk dark desktop utility theme.

Design tokens (Qt has no CSS variables, so these literals repeat throughout the
stylesheet — keep this table authoritative and never introduce a colour that is
not listed here):

    canvas      #0B0C0F   window background
    surface     #121419   primary cards, list bodies
    elevated    #1A1D24   rows, popups, hover fills
    viewport    #090A0D   camera well, input fields
    hairline    rgba(255,255,255,0.08)   dividers and quiet borders
    text        #F5F7FA   headings and primary values
    quiet       #C6CBD5   secondary copy, checkbox labels
    subtle      #8B93A1   labels, hints, inactive state
    muted       #5C636F   placeholder copy, disabled text

    accent      #5E8CFF   primary action, selection, armed state
    ready       #47D7A1   running / granted / healthy
    warning     #F5B942   attention, waiting, not determined
    danger      #FF6B6B   denied, error, stop

    radius-sm   12px   controls, rows
    radius-md   16px   inner wells
    radius-lg   20px   cards, sheets

Typography scale: 24/600 title · 20/600 page title · 18/600 session state ·
15/500 value · 13/400 body · 12/400 hint · 11/600 eyebrow.

Qt has no variables, and no transform/transition/box-shadow. Anything rotated or
animated belongs in paintEvent, never here.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

from core.resource_paths import resource_root


def _icon(name: str) -> str:
    """Absolute path to a shipped icon, valid in source and frozen builds."""
    return (resource_root() / "assets" / "icons" / name).as_posix()


# QApplication keeps a reference to the palette it was given, but the Python
# wrapper that built it is collectable. Holding one module-level reference costs
# nothing and keeps the QPalette data alive for the process lifetime, which is
# what a crash inside QPalette::detach during a later style polish points at.
_APP_PALETTE = None


def apply_dark_palette(app) -> None:
    """Give Fusion a dark palette before any widget exists.

    The stylesheet paints the surfaces it names, but Qt still asks the palette
    for everything it draws itself: unstyled containers, spin-box sub-controls,
    message boxes, tooltips, and any rule that resolves to ``transparent``.
    With Fusion's default light palette those areas render as near-white plates
    inside a dark window — which is what an apparently "unstyled" region is.
    """
    palette = QPalette()
    canvas = QColor("#0B0C0F")
    surface = QColor("#121419")
    elevated = QColor("#1A1D24")
    text = QColor("#F5F7FA")
    muted = QColor("#5C636F")
    accent = QColor("#5E8CFF")

    palette.setColor(QPalette.Window, canvas)
    palette.setColor(QPalette.WindowText, text)
    palette.setColor(QPalette.Base, surface)
    palette.setColor(QPalette.AlternateBase, elevated)
    palette.setColor(QPalette.Text, text)
    palette.setColor(QPalette.Button, elevated)
    palette.setColor(QPalette.ButtonText, text)
    palette.setColor(QPalette.BrightText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ToolTipBase, elevated)
    palette.setColor(QPalette.ToolTipText, text)
    palette.setColor(QPalette.PlaceholderText, muted)
    palette.setColor(QPalette.Highlight, accent)
    palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.Link, accent)
    palette.setColor(QPalette.LinkVisited, QColor("#AFC5FF"))

    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, muted)
    palette.setColor(QPalette.Disabled, QPalette.Base, surface)
    palette.setColor(QPalette.Disabled, QPalette.Button, QColor("#15171C"))
    palette.setColor(QPalette.Disabled, QPalette.Highlight, QColor("#2B303C"))

    global _APP_PALETTE
    _APP_PALETTE = palette
    app.setPalette(palette)


def use_styled_background(window) -> None:
    """Let a top-level window paint its own stylesheet background.

    A QMainWindow/QDialog subclass does not paint the stylesheet's ``background``
    declaration unless this attribute is set, so the window keeps the palette
    behind its children and the canvas rule silently does nothing.
    """
    window.setAttribute(Qt.WA_StyledBackground, True)


DARK_THEME = """
/* ── root ────────────────────────────────────────────────────────────────
   The window paints the canvas; unnamed children stay transparent so the
   surface reads as one continuous canvas instead of stacked plates. */
QMainWindow, QDialog {
    background-color: #0B0C0F;
}
QWidget {
    color: #F5F7FA;
    /* No background declaration here. A `background: transparent` base rule
       has the same specificity as the window rule above but is declared later,
       so it wins on the window itself and the canvas stops painting — the
       native light backing then shows through every gap between cards.
       Plain QWidgets do not paint a background by default anyway. */
    font-family: "SF Pro Display", "PingFang SC", "Segoe UI", "Microsoft YaHei";
    font-size: 13px;
}

/* ── typography ──────────────────────────────────────────────────────────── */
QLabel#appTitle {
    color: #F5F7FA;
    font-size: 24px;
    font-weight: 600;
    letter-spacing: -0.3px;
}
QLabel#settingsPageTitle {
    color: #F5F7FA;
    font-size: 20px;
    font-weight: 600;
    letter-spacing: -0.2px;
}
QLabel#eyebrow, QLabel#summaryLabel {
    color: #8B93A1;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.6px;
}
QLabel#summaryValue {
    color: #F5F7FA;
    font-size: 15px;
    font-weight: 500;
}
/* A section inside a page: one step below the page title, one above a label. */
QLabel#sectionTitle {
    color: #F5F7FA;
    font-size: 16px;
    font-weight: 600;
}
QLabel#hintLabel, QLabel#comboLabel {
    color: #8B93A1;
}
QLabel#comboPlus, QLabel#comboArrow {
    color: #5E8CFF;
    font-weight: 600;
}
QLabel#gestureName {
    color: #F5F7FA;
    font-size: 15px;
    font-weight: 600;
}
QLabel#hudLabel {
    color: #F5F7FA;
    background: transparent;
}

/* ── session state: the heartbeat of the whole app ────────────────────────
   The base rule is neutral, so an unmapped state degrades to quiet rather
   than to a wrong semantic colour. Every value the models emit has a rule. */
QLabel#sessionState {
    color: #8B93A1;
    font-size: 18px;
    font-weight: 600;
}
QLabel#sessionState[semantic="active"],
QLabel#sessionState[semantic="ready"] {
    color: #47D7A1;
}
QLabel#sessionState[semantic="armed"] {
    color: #5E8CFF;
}
QLabel#sessionState[semantic="waiting"] {
    color: #F5B942;
}
QLabel#sessionState[semantic="idle"] {
    color: #8B93A1;
}
QLabel#sessionState[semantic="danger"] {
    color: #FF6B6B;
}
QLabel#lastActionValue {
    color: #5C636F;
    font-size: 13px;
}
QLabel#lastActionValue[semantic="recent"] {
    color: #F5F7FA;
}

/* ── header chip: reports state, never the primary action's words ────────── */
QLabel#statusChip {
    color: #8B93A1;
    background: rgba(139, 147, 161, 0.12);
    border: 1px solid rgba(139, 147, 161, 0.22);
    border-radius: 12px;
    padding: 5px 10px;
    font-size: 12px;
}
QLabel#statusChip[semantic="running"] {
    color: #47D7A1;
    background: rgba(71, 215, 161, 0.12);
    border: 1px solid rgba(71, 215, 161, 0.26);
}
QLabel#statusChip[semantic="waiting"] {
    color: #F5B942;
    background: rgba(245, 185, 66, 0.12);
    border: 1px solid rgba(245, 185, 66, 0.26);
}
QLabel#statusChip[semantic="danger"] {
    color: #FF6B6B;
    background: rgba(255, 107, 107, 0.12);
    border: 1px solid rgba(255, 107, 107, 0.26);
}

/* ── status dots: a binary fact, scannable inside a list ─────────────────── */
QLabel#statusDot {
    min-width: 8px;
    max-width: 8px;
    min-height: 8px;
    max-height: 8px;
    border-radius: 4px;
    background: #5C636F;
}
QLabel#statusDot[semantic="granted"],
QLabel#statusDot[semantic="active"],
QLabel#statusDot[semantic="ready"] {
    background: #47D7A1;
}
QLabel#statusDot[semantic="pending"],
QLabel#statusDot[semantic="waiting"] {
    background: #F5B942;
}
QLabel#statusDot[semantic="denied"],
QLabel#statusDot[semantic="danger"] {
    background: #FF6B6B;
}
QLabel#permissionName {
    color: #C6CBD5;
    font-size: 13px;
}
QLabel#permissionValue {
    color: #F5F7FA;
    font-size: 13px;
    font-weight: 500;
}
QLabel#permissionValue[semantic="denied"] {
    color: #FF6B6B;
}
QLabel#permissionValue[semantic="pending"] {
    color: #F5B942;
}

/* ── surfaces ─────────────────────────────────────────────────────────────── */
QFrame#previewFrame, QFrame#sessionCard {
    background: #121419;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 20px;
}
QLabel#videoViewport, QLabel#recordingPreview {
    background: #090A0D;
    color: #8B93A1;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 16px;
}
QWidget#previewPlaceholder {
    background: transparent;
    border: none;
}
QLabel#previewStatus {
    color: #8B93A1;
    font-size: 12px;
}
QLabel#placeholderTitle {
    color: #8B93A1;
    font-size: 14px;
    font-weight: 500;
}
QFrame#hairline {
    background: rgba(255, 255, 255, 0.08);
    border: none;
    max-height: 1px;
    min-height: 1px;
}
QFrame#cameraDeviceRow, QFrame#gestureSettingsRow, QFrame#comboCard {
    background: #1A1D24;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
}
QFrame#cameraDeviceRow QPushButton {
    text-align: left;
    background: transparent;
    border: none;
    padding: 8px 10px;
}
QFrame#cameraDeviceRow[selected="on"] {
    background: rgba(94, 140, 255, 0.16);
    border-color: rgba(94, 140, 255, 0.34);
}
QFrame#cameraDeviceRow QPushButton:checked {
    color: #F5F7FA;
}

/* ── buttons: three ranks only ────────────────────────────────────────────── */
QPushButton {
    background: #1A1D24;
    color: #F5F7FA;
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 10px;
    padding: 6px 12px;
    min-height: 20px;
}
QPushButton:hover {
    background: #222632;
    border-color: rgba(255, 255, 255, 0.18);
}
QPushButton:pressed {
    background: #15171C;
}
QPushButton:focus {
    border-color: #5E8CFF;
}
QPushButton:disabled {
    background: rgba(255, 255, 255, 0.04);
    color: #5C636F;
    border-color: rgba(255, 255, 255, 0.06);
}
QPushButton#quietButton {
    background: transparent;
    color: #C6CBD5;
    border: 1px solid rgba(255, 255, 255, 0.10);
    padding: 5px 10px;
}
QPushButton#quietButton:hover {
    background: #1A1D24;
    color: #F5F7FA;
    border-color: rgba(255, 255, 255, 0.18);
}
/* A summary row is the control that changes it: hover is the affordance, and
   the trailing chevron says "opens somewhere". No "Change" word needed. */
QFrame#summaryRow {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 12px;
}
QFrame#summaryRow:hover {
    background: rgba(255, 255, 255, 0.045);
    border-color: rgba(255, 255, 255, 0.07);
}
QFrame#lastActionBlock {
    background: transparent;
    border: none;
}
QPushButton#primaryControlButton {
    background: #5E8CFF;
    border: none;
    color: #FFFFFF;
    font-size: 14px;
    font-weight: 600;
    padding: 14px 18px;
}
QPushButton#primaryControlButton:hover {
    background: #729BFF;
}
QPushButton#primaryControlButton:pressed {
    background: #4C79E8;
}
QPushButton#primaryControlButton:focus {
    border: 2px solid rgba(255, 255, 255, 0.85);
}
QPushButton#primaryControlButton[semantic="warning"] {
    background: #F5B942;
    color: #17120A;
}
QPushButton#primaryControlButton[semantic="danger"] {
    background: #FF6B6B;
    color: #280C0C;
}
QPushButton#saveBtn {
    background: #5E8CFF;
    border: none;
    color: #FFFFFF;
}
QPushButton#saveBtn:hover {
    background: #729BFF;
}
QPushButton#addComboBtn {
    background: rgba(94, 140, 255, 0.14);
    color: #AFC5FF;
    border: 1px solid rgba(94, 140, 255, 0.30);
    padding: 8px 18px;
}
QPushButton#addComboBtn:hover {
    background: rgba(94, 140, 255, 0.22);
    color: #F5F7FA;
}
QPushButton#deleteBtn {
    background: transparent;
    color: #8B93A1;
    border: 1px solid rgba(255, 255, 255, 0.10);
    padding: 4px 10px;
    min-width: 0;
}
QPushButton#deleteBtn:hover {
    background: rgba(255, 107, 107, 0.16);
    color: #FF6B6B;
    border-color: rgba(255, 107, 107, 0.34);
}

/* ── text inputs ──────────────────────────────────────────────────────────── */
QComboBox, QSpinBox, QLineEdit {
    background: #090A0D;
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 10px;
    /* Padding is part of the content rect, so the height has to reserve it;
       without the min-height Qt handed back an un-padded 25 px and sliced
       descenders off every combo and spin box. */
    padding: 5px 10px;
    min-height: 20px;
    color: #F5F7FA;
    selection-background-color: #2B447A;
    selection-color: #FFFFFF;
}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover {
    border-color: rgba(255, 255, 255, 0.18);
}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {
    border-color: #5E8CFF;
}
QComboBox:disabled, QSpinBox:disabled, QLineEdit:disabled {
    color: #5C636F;
    background: #15171C;
    border-color: rgba(255, 255, 255, 0.06);
}
QComboBox::drop-down {
    width: 30px;
    border: none;
    border-left: 1px solid rgba(255, 255, 255, 0.10);
}
QComboBox::down-arrow {
    image: url(__CHEVRON__);
    width: 14px;
    height: 14px;
    margin-right: 10px;
}
QComboBox QAbstractItemView {
    background: #1A1D24;
    color: #F5F7FA;
    border: 1px solid #343946;
    outline: none;
    selection-background-color: #2B447A;
    selection-color: #FFFFFF;
    padding: 4px;
}
QComboBox QAbstractItemView::item {
    min-height: 30px;
    padding: 4px 10px;
    color: #F5F7FA;
    background: #1A1D24;
}
QComboBox QAbstractItemView::item:hover,
QComboBox QAbstractItemView::item:selected {
    background: #2B447A;
    color: #FFFFFF;
}
QSpinBox {
    padding-right: 22px;
}
QSpinBox::up-button, QSpinBox::down-button {
    subcontrol-origin: border;
    width: 18px;
    background: transparent;
    border: none;
    border-left: 1px solid rgba(255, 255, 255, 0.08);
}
QSpinBox::up-button {
    subcontrol-position: top right;
    border-top-right-radius: 10px;
}
QSpinBox::down-button {
    subcontrol-position: bottom right;
    border-bottom-right-radius: 10px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background: #1A1D24;
}
QSpinBox::up-arrow {
    image: url(__CHEVRON_UP__);
    width: 12px;
    height: 12px;
}
QSpinBox::down-arrow {
    image: url(__CHEVRON__);
    width: 12px;
    height: 12px;
}
QComboBox#actionCombo {
    min-width: 120px;
}
QLineEdit#hotkeyInput {
    background: #090A0D;
    color: #F5F7FA;
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 10px;
    padding: 7px 10px;
}
QLineEdit#hotkeyInput:focus {
    border-color: #5E8CFF;
}

/* ── checkbox: the enable toggle used by gestures and recording ──────────── */
QCheckBox {
    color: #C6CBD5;
    spacing: 6px;
}
QCheckBox:hover {
    color: #F5F7FA;
}
QCheckBox:disabled {
    color: #5C636F;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 5px;
    border: 1px solid rgba(255, 255, 255, 0.16);
    background: #090A0D;
}
QCheckBox::indicator:hover {
    border-color: rgba(94, 140, 255, 0.60);
}
QCheckBox::indicator:checked {
    background: #5E8CFF;
    border-color: #5E8CFF;
    image: url(__CHECK__);
}
QCheckBox::indicator:disabled {
    background: rgba(255, 255, 255, 0.04);
    border-color: rgba(255, 255, 255, 0.08);
}

/* ── slider: sensitivity and thresholds ──────────────────────────────────── */
QSlider::groove:horizontal {
    height: 4px;
    background: #282C35;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #5E8CFF;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #F5F7FA;
    width: 16px;
    margin: -6px 0;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover {
    background: #FFFFFF;
}
QSlider::handle:horizontal:pressed {
    background: #AFC5FF;
}
QSlider::handle:horizontal:disabled {
    background: #3A3F4A;
}

/* ── group box: a settings section header that costs no extra row ────────── */
QGroupBox {
    background: transparent;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 14px;
    margin-top: 20px;
    padding: 16px 14px 12px 14px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 6px;
    color: #8B93A1;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.6px;
    background: transparent;
}

/* ── lists: generic first, the settings sidebar overrides it ─────────────── */
QListWidget#settingsSidebar {
    background: #121419;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 14px;
    padding: 6px;
    outline: none;
}
QListWidget#settingsSidebar::item {
    color: #8B93A1;
    border-radius: 9px;
    min-height: 34px;
    padding: 4px 10px;
}
QListWidget#settingsSidebar::item:hover {
    background: #1A1D24;
    color: #F5F7FA;
}
QListWidget#settingsSidebar::item:selected {
    background: rgba(94, 140, 255, 0.18);
    color: #F5F7FA;
}

/* ── scrollbars: overlay-thin, never a light plate ───────────────────────── */
QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 0.22);
    border-radius: 3px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(255, 255, 255, 0.24);
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: rgba(255, 255, 255, 0.22);
    border-radius: 3px;
    min-width: 28px;
}
QScrollBar::handle:horizontal:hover {
    background: rgba(255, 255, 255, 0.24);
}
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0;
    height: 0;
    border: none;
    background: none;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}

/* ── tabs: pane and tab styled apart, or the selected state disappears ───── */
QTabWidget::pane {
    background: #121419;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
}
QTabBar::tab {
    background: transparent;
    color: #8B93A1;
    padding: 7px 14px;
    margin-right: 4px;
    border: 1px solid transparent;
    border-radius: 8px;
    font-size: 12px;
    font-weight: 500;
}
QTabBar::tab:hover {
    color: #F5F7FA;
    background: rgba(255, 255, 255, 0.05);
}
QTabBar::tab:selected {
    color: #F5F7FA;
    background: rgba(94, 140, 255, 0.16);
    border: 1px solid rgba(94, 140, 255, 0.34);
}

/* ── tooltip ──────────────────────────────────────────────────────────────── */
QToolTip {
    background: #1A1D24;
    color: #F5F7FA;
    border: 1px solid rgba(255, 255, 255, 0.12);
    padding: 6px 8px;
}

/* ── empty states ─────────────────────────────────────────────────────────── */
QLabel#comboEmpty {
    color: #5C636F;
    font-size: 13px;
}
"""

# `url()` cannot be interpolated inside the stylesheet literal itself because the
# paths are resolved at import time (source tree vs PyInstaller extraction root).
DARK_THEME = (
    DARK_THEME.replace("__CHEVRON__", _icon("chevron-down.svg"))
    .replace("__CHEVRON_UP__", _icon("chevron-up.svg"))
    .replace("__CHECK__", _icon("check.svg"))
)
