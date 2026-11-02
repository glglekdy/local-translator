import shutil
import time
import zipfile

import pytest

from lt import __version__, engine, updater
from lt.main_window import MainWindow


# ---------- 버전 ----------
def test_parse_and_compare_versions():
    assert updater.parse_version("v1.2.3") == (1, 2, 3)
    assert updater.parse_version("1.10") == (1, 10)
    assert updater.parse_version("v2.0.0-beta") == (2, 0, 0)
    assert updater.is_newer("1.0.1", "1.0.0")
    assert updater.is_newer("1.10.0", "1.9.9")
    assert not updater.is_newer("1.0", "1.0.0")
    assert not updater.is_newer("0.9.9", "1.0.0")


# ---------- 릴리스 찾기 ----------
class FakeResponse:
    def __init__(self, status, data=None):
        self.status_code, self._data = status, data

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._data


RELEASE = {"tag_name": "v9.0.0", "body": "고친 것들", "html_url": "https://github.com/x/y/releases/v9.0.0",
           "zipball_url": "https://api.github.com/zipball/v9.0.0", "assets": []}


def test_latest_release_uses_source_zip_without_assets(monkeypatch):
    monkeypatch.setattr(updater.requests, "get", lambda *a, **k: FakeResponse(200, RELEASE))
    r = updater.latest_release()
    assert (r.version, r.tag, r.url, r.notes) == ("9.0.0", "v9.0.0", RELEASE["zipball_url"], "고친 것들")


def test_latest_release_prefers_uploaded_zip(monkeypatch):
    data = dict(RELEASE, assets=[{"name": "notes.txt", "browser_download_url": "a"},
                                 {"name": "local-translator.zip", "browser_download_url": "b"}])
    monkeypatch.setattr(updater.requests, "get", lambda *a, **k: FakeResponse(200, data))
    assert updater.latest_release().url == "b"
    data["assets"].append({"name": "other.zip", "browser_download_url": "c"})     # 여러 개면 소스 zip
    assert updater.latest_release().url == RELEASE["zipball_url"]


def test_latest_release_errors_are_friendly(monkeypatch):
    monkeypatch.setattr(updater.requests, "get", lambda *a, **k: FakeResponse(404))
    with pytest.raises(updater.UpdateError, match="릴리스가 없어요"):
        updater.latest_release()

    def offline(*a, **k):
        raise updater.requests.ConnectionError()
    monkeypatch.setattr(updater.requests, "get", offline)
    with pytest.raises(updater.UpdateError, match="인터넷"):
        updater.latest_release()


# ---------- 풀기 / 설치 ----------
def make_zip(path, files, prefix="owner-local-translator-abc123/"):
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(prefix + name, text)
    return path


NEW = {"app.py": "new app", "lt/__init__.py": '__version__ = "9.0.0"', "lt/new_module.py": "new",
       "requirements.txt": "PySide6\nnewdep\n", "config.json": '{"from": "release"}'}


@pytest.fixture
def app_dir(tmp_path):
    d = tmp_path / "app"
    (d / "lt" / "__pycache__").mkdir(parents=True)
    (d / "app.py").write_text("old app", encoding="utf-8")
    (d / "lt" / "__init__.py").write_text('__version__ = "1.0.0"', encoding="utf-8")
    (d / "lt" / "gone.py").write_text("old only", encoding="utf-8")
    (d / "lt" / "__pycache__" / "x.pyc").write_bytes(b"cache")
    (d / "requirements.txt").write_text("PySide6\n", encoding="utf-8")
    (d / "config.json").write_text('{"mine": true}', encoding="utf-8")
    return d


def test_extract_finds_app_root_inside_github_folder(tmp_path):
    root = updater.extract(make_zip(tmp_path / "u.zip", NEW), tmp_path / "x")
    assert (root / "app.py").read_text() == "new app"


