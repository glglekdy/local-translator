import json

import pytest
from PySide6.QtGui import QGuiApplication

from lt import engine
from lt.main_window import MainWindow
from lt.subtitle import SubtitleWindow


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "list_ollama_models", lambda: ["gemma4:e4b-it-qat"])
    w = MainWindow(config_path=tmp_path / "config.json")
    yield w
    w.set_subtitle(False)
    w.stop()
    w.close()


def saved(w):
    return json.loads(w.model.path.read_text(encoding="utf-8"))


def test_toggle_button_opens_and_closes_overlay(win):
    assert win.subtitle is None
    win.subtitle_btn.click()
    assert win.subtitle is not None and win.subtitle.isVisible()
    win.subtitle_btn.click()
    assert win.subtitle is None and not win.subtitle_btn.isChecked()


def test_closing_overlay_unchecks_button(win):
    win.set_subtitle(True)
    win.subtitle.close()
    assert win.subtitle is None and not win.subtitle_btn.isChecked()


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def sub(win):
    win.set_subtitle(True)
    s = win.subtitle
    s._clock = Clock()
    return s


def run(sub, secs):
    """가짜 시계로 secs 초만큼 애니메이션을 돌린다."""
    for _ in range(round(secs / 0.016)):
        sub._clock.t += 0.016
        sub._tick()


def alive(sub):
    return [line for line in sub.lines if not line.dying]


def shown(line):
    return [b[0] for b in line.blocks]


def test_overlay_shows_source_then_translation(win, sub):
    win._on_heard(10, "ja", "君のことをずっと待っていた")
    assert shown(alive(sub)[-1]) == ["君のことをずっと待っていた", "…"]
    win._on_translated(10, "너를 계속 기다리고 있었어")
    assert shown(alive(sub)[-1]) == ["君のことをずっと待っていた", "너를 계속 기다리고 있었어"]


def test_lines_stack_and_late_translation_fills_its_own_line(win, sub):
    win._on_heard(1, "en", "first")
    win._on_heard(2, "en", "second")
    assert [line.uid for line in alive(sub)] == [1, 2]       # 새 말이 아래에
    win._on_translated(1, "첫째")                             # 늦게 와도 자기 줄에
    assert shown(alive(sub)[0]) == ["first", "첫째"]
    assert shown(alive(sub)[1]) == ["second", "…"]


def test_status_line_leaves_when_speech_arrives(win, sub):
    assert alive(sub)[0].kind == "status"
    win._on_heard(1, "en", "hi")
    assert [line.uid for line in alive(sub)] == [1]
    win._on_status("listening", "")
    assert [line.uid for line in alive(sub)] == [1]           # 실제 자막이 뜬 뒤엔 상태가 끼어들지 않음


def test_too_many_lines_push_out_the_oldest(win, sub):
    from lt.subtitle import MAX_LINES
    for uid in range(1, MAX_LINES + 3):
        win._on_heard(uid, "en", f"line {uid}")
    assert [line.uid for line in alive(sub)] == list(range(3, MAX_LINES + 3))
    run(sub, 2)
    assert [line.uid for line in sub.lines] == list(range(3, MAX_LINES + 3))   # 밀려난 줄은 접혀서 없어짐


def test_max_lines_setting_applies_live(win, sub):
    for uid in range(1, 5):
        win._on_heard(uid, "en", f"line {uid}")
    assert len(alive(sub)) == 4
    win.pages["subtitle"].max_lines.setValue(2)
    assert saved(win)["subtitle_max_lines"] == 2
    assert [line.uid for line in alive(sub)] == [3, 4]        # 줄이면 넘치는 오래된 말이 바로 사라짐
    win._on_heard(5, "en", "line 5")
    assert [line.uid for line in alive(sub)] == [4, 5]
    win.pages["subtitle"].max_lines.setValue(6)
    for uid in range(6, 12):
        win._on_heard(uid, "en", f"line {uid}")
    assert [line.uid for line in alive(sub)] == list(range(6, 12))


def test_failed_translation_shows_in_overlay(win, sub):
    win._on_heard(3, "en", "hi")
    win._on_failed(3, "Gemini API 키를 넣어 주세요")
    assert "번역 실패" in shown(alive(sub)[-1])[-1]


