"""업데이트로 패키지 목록이 바뀌었으면, 앱이 패키지를 불러오기 전에 맞춘다.

app.py 가 PySide6 등을 import 하기 전에 부른다. 그래서 이 파일은 표준 라이브러리만 쓴다
(불러온 패키지는 Windows 가 파일을 잠가서 바꿀 수 없다).
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
MARKER = APP_DIR / ".sync_requirements"          # updater.SYNC_MARKER 와 같은 이름
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _uv() -> str | None:
    bundled = APP_DIR.parent / "uv" / "uv.exe"   # 설치판: <뿌리>\uv\uv.exe
    return str(bundled) if bundled.is_file() else shutil.which("uv")


def run() -> bool:
    """맞출 게 있으면 맞춘다. 무언가 했으면 True. 실패해도 앱은 켜지게 조용히 넘어간다."""
    if not MARKER.exists():
        return False
    MARKER.unlink(missing_ok=True)      # 실패해도 매번 다시 하지 않게 먼저 지운다
    uv = _uv()
    if uv is None:
        return False
    files = ["requirements.txt"]
    if importlib.util.find_spec("torch") is not None:    # AI 라이브러리를 이미 받은 PC 만
        files.append("requirements-ai.txt")
    for name in files:
        if (APP_DIR / name).is_file():
            subprocess.run([uv, "pip", "install", "--python", sys.prefix, "-r", str(APP_DIR / name)],
                           cwd=str(APP_DIR), creationflags=NO_WINDOW, capture_output=True)
    return True
