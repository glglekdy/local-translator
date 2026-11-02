"""AI 다운로드: 번역에 필요한 것들을 이 PC 에 받는다 (Qt 없음).

순서대로 하나씩:
  gpu    NVIDIA 그래픽카드 확인 (받는 건 없음. 없으면 나머지를 못 한다)
  libs   PyTorch(CUDA 판) + 음성 인식 라이브러리 → 지금 쓰는 가상환경에 uv 로 설치
  asr    음성 인식 모델 (설정에서 고른 것) → Hugging Face 캐시
  ollama Ollama 프로그램 → 공식 설치 파일을 받아 조용히 설치하고 켠다
  model  Ollama 번역 모델 (설정에서 고른 것)

ollama · model 은 번역 엔진이 Ollama 일 때만 필요하다 (Gemini 면 건너뜀).
무거운 라이브러리(torch 등)는 확인할 때도 import 하지 않는다: 불러오면 DLL 이 잠겨 다시 설치할 수 없다.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from . import engine

APP_DIR = Path(__file__).resolve().parent.parent
# 설치판은 <뿌리>\app (이 앱), <뿌리>\venv, <뿌리>\uv\uv.exe 로 놓인다 (tools/install.ps1)
ROOT_DIR = APP_DIR.parent if (APP_DIR.parent / "venv").is_dir() else None
TORCH_VERSION = "2.11.0"           # qwen-asr 와 같이 검증한 판
# (이 드라이버 버전부터, PyTorch 판). RTX 50 은 cu128 부터 된다
TORCH_BUILDS = ((570, "cu128"), (560, "cu126"))
OLLAMA_SETUP_URL = "https://ollama.com/download/OllamaSetup.exe"
OLLAMA_EXE = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

Progress = Callable[[float, str], None]     # (퍼센트 0~100, 모르면 -1; 상태 문구)


class SetupError(Exception):
    """사용자에게 그대로 보여 줄 수 있는 오류."""


@dataclass
class Status:
    ok: bool
    text: str                 # 지금 상태 한 줄
    needed: bool = True       # False: 지금 설정에선 필요 없음 (Gemini 일 때 Ollama 등)
    blocked: str = ""         # 앞 단계가 안 돼서 지금은 할 수 없음 (이유)
    action: str = "받기"      # 버튼 이름


# ---------------- 그래픽카드 ----------------
@dataclass
class GPU:
    name: str
    vram_gb: float
    driver: str

    @property
    def driver_major(self) -> int:
        try:
            return int(self.driver.split(".")[0])
        except ValueError:
            return 0


def _run(args: list[str], timeout: float = 10) -> str:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW,
                          encoding="utf-8", errors="replace").stdout


def parse_gpu(csv: str) -> GPU | None:
    """nvidia-smi --query-gpu=name,memory.total,driver_version 결과의 첫 줄."""
    for line in csv.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            try:
                return GPU(parts[0], round(float(parts[1]) / 1024, 1), parts[2])
            except ValueError:
                continue
    return None


def detect_gpu() -> GPU | None:
    exe = shutil.which("nvidia-smi") or r"C:\Windows\System32\nvidia-smi.exe"
    try:
        return parse_gpu(_run([exe, "--query-gpu=name,memory.total,driver_version",
                               "--format=csv,noheader,nounits"]))
    except (OSError, subprocess.SubprocessError):
        return None


def torch_build(gpu: GPU) -> str | None:
    for min_driver, build in TORCH_BUILDS:
        if gpu.driver_major >= min_driver:
            return build
    return None


# ---------------- 라이브러리 ----------------
def has_module(name: str) -> bool:
    importlib.invalidate_caches()
    return importlib.util.find_spec(name) is not None


def torch_cuda() -> str | None:
    """설치된 torch 의 CUDA 판 ('12.8'). torch 를 불러오지 않고 version.py 만 읽는다. 없으면 None, CPU 판이면 ''."""
    spec = importlib.util.find_spec("torch")
    if spec is None or not spec.submodule_search_locations:
        return None
    ver = Path(list(spec.submodule_search_locations)[0]) / "version.py"
    try:
        m = re.search(r"^cuda[^=]*=\s*'([^']*)'", ver.read_text(encoding="utf-8"), re.M)
    except OSError:
        return None
    return m.group(1) if m else ""


def libs_ready() -> bool:
    return bool(torch_cuda()) and has_module("qwen_asr") and has_module("faster_whisper")


def uv_exe() -> str | None:
    if ROOT_DIR and (ROOT_DIR / "uv" / "uv.exe").is_file():
        return str(ROOT_DIR / "uv" / "uv.exe")
    return shutil.which("uv")


def pip_command(args: list[str]) -> list[str]:
    """지금 앱이 도는 가상환경에 패키지를 설치하는 명령."""
    uv = uv_exe()
    if uv:
        return [uv, "pip", "install", "--python", sys.prefix, *args]
    if has_module("pip"):
        return [str(Path(sys.prefix) / "python.exe" if os.name == "nt" else sys.executable), "-m", "pip", "install",
                *args]
    raise SetupError("패키지를 설치할 도구(uv)를 찾지 못했어요. 설치.bat 으로 설치했는지 확인해 주세요")


def run_pip(args: list[str], progress: Progress, label: str) -> None:
    """설치 명령을 돌리며 마지막 줄을 상태로 보여 준다."""
    cmd = pip_command(args)
    env = dict(os.environ, UV_NO_PROGRESS="1", PYTHONIOENCODING="utf-8")
    if ROOT_DIR:
        env.setdefault("UV_CACHE_DIR", str(ROOT_DIR / "uv-cache"))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                         errors="replace", creationflags=NO_WINDOW, env=env, cwd=str(APP_DIR))
    tail: list[str] = []
    for line in p.stdout:
        line = line.strip()
        if line:
            tail = (tail + [line])[-8:]
            progress(-1, f"{label} · {line[:90]}")
    if p.wait() != 0:
        detail = next((t for t in reversed(tail) if "error" in t.lower()), tail[-1] if tail else "")
        raise SetupError(f"{label} 설치에 실패했어요: {detail[:200]}")


def install_libs(gpu: GPU | None, progress: Progress) -> None:
    if gpu is None:
        raise SetupError("NVIDIA 그래픽카드를 찾지 못했어요")
    build = torch_build(gpu)
    if build is None:
        raise SetupError(f"그래픽 드라이버({gpu.driver})가 오래됐어요. NVIDIA 드라이버를 최신으로 업데이트해 주세요")
    if not torch_cuda():
        # CUDA 판 torch 를 먼저: 나중 패키지가 PyPI 의 CPU 판 torch 를 끌어오지 않게
        run_pip([f"torch=={TORCH_VERSION}", f"torchaudio=={TORCH_VERSION}",
                 "--index-url", f"https://download.pytorch.org/whl/{build}"], progress, "PyTorch")
    run_pip(["-r", str(APP_DIR / "requirements-ai.txt")], progress, "음성 인식 라이브러리")
    if not libs_ready():
        raise SetupError("설치는 끝났는데 라이브러리를 찾지 못했어요. 앱을 다시 켜 보세요")


# ---------------- 음성 인식 모델 ----------------
def asr_cached(name: str) -> bool:
    try:
        if name in engine.QWEN_REPOS:
            from huggingface_hub import snapshot_download
            snapshot_download(engine.QWEN_REPOS[name], local_files_only=True)
        else:
            from faster_whisper.utils import download_model
            download_model(name, local_files_only=True)
        return True
    except Exception:
        return False


def _dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def download_asr(name: str, progress: Progress) -> None:
    label = engine.ASR_MODELS.get(name, (name,))[0]
    try:
        if name not in engine.QWEN_REPOS:
            from faster_whisper.utils import download_model
            progress(-1, f"{label} 받는 중…")
            download_model(name)
            return
        from huggingface_hub import HfApi, constants, snapshot_download
        repo = engine.QWEN_REPOS[name]
        total = sum(s.size or 0 for s in HfApi().model_info(repo, files_metadata=True).siblings)
        folder = Path(constants.HF_HUB_CACHE) / ("models--" + repo.replace("/", "--"))
        error: list[Exception] = []
        t = threading.Thread(target=lambda: _catch(error, snapshot_download, repo), daemon=True)
        t.start()
        while t.is_alive():
            t.join(0.5)
            got = (_dir_size(folder) if folder.exists() else 0)
            pct = min(99.0, got * 100 / total) if total else -1.0
            progress(pct, f"{label} 받는 중… {got / 1e9:.1f} / {total / 1e9:.1f} GB" if total else f"{label} 받는 중…")
        if error:
            raise error[0]
    except SetupError:
        raise
    except Exception as e:
        raise SetupError(f"{label} 을 받지 못했어요 ({e.__class__.__name__}). 인터넷 연결을 확인해 주세요") from None


def _catch(box: list, fn, *args) -> None:
    try:
        fn(*args)
    except Exception as e:
        box.append(e)


# ---------------- Ollama ----------------
def ollama_exe() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    return str(OLLAMA_EXE) if OLLAMA_EXE.is_file() else None


def ollama_running() -> bool:
    try:
        return requests.get(f"{engine.OLLAMA_BASE}/api/version", timeout=1).ok
    except requests.RequestException:
        return False


def start_ollama(wait: float = 30) -> bool:
    """꺼져 있으면 켠다 (창 없이, 앱과 따로). 켜졌으면 True."""
    if ollama_running():
        return True
    exe = ollama_exe()
    if exe is None:
        return False
    flags = NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([exe, "serve"], creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, close_fds=True)
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if ollama_running():
            return True
        time.sleep(0.5)
    return False


def download_file(url: str, dest: Path, progress: Progress, label: str) -> Path:
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            done = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    progress(done * 100 / total if total else -1,
                             f"{label} 받는 중… {done / 1e9:.2f} / {total / 1e9:.2f} GB" if total else f"{label} 받는 중…")
    except requests.RequestException as e:
        raise SetupError(f"{label} 을 받지 못했어요 ({e.__class__.__name__}). 인터넷 연결을 확인해 주세요") from None
    return dest


def install_ollama(progress: Progress) -> None:
    if ollama_exe() is None:
        with tempfile.TemporaryDirectory() as tmp:
            setup = download_file(OLLAMA_SETUP_URL, Path(tmp) / "OllamaSetup.exe", progress, "Ollama")
            progress(-1, "Ollama 설치 중… (1~2분)")
            # 공식 설치 파일(Inno Setup)을 창 없이 설치
            code = subprocess.run([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"],
                                  creationflags=NO_WINDOW).returncode
            if code != 0 or ollama_exe() is None:
                raise SetupError(f"Ollama 설치에 실패했어요 (코드 {code}). ollama.com 에서 직접 설치해 주세요")
    progress(-1, "Ollama 켜는 중…")
    if not start_ollama(wait=60):
        raise SetupError("Ollama 가 켜지지 않아요. PC 를 다시 시작한 뒤 해 보세요")


# ---------------- 번역 모델 ----------------
def model_installed(name: str, installed: list[str]) -> bool:
    base = name if ":" in name else f"{name}:latest"
    return name in installed or base in installed


def pull_model(name: str, progress: Progress) -> None:
    def on(pct, status):
        progress(-1 if pct is None else pct, f"{name} · {status}")
    try:
        engine.pull_ollama(name, on)
    except RuntimeError as e:
        raise SetupError(str(e)) from None


# ---------------- 전체 ----------------
STEPS = ("gpu", "libs", "asr", "ollama", "model")


def check_all(cfg: dict) -> dict[str, Status]:
    """지금 상태. 몇 초 걸릴 수 있으니(nvidia-smi, 네트워크) 스레드에서 부른다."""
    out: dict[str, Status] = {}
    gpu = detect_gpu()
    if gpu is None:
        out["gpu"] = Status(False, "NVIDIA 그래픽카드를 찾지 못했어요. 이 앱은 NVIDIA GPU 가 필요해요", action="")
    elif torch_build(gpu) is None:
        out["gpu"] = Status(False, f"{gpu.name} · 드라이버 {gpu.driver} 가 오래됐어요. NVIDIA 드라이버를 업데이트해 주세요",
                            action="")
    else:
        out["gpu"] = Status(True, f"{gpu.name} · {gpu.vram_gb:g} GB", action="")
    no_gpu = "" if out["gpu"].ok else "그래픽카드 확인이 먼저예요"

    cuda = torch_cuda()
    if libs_ready():
        out["libs"] = Status(True, f"설치됨 · PyTorch CUDA {cuda}")
    elif cuda == "":
        out["libs"] = Status(False, "PyTorch 가 CPU 판이에요. GPU 판으로 다시 설치해요", blocked=no_gpu, action="설치")
    else:
        out["libs"] = Status(False, "아직 없어요 · 약 6 GB", blocked=no_gpu, action="설치")

    asr = cfg["asr_model"]
    asr_name = engine.ASR_MODELS.get(asr, (asr,))[0]
    if not libs_ready():
        out["asr"] = Status(False, f"{asr_name} · 아직 없어요", blocked=no_gpu or "라이브러리 설치가 먼저예요")
    elif asr_cached(asr):
        out["asr"] = Status(True, f"{asr_name} · 받음")
    else:
        size = {"qwen3-asr-1.7b": "약 4.4 GB", "qwen3-asr-0.6b": "약 1.9 GB"}.get(asr, "")
        out["asr"] = Status(False, f"{asr_name} · 아직 없어요" + (f" · {size}" if size else ""))

    use_ollama = cfg["engine"] == "ollama"
    skip = "번역 엔진이 Gemini 라 필요 없어요"
    running = ollama_running()
    if running:
        out["ollama"] = Status(True, "켜져 있어요", needed=use_ollama)
    elif ollama_exe():
        out["ollama"] = Status(False, "설치됨 · 꺼져 있어요", needed=use_ollama, action="켜기")
    else:
        out["ollama"] = Status(False, "아직 없어요 · 약 1.7 GB", needed=use_ollama, action="설치")
    if not use_ollama:
        out["ollama"].text = skip if not out["ollama"].ok else out["ollama"].text

    model = cfg["ollama_model"]
    if not running:
        out["model"] = Status(False, model, needed=use_ollama, blocked="Ollama 가 먼저예요")
    elif model_installed(model, engine.list_ollama_models()):
        out["model"] = Status(True, f"{model} · 받음", needed=use_ollama)
    else:
        size = re.search(r"\(([\d.]+GB)\)", engine.OLLAMA_MODELS.get(model, ""))
        out["model"] = Status(False, f"{model} · 아직 없어요" + (f" · {size.group(1)}" if size else ""),
                              needed=use_ollama)
    if not use_ollama and not out["model"].ok:
        out["model"].text = skip
    return out


def ready(status: dict[str, Status]) -> bool:
    """번역을 시작할 수 있는 상태인지 (필요 없는 단계는 빼고)."""
    return all(s.ok for s in status.values() if s.needed)


def run_step(step: str, cfg: dict, progress: Progress) -> None:
    if step == "libs":
        install_libs(detect_gpu(), progress)
    elif step == "asr":
        download_asr(cfg["asr_model"], progress)
    elif step == "ollama":
        install_ollama(progress)
    elif step == "model":
        pull_model(cfg["ollama_model"], progress)
    else:
        raise ValueError(step)
