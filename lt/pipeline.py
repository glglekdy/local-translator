"""듣기 → 알아듣기 → 번역을 뒤에서 돌리는 스레드. 화면에는 신호로만 알린다.

- 오디오 읽기: 별도 파이썬 스레드 (0.1초 블록 → Chunker → 큐)
- 음성 인식: 이 QThread
- 번역: 일꾼 1개짜리 스레드 풀. 번역이 끝나길 기다리지 않고 다음 문장을 알아듣는다. 순서는 지켜진다.
"""

from __future__ import annotations

import contextlib
import itertools
import queue
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PySide6.QtCore import QThread, Signal

from . import engine

# 파이프라인을 다시 시작해도 카드 번호가 겹치지 않게 모듈 전체에서 센다
_ids = itertools.count(1)
HISTORY_TURNS = 3   # 번역할 때 같이 넘기는 앞 문장 수


class Pipeline(QThread):
    status = Signal(str, str)        # state(loading/listening/error), 문구
    heard = Signal(int, str, str)    # id, 언어 코드, 원문
    translated = Signal(int, str)    # id, 번역
    failed = Signal(int, str)        # id, 오류 문구

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = dict(cfg)
        self._stop = threading.Event()
        self._audio: queue.Queue[np.ndarray] = queue.Queue()
        # 번역 스레드(일꾼 1개라 차례대로 돈다)에서만 읽고 쓴다: 앞 문장들의 (원문, 번역)
        self._history: engine.History = []
        self._history_target = self.cfg["target"]

    # 메인 스레드에서 부른다. dict 참조 바꾸기는 원자적이라 잠금이 필요 없다
    def set_cfg(self, cfg: dict) -> None:
        self.cfg = dict(cfg)

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        cfg = self.cfg
        try:
            name = engine.ASR_MODELS[cfg["asr_model"]][0]
            self.status.emit("loading", f"{name} 준비 중… (처음이면 내려받느라 몇 분 걸려요)")
            model = engine.load_asr(
                cfg["asr_model"],
                lambda: self.status.emit("loading", "GPU 를 쓸 수 없어 CPU 로 준비 중… (느릴 수 있어요)"))
            if self._stop.is_set():
                return
            if cfg["engine"] == "ollama":
                self.status.emit("loading", f"번역 모델({cfg['ollama_model']}) 준비 중…")
                try:
                    engine.warmup_ollama(cfg["ollama_model"])
                except Exception:
                    pass  # 번역할 때 알기 쉬운 오류로 다시 알려 준다
        except Exception as e:
            self.status.emit("error", f"준비하다 멈췄어요: {e}")
            return
        if self._stop.is_set():
            return

        capture = threading.Thread(target=self._capture, args=(cfg,), daemon=True)
        capture.start()
        self.status.emit("listening", "듣는 중")
        language = engine.SOURCE_LANGUAGES.get(cfg["source_language"])
        with ThreadPoolExecutor(max_workers=1) as pool:
            while not self._stop.is_set():
                try:
                    audio = self._audio.get(timeout=0.2)
                except queue.Empty:
                    continue
                try:
                    text, lang = engine.transcribe(model, audio, language, engine.asr_hint(self.cfg))
                except Exception as e:
                    self.status.emit("error", f"음성 인식 오류: {e}")
                    continue
                if not text:
                    continue
                uid = next(_ids)
                self.heard.emit(uid, lang, text)
                pool.submit(self._translate, uid, text)
        capture.join(timeout=1)

    def _translate(self, uid: int, text: str) -> None:
        cfg = self.cfg
        if cfg["target"] != self._history_target:
            # 번역 언어를 바꿨으면 예전 언어로 된 기록은 버린다 (안 그러면 예전 언어로 답하기도 함)
            self._history, self._history_target = [], cfg["target"]
        try:
            out = engine.translate(text, cfg, self._history[-HISTORY_TURNS:])
        except Exception as e:
            self.failed.emit(uid, str(e))
            return
        self._history.append((text, out))
        del self._history[:-HISTORY_TURNS]
        self.translated.emit(uid, out)

    def _capture(self, cfg: dict) -> None:
        chunker = engine.Chunker(engine.SENSITIVITY.get(cfg["sensitivity"], 0.01), float(cfg["pause_sec"]))
        block = int(engine.SAMPLE_RATE * engine.BLOCK_SEC)
        keep_alive = engine.SilencePlayer() if cfg["source"] == "system" else contextlib.nullcontext()
        try:
            with keep_alive, engine.open_recorder(cfg["source"]) as rec:
                while not self._stop.is_set():
                    data = rec.record(numframes=block).reshape(-1).astype(np.float32)
                    chunk = chunker.feed(data)
                    if chunk is not None:
                        self._audio.put(chunk)
        except Exception as e:
            self.status.emit("error", f"소리를 가져올 수 없어요: {e}")
            self._stop.set()
