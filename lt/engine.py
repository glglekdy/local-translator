"""번역기 핵심. Qt 를 쓰지 않는다 — 설정, 오디오 덩어리 나누기, 음성 인식, 번역.

흐름: 오디오(시스템 소리·마이크) → Chunker 가 말 멈춤 기준으로 문장 덩어리를 만듦
     → 음성 인식(로컬: Qwen3-ASR 또는 faster-whisper) 이 글자로 → Ollama(로컬 LLM) 또는 Gemini API 가 번역.
"""

from __future__ import annotations

import glob
import json
import os
import re
import warnings
from pathlib import Path

import numpy as np
import requests

SAMPLE_RATE = 16000
BLOCK_SEC = 0.1             # 오디오 읽기 단위
MAX_SEGMENT_SEC = 10.0      # 말이 안 멈춰도 이만큼이면 끊는다
MIN_SEGMENT_SEC = 0.5       # 이보다 짧은 소리는 잡음으로 보고 버린다

# localhost 로 쓰면 Windows 가 IPv6(::1) 부터 시도했다가 2초 뒤에 IPv4 로 넘어가서
# 번역 한 번마다 2초씩 늦어졌다 (Ollama 는 127.0.0.1 에서만 듣는다)
OLLAMA_BASE = os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

TARGET_LANGUAGES = ["한국어", "English", "日本語", "中文", "Español", "Français", "Deutsch"]
# 화면 이름 → whisper 언어 코드 (None = 자동 감지)
SOURCE_LANGUAGES = {"자동 감지": None, "영어": "en", "일본어": "ja", "중국어": "zh", "한국어": "ko",
                    "스페인어": "es", "프랑스어": "fr", "독일어": "de"}
# 음성 인식 모델 → (화면 이름, 설명). Qwen3-ASR 는 노래·반주·잡음에 강하다
ASR_MODELS = {
    "qwen3-asr-1.7b": ("Qwen3-ASR 1.7B", "노래·잡음에 강함 (추천, 한 마디 약 1초)"),
    "qwen3-asr-0.6b": ("Qwen3-ASR 0.6B", "가벼움"),
    "large-v3-turbo": ("Whisper large-v3-turbo", "가장 빠름, 말소리 위주 (약 0.4초)"),
    "medium": ("Whisper medium", "말소리 위주, 가벼움"),
}
QWEN_REPOS = {"qwen3-asr-1.7b": "Qwen/Qwen3-ASR-1.7B", "qwen3-asr-0.6b": "Qwen/Qwen3-ASR-0.6B"}
# whisper 언어 코드 ↔ Qwen3-ASR 언어 이름
QWEN_LANGS = {"en": "English", "ja": "Japanese", "zh": "Chinese", "ko": "Korean",
              "es": "Spanish", "fr": "French", "de": "German"}
