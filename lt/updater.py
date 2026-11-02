"""업데이트: GitHub 릴리스에서 새 버전을 찾아 받아 설치한다 (Qt 없음).

- 최신 릴리스: GET https://api.github.com/repos/{REPO}/releases/latest (임시판·초안은 빠진다)
- 받을 파일: 릴리스에 .zip 을 올려 두면 그것, 없으면 GitHub 이 태그로 만들어 주는 소스 zip
- 설치: 앱 폴더 위에 새 파일을 덮어쓴다. config.json(개인 설정)은 건드리지 않는다.
  바뀌거나 지워질 파일은 .update_backup/<이전 버전>/ 에 먼저 복사해 두고, 중간에 실패하면 되돌린다
- git 저장소인 폴더(개발용)에는 설치하지 않는다: 작업 중인 코드를 덮어쓰지 않게
"""

from __future__ import annotations

import re
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from . import __version__

REPO = "glglekdy/local-translator"    # 업데이트를 받아 올 GitHub 저장소 (공개 저장소여야 함)
APP_DIR = Path(__file__).resolve().parent.parent
KEEP = {"config.json"}                     # 앱 폴더에 있어도 절대 덮어쓰지 않는 파일
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", ".update_backup"}
MIRROR_DIRS = {"lt", "tests"}              # 이 폴더에서 새 판에 없는 파일은 지운다 (백업은 남김)
REQUIREMENTS = ("requirements.txt", "requirements-ai.txt")
SYNC_MARKER = ".sync_requirements"         # 있으면 다음 실행 때 패키지를 맞춘다 (lt/presync.py)


class UpdateError(Exception):
    """사용자에게 그대로 보여 줄 수 있는 업데이트 오류."""


@dataclass
class Release:
    version: str        # "1.2.0"
    tag: str            # "v1.2.0"
    url: str            # 받을 zip
    notes: str          # 릴리스 설명
    page: str           # 릴리스 웹 페이지


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.2.3' → (1, 2, 3). 숫자가 없으면 (0,)."""
    nums = re.findall(r"\d+", text.split("-")[0].split("+")[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(latest: str, current: str = __version__) -> bool:
    a, b = parse_version(latest), parse_version(current)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def latest_release(repo: str = REPO, timeout: float = 10) -> Release:
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}/releases/latest",
                         headers={"Accept": "application/vnd.github+json"}, timeout=timeout)
    except requests.RequestException:
        raise UpdateError("인터넷에 연결할 수 없어요") from None
    if r.status_code == 404:
        raise UpdateError("아직 올라온 릴리스가 없어요")
    if r.status_code == 403:
        raise UpdateError("GitHub 확인 횟수를 넘었어요. 잠시 뒤에 다시 해 주세요")
    if not r.ok:
        raise UpdateError(f"GitHub 응답 오류 ({r.status_code})")
    d = r.json()
    zips = [a for a in d.get("assets") or [] if str(a.get("name", "")).lower().endswith(".zip")]
    tag = str(d.get("tag_name") or "")
    # 올린 zip 이 딱 하나일 때만 그것을 쓴다. 여러 개면 어느 게 앱인지 모르니 소스 zip 으로
    return Release(version=tag.lstrip("vV"), tag=tag,
                   url=zips[0]["browser_download_url"] if len(zips) == 1 else d["zipball_url"],
                   notes=(d.get("body") or "").strip(), page=d.get("html_url") or "")


def download(url: str, dest: Path, progress: Callable[[float], None] | None = None, timeout: float = 30) -> Path:
    """progress(퍼센트). 전체 크기를 모르면 -1."""
    try:
        with requests.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            done = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done * 100 / total if total else -1.0)
    except requests.RequestException as e:
        raise UpdateError(f"받는 중에 끊겼어요 ({e.__class__.__name__})") from None
    return dest


