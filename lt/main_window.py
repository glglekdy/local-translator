"""메인 창: 왼쪽 메뉴 | 화면(번역 · 설정 2개). QuickMedia 메인 창과 같은 틀.

번역 화면: 입력 고르기 · 번역 언어 · 시작 버튼 / 말 한 마디마다 카드(원문 위, 번역 아래) / 아래 독.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication

from . import NAME, __version__, engine, theme, updater
from .obs import ObsServer
from .pipeline import Pipeline
from .download_page import DownloadPage
from .settings_pages import PAGES, SettingsModel
from .sidebar import Sidebar
from .subtitle import SubtitleWindow

# 듣는 중에 이 설정이 바뀌면 다시 시작해야 한다 (번역 설정은 바로 반영된다)
RESTART_KEYS = {"source", "asr_model", "source_language", "sensitivity", "pause_sec"}
SOURCES = {"system": "시스템 소리", "mic": "마이크"}


class StatusDot(QWidget):
    """상태 점. 듣는 중이면 빨간 점이 천천히 깜빡인다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self.state = "idle"
        self._alpha = 1.0
        self.anim = QPropertyAnimation(self, b"alpha", self)
        self.anim.setDuration(1100)
        self.anim.setKeyValueAt(0, 1.0)
        self.anim.setKeyValueAt(0.5, 0.25)
        self.anim.setKeyValueAt(1, 1.0)
        self.anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.anim.setLoopCount(-1)

    def _get_alpha(self) -> float:
        return self._alpha

    def _set_alpha(self, v: float) -> None:
        self._alpha = v
        self.update()

    alpha = Property(float, _get_alpha, _set_alpha)

    def set_state(self, state: str) -> None:
        self.state = state
        if state == "listening":
            self.anim.start()
        else:
            self.anim.stop()
            self._alpha = 1.0
        self.update()

    def paintEvent(self, _e) -> None:
        key = {"listening": "accent", "error": "danger", "loading": "muted"}.get(self.state, "disabled_fg")
        c = QColor(theme.color(key))
        c.setAlphaF(self._alpha)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(QRectF(1, 1, 8, 8))


class UtteranceCard(QFrame):
    """말 한 마디. 위에 언어·시각, 원문(흐리게), 그 아래 번역(크게)."""

    def __init__(self, lang: str, text: str):
        super().__init__()
        self.setObjectName("utterance")
        self.lang, self.source_text, self.translation = lang, text, ""
        self.stamp = time.strftime("%H:%M:%S")
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 12, 16, 14)
        col.setSpacing(6)
        meta = QLabel(f"{lang.upper()}  ·  {self.stamp}")
        meta.setObjectName("uttMeta")
        col.addWidget(meta)
        src = QLabel(text)
        src.setObjectName("uttSource")
        src.setWordWrap(True)
        src.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        col.addWidget(src)
        self.tr = QLabel("번역 중…")
        self.tr.setObjectName("uttTranslation")
        self.tr.setWordWrap(True)
        self.tr.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._set_state("pending")
        col.addWidget(self.tr)

    def _set_state(self, state: str) -> None:
        self.tr.setProperty("state", state)
        self.tr.style().unpolish(self.tr)
        self.tr.style().polish(self.tr)

    def set_translation(self, text: str) -> None:
        self.translation = text
        self.tr.setText(text)
        self._set_state("")

    def set_failed(self, msg: str) -> None:
        self.tr.setText(f"번역 실패 · {msg}")
        self._set_state("error")

    def set_latest(self, on: bool) -> None:
        self.setProperty("latest", on)
        self.style().unpolish(self)
        self.style().polish(self)