SENSITIVITY = {"높음": 0.005, "보통": 0.01, "낮음": 0.02}   # 이 RMS 보다 작으면 무음
# Gemini API 모델 (2026-11 공식 목록 기준). 2.5 계열은 예전에 쓰던 계정만 쓸 수 있다
GEMINI_MODELS = {
    "gemini-3.8-flash": "3.8 Flash · 균형 (추천)",
    "gemini-3.5-flash-lite": "3.5 Flash-Lite · 가장 빠르고 저렴",
    "gemini-3.6-flash": "3.6 Flash",
    "gemini-4-argon": "4 Argon · 최고 성능, 느리고 비쌈",
}
# 실시간 번역이라 생각(추론)은 그 모델이 허용하는 가장 낮은 단계로
GEMINI_THINKING = {
    "gemini-4-argon": "low", "gemini-3.8-flash": "low", "gemini-3.1-pro-preview": "low",
    "gemini-3.6-flash": "minimal", "gemini-3.5-flash-lite": "minimal", "gemini-3-flash-preview": "minimal",
}
# 종료됐거나 새 계정은 못 쓰는 모델 → 기본값으로 바꿔 준다
_GEMINI_RETIRED = {"gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-3-pro-preview",
                   "gemini-3.1-flash-lite-preview", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"}
ENGINE_LABELS = {"ollama": "Ollama", "gemini": "Gemini API"}
# 추천 Ollama 번역 모델 (설치 안 돼 있어도 목록에 보여 주고 앱에서 받을 수 있게)
OLLAMA_MODELS = {
    "gemma4:e4b-it-qat": "Gemma 4 E4B QAT · 정확도 우선 (추천, 6.1GB)",
    "gemma4:e2b-it-qat": "Gemma 4 E2B QAT · 속도 우선 (4.3GB)",
}
# 지운 모델 → 기본값으로 (이 PC 에서 지웠거나 품질이 나빠 뺀 것)
_OLLAMA_RETIRED = {"gemma3:12b", "qwen2.5:7b"}

DEFAULT_CONFIG = {
    "engine": "ollama",
    "ollama_model": "gemma4:e4b-it-qat",
    "gemini_model": "gemini-3.8-flash",
    "gemini_api_key": "",
    "asr_model": "qwen3-asr-1.7b",
    "source_language": "자동 감지",
    "sensitivity": "보통",
    "pause_sec": 0.6,
    "source": "system",       # system = 시스템 소리, mic = 마이크
    "target": "한국어",
    "update_auto_check": True,    # 앱을 켤 때 새 버전 확인 (설치는 사용자가 눌러야)
    # 자막 모드
    "subtitle_enabled": False,    # 자막 켜 두기. 켜 두면 다음에 앱을 열 때도 켜진다
    "subtitle_size": 30,         # 번역 글자 크기(px). 원문은 이것의 55%
    "subtitle_original": True,    # 원문도 같이 보기
    "subtitle_opacity": 65,       # 배경 진하기 %
    "subtitle_hide_sec": 8,       # 말이 없으면 몇 초 뒤 사라질지 (0 = 계속 보이기)
    "subtitle_max_lines": 4,      # 한 번에 쌓이는 말 수. 넘치면 오래된 말부터 사라진다
    "subtitle_pos": None,         # [가운데 x, 아래 y]. None = 화면 아래 가운데
    # 배경 정보: 번역 프롬프트와 음성 인식 힌트에 들어간다
    "glossary": "",               # 한 줄에 하나: '원어 = 번역어'
    "background": "",             # 방송·캐릭터·세계관 설명
}

# 예전(tkinter 판) config.json 값 → 지금 값
_LEGACY = {
    "engine": {"Ollama (로컬)": "ollama", "Gemini API": "gemini"},
    "source": {"시스템 소리": "system", "마이크": "mic"},
}


# ---------------- 설정 ----------------
def load_config(path: Path | None = None) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        saved = json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))
        cfg.update({k: v for k, v in saved.items() if k in DEFAULT_CONFIG})
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    for key, table in _LEGACY.items():
        cfg[key] = table.get(cfg[key], cfg[key])
    if cfg["asr_model"] not in ASR_MODELS:
        cfg["asr_model"] = DEFAULT_CONFIG["asr_model"]
    if cfg["ollama_model"] in _OLLAMA_RETIRED:
        cfg["ollama_model"] = DEFAULT_CONFIG["ollama_model"]
    if cfg["gemini_model"] in _GEMINI_RETIRED:
        cfg["gemini_model"] = DEFAULT_CONFIG["gemini_model"]
    return cfg


def save_config(cfg: dict, path: Path | None = None) -> None:
    Path(path or CONFIG_PATH).write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def engine_summary(cfg: dict) -> str:
    model = cfg["gemini_model"] if cfg["engine"] == "gemini" else cfg["ollama_model"]
    return f"{ENGINE_LABELS[cfg['engine']]} · {model}"


