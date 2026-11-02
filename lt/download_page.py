"""다운로드 화면: 번역에 필요한 AI(라이브러리·음성 인식 모델·Ollama·번역 모델)를 받는다.

단계마다 한 줄: 상태 · 진행 막대 · 버튼. '한 번에 모두 받기'는 남은 단계를 차례로 한다.
실제 일은 setup_ai 가 스레드에서 하고, 한 단계가 끝날 때마다 상태를 다시 확인한 뒤 다음으로 간다.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from . import setup_ai
from .settings_pages import SettingsPage

LABELS = {"gpu": "그래픽카드", "libs": "AI 라이브러리", "asr": "음성 인식 모델", "ollama": "Ollama", "model": "번역 모델"}
HINTS = {
    "libs": "PyTorch(GPU 판)와 음성 인식 라이브러리. 가장 크고 오래 걸려요",
    "asr": "설정 > 음성 인식 에서 고른 모델이에요",
    "ollama": "내 PC 에서 번역 모델을 돌리는 프로그램 (ollama.com)",
    "model": "설정 > 번역 엔진 에서 고른 모델이에요",
}


class _Signal(QObject):
    checked = Signal(object)              # {단계: Status}
    progress = Signal(str, float, str)    # (단계, 퍼센트 또는 -1, 문구)
    finished = Signal(str, str)           # (단계, 오류 문구. 성공이면 "")


def _polish(label: QLabel, state: str) -> None:
    label.setProperty("state", state)
    label.style().unpolish(label)
    label.style().polish(label)


class StepRow(QWidget):
    """상태 문구 + 버튼, 그 아래 진행 막대."""

    def __init__(self, has_button: bool = True):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.text = QLabel("확인하는 중…")
        self.text.setObjectName("testResult")
        self.text.setWordWrap(True)
        top.addWidget(self.text, 1)
        self.button = QPushButton("받기")
        self.button.setVisible(False)
        if has_button:
            top.addWidget(self.button)
        col.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.hide()
        col.addWidget(self.bar)
        self._has_button = has_button

    def show_status(self, st: setup_ai.Status) -> None:
        self.bar.hide()
        text = st.text if not st.blocked or st.ok else f"{st.text} · {st.blocked}"
        self.text.setText(("✓ " if st.ok else "") + text)
        _polish(self.text, "ok" if st.ok else ("error" if st.needed and not st.blocked and not st.action else ""))
        show = self._has_button and st.needed and not st.ok and bool(st.action)
        self.button.setVisible(show)
        self.button.setText(st.action)
        self.button.setEnabled(not st.blocked)

    def start(self) -> None:
        self.button.setEnabled(False)
        self.bar.setRange(0, 0)
        self.bar.show()
        self.text.setText("준비 중…")
        _polish(self.text, "")

    def set_progress(self, pct: float, text: str) -> None:
        if pct < 0:
            self.bar.setRange(0, 0)       # 얼마나 남았는지 모를 땐 오가는 막대
        else:
            self.bar.setRange(0, 100)
            self.bar.setValue(round(pct))
        self.text.setText(text)

    def fail(self, error: str) -> None:
        self.bar.hide()
        self.button.setEnabled(True)
        self.button.setText("다시 하기")
        self.button.setVisible(self._has_button)
        self.text.setText(error)
        _polish(self.text, "error")


class DownloadPage(SettingsPage):
    title = "다운로드"
    description = ("번역에 필요한 AI 를 이 PC 에 받아요. 처음 한 번만 하면 되고, NVIDIA 그래픽카드가 필요해요. "
                   "모두 받으면 인터넷 없이도 번역할 수 있어요.")

    ready_changed = Signal(bool)    # 번역을 시작할 수 있는지 (확인할 때마다)

    def _build(self) -> None:
        self.status: dict[str, setup_ai.Status] = {}
        self.ready: bool | None = None      # 아직 확인 전이면 None
        self._queue: list[str] = []
        self._running: str | None = None
        self._checking = False
        self._recheck = False

        self.rows: dict[str, StepRow] = {}
        for step in setup_ai.STEPS:
            row = StepRow(has_button=step != "gpu")
            row.button.clicked.connect(lambda _=False, s=step: self.install([s]))
            self.rows[step] = row
            self._row(LABELS[step], row, HINTS.get(step, ""))

        bottom = QWidget()
        b = QHBoxLayout(bottom)
        b.setContentsMargins(0, 6, 0, 0)
        b.setSpacing(12)
        self.all_btn = QPushButton("한 번에 모두 받기")
        self.all_btn.setObjectName("primary")
        self.all_btn.setEnabled(False)
        self.all_btn.clicked.connect(self.install_all)
        b.addWidget(self.all_btn)
        self.summary = QLabel("")
        self.summary.setObjectName("testResult")
        self.summary.setWordWrap(True)
        b.addWidget(self.summary, 1)
        bottom.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._row("", bottom, "받는 동안 다른 화면으로 가도 괜찮아요. 앱을 닫으면 멈추고, 다시 누르면 남은 것부터 받아요")

        self._signal = _Signal(self)
        self._signal.checked.connect(self._checked)
        self._signal.progress.connect(self._progress)
        self._signal.finished.connect(self._finished)

    def _fill(self, cfg: dict) -> None:
        pass

    @property
    def busy(self) -> bool:
        return self._running is not None

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.refresh()

    # ---------- 확인 ----------
    def refresh(self) -> None:
        if self._running:
            return
        if self._checking:
            self._recheck = True        # 확인 중에 설정이 바뀌면 끝나고 한 번 더
            return
        self._checking = True
        cfg, signal = dict(self.model.value), self._signal

        def work():
            try:
                signal.checked.emit(setup_ai.check_all(cfg))
            except Exception as e:      # 확인 자체가 실패해도 화면은 멈추지 않게
                signal.checked.emit({"error": str(e)})
        threading.Thread(target=work, daemon=True).start()

    def _checked(self, status: dict) -> None:
        self._checking = False
        if "error" in status:
            self.summary.setText(f"확인하지 못했어요: {status['error']}")
            _polish(self.summary, "error")
            return
        if self._recheck:
            self._recheck = False
            self.refresh()
            return
        self.status = status
        for step, row in self.rows.items():
            row.show_status(status[step])
        self.ready = setup_ai.ready(status)
        if self.ready:
            self.summary.setText("✓ 모두 준비됐어요. 번역 화면에서 시작을 누르세요")
            _polish(self.summary, "ok")
        elif not status["gpu"].ok:
            self.summary.setText("NVIDIA 그래픽카드가 있어야 받을 수 있어요")
            _polish(self.summary, "error")
        else:
            left = sum(1 for s in status.values() if s.needed and not s.ok)
            self.summary.setText(f"받을 것이 {left}개 남았어요")
            _polish(self.summary, "")
        self.all_btn.setVisible(not self.ready)
        self.all_btn.setEnabled(status["gpu"].ok and not self.ready and not self._running)
        self.ready_changed.emit(self.ready)
        if self._queue:
            self._next()

    # ---------- 받기 ----------
    def install_all(self) -> None:
        self.install([s for s in setup_ai.STEPS if s != "gpu"])

    def install(self, steps: list[str]) -> None:
        if self._running:
            return
        self._queue = list(steps)
        self.all_btn.setEnabled(False)
        self._next()

    def _next(self) -> None:
        while self._queue:
            step = self._queue[0]
            st = self.status.get(step)
            if st is None or st.ok or not st.needed:
                self._queue.pop(0)
                continue
            if st.blocked:
                self._queue.clear()
                self.summary.setText(f"{LABELS[step]}: {st.blocked}")
                _polish(self.summary, "error")
                break
            self._queue.pop(0)
            self._start(step)
            return
        self.all_btn.setEnabled(bool(self.status) and self.status["gpu"].ok and not self.ready)

    def _start(self, step: str) -> None:
        self._running = step
        for row in self.rows.values():
            row.button.setEnabled(False)
        self.rows[step].start()
        self.summary.setText(f"{LABELS[step]} 받는 중… 창을 닫지 마세요")
        _polish(self.summary, "")
        cfg, signal = dict(self.model.value), self._signal

        def work():
            try:
                setup_ai.run_step(step, cfg, lambda pct, text: signal.progress.emit(step, pct, text))
                signal.finished.emit(step, "")
            except setup_ai.SetupError as e:
                signal.finished.emit(step, str(e))
            except Exception as e:
                signal.finished.emit(step, f"알 수 없는 오류 ({e.__class__.__name__}: {e})")
        threading.Thread(target=work, daemon=True).start()

    def _progress(self, step: str, pct: float, text: str) -> None:
        if step == self._running:
            self.rows[step].set_progress(pct, text)

    def _finished(self, step: str, error: str) -> None:
        self._running = None
        if error:
            self._queue.clear()
            self.rows[step].fail(error)
            for s, row in self.rows.items():
                if s != step and s in self.status:
                    row.show_status(self.status[s])
            self.summary.setText(f"{LABELS[step]} 을 받지 못했어요")
            _polish(self.summary, "error")
            self.all_btn.setEnabled(True)
            return
        self.refresh()                  # 다시 확인하고, 남은 단계가 있으면 이어서
