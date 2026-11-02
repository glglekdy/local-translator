"""색 토큰과 스타일시트. QuickMedia(DCCON 다운로더 / RCM 편집기)와 같은 결.

무채색 회색 단계 + 빨강 강조색, 테두리 없는 납작한 버튼.
OS 라이트/다크 설정을 따르고, 바꾸면 바로 따라간다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

LIGHT = {
    "bg": "#f5f5f5",
    "surface": "#ffffff",
    "border": "#e5e5e5",
    "text": "#1f1f1f",
    "heading": "#141414",
    "muted": "#737373",
    "btn_bg": "#ebebeb",
    "btn_hover": "#e0e0e0",
    "btn_pressed": "#d6d6d6",
    "disabled_fg": "#a3a3a3",
    "disabled_bg": "#f0f0f0",
    "primary_disabled_bg": "#fecaca",
    "primary_disabled_fg": "#ffffff",
    "input_bg": "#ebebeb",
    "input_focus_bg": "#ffffff",
    "popup_bg": "#ffffff",
    "card_bg": "#ffffff",
    "track": "#e5e5e5",
    "percent": "#b91c1c",
    "accent": "#dc2626",
    "danger": "#dc2626",
    "success": "#16a34a",
    "scroll_handle": "#d4d4d4",
    "nav_hover": "#f0f0f0",
}

# RCM tokens.css 값을 바탕으로 한다.
DARK = {
    "bg": "#141414",
    "surface": "#1c1c1c",
    "border": "#2e2e2e",
    "text": "#e6e6e6",
    "heading": "#f0f0f0",
    "muted": "#8c8c8c",
    "btn_bg": "#2c2c2c",
    "btn_hover": "#333333",
    "btn_pressed": "#3a3a3a",
    "disabled_fg": "#5c5c5c",
    "disabled_bg": "#1f1f1f",
    "primary_disabled_bg": "#5c2626",
    "primary_disabled_fg": "#8c8c8c",
    "input_bg": "#2c2c2c",
    "input_focus_bg": "#2c2c2c",
    "popup_bg": "#232323",
    "card_bg": "#232323",
    "track": "#2c2c2c",
    "percent": "#f87171",
    "accent": "#dc2626",
    "danger": "#ef4444",
    "success": "#22c55e",
    "scroll_handle": "#2c2c2c",
    "nav_hover": "#232323",
}

# 체크 표시·화살표 그림. exe 로 묶이면 _internal/lt/assets 에 들어간다.
ASSETS = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "lt" / "assets"

_TEMPLATE = """
QWidget {
    font-family: "Pretendard", "Malgun Gothic", "Segoe UI", sans-serif;
    font-size: 13px; color: $text;
}
QMainWindow, QDialog, #mainArea { background: $bg; }
QLabel { background: transparent; }
QToolTip { background: $popup_bg; color: $text; border: 1px solid $border; border-radius: 6px; padding: 6px 8px; }
#crumb { font-size: 22px; font-weight: 600; color: $heading; }
#viewHint, #hint { color: $muted; font-size: 12px; }
#sectionTitle { color: $muted; font-size: 12px; font-weight: 500; }
#segment { background: $input_bg; border-radius: 6px; }
QPushButton#segButton {
    background: transparent; color: $muted; border-radius: 4px; padding: 6px 14px; min-height: 14px;
}
QPushButton#segButton:hover { color: $text; }
QPushButton#segButton:checked { background: $btn_hover; color: $text; font-weight: 600; }
QPushButton {
    background: $btn_bg; border: none; border-radius: 6px;
    padding: 7px 12px; color: $text; font-weight: 500; min-height: 16px;
}
QPushButton:hover { background: $btn_hover; }
QPushButton:pressed { background: $btn_pressed; }
QPushButton:disabled { color: $disabled_fg; background: $disabled_bg; }
QPushButton#primary { background: $accent; color: white; font-weight: 600; padding: 7px 18px; }
QPushButton#primary:hover { background: #e54343; }
QPushButton#primary:pressed { background: #c41f1f; }
QPushButton#primary:disabled { background: $primary_disabled_bg; color: $primary_disabled_fg; }
QPushButton#toggle { padding: 7px 14px; }
QPushButton#toggle:checked { background: $btn_pressed; color: $heading; font-weight: 600; border: 1px solid $accent; }
QPushButton#ghost { background: transparent; color: $muted; padding: 4px 8px; }
QPushButton#ghost:hover { background: $btn_hover; color: $text; }
QLineEdit {
    background: $input_bg; border: 1px solid transparent; border-radius: 6px;
    padding: 8px 10px; color: $text; font-weight: 500;
    selection-background-color: $accent; selection-color: white;
}
QLineEdit:focus { border-color: $accent; background: $input_focus_bg; }
QPlainTextEdit {
    background: $input_bg; border: 1px solid transparent; border-radius: 6px;
    padding: 6px 8px; color: $text; selection-background-color: $accent; selection-color: white;
}
QPlainTextEdit:focus { border-color: $accent; background: $input_focus_bg; }
QLineEdit[readOnly="true"] { color: $muted; }
QComboBox, QSpinBox, QDoubleSpinBox {
    background: $input_bg; border: 1px solid transparent; border-radius: 6px;
    padding: 6px 10px; color: $text; font-weight: 500; min-height: 16px;
}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: $accent; }
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QLineEdit:disabled { color: $disabled_fg; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: url($assets/arrow-down.svg); width: 10px; height: 10px; }
QSpinBox, QDoubleSpinBox { padding-right: 22px; }
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border; width: 20px; border: none; background: transparent;
}
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-position: top right; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-position: bottom right; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover { background: $btn_hover; border-radius: 4px; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url($assets/arrow-up.svg); width: 9px; height: 9px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url($assets/arrow-down.svg); width: 9px; height: 9px; }
QComboBox QAbstractItemView {
    background: $popup_bg; border: 1px solid $border; selection-background-color: $btn_hover;
    selection-color: $text; outline: none;
}
QCheckBox, QRadioButton { spacing: 6px; background: transparent; }
QCheckBox::indicator, QRadioButton::indicator {
    width: 14px; height: 14px; border: 1px solid $disabled_fg; background: $input_focus_bg;
}
QCheckBox::indicator { border-radius: 4px; }
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; image: url($assets/check.svg); }
QRadioButton::indicator:checked { background: $input_focus_bg; border: 5px solid $accent; width: 6px; height: 6px; }
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled { border-color: $border; background: $disabled_bg; }
QCheckBox:disabled, QRadioButton:disabled { color: $disabled_fg; }
QTabWidget::pane { background: $card_bg; border: 1px solid $border; border-radius: 8px; top: -1px; }
QTabBar::tab {
    background: transparent; color: $muted; padding: 6px 12px; border: none;
    border-bottom: 2px solid transparent; font-weight: 500;
}
QTabBar::tab:hover { color: $text; }
QTabBar::tab:selected { color: $text; border-bottom: 2px solid $accent; }
#optionsPanel { background: transparent; }
#fieldError { color: $danger; font-size: 12px; }
QLineEdit[invalid="true"] { border-color: $danger; }
#savedBadge { color: $success; font-size: 12px; }
#updateTitle { font-size: 15px; font-weight: 600; color: $heading; }
QTextBrowser#updateNotes { background: transparent; border: none; border-top: 1px solid $border; padding-top: 8px; }
#settingsCard { background: $card_bg; border: 1px solid $border; border-radius: 10px; }
#cardSite { color: $muted; font-size: 11px; }
QScrollArea, #queueHolder, #settingsHolder { background: $bg; border: none; }
#card { background: $card_bg; border: 1px solid $border; border-radius: 10px; }
#cardTitle { font-weight: 500; }
#cardStatus { color: $muted; font-size: 12px; }
#cardStatus[state="error"] { color: $danger; }
#cardStatus[state="done"] { color: $success; }
#percent { color: $percent; font-size: 12px; font-weight: 600; }
#dock { background: $surface; border-top: 1px solid $border; }
#sidebar { background: $surface; border-right: 1px solid $border; }
#navVersion { color: $muted; font-size: 11px; }
#emptyState { color: $muted; font-size: 14px; padding: 32px; }
QProgressBar { border: none; border-radius: 3px; background: $track; max-height: 6px; }
QProgressBar::chunk { background: $accent; border-radius: 3px; }
#utterance { background: $card_bg; border: 1px solid $border; border-radius: 10px; }
#utterance[latest="true"] { border-color: $btn_pressed; }
#uttMeta { color: $muted; font-size: 11px; font-weight: 600; }
#uttSource { color: $muted; font-size: 13px; }
#uttTranslation { color: $heading; font-size: 17px; font-weight: 600; }
#uttTranslation[state="pending"] { color: $muted; font-size: 14px; font-weight: 500; }
#uttTranslation[state="error"] { color: $danger; font-size: 13px; font-weight: 500; }
#statusText { color: $muted; font-size: 12px; }
#statusText[state="error"] { color: $danger; }
#statusText[state="listening"] { color: $text; }
#arrowLabel { color: $muted; font-size: 15px; }
#engineName { color: $text; font-weight: 600; }
#testResult { color: $muted; font-size: 12px; }
#testResult[state="ok"] { color: $success; }
#testResult[state="error"] { color: $danger; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px 1px; }
QScrollBar::handle:vertical { background: $scroll_handle; border-radius: 3px; min-height: 40px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
"""

_active = LIGHT


def color(name: str) -> str:
    return _active[name]


def _palette(t: dict[str, str]) -> QPalette:
    """스타일시트가 안 닿는 곳(메시지 상자, 폴더 선택 창 등)을 위한 팔레트."""
    pal = QPalette()
    for role, key in {
        QPalette.ColorRole.Window: "bg",
        QPalette.ColorRole.WindowText: "text",
        QPalette.ColorRole.Base: "input_bg",
        QPalette.ColorRole.Text: "text",
        QPalette.ColorRole.Button: "btn_bg",
        QPalette.ColorRole.ButtonText: "text",
        QPalette.ColorRole.Highlight: "accent",
        QPalette.ColorRole.PlaceholderText: "muted",
    }.items():
        pal.setColor(role, QColor(t[key]))
    return pal


def stylesheet(tokens: dict[str, str]) -> str:
    values = {**tokens, "assets": ASSETS.as_posix()}
    return re.sub(r"\$(\w+)", lambda m: values[m.group(1)], _TEMPLATE)


def _restyle(app: QApplication) -> None:
    global _active
    _active = DARK if app.styleHints().colorScheme() == Qt.ColorScheme.Dark else LIGHT
    app.setPalette(_palette(_active))
    app.setStyleSheet(stylesheet(_active))


def apply(app: QApplication) -> None:
    app.styleHints().colorSchemeChanged.connect(lambda *_: _restyle(app))
    _restyle(app)