# ---------------- 오디오 ----------------
class Chunker:
    """0.1초 블록을 받아, 말이 pause_sec 만큼 멈추면 그때까지를 한 덩어리로 돌려준다.

    말이 안 멈추고 max_sec 를 넘기면, 끝쪽 1/3 에서 가장 조용한 블록에서 자르고
    나머지는 다음 덩어리로 넘긴다 — 단어 한가운데를 자르면 오역이 나기 때문.
    """

    def __init__(self, threshold: float, pause_sec: float, max_sec: float = MAX_SEGMENT_SEC,
                 min_sec: float = MIN_SEGMENT_SEC, block_sec: float = BLOCK_SEC):
        self.threshold, self.pause_sec = threshold, pause_sec
        self.max_sec, self.min_sec, self.block_sec = max_sec, min_sec, block_sec
        self.buf: list[np.ndarray] = []
        self.levels: list[float] = []
        self.silent = 0.0

    def feed(self, block: np.ndarray) -> np.ndarray | None:
        level = float(np.sqrt(np.mean(block ** 2)))
        loud = level > self.threshold
        if loud or self.buf:
            self.buf.append(block)
            self.levels.append(level)
        self.silent = 0.0 if loud else self.silent + self.block_sec
        dur = len(self.buf) * self.block_sec
        if self.buf and self.silent >= self.pause_sec:
            out = np.concatenate(self.buf) if dur - self.silent >= self.min_sec else None
            self.buf, self.levels, self.silent = [], [], 0.0
            return out
        if dur >= self.max_sec:
            start = len(self.levels) * 2 // 3
            quietest = start + int(np.argmin(self.levels[start:]))
            cut = quietest + 1
            out = np.concatenate(self.buf[:cut])
            self.buf, self.levels = self.buf[cut:], self.levels[cut:]
            return out
        return None


class SilencePlayer:
    """스피커로 무음을 계속 튼다.

    Windows 루프백은 아무 소리도 안 날 때 데이터를 아예 보내지 않아서, 영상을 멈추면
    '말이 멈췄다'를 알 수 없어 마지막 문장이 번역되지 않고 남는다. 무음을 틀어 두면 계속 흘러온다.
    """

    def __init__(self):
        import threading
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=1)

    def _run(self) -> None:
        import soundcard as sc
        try:
            with sc.default_speaker().player(samplerate=48000, channels=1) as p:
                zeros = np.zeros(4800, np.float32)
                while not self._stop.is_set():
                    p.play(zeros)
        except Exception:
            pass  # 없어도 동작은 한다 (멈춤 감지만 늦어질 뿐)


def open_recorder(source: str):
    """source: system(스피커로 나가는 소리) 또는 mic."""
    import soundcard as sc
    # 시스템 소리가 없을 때 루프백 장치가 내는 무해한 경고
    warnings.filterwarnings("ignore", message="data discontinuity")
    if source == "system":
        dev = sc.get_microphone(sc.default_speaker().name, include_loopback=True)
    else:
        dev = sc.default_microphone()
    return dev.recorder(samplerate=SAMPLE_RATE, channels=1)


# ---------------- 음성 인식 ----------------
def _add_cuda_dll_paths() -> None:
    """pip 로 설치한 nvidia-cublas/cudnn DLL 을 찾을 수 있게 한다 (Windows)."""
    try:
        import nvidia
    except ImportError:
        return
    for base in nvidia.__path__:
        for d in glob.glob(os.path.join(base, "*", "bin")):
            os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(d)


_add_cuda_dll_paths()


class WhisperASR:
    def __init__(self, name: str, on_cpu_fallback=lambda: None):
        from faster_whisper import WhisperModel
        try:
            self.model = WhisperModel(name, device="cuda", compute_type="int8_float16")  # fp16 과 정확도 같고 10% 빠름
            # 불러오기는 돼도 추론할 때 DLL 오류가 날 수 있어 한 번 돌려 본다
            self.transcribe(np.zeros(SAMPLE_RATE, np.float32), "en")
        except Exception:
            on_cpu_fallback()
            self.model = WhisperModel(name, device="cpu", compute_type="int8")

    def transcribe(self, audio: np.ndarray, language: str | None = None, hint: str = "") -> tuple[str, str]:
        segs, info = self.model.transcribe(audio, beam_size=5, vad_filter=True, language=language,
                                           hotwords=hint or None)
        return " ".join(s.text.strip() for s in segs).strip(), info.language


def qwen_lang_code(name: str | None) -> str:
    """Qwen3-ASR 가 돌려주는 'Korean' 같은 이름 → 'ko'."""
    if not name:
        return "?"
    for code, full in QWEN_LANGS.items():
        if full.lower() == name.lower():
            return code
    return name[:2].lower()