def test_extract_rejects_paths_outside(tmp_path):
    z = make_zip(tmp_path / "evil.zip", {"../../evil.txt": "x", "app.py": "", "lt/__init__.py": ""}, prefix="")
    with pytest.raises(updater.UpdateError, match="이상한 경로"):
        updater.extract(z, tmp_path / "x")


def test_extract_rejects_zip_without_app(tmp_path):
    with pytest.raises(updater.UpdateError, match="앱이 들어 있지"):
        updater.extract(make_zip(tmp_path / "u.zip", {"README.md": "hi"}), tmp_path / "x")


def test_install_overwrites_keeps_config_and_backs_up(tmp_path, app_dir):
    root = updater.extract(make_zip(tmp_path / "u.zip", NEW), tmp_path / "x")
    req_changed = updater.install(root, app_dir, old_version="1.0.0")
    assert req_changed and (app_dir / updater.SYNC_MARKER).exists()     # 다음 실행 때 패키지 맞춤
    assert (app_dir / "app.py").read_text() == "new app"
    assert (app_dir / "lt" / "new_module.py").exists()
    assert not (app_dir / "lt" / "gone.py").exists()                      # 새 판에 없는 코드는 지움
    assert (app_dir / "config.json").read_text() == '{"mine": true}'      # 내 설정은 그대로
    backup = app_dir / ".update_backup" / "1.0.0"
    assert (backup / "app.py").read_text() == "old app"
    assert (backup / "lt" / "gone.py").read_text() == "old only"
    assert not (backup / "config.json").exists()


def test_install_twice_keeps_both_backups(tmp_path, app_dir):
    root = updater.extract(make_zip(tmp_path / "u.zip", NEW), tmp_path / "x")
    updater.install(root, app_dir, old_version="1.0.0")
    (app_dir / "app.py").write_text("tweaked", encoding="utf-8")
    assert not updater.install(root, app_dir, old_version="1.0.0")       # 패키지는 그대로
    assert len(list((app_dir / ".update_backup").iterdir())) == 2


def test_install_refuses_git_checkout(tmp_path, app_dir):
    (app_dir / ".git").mkdir()
    root = updater.extract(make_zip(tmp_path / "u.zip", NEW), tmp_path / "x")
    with pytest.raises(updater.UpdateError, match="git"):
        updater.install(root, app_dir)
    assert (app_dir / "app.py").read_text() == "old app"


def test_install_rolls_back_when_copy_fails(tmp_path, app_dir, monkeypatch):
    root = updater.extract(make_zip(tmp_path / "u.zip", NEW), tmp_path / "x")
    real_copy, calls = shutil.copy2, []

    def flaky(src, dst):
        calls.append(dst)
        if str(src).startswith(str(root)) and "new_module" in str(dst):   # 새 파일을 쓰다 실패
            raise PermissionError("locked")
        return real_copy(src, dst)
    monkeypatch.setattr(updater.shutil, "copy2", flaky)
    with pytest.raises(updater.UpdateError, match="되돌렸어요"):
        updater.install(root, app_dir, old_version="1.0.0")
    assert (app_dir / "app.py").read_text() == "old app"
    assert (app_dir / "lt" / "__init__.py").read_text() == '__version__ = "1.0.0"'
    assert (app_dir / "lt" / "gone.py").exists()
    assert not (app_dir / "lt" / "new_module.py").exists()


def test_update_to_downloads_and_installs(tmp_path, app_dir, monkeypatch):
    z = make_zip(tmp_path / "u.zip", NEW)
    seen = []

    def fake_download(url, dest, progress=None, timeout=30):
        progress(100.0)
        seen.append(url)
        return shutil.copy(z, dest)
    monkeypatch.setattr(updater, "download", fake_download)
    release = updater.Release("9.0.0", "v9.0.0", "https://example/u.zip", "", "")
    assert updater.update_to(release, lambda p: None, app_dir=app_dir)
    assert seen == ["https://example/u.zip"] and (app_dir / "app.py").read_text() == "new app"


