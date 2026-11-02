import json

import pytest

from lt import engine
from lt.main_window import MainWindow, UtteranceCard


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "list_ollama_models", lambda: ["gemma4:e2b-it-qat", "gemma4:e4b-it-qat"])
    w = MainWindow(config_path=tmp_path / "config.json")
    yield w
    w.stop()
    w.close()


def saved(w):
    return json.loads(w.model.path.read_text(encoding="utf-8"))


def test_starts_on_translate_page_with_empty_state(win):
    assert win.stack.currentWidget() is win.pages["translate"]
    assert not win.empty.isHidden()
    assert win.engine_name.text() == "Ollama · gemma4:e4b-it-qat"
    assert win.start_btn.text() == "시작"


def test_heard_then_translated_fills_card(win):
    win._on_heard(1, "en", "Hello everyone.")
    card = win.cards[1]
    assert isinstance(card, UtteranceCard) and win.empty.isHidden()
    assert card.tr.text() == "번역 중…" and card.tr.property("state") == "pending"
    win._on_translated(1, "안녕하세요 여러분.")
    assert card.tr.text() == "안녕하세요 여러분." and card.tr.property("state") == ""


def test_newest_card_is_marked_latest_and_at_bottom(win):
    win._on_heard(1, "en", "a")
    win._on_heard(2, "en", "b")
    assert win.cards[2].property("latest") and not win.cards[1].property("latest")
    assert win.list.indexOf(win.cards[2]) > win.list.indexOf(win.cards[1])


def test_failed_translation_shows_error(win):
    win._on_heard(5, "ja", "こんにちは")
    win._on_failed(5, "Ollama 에 연결할 수 없어요")
    assert win.cards[5].tr.property("state") == "error"
    assert "번역 실패" in win.cards[5].tr.text()


def test_clear_removes_cards(win):
    win._on_heard(1, "en", "a")
    win.clear()
    assert win.cards == {} and not win.empty.isHidden()


def test_transcript_and_copy(win, qapp):
    win._on_heard(1, "en", "Hello")
    win._on_translated(1, "안녕")
    win._on_heard(2, "en", "Bye")
    win._on_translated(2, "잘가")
    win._on_heard(3, "en", "pending one")       # 번역 안 된 건 빠진다
    assert win.transcript(translations_only=True) == "안녕\n잘가"
    assert "(en) Hello\n안녕" in win.transcript()
    win.copy_all()
    assert qapp.clipboard().text() == "안녕\n잘가"


def test_source_and_target_are_saved(win):
    mic = next(b for b in win.source_group.buttons() if b.property("source") == "mic")
    mic.click()
    win.target.setCurrentText("日本語")
    cfg = saved(win)
    assert cfg["source"] == "mic" and cfg["target"] == "日本語"


def test_engine_page_switch_updates_dock(win):
    page = win.pages["engine"]
    page.use_gemini.setChecked(True)
    assert win.engine_name.text() == "Gemini API · gemini-3.8-flash"
    assert page.api_key.isEnabled() and not page.ollama_model.isEnabled()
    assert saved(win)["engine"] == "gemini"


def test_speech_page_saves(win):
    page = win.pages["speech"]
    page.asr.setCurrentIndex(page.asr.findData("large-v3-turbo"))
    page.language.setCurrentIndex(page.language.findData("일본어"))
    page.pause.setValue(1.0)
    cfg = saved(win)
    assert cfg["asr_model"] == "large-v3-turbo" and cfg["source_language"] == "일본어" and cfg["pause_sec"] == 1.0


def test_sidebar_navigation(win):
    win.sidebar.select("engine")
    assert win.stack.currentWidget() is win.pages["engine"]
    win.sidebar.select("translate")
    assert win.stack.currentWidget() is win.pages["translate"]


def test_live_translation_setting_does_not_restart(win, monkeypatch):
    class FakePipeline:
        def __init__(self):
            self.cfg = None
        def set_cfg(self, cfg):
            self.cfg = cfg
    fake = FakePipeline()
    win.pipeline = fake
    restarted = []
    monkeypatch.setattr(win, "stop", lambda: restarted.append("stop"))
    monkeypatch.setattr(win, "start", lambda: restarted.append("start"))
    win.target.setCurrentText("English")
    assert fake.cfg["target"] == "English" and restarted == []
    win.pages["speech"].pause.setValue(1.2)
    assert restarted == ["stop", "start"]
    win.pipeline = None