def test_original_can_be_hidden(win):
    win.model.update(subtitle_original=False)
    win.set_subtitle(True)
    sub = win.subtitle
    win._on_heard(4, "en", "Hello")
    assert shown(alive(sub)[-1]) == ["Hello"]                 # 번역 전엔 원문을 크게
    win._on_translated(4, "안녕")
    assert shown(alive(sub)[-1]) == ["안녕"]


def test_settings_page_changes_apply_live(win, sub):
    page = win.pages["subtitle"]
    page.font_size.setValue(44)
    page.opacity.setValue(30)
    assert sub.styles["ok"][0].pixelSize() == 44
    assert sub.bg_alpha == 76
    cfg = saved(win)
    assert cfg["subtitle_size"] == 44 and cfg["subtitle_opacity"] == 30


def test_overlay_menu_changes_are_saved(win, sub):
    sub._emit(subtitle_size=34)
    assert saved(win)["subtitle_size"] == 34
    assert win.pages["subtitle"].font_size.value() == 34


def test_default_position_is_bottom_center(win):
    win.set_subtitle(True)
    sub = win.subtitle
    area = QGuiApplication.primaryScreen().availableGeometry()
    g = sub.frameGeometry()
    assert abs(g.center().x() - area.center().x()) <= 2
    assert g.bottom() <= area.bottom() and g.bottom() >= area.bottom() - 200
    assert sub.width() <= 1200


def test_box_grows_upward_as_lines_stack(win, sub):
    win._on_heard(5, "en", "short")
    win._on_translated(5, "짧음")
    run(sub, 1)
    bottom, box = sub.frameGeometry().bottom(), sub.box_rect()
    win._on_heard(6, "en", "another line")
    win._on_translated(6, "두 번째 줄")
    run(sub, 0.05)
    mid = sub.box_rect()
    run(sub, 1)
    end = sub.box_rect()
    assert box.height() < mid.height() < end.height()        # 한 번에 튀지 않고 부드럽게 커짐
    assert abs(end.bottom() - box.bottom()) < 0.5             # 아래쪽은 그대로, 위로 자란다
    assert sub.frameGeometry().bottom() == bottom


def test_very_long_text_is_clipped_to_its_end(win, sub):
    from lt.subtitle import MAX_TRANSLATION_CHARS
    long_tr = " ".join(f"문장{i}" for i in range(200))
    win._on_heard(11, "en", "x")
    win._on_translated(11, long_tr)
    text = shown(alive(sub)[-1])[-1]
    assert text.startswith("… ") and text.endswith("문장199")
    assert len(text) <= MAX_TRANSLATION_CHARS + 2
    assert win.cards[11].translation == long_tr     # 기록 카드엔 전체가 남는다
    run(sub, 1)
    assert sub.box_rect().height() < sub.height()


def test_lines_fade_then_collapse_then_box_vanishes(win, sub):
    win.model.update(subtitle_hide_sec=5)
    win._on_heard(7, "en", "hi")
    win._on_translated(7, "안녕")
    run(sub, 1)
    line = alive(sub)[-1]
    full = line.h
    assert line.alpha == 1.0 and full > 0
    run(sub, 4.3)                                   # 5초가 막 지남: 흐려지는 중, 자리는 그대로
    assert line.dying and 0 < line.alpha < 1 and line.h == full
    run(sub, 2)                                     # 다 흐려지고 자리가 접힘
    assert sub.lines == [] and sub.box_rect().height() < 0.5
    assert not sub._frame.isActive()                # 다 끝나면 프레임 타이머도 멈춘다


def test_each_line_expires_on_its_own(win, sub):
    win.model.update(subtitle_hide_sec=3)
    win._on_heard(1, "en", "a")
    win._on_translated(1, "가")
    run(sub, 2)
    win._on_heard(2, "en", "b")
    win._on_translated(2, "나")
    run(sub, 2)                                     # 첫 말만 시간이 지남
    assert [line.uid for line in alive(sub)] == [2]
    run(sub, 3)
    assert sub.lines == []