# ---------- 화면 ----------
@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "list_ollama_models", lambda: ["gemma4:e4b-it-qat"])
    w = MainWindow(config_path=tmp_path / "config.json")
    yield w
    w.stop()
    w.close()


def wait_until(qapp, cond, secs=3.0):
    end = time.monotonic() + secs
    while not cond() and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.01)
    assert cond()


def newer():
    return updater.Release("99.0.0", "v99.0.0", "https://example/u.zip", "자막 개선\n버그 수정", "https://example/r")


def test_update_page_in_sidebar(win):
    win.sidebar.select("update")
    assert win.stack.currentWidget() is win.pages["update"]
    assert win.pages["update"].version.text() == __version__


def test_check_finds_new_version_and_marks_sidebar(qapp, win, monkeypatch):
    monkeypatch.setattr(updater, "latest_release", newer)
    page = win.pages["update"]
    page.check()
    wait_until(qapp, lambda: not page._busy)
    assert "99.0.0" in page.status.text() and page.new_box.isVisibleTo(page)
    assert "자막 개선<br>버그 수정" in page.notes.text()
    assert win.sidebar.nav["update"].dot
    assert "새 버전 99.0.0" in win.sidebar.version_label.text()


def test_check_says_up_to_date(qapp, win, monkeypatch):
    monkeypatch.setattr(updater, "latest_release",
                        lambda: updater.Release(__version__, "v" + __version__, "u", "", ""))
    page = win.pages["update"]
    page.check()
    wait_until(qapp, lambda: not page._busy)
    assert "최신 버전" in page.status.text() and not page.new_box.isVisibleTo(page)
    assert not win.sidebar.nav["update"].dot


def test_silent_check_hides_errors(qapp, win, monkeypatch):
    def fail():
        raise updater.UpdateError("인터넷에 연결할 수 없어요")
    monkeypatch.setattr(updater, "latest_release", fail)
    page = win.pages["update"]
    page.check(silent=True)
    wait_until(qapp, lambda: not page._busy)
    assert page.status.text() == ""
    page.check()
    wait_until(qapp, lambda: not page._busy)
    assert "인터넷" in page.status.text()


def test_install_then_restart(qapp, win, monkeypatch):
    monkeypatch.setattr(updater, "update_to", lambda release, progress: progress(50.0) or True)
    page = win.pages["update"]
    page._silent = False
    page._checked(newer(), "")
    restarts = []
    page.restart_requested.connect(lambda: restarts.append(1))
    page.install_btn.click()
    wait_until(qapp, lambda: not page._busy)
    assert "설치했어요" in page.status.text() and "패키지가 바뀌어서" in page.status.text()
    assert page.install_btn.text() == "다시 시작"
    page.install_btn.click()
    assert restarts == [1]


def test_install_failure_is_shown(qapp, win, monkeypatch):
    def fail(release, progress):
        raise updater.UpdateError("개발용 폴더(git)라 자동 설치는 하지 않아요. git pull 로 받아 주세요")
    monkeypatch.setattr(updater, "update_to", fail)
    page = win.pages["update"]
    page._silent = False
    page._checked(newer(), "")
    page.install_btn.click()
    wait_until(qapp, lambda: not page._busy)
    assert "git pull" in page.status.text() and page.install_btn.text() == "지금 업데이트"


def test_auto_check_setting(qapp, win, monkeypatch):
    calls = []
    monkeypatch.setattr(win.pages["update"], "check", lambda silent=False: calls.append(silent))
    win.check_updates_later(delay_ms=0)
    wait_until(qapp, lambda: calls == [True])
    win.pages["update"].auto.setChecked(False)
    assert win.model.value["update_auto_check"] is False
    win.check_updates_later(delay_ms=0)
    qapp.processEvents()
    assert calls == [True]
