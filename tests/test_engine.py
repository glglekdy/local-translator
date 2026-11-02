import json

import numpy as np
import pytest
import requests

from lt import engine

LOUD = np.full(1600, 0.1, np.float32)
QUIET = np.zeros(1600, np.float32)


# ---------- 설정 ----------
def test_load_missing_config_gives_defaults(tmp_path):
    assert engine.load_config(tmp_path / "none.json") == engine.DEFAULT_CONFIG


def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "c.json"
    cfg = dict(engine.DEFAULT_CONFIG, target="日本語", gemini_api_key="k")
    engine.save_config(cfg, p)
    assert engine.load_config(p) == cfg


def test_legacy_tkinter_config_is_migrated(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"engine": "Gemini API", "source": "마이크", "unknown": 1}), encoding="utf-8")
    cfg = engine.load_config(p)
    assert cfg["engine"] == "gemini" and cfg["source"] == "mic"
    assert "unknown" not in cfg


def test_old_whisper_setting_moves_to_qwen_default(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"whisper_model": "medium", "asr_model": "nonexistent"}), encoding="utf-8")
    assert engine.load_config(p)["asr_model"] == "qwen3-asr-1.7b"


def test_qwen_language_names_map_to_codes():
    assert engine.qwen_lang_code("Korean") == "ko"
    assert engine.qwen_lang_code("japanese") == "ja"
    assert engine.qwen_lang_code("Cantonese") == "ca"
    assert engine.qwen_lang_code(None) == "?"


def test_qwen_receives_forced_language_name(monkeypatch):
    calls = {}

    class FakeResult:
        text, language = " 안녕 ", "Korean"

    class FakeModel:
        def transcribe(self, audio, language, context=""):
            calls["language"] = language
            calls["sr"] = audio[1]
            return [FakeResult()]
    asr = engine.QwenASR.__new__(engine.QwenASR)
    asr.model = FakeModel()
    assert asr.transcribe(np.zeros(16000, np.float32), "ja") == ("안녕", "ko")
    assert calls == {"language": "Japanese", "sr": 16000}
    asr.transcribe(np.zeros(16000, np.float32), None)
    assert calls["language"] is None