class QwenASR:
    def __init__(self, name: str, on_cpu_fallback=lambda: None):
        import torch
        import transformers
        from qwen_asr import Qwen3ASRModel
        transformers.logging.set_verbosity_error()
        cuda = torch.cuda.is_available()
        if not cuda:
            on_cpu_fallback()
        self.model = Qwen3ASRModel.from_pretrained(
            QWEN_REPOS[name], dtype=torch.bfloat16 if cuda else torch.float32,
            device_map="cuda:0" if cuda else "cpu", max_new_tokens=256)

    def transcribe(self, audio: np.ndarray, language: str | None = None, hint: str = "") -> tuple[str, str]:
        r = self.model.transcribe(audio=(audio, SAMPLE_RATE), context=hint,
                                  language=QWEN_LANGS.get(language) if language else None)[0]
        return r.text.strip(), qwen_lang_code(r.language)


_asr_cache: dict[str, object] = {}


def load_asr(name: str, on_cpu_fallback=lambda: None):
    """음성 인식 모델을 불러온다 (처음 고른 모델은 내려받음). 같은 모델은 다시 쓰기.

    메모리를 아끼려고 다른 모델은 내려놓는다.
    """
    if name not in _asr_cache:
        if _asr_cache:
            _asr_cache.clear()
            import gc
            gc.collect()
            try:
                import torch
                torch.cuda.empty_cache()
            except ImportError:
                pass
        cls = QwenASR if name in QWEN_REPOS else WhisperASR
        _asr_cache[name] = cls(name, on_cpu_fallback)
    return _asr_cache[name]


def transcribe(model, audio: np.ndarray, language: str | None = None, hint: str = "") -> tuple[str, str]:
    return model.transcribe(audio, language, hint)


# ---------------- 배경 정보 (용어집 · 배경 설명) ----------------
MAX_HINT_CHARS = 300      # 음성 인식 힌트가 너무 길면 오히려 엉뚱한 글자를 만들어 낸다