def test_gemini_argon_can_be_chosen_from_list(win):
    page = win.pages["engine"]
    page.use_gemini.setChecked(True)
    i = page.gemini_model.findData("gemini-4-argon")
    assert i >= 0
    page.gemini_model.setCurrentIndex(i)
    page.gemini_model.activated.emit(i)
    assert saved(win)["gemini_model"] == "gemini-4-argon"
    assert win.engine_name.text() == "Gemini API · gemini-4-argon"


def test_gemini_custom_model_name_can_be_typed(win):
    page = win.pages["engine"]
    page.use_gemini.setChecked(True)
    page.gemini_model.setEditText("gemini-5-something")
    page.gemini_model.lineEdit().editingFinished.emit()
    assert saved(win)["gemini_model"] == "gemini-5-something"


def wait_until(qapp, cond, timeout=3.0):
    import time
    end = time.time() + timeout
    while time.time() < end and not cond():
        qapp.processEvents()
        time.sleep(0.01)
    assert cond()


def test_ollama_list_shows_recommended_and_installed(win):
    page = win.pages["engine"]
    items = {page.ollama_model.itemData(i): page.ollama_model.itemText(i) for i in range(page.ollama_model.count())}
    assert "Gemma 4 E4B QAT" in items["gemma4:e4b-it-qat"] and "받기 필요" not in items["gemma4:e4b-it-qat"]
    assert set(items) == {"gemma4:e4b-it-qat", "gemma4:e2b-it-qat"}


def test_choosing_gemma4_saves_plain_tag(win):
    page = win.pages["engine"]
    i = page.ollama_model.findData("gemma4:e2b-it-qat")
    page.ollama_model.setCurrentIndex(i)
    page.ollama_model.activated.emit(i)
    assert saved(win)["ollama_model"] == "gemma4:e2b-it-qat"
    assert win.engine_name.text() == "Ollama · gemma4:e2b-it-qat"
    assert page.pull_btn.isHidden()


def test_missing_model_shows_pull_button_and_pulls(win, qapp, monkeypatch):
    page = win.pages["engine"]
    monkeypatch.setattr(engine, "list_ollama_models", lambda: ["gemma4:e2b-it-qat"])
    page.refresh_models()
    i = page.ollama_model.findData("gemma4:e4b-it-qat")
    assert "받기 필요" in page.ollama_model.itemText(i)
    page.ollama_model.setCurrentIndex(i)
    page.ollama_model.activated.emit(i)
    assert not page.pull_btn.isHidden()

    def fake_pull(name, on_progress):
        on_progress(50.0, "downloading")
        monkeypatch.setattr(engine, "list_ollama_models", lambda: ["gemma4:e2b-it-qat", name])
    monkeypatch.setattr(engine, "pull_ollama", fake_pull)
    page.pull_btn.click()
    wait_until(qapp, lambda: page.test_result.property("state") == "ok")
    assert page.pull_btn.isHidden()
    assert win.model.value["ollama_model"] == "gemma4:e4b-it-qat"


def test_test_button_blocks_uninstalled_model(win, monkeypatch):
    page = win.pages["engine"]
    monkeypatch.setattr(engine, "list_ollama_models", lambda: ["gemma4:e2b-it-qat"])
    page.refresh_models()
    page.ollama_model.setCurrentIndex(page.ollama_model.findData("gemma4:e4b-it-qat"))
    page.run_test()
    assert page.test_result.property("state") == "error" and "받기" in page.test_result.text()


def test_context_page_saves_after_typing_pause(win, qapp):
    page = win.pages["context"]
    page.glossary.setPlainText("アリス = 앨리스\nABC")
    page.background.setPlainText("게임 방송")
    assert page._save_timer.isActive()
    wait_until(qapp, lambda: not page._save_timer.isActive(), timeout=3)
    cfg = saved(win)
    assert cfg["glossary"] == "アリス = 앨리스\nABC" and cfg["background"] == "게임 방송"
    assert page.count.text().startswith("용어 2개")


def test_context_page_saves_immediately_when_leaving(win):
    win.sidebar.select("context")
    page = win.pages["context"]
    page.glossary.setPlainText("A = 에이")
    win.sidebar.select("translate")
    assert saved(win)["glossary"] == "A = 에이"