def test_broken_config_falls_back_to_defaults(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{not json", encoding="utf-8")
    assert engine.load_config(p) == engine.DEFAULT_CONFIG


def test_engine_summary():
    assert engine.engine_summary(engine.DEFAULT_CONFIG) == "Ollama · gemma4:e4b-it-qat"
    assert engine.engine_summary(dict(engine.DEFAULT_CONFIG, engine="gemini")) == "Gemini API · gemini-3.8-flash"


# ---------- Chunker ----------
def feed_all(chunker, blocks):
    return [c for c in (chunker.feed(b) for b in blocks) if c is not None]


def test_chunker_splits_on_pause():
    ch = engine.Chunker(threshold=0.01, pause_sec=0.6)
    out = feed_all(ch, [QUIET] * 3 + [LOUD] * 10 + [QUIET] * 6 + [LOUD] * 8 + [QUIET] * 6)
    assert len(out) == 2
    assert len(out[0]) == 16 * 1600   # 말 10블록 + 멈춤 6블록


def test_chunker_ignores_silence_only():
    ch = engine.Chunker(threshold=0.01, pause_sec=0.6)
    assert feed_all(ch, [QUIET] * 50) == []


def test_chunker_drops_short_noise():
    ch = engine.Chunker(threshold=0.01, pause_sec=0.6)
    assert feed_all(ch, [LOUD] * 2 + [QUIET] * 6) == []   # 0.2초짜리 소리


def test_chunker_cuts_long_speech_without_losing_audio():
    ch = engine.Chunker(threshold=0.01, pause_sec=0.6, max_sec=3.0)
    out = feed_all(ch, [LOUD] * 70 + [QUIET] * 6)
    assert len(out) >= 3
    assert all(len(c) <= 30 * 1600 for c in out)
    loud_kept = sum(int((c != 0).sum()) for c in out)
    assert loud_kept == 70 * 1600   # 말소리는 하나도 버리지 않는다 (끝 무음만 버림)


def test_chunker_cuts_long_speech_at_quietest_point():
    # 3초 한도. 2.4초 지점에 짧은 숨(작은 소리)이 있으면 거기서 자른다
    dip = np.full(1600, 0.02, np.float32)
    ch = engine.Chunker(threshold=0.01, pause_sec=0.6, max_sec=3.0)
    out = feed_all(ch, [LOUD] * 24 + [dip] + [LOUD] * 5)
    assert len(out) == 1 and len(out[0]) == 25 * 1600
    assert len(ch.buf) == 5   # 남은 말은 다음 덩어리로


def test_short_pause_inside_sentence_does_not_split():
    ch = engine.Chunker(threshold=0.01, pause_sec=0.6)
    out = feed_all(ch, [LOUD] * 5 + [QUIET] * 3 + [LOUD] * 5 + [QUIET] * 6)
    assert len(out) == 1


# ---------- 번역 ----------
def test_prompt_has_target():
    p = engine.build_prompt("日本語")
    assert "日本語" in p and "Output ONLY the translation" in p


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, json.dumps(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def test_translate_uses_ollama(monkeypatch):
    seen = {}

    def fake_post(url, json=None, **kw):
        seen["url"], seen["body"] = url, json
        return FakeResponse(200, {"message": {"content": "  안녕하세요  "}})
    monkeypatch.setattr(engine.requests, "post", fake_post)
    out = engine.translate("Hello", engine.DEFAULT_CONFIG, [("皆さんこんにちは。", "여러분, 안녕하세요.")])
    assert out == "안녕하세요"
    assert seen["url"].endswith("/api/chat")
    assert seen["body"]["model"] == "gemma4:e4b-it-qat"
    assert seen["body"]["think"] is False
    # 앞 문장은 시스템 문구가 아니라 '이미 번역한 대화'로 들어간다
    roles = [(m["role"], m["content"]) for m in seen["body"]["messages"]]
    assert roles[0][0] == "system" and "皆さん" not in roles[0][1]
    assert roles[1:] == [("user", "皆さんこんにちは。"), ("assistant", "여러분, 안녕하세요."), ("user", "Hello")]


def test_gemini_gets_history_as_model_turns(monkeypatch):
    seen = {}

    def fake_post(url, headers=None, json=None, **kw):
        seen["body"] = json
        return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "둘째"}]}}]})
    monkeypatch.setattr(engine.requests, "post", fake_post)
    cfg = dict(engine.DEFAULT_CONFIG, engine="gemini", gemini_api_key="K")
    engine.translate("second", cfg, [("first", "첫째")])
    turns = [(c["role"], c["parts"][0]["text"]) for c in seen["body"]["contents"]]
    assert turns == [("user", "first"), ("model", "첫째"), ("user", "second")]


def test_translate_uses_gemini(monkeypatch):
    seen = {}

    def fake_post(url, headers=None, json=None, **kw):
        seen["url"], seen["headers"] = url, headers
        return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "こんにちは"}]}}]})
    monkeypatch.setattr(engine.requests, "post", fake_post)
    cfg = dict(engine.DEFAULT_CONFIG, engine="gemini", gemini_api_key="KEY", target="日本語")
    assert engine.translate("Hello", cfg) == "こんにちは"
    assert "gemini-3.8-flash:generateContent" in seen["url"]
    assert seen["headers"] == {"x-goog-api-key": "KEY"}


def test_gemini_without_key_fails_clearly():
    with pytest.raises(RuntimeError, match="API 키"):
        engine.translate("hi", dict(engine.DEFAULT_CONFIG, engine="gemini"))


def test_gemini_error_message_is_shown(monkeypatch):
    monkeypatch.setattr(engine.requests, "post",
                        lambda *a, **k: FakeResponse(400, {"error": {"message": "API key not valid"}}))
    with pytest.raises(RuntimeError, match="400: API key not valid"):
        engine.translate("hi", dict(engine.DEFAULT_CONFIG, engine="gemini", gemini_api_key="bad"))


def test_ollama_not_running_fails_clearly(monkeypatch):
    def refuse(*a, **k):
        raise requests.ConnectionError()
    monkeypatch.setattr(engine.requests, "post", refuse)
    with pytest.raises(RuntimeError, match="Ollama 에 연결할 수 없어요"):
        engine.translate("hi", engine.DEFAULT_CONFIG)


