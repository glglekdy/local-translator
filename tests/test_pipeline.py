"""Pipeline 의 번역 부분(앞 문장 기록 관리). 오디오·모델 없이 _translate 만 직접 부른다."""
from lt import engine, pipeline


def make(monkeypatch, target="한국어"):
    calls = []

    def fake_translate(text, cfg, history):
        calls.append((text, cfg["target"], list(history)))
        return f"{cfg['target']}:{text}"
    monkeypatch.setattr(engine, "translate", fake_translate)
    p = pipeline.Pipeline(dict(engine.DEFAULT_CONFIG, target=target))
    got = []
    p.translated.connect(lambda uid, t: got.append((uid, t)))
    p.failed.connect(lambda uid, m: got.append((uid, "FAIL " + m)))
    return p, calls, got


def test_history_passes_previous_pairs(monkeypatch):
    p, calls, got = make(monkeypatch)
    for i, t in enumerate(["a", "b", "c"], 1):
        p._translate(i, t)
    assert calls[0][2] == []
    assert calls[2][2] == [("a", "한국어:a"), ("b", "한국어:b")]
    assert got[-1] == (3, "한국어:c")


def test_history_is_capped(monkeypatch):
    p, calls, _ = make(monkeypatch)
    for i in range(10):
        p._translate(i, f"s{i}")
    assert len(calls[-1][2]) == pipeline.HISTORY_TURNS
    assert calls[-1][2][-1][0] == "s8"


def test_history_resets_when_target_changes(monkeypatch):
    p, calls, _ = make(monkeypatch)
    p._translate(1, "hello")
    p.set_cfg(dict(p.cfg, target="日本語"))
    p._translate(2, "world")
    assert calls[1][1] == "日本語" and calls[1][2] == []


def test_failed_translation_is_not_added_to_history(monkeypatch):
    p, calls, got = make(monkeypatch)

    def boom(text, cfg, history):
        raise RuntimeError("down")
    monkeypatch.setattr(engine, "translate", boom)
    p._translate(1, "x")
    assert got == [(1, "FAIL down")] and p._history == []