def parse_glossary(text: str) -> list[tuple[str, str]]:
    """'アリス = 앨리스' 처럼 한 줄에 하나. '=' 가 없으면 번역어 없이 (원어 그대로 두라는 뜻).
    '#' 으로 시작하는 줄과 빈 줄은 무시. '→', '->', ':' 도 '=' 처럼 받아 준다."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for sep in ("=", "→", "->", ":"):
            if sep in line:
                src, dst = line.split(sep, 1)
                break
        else:
            src, dst = line, ""
        if src.strip():
            out.append((src.strip(), dst.strip()))
    return out


def asr_hint(cfg: dict) -> str:
    """음성 인식에 주는 힌트: 용어집의 원어(이름 등). 짧게."""
    terms = [src for src, _ in parse_glossary(cfg.get("glossary", ""))]
    hint = ", ".join(terms)
    return hint[:MAX_HINT_CHARS]


# ---------------- 번역 ----------------
def build_prompt(target: str, glossary: str = "", background: str = "") -> str:
    p = (
        f"You are a professional real-time interpreter. Translate the user's text into natural, fluent {target}.\n"
        "Rules:\n"
        f"- Translate EVERY word into {target}; never leave source-language words in the output "
        "(except proper nouns and brand names).\n"
        "- The text comes from speech recognition and may contain small errors; infer the intended meaning.\n"
        "- Write numbers, times and units the way a native speaker would write them "
        "(e.g. Korean: '10분', not '열 분').\n"
        "- The text may be song lyrics; keep a natural, lyrical tone when it is.\n"
        "- Output ONLY the translation. No explanations, notes, quotes, or romanization.\n"
        "- If the text is already in the target language, return it unchanged."
    )
    terms = parse_glossary(glossary)
    if terms:
        lines = [f"- {src} → {dst}" if dst else f"- {src} (keep this name as is)" for src, dst in terms]
        p += ("\n\nGlossary — whenever these names/terms appear (even if speech recognition spelled them a bit "
              "differently), translate them exactly like this:\n" + "\n".join(lines))
    if background.strip():
        p += ("\n\nBackground information about the speaker and topic (use it only to understand context, "
              "names and tone; never add it to the translation):\n" + background.strip())
    return p


# 앞 문장들은 '이미 번역을 마친 대화'(원문 → 번역)로 넘긴다.
# 시스템 문구에 "문맥이니 번역하지 마" 라고 넣으면 작은 모델이 앞 문장까지 번역해 붙이는 일이
# 20번 중 4번 있었고, 대화 기록으로 넘기면 0번이었다.
History = list[tuple[str, str]]


def list_ollama_models() -> list[str]:
    try:
        r = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=3)
        return sorted(m["name"] for m in r.json().get("models", []))
    except Exception:
        return []


def warmup_ollama(model: str) -> None:
    """모델을 미리 GPU 에 올려 첫 번역이 늦지 않게."""
    requests.post(f"{OLLAMA_BASE}/api/generate",
                  json={"model": model, "prompt": "", "keep_alive": "30m"}, timeout=180)


def pull_ollama(model: str, on_progress=lambda pct, status: None) -> None:
    """Ollama 로 모델을 내려받는다. on_progress(0~100 또는 None, 상태 문구)."""
    try:
        r = requests.post(f"{OLLAMA_BASE}/api/pull", json={"model": model, "stream": True},
                          stream=True, timeout=(5, 600))
    except requests.ConnectionError:
        raise RuntimeError("Ollama 에 연결할 수 없어요. Ollama 가 켜져 있는지 확인하세요") from None
    with r:
        for line in r.iter_lines():
            if not line:
                continue
            msg = json.loads(line)
            if "error" in msg:
                raise RuntimeError(f"받기 실패: {msg['error']}")
            total, done = msg.get("total"), msg.get("completed")
            pct = done * 100 / total if total and done is not None else None
            on_progress(pct, msg.get("status", ""))


def translate_ollama(text: str, system: str, model: str, history: History = ()) -> str:
    messages = [{"role": "system", "content": system}]
    for src, done in history:
        messages += [{"role": "user", "content": src}, {"role": "assistant", "content": done}]
    messages.append({"role": "user", "content": text})
    try:
        r = requests.post(f"{OLLAMA_BASE}/api/chat", json={
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,          # Gemma 4 처럼 생각 기능이 기본으로 켜진 모델도 바로 답하게
            "keep_alive": "30m",
            "options": {"temperature": 0.2},
        }, timeout=120)
    except requests.ConnectionError:
        raise RuntimeError("Ollama 에 연결할 수 없어요. Ollama 가 켜져 있는지 확인하세요") from None
    if r.status_code == 404:
        raise RuntimeError(f"Ollama 에 '{model}' 모델이 없어요. 'ollama pull {model}' 로 받으세요")
    r.raise_for_status()
    content = r.json()["message"]["content"].strip()
    # think=False 를 무시하는 모델이 생각을 본문에 섞어 보내는 경우 대비
    return re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()


def translate_gemini(text: str, system: str, model: str, api_key: str, history: History = ()) -> str:
    if not api_key:
        raise RuntimeError("Gemini API 키를 넣어 주세요")
    gen = {"temperature": 0.2}
    level = GEMINI_THINKING.get(model)
    if level:
        gen["thinkingConfig"] = {"thinkingLevel": level}
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [turn for src, done in history for turn in (
            {"role": "user", "parts": [{"text": src}]}, {"role": "model", "parts": [{"text": done}]})]
        + [{"role": "user", "parts": [{"text": text}]}],
        "generationConfig": gen,
    }
    url, headers = GEMINI_URL.format(model=model), {"x-goog-api-key": api_key}
    r = requests.post(url, headers=headers, json=body, timeout=60)
    if r.status_code == 400 and "thinkingConfig" in gen and "thinking" in r.text.lower():
        # 이 모델이 그 생각 단계를 안 받으면 기본값으로 다시
        del gen["thinkingConfig"]
        r = requests.post(url, headers=headers, json=body, timeout=60)
    if r.status_code != 200:
        try:
            msg = r.json()["error"]["message"]
        except Exception:
            msg = r.text[:200]
        if r.status_code == 404:
            msg = f"'{model}' 모델을 찾을 수 없어요. 모델 이름을 확인하세요 ({msg})"
        raise RuntimeError(f"Gemini 오류 {r.status_code}: {msg}")
    parts = r.json()["candidates"][0]["content"]["parts"]
    # 생각(thought) 부분은 빼고 답만
    return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()


def translate(text: str, cfg: dict, history: History | None = None) -> str:
    """history: 앞 문장들의 (원문, 번역). 같은 번역 언어로 한 것만 넘긴다."""
    system = build_prompt(cfg["target"], cfg.get("glossary", ""), cfg.get("background", ""))
    history = list(history or [])
    if cfg["engine"] == "gemini":
        return translate_gemini(text, system, cfg["gemini_model"], cfg["gemini_api_key"], history)
    return translate_ollama(text, system, cfg["ollama_model"], history)