class MainWindow(QMainWindow):
    def __init__(self, config_path: Path | None = None):
        super().__init__()
        self.setWindowTitle(NAME)
        self.resize(920, 680)
        self.setMinimumSize(700, 500)
        self.model = SettingsModel(engine.load_config(config_path), config_path, self)
        self.model.changed.connect(self._cfg_changed)
        self.pipeline: Pipeline | None = None
        self._retired: list[Pipeline] = []   # 멈추는 중인 이전 파이프라인
        self.cards: dict[int, UtteranceCard] = {}
        self.subtitle: SubtitleWindow | None = None
        self.obs: ObsServer | None = None       # OBS 브라우저 소스로 보내는 서버
        self._quitting = False
        self._setup_prompted = False
        self._build_ui()
        self._sync()
        if self.model.value["subtitle_enabled"]:   # 지난번에 켜 두고 닫았으면 다시 켠다
            self.set_subtitle(True)
        self._apply_obs()

    # ---------- 화면 ----------
    def _build_ui(self) -> None:
        main = QWidget()
        main.setObjectName("mainArea")
        root = QVBoxLayout(main)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QVBoxLayout()
        head.setContentsMargins(28, 24, 28, 8)
        head.setSpacing(4)
        crumb = QLabel(NAME)
        crumb.setObjectName("crumb")
        head.addWidget(crumb)
        hint = QLabel("들리는 말을 알아듣고 바로 번역해요. 원문 아래에 번역이 나와요.")
        hint.setObjectName("viewHint")
        head.addWidget(hint)
        root.addLayout(head)

        form = QHBoxLayout()
        form.setContentsMargins(28, 12, 28, 16)
        form.setSpacing(10)
        seg = QFrame()
        seg.setObjectName("segment")
        seg_row = QHBoxLayout(seg)
        seg_row.setContentsMargins(3, 3, 3, 3)
        seg_row.setSpacing(2)
        self.source_group = QButtonGroup(self)
        for key, label in SOURCES.items():
            btn = QPushButton(label)
            btn.setObjectName("segButton")
            btn.setCheckable(True)
            btn.setProperty("source", key)
            self.source_group.addButton(btn)
            seg_row.addWidget(btn)
        self.source_group.buttonClicked.connect(lambda b: self.model.update(source=b.property("source")))
        form.addWidget(seg)
        arrow = QLabel("→")
        arrow.setObjectName("arrowLabel")
        form.addWidget(arrow)
        self.target = QComboBox()
        self.target.addItems(engine.TARGET_LANGUAGES)
        self.target.setMinimumWidth(110)
        self.target.currentTextChanged.connect(lambda t: self.model.update(target=t))
        form.addWidget(self.target)
        form.addStretch(1)
        self.dot = StatusDot()
        form.addWidget(self.dot)
        self.status = QLabel("대기 중")
        self.status.setObjectName("statusText")
        form.addWidget(self.status)
        form.addSpacing(6)
        self.subtitle_btn = QPushButton("자막 모드")
        self.subtitle_btn.setObjectName("toggle")
        self.subtitle_btn.setCheckable(True)
        self.subtitle_btn.setToolTip("화면 아래에 영화 자막처럼 번역을 띄워요. 끌어서 옮기고, 오른쪽 클릭으로 설정해요")
        self.subtitle_btn.toggled.connect(self.set_subtitle)
        form.addWidget(self.subtitle_btn)
        self.start_btn = QPushButton("시작")
        self.start_btn.setObjectName("primary")
        self.start_btn.setMinimumWidth(84)
        self.start_btn.clicked.connect(self.toggle)
        form.addWidget(self.start_btn)
        root.addLayout(form)

        list_head = QHBoxLayout()
        list_head.setContentsMargins(28, 4, 28, 6)
        title = QLabel("번역 기록")
        title.setObjectName("sectionTitle")
        list_head.addWidget(title)
        list_head.addStretch(1)
        clear = QPushButton("모두 지우기")
        clear.setObjectName("ghost")
        clear.clicked.connect(self.clear)
        list_head.addWidget(clear)
        root.addLayout(list_head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        holder.setObjectName("queueHolder")
        self.list = QVBoxLayout(holder)
        self.list.setContentsMargins(28, 0, 28, 16)
        self.list.setSpacing(8)
        self.empty = QLabel("시작을 누르면 들리는 말을 번역해요\n유튜브·회의처럼 PC 에서 나는 소리는 '시스템 소리'를 고르세요")
        self.empty.setObjectName("emptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.list.addWidget(self.empty)
        self.list.addStretch(1)
        self.scroll.setWidget(holder)
        # 새 카드가 붙어 길이가 늘면 맨 아래로 (사용자가 위를 보고 있으면 그대로)
        self._stick = True
        bar = self.scroll.verticalScrollBar()
        bar.rangeChanged.connect(self._on_range)
        bar.valueChanged.connect(lambda v: setattr(self, "_stick", v >= bar.maximum() - 24))
        root.addWidget(self.scroll, 1)

        dock = QFrame()
        dock.setObjectName("dock")
        d = QHBoxLayout(dock)
        d.setContentsMargins(28, 12, 28, 12)
        d.setSpacing(6)
        lbl = QLabel("번역 엔진")
        lbl.setObjectName("hint")
        d.addWidget(lbl)
        d.addSpacing(4)
        self.engine_name = QLabel()
        self.engine_name.setObjectName("engineName")
        d.addWidget(self.engine_name)
        change = QPushButton("변경")
        change.setObjectName("ghost")
        change.clicked.connect(lambda: self.sidebar.select("engine"))
        d.addWidget(change)
        d.addStretch(1)
        copy = QPushButton("번역 복사")
        copy.clicked.connect(self.copy_all)
        d.addWidget(copy)
        save = QPushButton("텍스트로 저장")
        save.clicked.connect(self.save_text)
        d.addWidget(save)
        root.addWidget(dock)

        self.stack = QStackedWidget()
        self.pages: dict[str, QWidget] = {"translate": main}
        self.stack.addWidget(main)
        for key, cls in PAGES.items():
            self.pages[key] = cls(self.model)
            self.stack.addWidget(self.pages[key])
        self.pages["download"] = DownloadPage(self.model)
        self.stack.addWidget(self.pages["download"])
        self.pages["download"].ready_changed.connect(self._setup_ready)
        self.sidebar = Sidebar()
        self.sidebar.page_changed.connect(lambda k: self.stack.setCurrentWidget(self.pages[k]))
        self.pages["update"].available.connect(self._update_available)
        self.pages["update"].restart_requested.connect(self.restart)
        self.sidebar.version_label.linkActivated.connect(lambda _: self.sidebar.select("update"))
        shell = QWidget()
        row = QHBoxLayout(shell)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.sidebar)
        row.addWidget(self.stack, 1)
        self.setCentralWidget(shell)

    def _sync(self) -> None:
        """화면 칸을 지금 설정에 맞춘다."""
        cfg = self.model.value
        for b in self.source_group.buttons():
            b.setChecked(b.property("source") == cfg["source"])
        self.target.blockSignals(True)
        self.target.setCurrentText(cfg["target"])
        self.target.blockSignals(False)
        self.engine_name.setText(engine.engine_summary(cfg))

    def _on_range(self, _lo: int, hi: int) -> None:
        if self._stick:
            self.scroll.verticalScrollBar().setValue(hi)

    # ---------- 설정 ----------
    def _cfg_changed(self, cfg: dict, keys: set) -> None:
        self._sync()
        if keys & {"engine", "asr_model", "ollama_model"} and self.pages["download"].ready is not None:
            self.pages["download"].refresh()     # 고른 모델이 바뀌면 받을 것도 바뀐다
        if "subtitle_enabled" in keys:
            self.set_subtitle(bool(cfg["subtitle_enabled"]))     # 설정 화면에서 켜고 끈 경우
            check = self.pages["subtitle"].enabled                # 보고 있는 설정 화면도 맞춰 둔다
            check.blockSignals(True)
            check.setChecked(bool(cfg["subtitle_enabled"]))
            check.blockSignals(False)
        if self.subtitle is not None and any(k.startswith("subtitle_") for k in keys):
            self.subtitle.apply_cfg(cfg)
            if "subtitle_pos" in keys:
                self.subtitle.place()
        if keys & {"obs_enabled", "obs_port"}:
            self._apply_obs()
        elif self.obs is not None and any(k.startswith("subtitle_") for k in keys):
            self.obs.apply_cfg(cfg)
        for page in self.pages.values():
            if hasattr(page, "load") and page.isHidden():
                page.load(cfg)
        if self.pipeline is None:
            return
        if keys & RESTART_KEYS:
            self.stop()
            self.start()
        else:
            self.pipeline.set_cfg(cfg)

    # ---------- 시작 / 정지 ----------
    def toggle(self) -> None:
        if self.pipeline is None:
            download = self.pages["download"]
            if download.ready is False or download.busy:    # 아직 받을 AI 가 남았으면 다운로드 화면으로
                self.sidebar.select("download")
                self._set_status("error", "먼저 다운로드 화면에서 AI 를 받아 주세요")
                return
            self.start()
        else:
            self.stop()
            self._set_status("idle", "멈췄어요")

    def start(self) -> None:
        p = Pipeline(self.model.value)
        p.status.connect(self._on_status)
        p.heard.connect(self._on_heard)
        p.translated.connect(self._on_translated)
        p.failed.connect(self._on_failed)
        p.finished.connect(self._on_finished)
        self.pipeline = p
        self.start_btn.setText("정지")
        self._set_status("loading", "준비 중…")
        p.start()

    def stop(self) -> None:
        p, self.pipeline = self.pipeline, None
        if p is not None:
            p.stop()
            p.status.disconnect(self._on_status)   # 멈추는 중에 오는 상태 문구는 무시
            self._retired.append(p)
        self.start_btn.setText("시작")

    def _on_finished(self) -> None:
        p = self.sender()
        if p is self.pipeline:          # 오류로 스스로 끝남
            self.pipeline = None
            self.start_btn.setText("시작")
            if self.dot.state != "error":
                self._set_status("idle", "멈췄어요")
        if p in self._retired:
            self._retired.remove(p)
        p.deleteLater()

    def _set_status(self, state: str, text: str) -> None:
        self.dot.set_state(state)
        self.status.setText(text)
        self.status.setProperty("state", state)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _on_status(self, state: str, text: str) -> None:
        if state == "listening":
            text = f"{SOURCES[self.model.value['source']]} 듣는 중"
        self._set_status(state, text)
        if self.subtitle is not None:
            self.subtitle.show_status(text)

    # ---------- 업데이트 ----------
    # ---------- AI 다운로드 ----------
    def check_setup_later(self, delay_ms: int = 300) -> None:
        """앱을 켜고 곧 필요한 AI 가 다 있는지 확인한다. 없으면 다운로드 화면으로 안내."""
        QTimer.singleShot(delay_ms, self.pages["download"].refresh)

    def _setup_ready(self, ready: bool) -> None:
        self.sidebar.set_dot("download", not ready)
        if not ready and not self._setup_prompted and self.pipeline is None:
            self._setup_prompted = True             # 처음 한 번만 데려간다
            self.sidebar.select("download")

    def check_updates_later(self, delay_ms: int = 3000) -> None:
        """앱을 켜고 조금 뒤 조용히 새 버전을 확인한다 (설정에서 끌 수 있음)."""
        if self.model.value["update_auto_check"]:
            QTimer.singleShot(delay_ms, lambda: self.pages["update"].check(silent=True))

    def _update_available(self, release: updater.Release) -> None:
        self.sidebar.set_dot("update", True)
        self.sidebar.version_label.setText(
            f'버전 {__version__} · <a href="update" style="color:{theme.color("accent")}; text-decoration:none">'
            f"새 버전 {release.version}</a>")

    def restart(self) -> None:
        """새로 설치한 판으로 다시 켠다."""
        QProcess.startDetached(sys.executable, [str(updater.APP_DIR / "app.py")], str(updater.APP_DIR))
        self.close()
        QApplication.quit()

    # ---------- 자막 모드 ----------
    def set_subtitle(self, on: bool) -> None:
        if on and self.subtitle is None:
            self.subtitle = SubtitleWindow(self.model.value)
            self.subtitle.changed.connect(lambda fields: self.model.update(**fields))
            self.subtitle.closed.connect(self._subtitle_closed)
            self.subtitle.place()
            self.subtitle.show()
            if self.pipeline is None:
                self.subtitle.show_status("자막 모드 · 시작을 누르면 여기에 번역이 나와요")
        elif not on and self.subtitle is not None:
            self.subtitle.close()
        if self.subtitle_btn.isChecked() != on:
            self.subtitle_btn.setChecked(on)
        self.model.update(subtitle_enabled=on)      # 켜 둔 상태를 기억해 다음 실행 때 다시 켠다

    def _subtitle_closed(self) -> None:
        sub, self.subtitle = self.subtitle, None
        if sub is not None:
            sub.deleteLater()
        self.subtitle_btn.blockSignals(True)
        self.subtitle_btn.setChecked(False)
        self.subtitle_btn.blockSignals(False)
        if not self._quitting:                      # 앱을 닫느라 같이 닫힌 건 '끔'으로 치지 않는다
            self.model.update(subtitle_enabled=False)

    # ---------- OBS ----------
    def _apply_obs(self) -> None:
        """설정대로 OBS 서버를 켜고 끈다. 포트가 바뀌면 다시 연다."""
        cfg = self.model.value
        want = bool(cfg["obs_enabled"])
        port = int(cfg["obs_port"])
        if self.obs is not None and (not want or self.obs.port != port):
            self.obs.stop()
            self.obs = None
        page = self.pages["subtitle"]
        if not want:
            page.set_obs_state("", "")
            return
        if self.obs is None:
            srv = ObsServer(cfg, port)
            try:
                srv.start()
            except OSError:
                page.set_obs_state("error", f"{port} 번 포트를 열 수 없어요. 다른 프로그램이 쓰고 있으면 포트를 바꿔 주세요")
                return
            self.obs = srv
        page.set_obs_state("ok", "✓ 보내는 중이에요. OBS 에서 아래 주소를 브라우저 소스로 추가하세요")

    # ---------- 카드 ----------
    def _on_heard(self, uid: int, lang: str, text: str) -> None:
        self.empty.hide()
        for c in self.cards.values():
            c.set_latest(False)
        card = UtteranceCard(lang, text)
        card.set_latest(True)
        self.list.insertWidget(self.list.count() - 1, card)   # 맨 아래 stretch 바로 위
        self.cards[uid] = card
        if self.subtitle is not None:
            self.subtitle.show_source(uid, lang, text)
        if self.obs is not None:
            self.obs.show_source(uid, text)

    def _on_translated(self, uid: int, text: str) -> None:
        if uid in self.cards:
            self.cards[uid].set_translation(text)
            if self.subtitle is not None:
                self.subtitle.show_translation(uid, self.cards[uid].source_text, text)
            if self.obs is not None:
                self.obs.show_translation(uid, self.cards[uid].source_text, text)

    def _on_failed(self, uid: int, msg: str) -> None:
        if uid in self.cards:
            self.cards[uid].set_failed(msg)
            if self.subtitle is not None:
                self.subtitle.show_failed(uid, self.cards[uid].source_text, msg)
            if self.obs is not None:
                self.obs.show_failed(uid)

    def clear(self) -> None:
        for card in self.cards.values():
            self.list.removeWidget(card)
            card.deleteLater()
        self.cards.clear()
        self.empty.show()

    def transcript(self, translations_only: bool = False) -> str:
        cards = [c for c in self.cards.values() if c.translation]
        if translations_only:
            return "\n".join(c.translation for c in cards)
        return "\n\n".join(f"[{c.stamp}] ({c.lang}) {c.source_text}\n{c.translation}" for c in cards)

    def copy_all(self) -> None:
        QGuiApplication.clipboard().setText(self.transcript(translations_only=True))
        self._flash("번역을 복사했어요")

    def save_text(self) -> None:
        default = str(Path.home() / "Documents" / f"번역 {time.strftime('%Y-%m-%d %H%M')}.txt")
        path, _ = QFileDialog.getSaveFileName(self, "텍스트로 저장", default, "텍스트 (*.txt)")
        if path:
            Path(path).write_text(self.transcript(), encoding="utf-8")
            self._flash("저장했어요")

    def _flash(self, text: str) -> None:
        """상태 문구를 잠깐 바꿨다가 되돌린다."""
        before = (self.dot.state, self.status.text())
        self.status.setText(text)
        QTimer.singleShot(1500, lambda: self.status.text() == text and self.status.setText(before[1]))

    def closeEvent(self, e) -> None:
        self._quitting = True
        if self.subtitle is not None:
            self.subtitle.close()
        if self.obs is not None:
            self.obs.stop()
            self.obs = None
        self.stop()
        for p in list(self._retired):
            p.wait(3000)
        super().closeEvent(e)

    def sizeHint(self) -> QSize:
        return QSize(920, 680)