def extract(zip_path: Path, into: Path) -> Path:
    """zip 을 풀고 앱의 뿌리(app.py 와 lt/ 가 있는 폴더)를 돌려준다."""
    into.mkdir(parents=True, exist_ok=True)
    base = into.resolve()
    try:
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                if not (base / name).resolve().is_relative_to(base):
                    raise UpdateError("받은 파일 안에 이상한 경로가 있어 설치하지 않았어요")
            z.extractall(base)
    except zipfile.BadZipFile:
        raise UpdateError("받은 파일이 망가졌어요") from None
    # GitHub 소스 zip 은 '주인-저장소-커밋/' 폴더 하나로 감싸져 있다
    for cand in (base, *sorted(p for p in base.iterdir() if p.is_dir())):
        if (cand / "app.py").is_file() and (cand / "lt" / "__init__.py").is_file():
            return cand
    raise UpdateError("받은 파일에 앱이 들어 있지 않아요")


def _files(root: Path) -> set[Path]:
    out = set()
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if p.is_file() and not set(rel.parts) & SKIP_DIRS and rel.as_posix() not in KEEP:
            out.add(rel)
    return out


def is_dev_checkout(app_dir: Path = APP_DIR) -> bool:
    return (app_dir / ".git").exists()


def install(new_root: Path, app_dir: Path = APP_DIR, old_version: str = __version__) -> bool:
    """새 판을 앱 폴더에 덮어쓴다. 패키지 목록(requirements*.txt)이 바뀌었으면 True."""
    if is_dev_checkout(app_dir):
        raise UpdateError("개발용 폴더(git)라 자동 설치는 하지 않아요. git pull 로 받아 주세요")
    new = _files(new_root)
    changed = [rel for rel in sorted(new)
               if not (app_dir / rel).is_file() or (app_dir / rel).read_bytes() != (new_root / rel).read_bytes()]
    stale = sorted(rel for rel in _files(app_dir) if rel.parts[0] in MIRROR_DIRS and rel not in new)
    def reqs() -> list[bytes]:
        return [(app_dir / n).read_bytes() if (app_dir / n).is_file() else b"" for n in REQUIREMENTS]
    old_reqs = reqs()

    backup = app_dir / ".update_backup" / old_version
    if backup.exists():
        backup = backup.with_name(f"{old_version}-{time.strftime('%Y%m%d-%H%M%S')}")
    saved: list[Path] = []          # 백업해 둔 원래 파일
    added: list[Path] = []          # 새로 생긴 파일
    try:
        for rel in [*changed, *stale]:
            if (app_dir / rel).is_file():
                (backup / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(app_dir / rel, backup / rel)
                saved.append(rel)
        for rel in changed:
            dst = app_dir / rel
            if not dst.exists():
                added.append(rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(new_root / rel, dst)
        for rel in stale:
            (app_dir / rel).unlink()
    except OSError as e:
        for rel in saved:           # 하던 걸 되돌린다
            shutil.copy2(backup / rel, app_dir / rel)
        for rel in added:
            (app_dir / rel).unlink(missing_ok=True)
        raise UpdateError(f"파일을 바꾸지 못해 원래대로 되돌렸어요 ({e.__class__.__name__})") from None
    if reqs() == old_reqs:
        return False
    # 도는 중인 앱이 쓰는 패키지는 지금 못 바꾼다 (Windows 는 불러온 파일을 잠근다) → 다음 실행 때
    (app_dir / SYNC_MARKER).write_text("", encoding="utf-8")
    return True


def update_to(release: Release, progress: Callable[[float], None] | None = None, app_dir: Path = APP_DIR) -> bool:
    """받아서 설치까지. 패키지 목록이 바뀌었으면 True (다시 켤 때 맞춘다)."""
    if is_dev_checkout(app_dir):
        raise UpdateError("개발용 폴더(git)라 자동 설치는 하지 않아요. git pull 로 받아 주세요")
    with tempfile.TemporaryDirectory() as tmp:
        z = download(release.url, Path(tmp) / "update.zip", progress)
        return install(extract(z, Path(tmp) / "new"), app_dir)
