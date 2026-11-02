"""자막 모드: 하프라이프 캡션처럼 화면 아래에 쌓이는 자막 창.

- 새 말은 맨 아래에 붙고, 앞의 말들은 위로 밀려 올라간다 (최대 개수는 설정 'subtitle_max_lines')
- 말마다 몇 초 뒤 스르륵 흐려지고, 빈자리가 부드럽게 접히면서 배경 상자도 따라 줄어든다
- 번역이 오기 전엔 원문만 먼저 보여 주고, 번역이 오면 그 줄이 제자리에서 바뀐다 (늦게 와도)
- 테두리 없음, 항상 맨 위, 포커스를 빼앗지 않음. 그려진 곳만 마우스를 받고 빈 곳은 클릭이 뒤로 통과
- 끌어서 옮기면 위치를 기억한다 ('가운데 x, 아래 y'). 오른쪽 클릭: 원문 보기 · 글자 크기 · 위치 초기화 · 닫기
- 마우스를 올려 두면 사라지지 않고 기다린다

그리기는 QPainter 로 직접 한다. 창은 최대 크기로 고정하고 상자만 창 안에서 움직인다
(투명 창을 매 프레임 옮기거나 크기를 바꾸면 Windows 에서 깜빡인다).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import QMenu, QWidget

MAX_WIDTH = 1200
MIN_WIDTH = 320
BOTTOM_MARGIN = 72     # 화면(작업 표시줄 위) 아래에서 띄우는 거리
MAX_LINES = 4          # 설정에 없을 때 한 번에 쌓이는 말 수. 넘치면 가장 오래된 말부터 사라진다
MAX_TRANSLATION_CHARS = 140   # 자막이 화면을 덮지 않게. 넘으면 앞을 줄이고 끝부분을 보여 준다
MAX_SOURCE_CHARS = 160
PAD_X, PAD_Y = 28, 14
LINE_GAP = 10          # 말과 말 사이
BLOCK_GAP = 4          # 원문과 번역 사이
RADIUS = 12
APPEAR_SEC = 0.25      # 새 말이 또렷해지는 시간
FADE_SEC = 0.6         # 말이 흐려지는 시간. 다 흐려진 뒤에 자리가 접힌다
PENDING_MAX_SEC = 60   # 번역을 기다리는 말이 남아 있는 최대 시간
EASE_SEC = 0.08        # 높이·폭이 목표로 다가가는 빠르기 (작을수록 빠름)
FRAME_MS = 16
TEXT_FLAGS = Qt.AlignmentFlag.AlignHCenter.value | Qt.AlignmentFlag.AlignTop.value | Qt.TextFlag.TextWordWrap.value
SHADOW = ((0, 2, 150), (1, 1, 110), (-1, 1, 110))   # 글자 그림자 (dx, dy, 진하기)


def clip(text: str, limit: int) -> str:
    """자막에는 끝부분만. 단어 중간에서 자르지 않게 첫 공백까지 더 버린다."""
    if len(text) <= limit:
        return text
    tail = text[-limit:]
    cut = tail.find(" ")
    if 0 <= cut < 20:
        tail = tail[cut + 1:]
    return "… " + tail


def _approach(cur: float, target: float, k: float, eps: float = 0.5) -> float:
    nxt = cur + (target - cur) * k
    return target if abs(target - nxt) < eps else nxt


@dataclass
class Line:
    """자막 상자 안의 말 하나 (원문 + 번역)."""
    uid: int
    source: str
    text: str = ""
    kind: str = "pending"            # pending · ok · error · status
    expire_at: float | None = None   # 이 시각에 흐려지기 시작. None = 계속
    dying: bool = False
    alpha: float = 0.0               # 글자 진하기 0..1
    h: float = 0.0                   # 지금 차지하는 높이 (위쪽 줄 간격 포함)
    full_h: float = 0.0              # 다 펼쳐졌을 때 글 높이
    natural_w: float = 0.0           # 가장 긴 줄의 폭
    blocks: list = field(default_factory=list)   # (글, 글꼴, 색, 높이)

    @property
    def gone(self) -> bool:
        return self.dying and self.alpha <= 0.0

    @property
    def target_h(self) -> float:
        return 0.0 if self.gone else self.full_h + LINE_GAP


class SubtitleWindow(QWidget):
    closed = Signal()
    changed = Signal(dict)      # 사용자가 창에서 바꾼 설정 (위치, 글자 크기, 원문 보기)

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("자막")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.cfg = dict(cfg)
        self.uid = 0                    # 지금까지 들어온 가장 새 말 번호
        self.lines: list[Line] = []     # 위(오래된 말) → 아래(새 말)
        self._clock = time.monotonic
        self._last: float | None = None
        self._box_w = 0.0
        self._presence = 0.0            # 상자 자체가 보이는 정도 0..1 (안쪽 여백·배경)
        self._max_w = MAX_WIDTH
        self._hover = False
        self._drag: QPoint | None = None
        self._anchor: tuple[int, int] | None = None

        self._frame = QTimer(self)      # 움직이는 동안만 도는 프레임 타이머
        self._frame.setInterval(FRAME_MS)
        self._frame.timeout.connect(self._tick)
        self._expiry = QTimer(self)     # 멈춰 있을 땐 다음 말이 사라질 때까지 잔다
        self._expiry.setSingleShot(True)
        self._expiry.timeout.connect(self._kick)

        self.apply_cfg(cfg)
        self._add(Line(0, "", "자막 모드 · 말이 들리면 여기에 번역이 나와요", "status"))

    # ---------- 모양 ----------
    @staticmethod
    def _font(px: int, weight: QFont.Weight) -> QFont:
        f = QFont()
        f.setFamilies(["Pretendard", "Malgun Gothic"])
        f.setPixelSize(px)
        f.setWeight(weight)
        return f

    def apply_cfg(self, cfg: dict) -> None:
        self.cfg = dict(cfg)
        size = int(cfg["subtitle_size"])
        self.bg_alpha = round(255 * int(cfg["subtitle_opacity"]) / 100)
        pending = (self._font(round(size * 0.8), QFont.Weight.DemiBold), QColor(255, 255, 255, 150))
        self.styles = {
            "ok": (self._font(size, QFont.Weight.Bold), QColor(255, 255, 255)),
            "pending": pending,
            "status": pending,
            "error": (self._font(round(size * 0.6), QFont.Weight.DemiBold), QColor("#f87171")),
            "source": (self._font(max(12, round(size * 0.55)), QFont.Weight.Normal), QColor(255, 255, 255, 190)),
        }
        self._resize()
        self._remeasure()

    def _wrap_w(self) -> float:
        return self._max_w - 2 * PAD_X

    def _blocks(self, line: Line) -> list[tuple[str, str]]:
        show_src = bool(self.cfg["subtitle_original"])
        if line.kind == "status":
            return [(line.text, "status")]
        if line.kind == "pending":
            # 번역이 올 때까지는 원문을 크게 (원문 보기를 꺼 뒀어도 '…' 만 보이면 답답하므로)
            return [(line.source, "source"), ("…", "pending")] if show_src else [(line.source, "pending")]
        head = [(line.source, "source")] if show_src and line.source else []
        return head + [(line.text, line.kind)]

    def _measure(self, line: Line) -> None:
        rect = QRectF(0, 0, self._wrap_w(), 100000)
        line.blocks, line.natural_w = [], 0.0
        for text, style in self._blocks(line):
            if not text:
                continue
            font, color = self.styles[style]
            r = QFontMetricsF(font).boundingRect(rect, TEXT_FLAGS, text)
            line.blocks.append((text, font, color, math.ceil(r.height())))
            line.natural_w = max(line.natural_w, r.width())
        line.full_h = sum(b[3] for b in line.blocks) + BLOCK_GAP * max(0, len(line.blocks) - 1)

    def _remeasure(self) -> None:
        for line in self.lines:
            self._measure(line)
        self._trim()
        self._kick()

    def _screen_area(self):
        screen = QGuiApplication.screenAt(QPoint(*self._anchor)) if self._anchor else None
        return (screen or QGuiApplication.primaryScreen()).availableGeometry()

    def _default_anchor(self) -> tuple[int, int]:
        area = QGuiApplication.primaryScreen().availableGeometry()
        return area.center().x(), area.bottom() - BOTTOM_MARGIN

    def place(self) -> None:
        pos = self.cfg.get("subtitle_pos")
        anchor = tuple(pos) if isinstance(pos, (list, tuple)) and len(pos) == 2 else None
        # 저장된 자리가 지금 연결된 화면 밖이면(모니터를 뺐을 때 등) 기본 자리로
        if anchor is None or QGuiApplication.screenAt(QPoint(*anchor)) is None:
            anchor = self._default_anchor()
        self._anchor = (int(anchor[0]), int(anchor[1]))
        old_w = self._max_w
        self._resize()
        if self._max_w != old_w:
            self._remeasure()

    def _resize(self) -> None:
        """창은 상자가 커질 수 있는 최대 크기로 고정: 폭은 화면의 70% (최대 1200), 높이는 화면의 60%."""
        area = self._screen_area()
        self._max_w = min(MAX_WIDTH, int(area.width() * 0.7))
        self.setFixedSize(self._max_w, int(area.height() * 0.6))
        if self._anchor is None:
            return
        cx, bottom = self._anchor
        x = min(max(area.left(), cx - self.width() // 2), area.right() - self.width() + 1)
        bottom = min(max(bottom, area.top() + 80), area.bottom())
        self.move(x, bottom - self.height() + 1)    # 창의 아래쪽 = 상자의 아래쪽 = 기준점

    def box_rect(self) -> QRectF:
        """지금 그려지는 배경 상자. 창 아래쪽 가운데에 붙어 위로 자란다."""
        content = sum(line.h for line in self.lines)
        h = content + (2 * PAD_Y - LINE_GAP) * self._presence
        return QRectF((self.width() - self._box_w) / 2, self.height() - h, self._box_w, h)

    # ---------- 내용 ----------
    def _find(self, uid: int) -> Line | None:
        return next((line for line in self.lines if line.uid == uid), None)

    def _set_expiry(self, line: Line) -> None:
        hide = int(self.cfg["subtitle_hide_sec"])
        if hide <= 0:
            line.expire_at = None
        elif line.kind == "pending":
            # 번역을 기다리는 동안은 사라지지 않는다. 시간은 번역이 온 뒤부터 잰다.
            # 번역이 끝내 안 오면(엔진 멈춤 등) 화면에 남지 않게 넉넉한 한도만 둔다
            line.expire_at = self._clock() + PENDING_MAX_SEC
        else:
            # 긴 문장은 읽을 시간을 더 준다
            line.expire_at = self._clock() + hide + len(line.text or line.source) // 15

    def _add(self, line: Line) -> None:
        self._set_expiry(line)
        self._measure(line)
        self.lines.append(line)
        self._trim()
        self._kick()

    def _update(self, line: Line, **fields) -> None:
        for k, v in fields.items():
            setattr(line, k, v)
        line.dying = False          # 흐려지던 중이어도 새 내용이 오면 다시 또렷하게
        self._set_expiry(line)
        self._measure(line)
        self._trim()
        self._kick()

    def _trim(self) -> None:
        """너무 많이 쌓이면 가장 오래된 말부터 흐려지게 한다."""
        alive = [line for line in self.lines if not line.dying]
        room = self.height() - 2 * PAD_Y
        limit = max(1, int(self.cfg.get("subtitle_max_lines", MAX_LINES)))
        while len(alive) > 1 and (len(alive) > limit or sum(l.full_h + LINE_GAP for l in alive) > room):
            alive.pop(0).dying = True

    def show_source(self, uid: int, lang: str, text: str) -> None:
        if uid < self.uid:
            return
        self.uid = uid
        for line in self.lines:
            if line.kind == "status":
                line.dying = True
        line = self._find(uid)
        if line is not None:
            self._update(line, source=clip(text, MAX_SOURCE_CHARS))
        else:
            self._add(Line(uid, clip(text, MAX_SOURCE_CHARS)))

    def show_translation(self, uid: int, source: str, text: str) -> None:
        line = self._find(uid)
        if line is not None:        # 더 새 말이 와 있어도 그 줄이 남아 있으면 제자리에 채운다
            self._update(line, source=clip(source, MAX_SOURCE_CHARS),
                         text=clip(text, MAX_TRANSLATION_CHARS), kind="ok")

    def show_failed(self, uid: int, source: str, msg: str) -> None:
        line = self._find(uid)
        if line is not None:
            self._update(line, source=clip(source, MAX_SOURCE_CHARS), text=f"번역 실패 · {msg}", kind="error")

    def show_status(self, text: str) -> None:
        """듣기 전 준비 상태 등. 실제 자막이 한 번이라도 떴으면 끼어들지 않는다."""
        if self.uid != 0:
            return
        line = self._find(0)
        if line is not None:
            self._update(line, text=text)
        else:
            self._add(Line(0, "", text, "status"))

    # ---------- 움직임 ----------
    def _kick(self) -> None:
        """프레임 타이머를 돌린다 (이미 돌고 있으면 그대로)."""
        self._expiry.stop()
        if not self._frame.isActive():
            self._last = self._clock()
            self._frame.start()

    def _tick(self) -> None:
        now = self._clock()
        dt = 0.0 if self._last is None else min(0.1, max(0.0, now - self._last))
        self._last = now
        k = 1 - math.exp(-dt / EASE_SEC) if dt > 0 else 0.0

        if not self._hover:
            for line in self.lines:
                if not line.dying and line.expire_at is not None and now >= line.expire_at:
                    line.dying = True
        busy = False
        for line in self.lines:
            if line.dying:
                line.alpha = max(0.0, line.alpha - dt / FADE_SEC)
            else:
                line.alpha = min(1.0, line.alpha + dt / APPEAR_SEC)
            line.h = _approach(line.h, line.target_h, k)
            busy |= line.h != line.target_h or (line.alpha > 0 if line.dying else line.alpha < 1)
        self.lines = [line for line in self.lines if not (line.gone and line.h == 0.0)]

        shown = [line for line in self.lines if not line.gone]
        presence = 1.0 if shown else 0.0
        self._presence = _approach(self._presence, presence, k, eps=0.01)
        if shown:
            target_w = min(self._max_w, max(MIN_WIDTH, max(l.natural_w for l in shown) + 2 * PAD_X + 12))
            # 상자가 거의 안 보일 땐 폭을 바로 맞춘다 (옆으로 자라지 않고 위로만 자라게)
            self._box_w = target_w if self._presence < 0.05 else _approach(self._box_w, target_w, k)
            busy |= self._box_w != target_w
        busy |= self._presence != presence
        self.update()

        if not busy:
            self._frame.stop()
            waits = [l.expire_at for l in self.lines if not l.dying and l.expire_at is not None]
            if waits and not self._hover:
                self._expiry.start(max(0, int((min(waits) - now) * 1000)) + 5)

    # ---------- 그리기 ----------
    def paintEvent(self, _e) -> None:
        box = self.box_rect()
        if box.height() < 0.5 or box.width() < 1 or (not self.lines and self._presence <= 0):
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        r = min(RADIUS, box.height() / 2, box.width() / 2)
        path = QPainterPath()
        path.addRoundedRect(box, r, r)
        # 최소 1: 배경 0 % 라도 상자 위에서는 마우스를 받게 (완전 투명한 곳은 클릭이 통과한다)
        p.fillPath(path, QColor(12, 12, 12, max(1, round(self.bg_alpha * min(1.0, self._presence)))))
        p.setClipPath(path)

        wrap = self._wrap_w()
        left = box.center().x() - wrap / 2
        y = box.bottom() - PAD_Y * self._presence
        for line in reversed(self.lines):
            if line.h > 0.5 and line.alpha > 0:
                p.save()
                # 자기 자리 밖으로는 안 그린다: 자리가 자라거나 접힐 때 이웃 줄과 겹치지 않게
                p.setClipRect(QRectF(box.left(), y - line.h, box.width(), line.h), Qt.ClipOperation.IntersectClip)
                top = y - line.full_h       # 글은 자리의 아래쪽에 붙인다 → 아래에서 밀고 올라오는 느낌
                for text, font, color, h in line.blocks:
                    rect = QRectF(left, top, wrap, h)
                    p.setFont(font)
                    for dx, dy, a in SHADOW:
                        p.setPen(QColor(0, 0, 0, round(a * line.alpha)))
                        p.drawText(rect.translated(dx, dy), TEXT_FLAGS, text)
                    c = QColor(color)
                    c.setAlphaF(color.alphaF() * line.alpha)
                    p.setPen(c)
                    p.drawText(rect, TEXT_FLAGS, text)
                    top += h + BLOCK_GAP
                p.restore()
            y -= line.h
        p.end()

    # ---------- 마우스 ----------
    def _on_box(self, pos: QPointF) -> bool:
        return self.box_rect().contains(pos)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self._on_box(e.position()):
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            e.ignore()

    def mouseMoveEvent(self, e) -> None:
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e) -> None:
        if self._drag is None:
            return
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        g = self.frameGeometry()
        self._anchor = (g.center().x(), g.bottom())
        self._emit(subtitle_pos=list(self._anchor))

    def enterEvent(self, e) -> None:
        self._hover = True          # 마우스를 올려 두면 사라지지 않는다
        self._expiry.stop()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._hover = False
        soon = self._clock() + 2    # 마우스를 뗀 뒤에도 잠깐은 남겨 둔다
        for line in self.lines:
            if not line.dying and line.expire_at is not None:
                line.expire_at = max(line.expire_at, soon)
        self._kick()
        super().leaveEvent(e)

    def contextMenuEvent(self, e) -> None:
        if not self._on_box(QPointF(e.pos())):
            e.ignore()
            return
        menu = QMenu(self)
        original = QAction("원문 같이 보기", menu, checkable=True, checked=bool(self.cfg["subtitle_original"]))
        original.toggled.connect(lambda on: self._emit(subtitle_original=on))
        menu.addAction(original)
        menu.addSeparator()
        bigger = menu.addAction("글자 크게")
        bigger.triggered.connect(lambda: self._emit(subtitle_size=min(72, self.cfg["subtitle_size"] + 4)))
        smaller = menu.addAction("글자 작게")
        smaller.triggered.connect(lambda: self._emit(subtitle_size=max(16, self.cfg["subtitle_size"] - 4)))
        reset = menu.addAction("원래 자리로")
        reset.triggered.connect(self.reset_position)
        menu.addSeparator()
        close = menu.addAction("자막 닫기")
        close.triggered.connect(self.close)
        menu.exec(e.globalPos())

    def reset_position(self) -> None:
        self.cfg["subtitle_pos"] = None
        self.place()
        self._emit(subtitle_pos=None)

    def _emit(self, **fields) -> None:
        self.changed.emit(fields)

    def closeEvent(self, e) -> None:
        self._frame.stop()
        self._expiry.stop()
        self.closed.emit()
        super().closeEvent(e)