def test_ollama_missing_model_fails_clearly(monkeypatch):
    monkeypatch.setattr(engine.requests, "post", lambda *a, **k: FakeResponse(404, {}))
    with pytest.raises(RuntimeError, match="ollama pull"):
        engine.translate("hi", engine.DEFAULT_CONFIG)


# ---------- Gemini 모델 ----------
def gemini_cfg(model):
    return dict(engine.DEFAULT_CONFIG, engine="gemini", gemini_api_key="KEY", gemini_model=model)


def capture_gemini(monkeypatch, responses):
    calls = []

    def fake_post(url, headers=None, json=None, **kw):
        import copy
        calls.append((url, copy.deepcopy(json)))
        return responses.pop(0)
    monkeypatch.setattr(engine.requests, "post", fake_post)
    return calls


OK = lambda text: FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": text}]}}]})


def test_argon_is_selectable_and_uses_low_thinking(monkeypatch):
    assert "gemini-4-argon" in engine.GEMINI_MODELS
    calls = capture_gemini(monkeypatch, [OK("안녕")])
    assert engine.translate("Hi", gemini_cfg("gemini-4-argon")) == "안녕"
    url, body = calls[0]
    assert "models/gemini-4-argon:generateContent" in url
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}


def test_flash_lite_uses_minimal_thinking(monkeypatch):
    calls = capture_gemini(monkeypatch, [OK("x")])
    engine.translate("Hi", gemini_cfg("gemini-3.5-flash-lite"))
    assert calls[0][1]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "minimal"}


def test_unknown_model_sends_no_thinking_config(monkeypatch):
    calls = capture_gemini(monkeypatch, [OK("x")])
    engine.translate("Hi", gemini_cfg("gemini-9-future"))
    assert "thinkingConfig" not in calls[0][1]["generationConfig"]


def test_rejected_thinking_level_retries_without_it(monkeypatch):
    bad = FakeResponse(400, {"error": {"message": "Unsupported thinking level"}})
    calls = capture_gemini(monkeypatch, [bad, OK("재시도 성공")])
    assert engine.translate("Hi", gemini_cfg("gemini-4-argon")) == "재시도 성공"
    assert len(calls) == 2 and "thinkingConfig" not in calls[1][1]["generationConfig"]


def test_thought_parts_are_dropped(monkeypatch):
    resp = FakeResponse(200, {"candidates": [{"content": {"parts": [
        {"text": "let me think...", "thought": True}, {"text": "안녕하세요"}]}}]})
    capture_gemini(monkeypatch, [resp])
    assert engine.translate("Hi", gemini_cfg("gemini-4-argon")) == "안녕하세요"


def test_missing_model_404_is_explained(monkeypatch):
    capture_gemini(monkeypatch, [FakeResponse(404, {"error": {"message": "not found"}})])
    with pytest.raises(RuntimeError, match="모델을 찾을 수 없어요"):
        engine.translate("Hi", gemini_cfg("gemini-typo"))


def test_retired_gemini_model_migrates_to_default(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"gemini_model": "gemini-2.5-flash"}), encoding="utf-8")
    assert engine.load_config(p)["gemini_model"] == "gemini-3.8-flash"
    p.write_text(json.dumps({"gemini_model": "gemini-4-argon"}), encoding="utf-8")
    assert engine.load_config(p)["gemini_model"] == "gemini-4-argon"


# ---------- Ollama: Gemma 4 ----------
def test_gemma4_qat_is_recommended():
    assert "gemma4:e4b-it-qat" in engine.OLLAMA_MODELS
    assert engine.DEFAULT_CONFIG["ollama_model"] == "gemma4:e4b-it-qat"


def test_ollama_strips_inline_think_block(monkeypatch):
    monkeypatch.setattr(engine.requests, "post", lambda *a, **k: FakeResponse(
        200, {"message": {"content": "<think>hmm, Korean...</think>\n안녕하세요"}}))
    assert engine.translate("Hello", engine.DEFAULT_CONFIG) == "안녕하세요"


