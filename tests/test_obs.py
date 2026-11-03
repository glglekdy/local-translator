import json
import socket
import urllib.request

import pytest

from lt import engine, obs
from lt.main_window import MainWindow
from lt.obs import ObsServer


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Events:
    """/events 에 붙어서 SSE 메시지를 하나씩 읽는다."""

    def __init__(self, port: int):
        self.resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/events", timeout=5)
        assert self.resp.headers["Content-Type"].startswith("text/event-stream")

    def next(self) -> dict:
        while True:
            line = self.resp.readline().decode("utf-8")
            assert line, "연결이 끊겼어요"
            if line.startswith("data: "):
                return json.loads(line[6:])

    def close(self):
        self.resp.close()


@pytest.fixture
def server():
    s = ObsServer(engine.DEFAULT_CONFIG, port=0)
    s.start()
    yield s
    s.stop()


def test_page_is_transparent_overlay(server):
    with urllib.request.urlopen(server.url, timeout=5) as r:
        html = r.read().decode("utf-8")
    assert r.headers["Content-Type"] == "text/html; charset=utf-8"
    assert "background: transparent" in html and 'new EventSource("/events")' in html


def test_unknown_path_is_404(server):
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(server.url + "nope", timeout=5)
    assert e.value.code == 404


def test_new_client_gets_cfg_and_recent_lines(server):
    server.show_source(1, "Hello")
    server.show_translation(1, "Hello", "안녕")
    ev = Events(server.port)
    reset = ev.next()
    assert reset["type"] == "reset"
    assert reset["cfg"]["subtitle_size"] == engine.DEFAULT_CONFIG["subtitle_size"]
    [line] = reset["lines"]
    assert line["uid"] == 1 and line["text"] == "안녕" and line["kind"] == "ok" and line["age"] >= 0
    ev.close()


def test_source_translation_and_failure_are_streamed(server):
    ev = Events(server.port)
    assert ev.next()["type"] == "reset"
    server.show_source(3, "How are you?")
    assert ev.next() == {"type": "line", "line": {"uid": 3, "source": "How are you?", "text": "", "kind": "pending"}}
    server.show_translation(3, "How are you?", "잘 지내?")
    assert ev.next()["line"] == {"uid": 3, "source": "How are you?", "text": "잘 지내?", "kind": "ok"}
    server.show_source(4, "Bad")
    ev.next()
    server.show_failed(4)           # 시청자에게 오류 문구는 안 보이고 줄만 사라진다
    assert ev.next() == {"type": "drop", "uid": 4}
    server.apply_cfg({**engine.DEFAULT_CONFIG, "subtitle_size": 44})
    assert ev.next() == {"type": "cfg", "cfg": {**{k: engine.DEFAULT_CONFIG[k] for k in obs.CFG_KEYS},
                                                "subtitle_size": 44}}
    ev.close()


def test_older_source_and_unknown_translation_are_ignored(server):
    server.show_source(5, "new")
    server.show_source(4, "old")            # 더 오래된 말은 무시 (자막 창과 같은 규칙)
    server.show_translation(9, "?", "없는 줄")
    server.show_failed(9)
    ev = Events(server.port)
    assert [l["uid"] for l in ev.next()["lines"]] == [5]
    ev.close()


def test_keeps_only_recent_lines(server):
    for uid in range(1, 20):
        server.show_source(uid, f"line {uid}")
    ev = Events(server.port)
    assert [l["uid"] for l in ev.next()["lines"]] == list(range(20 - obs.KEEP, 20))
    ev.close()


def test_long_text_is_clipped(server):
    server.show_source(1, "word " * 100)
    ev = Events(server.port)
    assert ev.next()["lines"][0]["source"].startswith("… ")
    ev.close()


def test_port_in_use_raises(server):
    other = ObsServer(engine.DEFAULT_CONFIG, port=server.port)
    with pytest.raises(OSError):
        other.start()


def test_stop_ends_open_streams(server):
    ev = Events(server.port)
    ev.next()
    server.stop()
    assert ev.resp.read().strip() == b""     # 남은 빈 줄 뒤에 연결이 닫힌다
    assert server.client_count == 0


# ---------- 앱과 연결 ----------
@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "list_ollama_models", lambda: ["gemma4:e4b-it-qat"])
    w = MainWindow(config_path=tmp_path / "config.json")
    w.model.update(obs_port=free_port())
    yield w
    w.close()


def test_off_by_default(win):
    assert win.obs is None
    assert win.pages["subtitle"].obs_state.isHidden()


def test_enabling_starts_server_and_feeds_subtitles(win):
    win.model.update(obs_enabled=True)
    assert win.obs is not None and win.obs.port == win.model.value["obs_port"]
    page = win.pages["subtitle"]
    assert page.obs_state.property("state") == "ok"
    assert page.obs_url.text() == f"http://127.0.0.1:{win.obs.port}/"
    ev = Events(win.obs.port)
    ev.next()
    win._on_heard(1, "en", "Hello")
    assert ev.next()["line"]["source"] == "Hello"
    win._on_translated(1, "안녕")
    assert ev.next()["line"]["text"] == "안녕"
    win.model.update(subtitle_size=40)      # 자막 설정을 바꾸면 OBS 화면도 따라간다
    assert ev.next()["cfg"]["subtitle_size"] == 40
    ev.close()


def test_works_without_subtitle_window(win):
    win.model.update(obs_enabled=True)
    assert win.subtitle is None
    win._on_heard(1, "en", "Hi")
    ev = Events(win.obs.port)
    assert ev.next()["lines"][0]["source"] == "Hi"
    ev.close()


def test_port_change_reopens_and_disable_stops(win):
    win.model.update(obs_enabled=True)
    new_port = free_port()
    win.model.update(obs_port=new_port)
    assert win.obs.port == new_port
    urllib.request.urlopen(f"http://127.0.0.1:{new_port}/", timeout=5).close()
    win.model.update(obs_enabled=False)
    assert win.obs is None
    with pytest.raises(OSError):
        urllib.request.urlopen(f"http://127.0.0.1:{new_port}/", timeout=2)


def test_busy_port_shows_error(win):
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        win.model.update(obs_port=blocker.getsockname()[1], obs_enabled=True)
        assert win.obs is None
        assert win.pages["subtitle"].obs_state.property("state") == "error"


def test_settings_page_controls(win):
    page = win.pages["subtitle"]
    page.obs_enabled.setChecked(True)
    assert win.model.value["obs_enabled"] and win.obs is not None
    page.obs_port.setValue(free_port())
    assert win.obs.port == page.obs_port.value()
    page.copy_url.click()
    from PySide6.QtGui import QGuiApplication
    assert QGuiApplication.clipboard().text() == page.obs_url.text()
