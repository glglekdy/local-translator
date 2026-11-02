"""설정 화면 2개(음성 인식 / 번역 엔진). QuickMedia 설정 화면과 같은 틀 — 제목 + 설명 + 카드.

바꾸면 바로 config.json 에 저장하고 `SettingsModel.changed` 로 알린다.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QProgressBar, QPushButton, QRadioButton, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from . import __version__, engine, updater


class SettingsModel(QObject):
    """지금 설정. 값이 실제로 바뀔 때만 저장하고 `changed(새 설정, 바뀐 키들)`를 낸다."""

    changed = Signal(dict, set)

    def __init__(self, value: dict, path: Path | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self.value = dict(value)
        self.path = path

    def update(self, **fields) -> bool:
        keys = {k for k, v in fields.items() if self.value.get(k) != v}
        if not keys:
            return False
        self.value = {**self.value, **fields}
        engine.save_config(self.value, self.path)
        self.changed.emit(dict(self.value), keys)
        return True


class SettingsPage(QWidget):
    """제목 + 설명 + 카드(이름 | 입력 칸, 그 아래 안내). 화면마다 `_build`, `_fill` 을 채운다."""

    title = ""
    description = ""
    label_width = 128

    def __init__(self, model: SettingsModel, parent: QWidget | None = None):
        super().__init__(parent)
        self.model = model
        self._loading = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        holder = QWidget()
        holder.setObjectName("settingsHolder")
        scroll.setWidget(holder)
        col = QVBoxLayout(holder)
        col.setContentsMargins(28, 24, 28, 24)
        col.setSpacing(0)

        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel(self.title)
        title.setObjectName("crumb")
        head.addWidget(title)
        self.saved_badge = QLabel("✓ 저장했어요")
        self.saved_badge.setObjectName("savedBadge")
        self.saved_badge.hide()
        head.addWidget(self.saved_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addStretch(1)
        col.addLayout(head)
        col.addSpacing(4)
        desc = QLabel(self.description)
        desc.setObjectName("viewHint")
        desc.setWordWrap(True)
        col.addWidget(desc)
        col.addSpacing(16)

        card = QFrame()
        card.setObjectName("settingsCard")
        self._grid = QGridLayout(card)
        self._grid.setContentsMargins(20, 18, 20, 18)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(14)
        self._grid.setColumnMinimumWidth(0, self.label_width)
        self._grid.setColumnStretch(1, 1)
        col.addWidget(card)
        col.addStretch(1)

        self._badge_timer = QTimer(self)
        self._badge_timer.setSingleShot(True)
        self._badge_timer.setInterval(1500)
        self._badge_timer.timeout.connect(self.saved_badge.hide)

        self._build()
        self.load(model.value)

    def _build(self) -> None:
        raise NotImplementedError

    def _fill(self, cfg: dict) -> None:
        raise NotImplementedError

    def _refresh(self) -> None:
        """켜고 끄는 규칙."""

    def _row(self, label: QWidget | str, control: QWidget | None = None, hint: str = "") -> QLabel | None:
        r = self._grid.rowCount()
        if isinstance(label, str):
            label = QLabel(label)
        cell = QVBoxLayout()
        cell.setSpacing(4)
        if control is not None:
            control.setMaximumWidth(420)
            grows = control.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
            cell.addWidget(control, 0, Qt.AlignmentFlag(0) if grows else Qt.AlignmentFlag.AlignLeft)
            label.setMinimumHeight(control.sizeHint().height())
        note = None
        if hint:
            note = QLabel(hint)
            note.setObjectName("hint")
            note.setWordWrap(True)
            note.setOpenExternalLinks(True)
            cell.addWidget(note)
        self._grid.addWidget(label, r, 0, Qt.AlignmentFlag.AlignTop)
        self._grid.addLayout(cell, r, 1)
        return note

    def load(self, cfg: dict) -> None:
        self._loading = True
        try:
            self._fill(cfg)
        finally:
            self._loading = False
        self._refresh()

    def commit(self, **fields) -> None:
        if self._loading:
            return
        self._refresh()
        if self.model.update(**fields):
            self.saved_badge.show()
            self._badge_timer.start()


def _combo(items: dict | list) -> QComboBox:
    """items: {값: 보이는 이름} 또는 [값]."""
    c = QComboBox()
    pairs = items.items() if isinstance(items, dict) else ((v, v) for v in items)
    for data, label in pairs:
        c.addItem(label, data)
    return c


def _select(c: QComboBox, data) -> None:
    i = c.findData(data)
    if i < 0 and c.isEditable():
        c.setEditText(str(data))
    else:
        c.setCurrentIndex(max(0, i))


class SpeechPage(SettingsPage):
    title = "음성 인식"
    description = "들리는 말을 글자로 바꾸는 방법이에요. 듣는 중에 바꾸면 알아서 다시 시작해요."

    def _build(self) -> None:
        self.asr = _combo({k: f"{name}  ·  {desc}" for k, (name, desc) in engine.ASR_MODELS.items()})
        self.asr.currentIndexChanged.connect(lambda: self.commit(asr_model=self.asr.currentData()))
        self.language = _combo(list(engine.SOURCE_LANGUAGES))
        self.language.currentIndexChanged.connect(lambda: self.commit(source_language=self.language.currentData()))
        self.sensitivity = _combo(list(engine.SENSITIVITY))
        self.sensitivity.currentIndexChanged.connect(lambda: self.commit(sensitivity=self.sensitivity.currentData()))
        self.pause = QDoubleSpinBox()
        self.pause.setRange(0.3, 2.0)
        self.pause.setSingleStep(0.1)
        self.pause.setDecimals(1)
        self.pause.setSuffix(" 초")
        self.pause.setFixedWidth(110)
        self.pause.valueChanged.connect(lambda v: self.commit(pause_sec=round(v, 1)))

        self._row("모델", self.asr, "노래·반주가 섞인 소리는 Qwen3-ASR 가 훨씬 정확해요. 처음 고른 모델은 한 번 내려받아요")
        self._row("말하는 언어", self.language, "자동 감지가 엉뚱한 언어로 알아들을 때만 고르세요. 고르면 더 정확해요")
        self._row("소리 감도", self.sensitivity, "작은 소리를 놓치면 높음, 잡음까지 번역되면 낮음")
        self._row("문장 끊기", self.pause, "말이 이만큼 멈추면 한 문장으로 보고 번역해요. 너무 잘게 끊기면 늘리세요")

    def _fill(self, cfg: dict) -> None:
        _select(self.asr, cfg["asr_model"])
        _select(self.language, cfg["source_language"])
        _select(self.sensitivity, cfg["sensitivity"])
        self.pause.setValue(float(cfg["pause_sec"]))


def _combo_id(c: QComboBox) -> str:
    """'ID · 설명' 으로 보이는 편집 가능 콤보에서 ID 만. 직접 입력한 글자는 첫 '·' 앞까지."""
    text = c.currentText().strip()
    i = c.findText(text)
    if i >= 0 and c.itemData(i):
        return c.itemData(i)
    return text.split("·")[0].strip()


def _select_id(c: QComboBox, model_id: str) -> None:
    i = c.findData(model_id)
    if i >= 0:
        c.setCurrentIndex(i)
    else:
        c.setEditText(model_id)


class _TestSignal(QObject):
    done = Signal(bool, str)


class _PullSignal(QObject):
    progress = Signal(float, str)
    done = Signal(bool, str)


class EnginePage(SettingsPage):
    title = "번역 엔진"
    description = "알아들은 문장을 어떤 AI 로 번역할지 정해요."
    label_width = 140

    def _build(self) -> None:
        self.use_ollama = QRadioButton("Ollama  ·  내 PC 에서 (오프라인, 무료)")
        self.use_gemini = QRadioButton("Gemini API  ·  인터넷 (API 키 필요)")
        group = QButtonGroup(self)
        group.addButton(self.use_ollama)
        group.addButton(self.use_gemini)
        group.buttonToggled.connect(self._on_engine)

        ollama_row = QWidget()
        box = QHBoxLayout(ollama_row)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.ollama_model = QComboBox()
        self.ollama_model.setEditable(True)   # 목록에 없는 모델 이름도 직접 넣을 수 있게
        self.ollama_model.setMinimumWidth(320)
        self.ollama_model.activated.connect(self._commit_ollama)
        self.ollama_model.lineEdit().editingFinished.connect(self._commit_ollama)
        box.addWidget(self.ollama_model, 1)
        self.pull_btn = QPushButton("받기")
        self.pull_btn.setObjectName("primary")
        self.pull_btn.clicked.connect(self.pull_model)
        self.pull_btn.hide()
        box.addWidget(self.pull_btn)
        self.refresh_btn = QPushButton("새로고침")
        self.refresh_btn.clicked.connect(self.refresh_models)
        box.addWidget(self.refresh_btn)
        self.installed: list[str] = []
        ollama_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        key_row = QWidget()
        box = QHBoxLayout(key_row)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("AIza…")
        self.api_key.editingFinished.connect(lambda: self.commit(gemini_api_key=self.api_key.text().strip()))
        box.addWidget(self.api_key, 1)
        self.show_key = QPushButton("보기")
        self.show_key.setObjectName("ghost")
        self.show_key.setCheckable(True)
        self.show_key.toggled.connect(self._toggle_key)
        box.addWidget(self.show_key)
        key_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.gemini_model = QComboBox()
        self.gemini_model.setEditable(True)   # 목록에 없는 새 모델 이름도 직접 넣을 수 있게
        for model_id, desc in engine.GEMINI_MODELS.items():
            self.gemini_model.addItem(f"{model_id}  ·  {desc}", model_id)
        self.gemini_model.setMinimumWidth(320)
        self.gemini_model.activated.connect(self._commit_gemini_model)
        self.gemini_model.lineEdit().editingFinished.connect(self._commit_gemini_model)

        test_row = QWidget()
        box = QHBoxLayout(test_row)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)
        self.test_btn = QPushButton("테스트")
        self.test_btn.clicked.connect(self.run_test)
        box.addWidget(self.test_btn)
        self.test_result = QLabel("지금 설정으로 짧은 문장을 번역해 봐요")
        self.test_result.setObjectName("testResult")
        self.test_result.setWordWrap(True)
        box.addWidget(self.test_result, 1)
        test_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._row("엔진", self.use_ollama)
        self._row("", self.use_gemini)
        self._row("Ollama 모델", ollama_row,
                  "E4B 가 더 정확하고, E2B 가 더 빨라요. "
                  "안 받은 모델은 '받기'를 누르세요")
        self._row("Gemini API 키", key_row,
                  '<a href="https://aistudio.google.com/apikey" style="color:#dc2626">aistudio.google.com/apikey</a>'
                  " 에서 무료로 받을 수 있어요. 이 PC 의 config.json 에만 저장돼요")
        self._row("Gemini 모델", self.gemini_model,
                  "실시간 번역에는 3.8 Flash 나 Flash-Lite 가 알맞아요. 4 Argon 은 가장 똑똑하지만 느리고 비싸요")
        self._row("확인", test_row)

        self._test_signal = _TestSignal(self)
        self._test_signal.done.connect(self._test_done)
        self._pull_signal = _PullSignal(self)
        self._pull_signal.progress.connect(self._pull_progress)
        self._pull_signal.done.connect(self._pull_done)
        self.ollama_model.currentTextChanged.connect(lambda _: self._sync_pull_btn())
        self.refresh_models()

    def _fill(self, cfg: dict) -> None:
        (self.use_gemini if cfg["engine"] == "gemini" else self.use_ollama).setChecked(True)
        _select_id(self.ollama_model, cfg["ollama_model"])
        self.api_key.setText(cfg["gemini_api_key"])
        _select_id(self.gemini_model, cfg["gemini_model"])

    def _refresh(self) -> None:
        ollama = self.use_ollama.isChecked()
        for w in (self.ollama_model, self.refresh_btn, self.pull_btn):
            w.setEnabled(ollama)
        for w in (self.api_key, self.show_key, self.gemini_model):
            w.setEnabled(not ollama)

    def _on_engine(self, _btn, checked: bool) -> None:
        if checked:
            self.commit(engine="gemini" if self.use_gemini.isChecked() else "ollama")

    def ollama_model_id(self) -> str:
        return _combo_id(self.ollama_model)

    def _commit_ollama(self, *_) -> None:
        name = self.ollama_model_id()
        if name:
            self.commit(ollama_model=name)
        self._sync_pull_btn()

    def gemini_model_id(self) -> str:
        return _combo_id(self.gemini_model)

    def _commit_gemini_model(self, *_) -> None:
        name = self.gemini_model_id()
        if name:
            self.commit(gemini_model=name)

    def _toggle_key(self, on: bool) -> None:
        self.api_key.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password)
        self.show_key.setText("숨기기" if on else "보기")

    def refresh_models(self) -> None:
        """받은 모델 + 추천 모델을 목록에. 추천인데 안 받은 건 '받기 필요' 표시."""
        current = self.ollama_model_id() or self.model.value["ollama_model"]
        self.installed = engine.list_ollama_models()
        names = list(engine.OLLAMA_MODELS) + [m for m in self.installed if m not in engine.OLLAMA_MODELS]
        was_loading, self._loading = self._loading, True
        self.ollama_model.clear()
        for name in names:
            parts = [name]
            if name in engine.OLLAMA_MODELS:
                parts.append(engine.OLLAMA_MODELS[name])
            if name not in self.installed:
                parts.append("받기 필요")
            self.ollama_model.addItem("  ·  ".join(parts), name)
        _select_id(self.ollama_model, current)
        self._loading = was_loading
        self._sync_pull_btn()
        if not self.installed:
            self._set_test("error", "Ollama 에 연결할 수 없거나 받은 모델이 없어요")

    def _sync_pull_btn(self) -> None:
        name = self.ollama_model_id()
        self.pull_btn.setVisible(bool(name) and name not in self.installed)

    def pull_model(self) -> None:
        name = self.ollama_model_id()
        if not name:
            return
        self.pull_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self._set_test("", f"{name} 받는 중…")
        signal = self._pull_signal

        def work():
            try:
                engine.pull_ollama(name, lambda pct, status: signal.progress.emit(-1.0 if pct is None else pct, status))
                signal.done.emit(True, name)
            except Exception as e:
                signal.done.emit(False, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _pull_progress(self, pct: float, status: str) -> None:
        name = self.ollama_model_id()
        self._set_test("", f"{name} 받는 중… {pct:.0f}%" if pct >= 0 else f"{name} · {status}")

    def _pull_done(self, ok: bool, text: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.pull_btn.setEnabled(True)
        if ok:
            self.refresh_models()
            self._commit_ollama()
            self._set_test("ok", f"✓ {text} 받았어요. 테스트로 확인해 보세요")
        else:
            self._set_test("error", text)

    def _set_test(self, state: str, text: str) -> None:
        self.test_result.setProperty("state", state)
        self.test_result.setText(text)
        self.test_result.style().unpolish(self.test_result)
        self.test_result.style().polish(self.test_result)

    def run_test(self) -> None:
        # 칸에 쓰다 만 값도 먼저 저장
        self.commit(gemini_api_key=self.api_key.text().strip())
        self._commit_ollama()
        self._commit_gemini_model()
        cfg = dict(self.model.value)
        if cfg["engine"] == "ollama" and self.installed and cfg["ollama_model"] not in self.installed:
            self._set_test("error", f"{cfg['ollama_model']} 은(는) 아직 안 받았어요. '받기'를 누르세요")
            return
        self.test_btn.setEnabled(False)
        self._set_test("", f"{engine.engine_summary(cfg)} 로 번역해 보는 중…")
        signal = self._test_signal

        def work():
            try:
                out = engine.translate("Hello! The translation engine is working correctly.", cfg)
                signal.done.emit(True, out)
            except Exception as e:
                signal.done.emit(False, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _test_done(self, ok: bool, text: str) -> None:
        self.test_btn.setEnabled(True)
        self._set_test("ok" if ok else "error", f"✓ {text}" if ok else text)


class SubtitlePage(SettingsPage):
    title = "자막"
    description = ("번역 화면의 '자막 모드'를 켜면 화면 아래에 하프라이프 자막처럼 말이 한 줄씩 쌓여요. "
                   "자막은 끌어서 옮길 수 있어요.")

    def _build(self) -> None:
        self.enabled = QCheckBox("자막 켜기")
        self.enabled.toggled.connect(lambda on: self.commit(subtitle_enabled=on))
        self.font_size = QSpinBox()
        self.font_size.setRange(16, 72)
        self.font_size.setSingleStep(2)
        self.font_size.setSuffix(" px")
        self.font_size.setFixedWidth(110)
        self.font_size.valueChanged.connect(lambda v: self.commit(subtitle_size=v))
        self.original = QCheckBox("원문도 번역 위에 작게 보기")
        self.original.toggled.connect(lambda on: self.commit(subtitle_original=on))
        self.opacity = QSpinBox()
        self.opacity.setRange(0, 100)
        self.opacity.setSingleStep(5)
        self.opacity.setSuffix(" %")
        self.opacity.setFixedWidth(110)
        self.opacity.valueChanged.connect(lambda v: self.commit(subtitle_opacity=v))
        self.hide_sec = QSpinBox()
        self.hide_sec.setRange(0, 60)
        self.hide_sec.setSuffix(" 초")
        self.hide_sec.setSpecialValueText("계속 보이기")
        self.hide_sec.setFixedWidth(130)
        self.hide_sec.valueChanged.connect(lambda v: self.commit(subtitle_hide_sec=v))
        self.max_lines = QSpinBox()
        self.max_lines.setRange(1, 8)
        self.max_lines.setSuffix(" 개")
        self.max_lines.setFixedWidth(110)
        self.max_lines.valueChanged.connect(lambda v: self.commit(subtitle_max_lines=v))
        self.reset_btn = QPushButton("화면 아래 가운데로")
        self.reset_btn.clicked.connect(lambda: self.commit(subtitle_pos=None))

        self._row("자막", self.enabled, "번역 화면의 '자막 모드' 버튼과 같아요. 켜 두면 다음에 앱을 열 때도 켜져 있어요")
        self._row("글자 크기", self.font_size, "자막 위에서 오른쪽 클릭해도 바꿀 수 있어요")
        self._row("", self.original)
        self._row("배경 진하기", self.opacity, "0 % 면 배경 없이 글자만 (그림자는 남아요)")
        self._row("사라지는 시간", self.hide_sec, "번역이 나온 뒤 이만큼 지나면 스르륵 사라지고 상자가 줄어들어요. 번역을 기다리는 동안은 남아 있고, 긴 문장은 조금 더 오래 보여요")
        self._row("쌓이는 말 수", self.max_lines, "이보다 많아지면 가장 오래된 말부터 사라져요. 1 개면 한 줄씩 바뀌어요")
        self._row("위치", self.reset_btn, "자막을 끌어서 옮기면 그 자리를 기억해요")

    def _fill(self, cfg: dict) -> None:
        self.enabled.setChecked(bool(cfg["subtitle_enabled"]))
        self.font_size.setValue(int(cfg["subtitle_size"]))
        self.original.setChecked(bool(cfg["subtitle_original"]))
        self.opacity.setValue(int(cfg["subtitle_opacity"]))
        self.hide_sec.setValue(int(cfg["subtitle_hide_sec"]))
        self.max_lines.setValue(int(cfg["subtitle_max_lines"]))


GLOSSARY_EXAMPLE = "한 줄에 하나씩: 원어 = 번역어\n('= 번역어'를 빼면 원어 그대로 둬요)"

BACKGROUND_EXAMPLE = "어떤 방송·영상인지, 누가 어떤 말투로 이야기하는지 자유롭게 적어 주세요"


class ContextPage(SettingsPage):
    title = "배경 정보"
    description = ("방송·캐릭터·세계관을 미리 알려 주면 번역이 맥락에 맞고 이름이 정확해져요. "
                   "용어집의 이름은 음성 인식에도 힌트로 들어가요.")
    label_width = 110

    def _build(self) -> None:
        self.glossary = QPlainTextEdit()
        self.glossary.setPlaceholderText(GLOSSARY_EXAMPLE)
        self.glossary.setFixedHeight(150)
        self.background = QPlainTextEdit()
        self.background.setPlaceholderText(BACKGROUND_EXAMPLE)
        self.background.setFixedHeight(150)
        for edit in (self.glossary, self.background):
            edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # 글자 칸은 칠 때마다 저장하지 않고, 손을 멈추면 저장
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(700)
        self._save_timer.timeout.connect(self.save_now)
        self.glossary.textChanged.connect(self._typed)
        self.background.textChanged.connect(self._typed)
        self.count = QLabel()
        self.count.setObjectName("hint")

        self._row("이름 · 용어", self.glossary,
                  "캐릭터·사람 이름, 고유명사, 자주 나오는 말. 음성 인식이 조금 다르게 받아적어도 이 번역어로 맞춰요")
        self._row("배경 설명", self.background,
                  "누가 어떤 말투로 무슨 이야기를 하는지. 번역에만 쓰이고 자막에 나오지는 않아요")
        self._row("", self.count)

    def _typed(self) -> None:
        if not self._loading:
            self._save_timer.start()
        self._update_count()

    def _update_count(self) -> None:
        n = len(engine.parse_glossary(self.glossary.toPlainText()))
        self.count.setText(f"용어 {n}개" + (" · 음성 인식 힌트가 길어 앞부분만 써요" if
                                          len(engine.asr_hint({"glossary": self.glossary.toPlainText()}))
                                          >= engine.MAX_HINT_CHARS else ""))

    def save_now(self) -> None:
        self._save_timer.stop()
        self.commit(glossary=self.glossary.toPlainText(), background=self.background.toPlainText())

    def _fill(self, cfg: dict) -> None:
        if self.glossary.toPlainText() != cfg["glossary"]:
            self.glossary.setPlainText(cfg["glossary"])
        if self.background.toPlainText() != cfg["background"]:
            self.background.setPlainText(cfg["background"])
        self._update_count()

    def hideEvent(self, e) -> None:
        if self._save_timer.isActive():   # 다른 화면으로 가면 바로 저장
            self.save_now()
        super().hideEvent(e)


class _UpdateSignal(QObject):
    checked = Signal(object, str)       # (Release 또는 None, 오류 문구)
    progress = Signal(float)
    installed = Signal(bool, bool, str)  # (성공, 패키지 바뀜, 오류 문구)


class UpdatePage(SettingsPage):
    title = "업데이트"
    description = "GitHub 에 올라온 새 버전을 받아 설치해요. 설정(config.json)은 그대로 남아요."

    available = Signal(object)          # 새 버전을 찾음 (Release)
    restart_requested = Signal()

    def _build(self) -> None:
        self.release: updater.Release | None = None
        self._busy = False
        self._silent = False
        self.version = QLabel(__version__)
        self.check_btn = QPushButton("업데이트 확인")
        self.check_btn.clicked.connect(lambda: self.check())
        self.status = QLabel("")
        self.status.setObjectName("testResult")
        self.status.setWordWrap(True)
        check_row = QWidget()
        r = QHBoxLayout(check_row)
        r.setContentsMargins(0, 0, 0, 0)
        r.setSpacing(10)
        r.addWidget(self.check_btn)
        r.addWidget(self.status, 1)
        check_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.notes = QLabel()
        self.notes.setObjectName("hint")
        self.notes.setWordWrap(True)
        self.notes.setOpenExternalLinks(True)
        self.install_btn = QPushButton("지금 업데이트")
        self.install_btn.setObjectName("primary")
        self.install_btn.clicked.connect(self._install_or_restart)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.hide()
        self.new_box = QWidget()
        col = QVBoxLayout(self.new_box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)
        col.addWidget(self.notes)
        col.addWidget(self.bar)
        col.addWidget(self.install_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.new_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.auto = QCheckBox("앱을 켤 때 새 버전이 있는지 확인")
        self.auto.toggled.connect(lambda on: self.commit(update_auto_check=on))

        self._row("지금 버전", self.version)
        self._row("확인", check_row)
        self._new_label = QLabel("새 버전")
        self._row(self._new_label, self.new_box)
        self._row("", self.auto, "확인만 하고, 설치는 '지금 업데이트'를 눌러야 해요")
        self._show_new(False)

        self._signal = _UpdateSignal(self)
        self._signal.checked.connect(self._checked)
        self._signal.progress.connect(self._progress)
        self._signal.installed.connect(self._installed)

    def _fill(self, cfg: dict) -> None:
        self.auto.setChecked(bool(cfg["update_auto_check"]))

    def _show_new(self, on: bool) -> None:
        self._new_label.setVisible(on)
        self.new_box.setVisible(on)

    def _set_status(self, state: str, text: str) -> None:
        self.status.setProperty("state", state)
        self.status.setText(text)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    # ---------- 확인 ----------
    def check(self, silent: bool = False) -> None:
        """silent: 앱을 켤 때 하는 자동 확인. 실패하거나 최신이면 아무것도 안 보여 준다."""
        if self._busy:
            return
        self._busy = True
        self._silent = silent
        self.check_btn.setEnabled(False)
        if not silent:
            self._set_status("", "확인하는 중…")
        signal = self._signal

        def work():
            try:
                signal.checked.emit(updater.latest_release(), "")
            except updater.UpdateError as e:
                signal.checked.emit(None, str(e))
            except Exception as e:      # 예상 못 한 응답 등
                signal.checked.emit(None, f"확인하지 못했어요 ({e.__class__.__name__})")
        threading.Thread(target=work, daemon=True).start()

    def _checked(self, release, error: str) -> None:
        self._busy = False
        self.check_btn.setEnabled(True)
        if release is None:
            if not self._silent:
                self._set_status("error", error)
            return
        if not updater.is_newer(release.version):
            if not self._silent:
                self._set_status("ok", f"✓ 최신 버전이에요 ({__version__})")
            return
        self.release = release
        self._set_status("ok", f"새 버전 {release.version} 이 있어요")
        notes = release.notes[:600] + ("…" if len(release.notes) > 600 else "")
        notes = notes.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")
        link = f' · <a href="{release.page}" style="color:#dc2626">릴리스 보기</a>' if release.page else ""
        self.notes.setText(f"<b>{release.tag}</b>{link}" + (f"<br>{notes}" if notes else ""))
        self.install_btn.setText("지금 업데이트")
        self.install_btn.setProperty("restart", False)
        self.install_btn.setEnabled(True)
        self._show_new(True)
        self.available.emit(release)

    # ---------- 설치 ----------
    def _install_or_restart(self) -> None:
        if self.install_btn.property("restart"):
            self.restart_requested.emit()
            return
        if self.release is None or self._busy:
            return
        self._busy = True
        self.install_btn.setEnabled(False)
        self.check_btn.setEnabled(False)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.show()
        self._set_status("", f"{self.release.version} 받는 중…")
        signal, release = self._signal, self.release

        def work():
            try:
                req = updater.update_to(release, signal.progress.emit)
                signal.installed.emit(True, req, "")
            except updater.UpdateError as e:
                signal.installed.emit(False, False, str(e))
            except Exception as e:
                signal.installed.emit(False, False, f"설치하지 못했어요 ({e.__class__.__name__})")
        threading.Thread(target=work, daemon=True).start()

    def _progress(self, pct: float) -> None:
        if pct < 0:
            self.bar.setRange(0, 0)     # 크기를 모르면 오가는 막대
        else:
            self.bar.setRange(0, 100)
            self.bar.setValue(round(pct))

    def _installed(self, ok: bool, req_changed: bool, error: str) -> None:
        self._busy = False
        self.bar.hide()
        self.check_btn.setEnabled(True)
        self.install_btn.setEnabled(True)
        if not ok:
            self._set_status("error", error)
            return
        text = f"✓ {self.release.version} 을 설치했어요. 다시 시작하면 적용돼요"
        if req_changed:
            text += ". 필요한 패키지가 바뀌어서 다시 켤 때 조금 더 걸려요"
        self._set_status("ok", text)
        self.install_btn.setText("다시 시작")
        self.install_btn.setProperty("restart", True)


PAGES: dict[str, type[SettingsPage]] = {"speech": SpeechPage, "engine": EnginePage, "context": ContextPage,
                                        "subtitle": SubtitlePage, "update": UpdatePage}