class FakeStream:
    def __init__(self, lines):
        self.lines = [json.dumps(l).encode() for l in lines]

    def iter_lines(self):
        yield from self.lines

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def test_pull_reports_progress(monkeypatch):
    seen = {}

    def fake_post(url, json=None, **kw):
        seen["url"], seen["body"] = url, json
        return FakeStream([{"status": "pulling manifest"},
                           {"status": "downloading", "total": 200, "completed": 50},
                           {"status": "downloading", "total": 200, "completed": 200},
                           {"status": "success"}])
    monkeypatch.setattr(engine.requests, "post", fake_post)
    events = []
    engine.pull_ollama("gemma4:e4b-it-qat", lambda pct, st: events.append((pct, st)))
    assert seen["url"].endswith("/api/pull") and seen["body"]["model"] == "gemma4:e4b-it-qat"
    assert events == [(None, "pulling manifest"), (25.0, "downloading"), (100.0, "downloading"), (None, "success")]


def test_pull_error_is_raised(monkeypatch):
    monkeypatch.setattr(engine.requests, "post", lambda *a, **k: FakeStream([{"error": "file does not exist"}]))
    with pytest.raises(RuntimeError, match="받기 실패: file does not exist"):
        engine.pull_ollama("gemma4:nope")


# ---------- 배경 정보 ----------
def test_parse_glossary():
    text = "# 주석\nアリス = 앨리스\n\n白石 → 시라이시\nABC\nfoo: 푸\n = 빈칸\n"
    assert engine.parse_glossary(text) == [("アリス", "앨리스"), ("白石", "시라이시"), ("ABC", ""), ("foo", "푸")]


def test_prompt_includes_glossary_and_background():
    p = engine.build_prompt("한국어", "アリス = 앨리스\nABC", "일본 게임 방송")
    assert "アリス → 앨리스" in p and "ABC (keep this name as is)" in p
    assert "일본 게임 방송" in p and "never add it to the translation" in p
    plain = engine.build_prompt("한국어")
    assert "Glossary" not in plain and "Background" not in plain


def test_translate_sends_glossary_in_system_prompt(monkeypatch):
    seen = {}

    def fake_post(url, json=None, **kw):
        seen["body"] = json
        return FakeResponse(200, {"message": {"content": "앨리스"}})
    monkeypatch.setattr(engine.requests, "post", fake_post)
    engine.translate("アリス", dict(engine.DEFAULT_CONFIG, glossary="アリス = 앨리스", background="방송"))
    system = seen["body"]["messages"][0]["content"]
    assert "アリス → 앨리스" in system and "방송" in system


def test_asr_hint_uses_source_terms_and_is_capped():
    assert engine.asr_hint(dict(engine.DEFAULT_CONFIG, glossary="アリス = 앨리스\nABC")) == "アリス, ABC"
    assert engine.asr_hint(engine.DEFAULT_CONFIG) == ""
    long = "\n".join(f"name{i} = 이름{i}" for i in range(200))
    assert len(engine.asr_hint({"glossary": long})) == engine.MAX_HINT_CHARS


def test_qwen_gets_hint_as_context():
    calls = {}

    class R:
        text, language = "アリス", "Japanese"

    class M:
        def transcribe(self, audio, context, language):
            calls["context"] = context
            return [R()]
    asr = engine.QwenASR.__new__(engine.QwenASR)
    asr.model = M()
    engine.transcribe(asr, np.zeros(16000, np.float32), None, "アリス, ABC")
    assert calls["context"] == "アリス, ABC"


def test_deleted_ollama_model_migrates(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"ollama_model": "gemma3:12b"}), encoding="utf-8")
    assert engine.load_config(p)["ollama_model"] == engine.DEFAULT_CONFIG["ollama_model"]
    assert "gemma3:12b" not in engine.OLLAMA_MODELS and "gemma4:e2b-it-qat" in engine.OLLAMA_MODELS


def test_ollama_url_avoids_localhost_ipv6_delay():
    # Windows 에서 localhost 는 IPv6 를 먼저 시도해 요청마다 2초씩 늦어진다
    assert "localhost" not in engine.OLLAMA_BASE
