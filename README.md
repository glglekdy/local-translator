# 로컬 번역기

들리는 말(시스템 소리 또는 마이크)을 알아듣고 바로 번역하는 Windows 앱이에요.
유튜브·방송·게임·회의 소리를 내 PC 의 AI 가 받아적고 번역해서, 화면 아래에 자막처럼 띄워 줘요.

- 음성 인식: [Qwen3-ASR](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) (기본, 노래·반주·잡음에 강함) 또는 [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — 내 PC, GPU
- 번역: **Ollama**(내 PC, 오프라인) 또는 **Gemini API**(인터넷, API 키)
- 자막 모드: 하프라이프 캡션처럼 말이 한 줄씩 쌓이고 스르륵 사라져요

## 필요한 것
- Windows 10 / 11 (64비트)
- **NVIDIA 그래픽카드** (VRAM 8GB 이상 권장) + 최신 드라이버
- 디스크 여유 약 15GB (AI 라이브러리 약 6GB, 음성 인식 모델 약 4GB, Ollama + 번역 모델 약 8GB)

## 설치
1. [Releases](https://github.com/glglekdy/local-translator/releases/latest) 에서 **`LocalTranslator-Setup-x.y.z.exe`** 를 받아 실행해요
   - "Windows의 PC 보호" 창이 뜨면 **추가 정보 → 실행** 을 눌러요 (서명하지 않은 오픈소스 프로그램이라 떠요)
   - 관리자 권한 없이 `%LOCALAPPDATA%\LocalTranslator` 에 설치돼요. 마지막에 Python 과 기본 패키지를 받아요 (인터넷 필요, 1~3분)
2. 설치가 끝나면 앱이 켜져요. **다운로드** 화면에서 **한 번에 모두 받기** 를 눌러요
   - 그래픽카드를 확인하고 AI 라이브러리 → 음성 인식 모델 → Ollama → 번역 모델을 차례로 받아요
   - 인터넷 속도에 따라 10~30분 걸려요. 처음 한 번만 하면 돼요
3. 다음부터는 시작 메뉴나 바탕화면의 **로컬 번역기** 로 켜요

지우려면 Windows **설정 > 앱 > 설치된 앱** 에서 **로컬 번역기 → 제거**.
받아 둔 음성 인식 모델(`%USERPROFILE%\.cache\huggingface`)과 Ollama 는 다른 앱도 쓸 수 있어서 남겨 둬요.
Ollama 도 지우려면 설치된 앱 목록에서 따로 제거해요.

## 쓰는 법
1. **시스템 소리**(PC 에서 나는 소리) / **마이크** 고르기
2. 번역할 언어 고르기 → **시작**
3. 설정 > 음성 인식 / 번역 엔진 / 배경 정보 에서 모델·언어·감도·엔진을 바꿀 수 있어요. 바꾸면 바로 저장돼요
4. **자막 모드**: 하프라이프 자막처럼 화면 아래에 번역이 한 줄씩 쌓여요 (항상 맨 위, 반투명).
   번역이 나온 뒤 몇 초 지나면 스르륵 사라지고 배경 상자도 부드럽게 줄어들어요. 마우스를 올려 두면 멈춰 기다려요.
   끌어서 옮기면 자리를 기억하고, 오른쪽 클릭으로 원문 보기·글자 크기·위치 초기화·닫기.
   설정 > 자막 에서 켜기/끄기·글자 크기·배경·사라지는 시간·쌓이는 말 수를 정해요
5. **배경 정보**: 캐릭터·사람 이름을 `원어 = 번역어` 로 적어 두면 번역이 그 이름으로 맞춰지고,
   음성 인식에도 힌트로 들어가요. 방송·세계관 설명을 적어 두면 말투와 맥락을 맞춰 번역해요

| 번역 엔진 | 특징 |
|---|---|
| Ollama · `gemma4:e4b-it-qat` (기본) | 오프라인·무료. 정확도 우선 |
| Ollama · `gemma4:e2b-it-qat` | 오프라인·무료. 속도 우선 |
| Gemini API | 인터넷 + API 키. 키 발급: https://aistudio.google.com/apikey |

설정(API 키 포함)은 앱 폴더의 `config.json` 에만 저장돼요.

## 업데이트
설정 > 업데이트 에서 새 버전을 확인하고 **지금 업데이트 → 다시 시작** 으로 설치해요.
앱을 켤 때도 조용히 확인해서, 새 버전이 있으면 왼쪽 아래에 `새 버전 x.y.z` 가 떠요.

- `config.json`(설정·API 키)은 건드리지 않고, 바뀐 파일은 `.update_backup/<이전 버전>/` 에 남겨요.
  중간에 실패하면 원래대로 되돌려요
- 필요한 패키지가 바뀐 판이면 다시 켤 때 알아서 맞춰요
- git 으로 받은 폴더(개발용)에는 설치하지 않아요. 거기선 `git pull`

## 개발
의존성 하나(nagisa)가 **한글 경로**에서 파일을 못 읽어서 가상환경은 영문 경로에 만들어요.
```
uv venv --python 3.12 %USERPROFILE%\.venvs\local-translator
set PY=%USERPROFILE%\.venvs\local-translator\Scripts\python.exe
uv pip install --python %PY% torch==2.11.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu128
uv pip install --python %PY% -r requirements.txt -r requirements-ai.txt pytest
```
`실행.bat` 으로 켜요. Ollama 와 모델은 앱의 다운로드 화면에서 받을 수 있어요.

테스트:
```
%USERPROFILE%\.venvs\local-translator\Scripts\python.exe -m pytest
```

새 버전 내는 법 (Inno Setup 6 필요: `winget install JRSoftware.InnoSetup`):
1. `lt/__init__.py` 의 `__version__` 을 올리고 커밋·푸시 (예: `1.1.0`)
2. `powershell -ExecutionPolicy Bypass -File tools\build_installer.ps1` → `dist\` 에
   `LocalTranslator-Setup-1.1.0.exe`(설치 프로그램)와 `LocalTranslator-1.1.0.zip`(앱 안 업데이트용)이 생겨요
3. `gh release create v1.1.0 dist\LocalTranslator-Setup-1.1.0.exe dist\LocalTranslator-1.1.0.zip --title "로컬 번역기 1.1.0" --notes "바뀐 점"`
   (앱의 업데이트는 릴리스의 zip 을 받아요. zip 은 꼭 하나만 올려요)

### 구조
```
installer/                   설치 프로그램 (Inno Setup 스크립트, 실행 파일 LocalTranslator.exe 소스)
tools/build_installer.ps1    릴리스 파일 만들기 → dist/
tools/install.ps1            uv · Python · 기본 패키지 (설치 프로그램이 부름. 설치.bat 으로 직접도 가능)
실행.bat                     개발용 실행
app.py                       진입점
requirements.txt             기본 패키지 (화면·소리)
requirements-ai.txt          AI 라이브러리 (다운로드 화면이 설치, PyTorch 는 따로)
lt/engine.py                 Qt 없는 핵심: 설정, Chunker(문장 나누기), 음성 인식, 번역
lt/pipeline.py               듣기 → 알아듣기 → 번역 스레드
lt/main_window.py            번역 화면 (카드 목록)
lt/settings_pages.py         설정 화면 (음성 인식·번역 엔진·배경 정보·자막·업데이트)
lt/download_page.py          다운로드 화면
lt/setup_ai.py               AI 받기: GPU 확인 · PyTorch · 음성 인식 모델 · Ollama · 번역 모델 (Qt 없음)
lt/subtitle.py               자막 모드 창
lt/updater.py, presync.py    업데이트: GitHub 릴리스 확인 · 받기 · 설치, 다음 실행 때 패키지 맞추기
lt/sidebar.py, theme.py      메뉴·테마 (OS 다크/라이트 따라감)
```

## 라이선스
[MIT](LICENSE)
