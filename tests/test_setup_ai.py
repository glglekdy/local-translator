import time

import pytest

from lt import engine, presync, setup_ai
from lt.main_window import MainWindow

S = setup_ai.Status


# ---------- 그래픽카드 ----------
def test_parse_gpu():
    g = setup_ai.parse_gpu("NVIDIA GeForce RTX 4060 Ti, 16380, 617.42\n")
    assert (g.name, g.vram_gb, g.driver, g.driver_major) == ("NVIDIA GeForce RTX 4060 Ti", 16.0, "617.42", 617)
    assert setup_ai.parse_gpu("") is None
    assert setup_ai.parse_gpu("garbage") is None


def test_torch_build_follows_driver():
    gpu = lambda d: setup_ai.GPU("x", 8, d)          # noqa: E731
    assert setup_ai.torch_build(gpu("617.42")) == "cu128"
    assert setup_ai.torch_build(gpu("570.10")) == "cu128"
    assert setup_ai.torch_build(gpu("561.09")) == "cu126"
    assert setup_ai.torch_build(gpu("531.00")) is None


# ---------- 라이브러리 ----------
def test_torch_cuda_reads_version_without_import(tmp_path, monkeypatch):
    pkg = tmp_path / "torch"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("raise ImportError('불러오면 안 됨')")
    (pkg / "version.py").write_text("__version__ = '2.11.0+cu128'\ncuda: Optional[str] = '12.8'\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert setup_ai.torch_cuda() == "12.8"
    (pkg / "version.py").write_text("cuda: Optional[str] = None\n")
    assert setup_ai.torch_cuda() == ""                # CPU 판


def test_install_libs_installs_cuda_torch_first(monkeypatch):
    calls = []
    monkeypatch.setattr(setup_ai, "run_pip", lambda args, progress, label: calls.append(args))
    monkeypatch.setattr(setup_ai, "torch_cuda", lambda: None)
    monkeypatch.setattr(setup_ai, "libs_ready", lambda: True)
    setup_ai.install_libs(setup_ai.GPU("RTX", 16, "617.42"), lambda p, t: None)
    assert calls[0][:2] == [f"torch=={setup_ai.TORCH_VERSION}", f"torchaudio=={setup_ai.TORCH_VERSION}"]
    assert calls[0][-1] == "https://download.pytorch.org/whl/cu128"
    assert calls[1][0] == "-r" and calls[1][1].endswith("requirements-ai.txt")


def test_install_libs_needs_gpu_and_new_driver():
    with pytest.raises(setup_ai.SetupError, match="그래픽카드"):
        setup_ai.install_libs(None, lambda p, t: None)
    with pytest.raises(setup_ai.SetupError, match="드라이버"):
        setup_ai.install_libs(setup_ai.GPU("GTX", 4, "470.00"), lambda p, t: None)


def test_run_pip_reports_failure(monkeypatch, tmp_path):
    import sys
    script = tmp_path / "fail.py"
    script.write_text("print('Resolving'); print('error: No solution found'); raise SystemExit(1)")
    monkeypatch.setattr(setup_ai, "pip_command", lambda args: [sys.executable, str(script)])
    seen = []
    with pytest.raises(setup_ai.SetupError, match="No solution found"):
        setup_ai.run_pip([], lambda p, t: seen.append(t), "PyTorch")
    assert seen and seen[0].startswith("PyTorch · ")


# ---------- 전체 상태 ----------
@pytest.fixture
def machine(monkeypatch):
    """가짜 PC: 값을 바꿔 가며 check_all 을 본다."""
    m = {"gpu": setup_ai.GPU("RTX 4060 Ti", 16, "617.42"), "libs": True, "cuda": "12.8", "asr": True,
         "running": True, "exe": "ollama.exe", "models": ["gemma4:e4b-it-qat"]}
    monkeypatch.setattr(setup_ai, "detect_gpu", lambda: m["gpu"])
    monkeypatch.setattr(setup_ai, "libs_ready", lambda: m["libs"])
    monkeypatch.setattr(setup_ai, "torch_cuda", lambda: m["cuda"])
    monkeypatch.setattr(setup_ai, "asr_cached", lambda name: m["asr"])
    monkeypatch.setattr(setup_ai, "ollama_running", lambda: m["running"])
    monkeypatch.setattr(setup_ai, "ollama_exe", lambda: m["exe"])
    monkeypatch.setattr(engine, "list_ollama_models", lambda: m["models"])
    return m


CFG = dict(engine.DEFAULT_CONFIG)


def test_everything_ready(machine):
    st = setup_ai.check_all(CFG)
    assert all(s.ok for s in st.values()) and setup_ai.ready(st)


def test_fresh_pc_blocks_steps_in_order(machine):
    machine.update(libs=False, cuda=None, asr=False, running=False, exe=None, models=[])
    st = setup_ai.check_all(CFG)
    assert st["gpu"].ok and not setup_ai.ready(st)
    assert not st["libs"].blocked and st["libs"].action == "설치"
    assert st["asr"].blocked                          # 라이브러리 먼저
    assert st["ollama"].action == "설치" and not st["ollama"].blocked
    assert st["model"].blocked                        # Ollama 먼저


def test_no_gpu_blocks_everything(machine):
    machine.update(gpu=None, libs=False, cuda=None)
    st = setup_ai.check_all(CFG)
    assert not st["gpu"].ok and "NVIDIA" in st["gpu"].text
    assert st["libs"].blocked and st["asr"].blocked


def test_old_driver_is_reported(machine):
    machine.update(gpu=setup_ai.GPU("GTX 1060", 6, "470.00"))
    st = setup_ai.check_all(CFG)
    assert not st["gpu"].ok and "드라이버" in st["gpu"].text


def test_cpu_torch_needs_reinstall(machine):
    machine.update(libs=False, cuda="")
    assert "CPU 판" in setup_ai.check_all(CFG)["libs"].text


def test_ollama_installed_but_off_offers_start(machine):
    machine.update(running=False)
    st = setup_ai.check_all(CFG)
    assert st["ollama"].action == "켜기" and not setup_ai.ready(st)


def test_gemini_does_not_need_ollama(machine):
    machine.update(running=False, exe=None, models=[])
    st = setup_ai.check_all(dict(CFG, engine="gemini"))
    assert not st["ollama"].needed and not st["model"].needed
    assert setup_ai.ready(st)


def test_model_name_matching():
    assert setup_ai.model_installed("gemma4:e4b-it-qat", ["gemma4:e4b-it-qat"])
    assert setup_ai.model_installed("llama3", ["llama3:latest"])
    assert not setup_ai.model_installed("gemma4:e2b-it-qat", ["gemma4:e4b-it-qat"])


# ---------- 업데이트 뒤 패키지 맞추기 ----------
def test_presync_runs_only_with_marker(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(presync, "MARKER", tmp_path / ".sync_requirements")
    monkeypatch.setattr(presync, "APP_DIR", tmp_path)
    monkeypatch.setattr(presync, "_uv", lambda: "uv.exe")
    monkeypatch.setattr(presync.subprocess, "run", lambda cmd, **k: calls.append(cmd))
    (tmp_path / "requirements.txt").write_text("PySide6")
    assert not presync.run() and calls == []
    presync.MARKER.write_text("")
    assert presync.run()
    assert calls and calls[0][:3] == ["uv.exe", "pip", "install"] and not presync.MARKER.exists()


# ---------- 화면 ----------
@pytest.fixture
def win(qapp, tmp_path, monkeypatch, machine):
    monkeypatch.setattr(engine, "list_ollama_models", lambda: machine["models"])
    w = MainWindow(config_path=tmp_path / "config.json")
    yield w
    w._quitting = True
    w.stop()
    w.close()


def wait_until(qapp, cond, secs=3.0):
    end = time.monotonic() + secs
    while not cond() and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.01)
    assert cond()


def test_download_tab_sits_below_settings(win):
    box = win.sidebar.layout()
    order = [box.itemAt(i).widget() for i in range(box.count()) if box.itemAt(i).widget()]
    assert order.index(win.sidebar.nav["download"]) == order.index(win.sidebar._children) + 1
    win.sidebar.select("download")
    assert win.stack.currentWidget() is win.pages["download"]
    assert not win.sidebar.expanded                   # 설정 묶음은 접힌다


def test_ready_pc_shows_all_checked(qapp, win):
    page = win.pages["download"]
    page.refresh()
    wait_until(qapp, lambda: page.ready is not None)
    assert page.ready and "모두 준비됐어요" in page.summary.text()
    assert not page.all_btn.isVisibleTo(page)
    assert not win.sidebar.nav["download"].dot


def test_missing_ai_leads_to_download_tab_once(qapp, win, machine):
    machine.update(libs=False, cuda=None, asr=False)
    win.check_setup_later(delay_ms=0)
    wait_until(qapp, lambda: win.pages["download"].ready is False)
    assert win.stack.currentWidget() is win.pages["download"] and win.sidebar.nav["download"].dot
    win.sidebar.select("translate")
    win.pages["download"].refresh()
    wait_until(qapp, lambda: not win.pages["download"]._checking)
    assert win.stack.currentWidget() is win.pages["translate"]     # 두 번 끌고 가지 않는다


def test_start_button_points_to_download_when_not_ready(qapp, win, machine):
    machine.update(libs=False, cuda=None)
    page = win.pages["download"]
    page.refresh()
    wait_until(qapp, lambda: page.ready is False)
    win.sidebar.select("translate")
    win.toggle()
    assert win.pipeline is None and win.stack.currentWidget() is page
    assert "다운로드" in win.status.text()


def test_install_all_runs_missing_steps_in_order(qapp, win, machine, monkeypatch):
    machine.update(libs=False, cuda=None, asr=False, running=False, models=[])
    done = []

    def fake_step(step, cfg, progress):
        progress(50.0, f"{step} 반쯤")
        done.append(step)
        if step == "libs":
            machine.update(libs=True, cuda="12.8")
        elif step == "asr":
            machine.update(asr=True)
        elif step == "ollama":
            machine.update(running=True)
        elif step == "model":
            machine.update(models=["gemma4:e4b-it-qat"])
    monkeypatch.setattr(setup_ai, "run_step", fake_step)
    page = win.pages["download"]
    page.refresh()
    wait_until(qapp, lambda: page.ready is False)
    page.install_all()
    wait_until(qapp, lambda: page.ready, secs=5)
    assert done == ["libs", "asr", "ollama", "model"]
    assert all(page.rows[s].text.text().startswith("✓") for s in setup_ai.STEPS)


def test_failed_step_stops_and_can_retry(qapp, win, machine, monkeypatch):
    machine.update(libs=False, cuda=None, asr=False)
    calls = []

    def boom(step, cfg, progress):
        calls.append(step)
        raise setup_ai.SetupError("PyTorch 설치에 실패했어요: 디스크 공간 부족")
    monkeypatch.setattr(setup_ai, "run_step", boom)
    page = win.pages["download"]
    page.refresh()
    wait_until(qapp, lambda: page.ready is False)
    page.install_all()
    wait_until(qapp, lambda: not page.busy and calls)
    assert calls == ["libs"]                          # 실패하면 다음 단계로 안 간다
    row = page.rows["libs"]
    assert "디스크 공간" in row.text.text() and row.button.text() == "다시 하기" and row.button.isEnabled()