def test_hide_timer_starts_after_translation(win, sub):
    win.model.update(subtitle_hide_sec=2)
    win._on_heard(8, "en", "slow")
    run(sub, 10)                                    # 번역이 한참 늦어도 기다린다
    assert not sub._find(8).dying
    win._on_translated(8, "느림")
    run(sub, 1.5)
    assert not sub._find(8).dying                   # 번역이 온 뒤 2초가 아직 안 됨
    run(sub, 1)
    assert sub._find(8).dying                       # 번역 2초 뒤부터 흐려진다


def test_failed_translation_also_waits_then_hides(win, sub):
    win.model.update(subtitle_hide_sec=2)
    win._on_heard(13, "en", "oops")
    run(sub, 5)
    win._on_failed(13, "연결 안 됨")
    run(sub, 1.5)
    assert not sub._find(13).dying
    run(sub, 3)
    assert sub._find(13) is None


def test_pending_line_without_translation_leaves_eventually(win, sub):
    from lt.subtitle import PENDING_MAX_SEC
    win.model.update(subtitle_hide_sec=2)
    win._on_heard(14, "en", "lost")
    sub._clock.t += PENDING_MAX_SEC
    run(sub, 1)
    assert sub._find(14) is None or sub._find(14).dying


def test_zero_hide_keeps_lines(win, sub):
    win.model.update(subtitle_hide_sec=0)
    win._on_heard(9, "en", "stay")
    run(sub, 1)
    sub._clock.t += 1000
    run(sub, 0.5)
    assert [line.uid for line in alive(sub)] == [9]
    assert not sub._frame.isActive() and not sub._expiry.isActive()


def test_paints_box_and_text(win, sub):
    win._on_heard(12, "en", "paint me")
    win._on_translated(12, "그려 줘")
    run(sub, 1)
    img = sub.grab().toImage()
    box = sub.box_rect()
    assert img.pixelColor(int(box.left()) + 6, int(box.center().y())).alpha() > 0
    assert img.pixelColor(2, 2).alpha() == 0         # 상자 밖은 완전 투명 → 클릭이 뒤로 통과


def test_saved_position_off_screen_falls_back(win):
    win.model.update(subtitle_pos=[-99999, -99999])
    win.set_subtitle(True)
    area = QGuiApplication.primaryScreen().availableGeometry()
    assert area.contains(win.subtitle.frameGeometry().center())


def test_reset_position_clears_saved_spot(win):
    win.set_subtitle(True)
    area = QGuiApplication.primaryScreen().availableGeometry()
    win.model.update(subtitle_pos=[area.left() + 400, area.top() + 300])
    assert abs(win.subtitle.frameGeometry().bottom() - (area.top() + 300)) <= 1
    win.pages["subtitle"].reset_btn.click()
    assert win.model.value["subtitle_pos"] is None
    assert abs(win.subtitle.frameGeometry().center().x() - area.center().x()) <= 2


def test_main_window_close_closes_overlay(win):
    win.set_subtitle(True)
    sub = win.subtitle
    win.close()
    assert not sub.isVisible()


def test_settings_switch_turns_overlay_on_and_off(win):
    check = win.pages["subtitle"].enabled
    check.setChecked(True)
    assert win.subtitle is not None and win.subtitle.isVisible()
    assert win.subtitle_btn.isChecked() and saved(win)["subtitle_enabled"] is True
    check.setChecked(False)
    assert win.subtitle is None and not win.subtitle_btn.isChecked()
    assert saved(win)["subtitle_enabled"] is False


def test_main_button_and_overlay_close_update_switch(win):
    check = win.pages["subtitle"].enabled
    win.subtitle_btn.click()
    assert check.isChecked() and saved(win)["subtitle_enabled"] is True
    win.subtitle.close()                              # 자막 위 오른쪽 클릭 > 자막 닫기
    assert not check.isChecked() and saved(win)["subtitle_enabled"] is False


def test_enabled_subtitle_comes_back_after_restart(win, tmp_path):
    win.set_subtitle(True)
    win.close()                                       # 앱을 닫아도 '켜 둠'은 그대로
    assert saved(win)["subtitle_enabled"] is True
    again = MainWindow(config_path=tmp_path / "config.json")
    try:
        assert again.subtitle is not None and again.subtitle.isVisible()
        assert again.subtitle_btn.isChecked() and again.pages["subtitle"].enabled.isChecked()
    finally:
        again._quitting = True
        again.close()
