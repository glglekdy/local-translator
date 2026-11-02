"""메인 창 왼쪽 메뉴. 번역 / 설정(누르면 아래로 펼쳐지는 음성 인식·번역 엔진·배경 정보·자막·업데이트) / 다운로드. QuickMedia 메뉴와 같은 모양.

밖으로는 `page_changed(key)` 하나만 내보낸다. 화면을 실제로 바꾸는 건 메인 창이 한다.
펼침·선택 상태는 누르는 즉시 바뀌고, 애니메이션은 보이는 것만 맡는다.
"""

from __future__ import annotations

from PySide6.QtCore import (
    Property, QEasingCurve, QParallelAnimationGroup, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QLabel, QVBoxLayout, QWidget

from . import __version__, theme
from .theme import ASSETS

SETTINGS_KEYS = ("speech", "engine", "context", "subtitle", "update")

_ITEM_H = 34
_TEXT_X = 38  # 아이콘 16px 뒤. 하위 항목도 이 위치에 글자를 맞춘다
_ANIM_MS = 200


class NavItem(QAbstractButton):
    """직접 그리는 메뉴 항목. 선택 표시는 Sidebar 가 정하므로 눌러도 저절로 바뀌지 않는다."""

    def __init__(self, text: str, icon: str | None = None, chevron: bool = False, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.key = ""  # Sidebar 가 정한다
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(_ITEM_H)
        self._icon = QIcon(str(ASSETS / icon)) if icon else None
        self._chevron = chevron
        self._angle = 0.0
        self.dot = False  # 새 버전 알림 빨간 점

    def nextCheckState(self) -> None:
        pass

    def _get_angle(self) -> float:
        return self._angle

    def _set_angle(self, v: float) -> None:
        self._angle = v
        self.update()

    angle = Property(float, _get_angle, _set_angle)

    def sizeHint(self) -> QSize:
        return QSize(152, _ITEM_H)

    def enterEvent(self, e) -> None:
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(Qt.PenStyle.NoPen)
        if self.isChecked() or self.underMouse():
            p.setBrush(QColor(theme.color("btn_bg" if self.isChecked() else "nav_hover")))
            p.drawRoundedRect(QRectF(0, 0, w, h), 6, 6)
        if self.isChecked():
            p.setBrush(QColor(theme.color("accent")))
            p.drawRoundedRect(QRectF(0, 9, 3, h - 18), 1.5, 1.5)
        if self._icon:
            self._icon.paint(p, QRect(12, (h - 16) // 2, 16, 16))
        font = QFont(self.font())
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold if self.isChecked() else QFont.Weight.Medium)
        p.setFont(font)
        p.setPen(QColor(theme.color("text")))
        p.drawText(QRect(_TEXT_X, 0, w - _TEXT_X - 24, h), Qt.AlignmentFlag.AlignVCenter, self.text())
        if self.dot:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.color("accent")))
            p.drawEllipse(QPointF(w - 16, h / 2), 3.5, 3.5)
        if self._chevron:
            pen = QPen(QColor(theme.color("muted")), 1.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.translate(w - 18, h / 2)
            p.rotate(self._angle)
            p.drawPolyline([QPointF(-2, -4), QPointF(2, 0), QPointF(-2, 4)])


class Sidebar(QWidget):
    page_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedWidth(168)
        self.current = "translate"
        self.expanded = False

        self.nav: dict[str, NavItem] = {
            "translate": NavItem("번역", "translate.svg"),
            "settings": NavItem("설정", "gear.svg", chevron=True),
        }
        self._children = QWidget()
        child_box = QVBoxLayout(self._children)
        child_box.setContentsMargins(0, 2, 0, 0)
        child_box.setSpacing(2)
        for key, text in zip(SETTINGS_KEYS, ("음성 인식", "번역 엔진", "배경 정보", "자막", "업데이트")):
            self.nav[key] = NavItem(text)
            child_box.addWidget(self.nav[key])
        self._children_h = child_box.sizeHint().height()
        self.nav["download"] = NavItem("다운로드", "download.svg")   # 설정 묶음 바로 아래
        self._children.setMaximumHeight(0)

        box = QVBoxLayout(self)
        box.setContentsMargins(8, 12, 8, 12)
        box.setSpacing(2)
        box.addWidget(self.nav["translate"])
        box.addWidget(self.nav["settings"])
        box.addWidget(self._children)
        box.addWidget(self.nav["download"])
        box.addStretch(1)
        self.version_label = QLabel(f"버전 {__version__}")
        self.version_label.setObjectName("navVersion")
        self.version_label.setContentsMargins(12, 0, 0, 0)
        box.addWidget(self.version_label)

        for key, item in self.nav.items():
            # lambda 로 self 를 붙잡으면 메뉴가 지워지지 않고 앱이 끝날 때 죽으므로 bound method 로 잇는다
            item.key = key
            item.clicked.connect(self._on_item_clicked)

        self.anim = QParallelAnimationGroup(self)
        self._height_anim = QPropertyAnimation(self._children, b"maximumHeight", self)
        self._angle_anim = QPropertyAnimation(self.nav["settings"], b"angle", self)
        for a in (self._height_anim, self._angle_anim):
            a.setDuration(_ANIM_MS)
            a.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.anim.addAnimation(a)
        self._refresh()

    def select(self, key: str) -> None:
        """그 화면으로 간다. 설정 화면이면 묶음을 펼치고, 아니면 접는다."""
        self._set_expanded(key in SETTINGS_KEYS)
        changed = key != self.current
        self.current = key
        self._refresh()
        if changed:
            self.page_changed.emit(key)

    def set_dot(self, key: str, on: bool) -> None:
        self.nav[key].dot = on
        self.nav[key].update()

    def _on_item_clicked(self) -> None:
        key = self.sender().key
        if key != "settings":
            self.select(key)
        elif self.expanded:
            self._set_expanded(False)
            self._refresh()
        elif self.current in SETTINGS_KEYS:
            # 접어 둔 채 보던 설정 화면은 그대로 둔다
            self._set_expanded(True)
            self._refresh()
        else:
            self.select("speech")

    def _set_expanded(self, on: bool) -> None:
        if on == self.expanded:
            return
        self.expanded = on
        self.anim.stop()
        self._height_anim.setStartValue(self._children.maximumHeight())
        self._height_anim.setEndValue(self._children_h if on else 0)
        self._angle_anim.setStartValue(self.nav["settings"].angle)
        self._angle_anim.setEndValue(90.0 if on else 0.0)
        self.anim.start()

    def _refresh(self) -> None:
        for key, item in self.nav.items():
            if key == "settings":
                item.setChecked(self.current in SETTINGS_KEYS and not self.expanded)
            else:
                item.setChecked(key == self.current)
