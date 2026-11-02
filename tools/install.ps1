# 로컬 번역기 설치: Python 과 앱 화면에 필요한 패키지만 설치하고 앱을 켠다.
# 무거운 AI(PyTorch·음성 인식·Ollama·번역 모델)는 앱의 '다운로드' 화면에서 받는다.
#
#   <뿌리>\app     이 앱 (업데이트도 여기에)
#   <뿌리>\venv    가상환경
#   <뿌리>\uv      uv.exe (파이썬·패키지 관리자)
#   <뿌리>\python  uv 가 받은 Python
#
# <뿌리> 는 %LOCALAPPDATA%\LocalTranslator. 사용자 이름이 한글이면 C:\LocalTranslator
# (의존성 하나가 한글 경로에서 파일을 못 읽는다).
#
# 이 파일은 UTF-8 BOM 으로 저장해야 Windows PowerShell 5.1 이 한글을 바르게 읽는다.

param(
    [string]$Root = "",
    [switch]$NoShortcut,
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"     # Invoke-WebRequest 가 훨씬 빨라진다
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

$AppName = "로컬 번역기"
$Src = Split-Path -Parent $PSScriptRoot      # tools\ 의 부모 = 받은 앱 폴더

function Step($msg) { Write-Host ""; Write-Host "▶ $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host ""; Write-Host "✗ $msg" -ForegroundColor Red; exit 1 }
function IsAscii($s) { return $s -notmatch '[^\x00-\x7F]' }
function Check($what) { if ($LASTEXITCODE -ne 0) { Fail "$what 에 실패했어요 (코드 $LASTEXITCODE). 인터넷 연결을 확인하고 다시 실행해 주세요" } }

Write-Host "$AppName 설치" -ForegroundColor White
Write-Host "Python 과 앱을 설치해요. AI 는 앱이 켜지면 '다운로드' 화면에서 받아요."

if (-not $Root) {
    $Root = Join-Path $env:LOCALAPPDATA "LocalTranslator"
    if (-not (IsAscii $Root)) { $Root = Join-Path $env:SystemDrive "LocalTranslator" }
}
if (-not (IsAscii $Root)) { Fail "설치 폴더에 한글이 없어야 해요: $Root" }
$App = Join-Path $Root "app"
$Venv = Join-Path $Root "venv"
$UvDir = Join-Path $Root "uv"
$Uv = Join-Path $UvDir "uv.exe"
New-Item -ItemType Directory -Force -Path $Root | Out-Null
Write-Host "설치 폴더: $Root"

# 1. 앱 복사 (내 설정 config.json 은 남겨 둔다)
Step "앱 파일 복사"
if ((Resolve-Path $Src).Path.TrimEnd('\') -ne $App.TrimEnd('\')) {
    robocopy $Src $App /E /NFL /NDL /NJH /NJS /NP /XD .git __pycache__ .pytest_cache .update_backup venv .venv /XF config.json | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "앱 파일을 복사하지 못했어요 (robocopy $LASTEXITCODE)" }
}

# 2. uv
if (-not (Test-Path $Uv)) {
    Step "uv 받기 (파이썬 관리자)"
    $zip = Join-Path $env:TEMP "uv-$([guid]::NewGuid()).zip"
    try {
        Invoke-WebRequest "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" -OutFile $zip -UseBasicParsing
        Expand-Archive $zip -DestinationPath $UvDir -Force
    } catch { Fail "uv 를 받지 못했어요: $($_.Exception.Message)" }
    finally { Remove-Item $zip -ErrorAction SilentlyContinue }
    $found = Get-ChildItem $UvDir -Recurse -Filter uv.exe | Select-Object -First 1
    if (-not $found) { Fail "uv.exe 를 찾지 못했어요" }
    if ($found.FullName -ne $Uv) { Move-Item $found.FullName $Uv -Force }
}
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Root "python"
$env:UV_CACHE_DIR = Join-Path $Root "uv-cache"
$env:UV_NO_PROGRESS = "1"

# 3. Python + 가상환경
Step "Python 3.12 설치"
& $Uv python install 3.12
Check "Python 설치"
if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) {
    & $Uv venv --python 3.12 $Venv
    Check "가상환경 만들기"
}

# 4. 기본 패키지 (화면·소리)
Step "기본 패키지 설치 (1~2분)"
& $Uv pip install --python $Venv -r (Join-Path $App "requirements.txt")
Check "패키지 설치"

$Pyw = Join-Path $Venv "Scripts\pythonw.exe"
$Main = Join-Path $App "app.py"
$Icon = Join-Path $App "lt\assets\icon.ico"

# 5. 바로가기 (바탕화면 + 시작 메뉴)
if (-not $NoShortcut) {
    Step "바로가기 만들기"
    $shell = New-Object -ComObject WScript.Shell
    $places = @([Environment]::GetFolderPath("Desktop"), (Join-Path ([Environment]::GetFolderPath("Programs")) ""))
    foreach ($dir in $places) {
        $lnk = $shell.CreateShortcut((Join-Path $dir "$AppName.lnk"))
        $lnk.TargetPath = $Pyw
        $lnk.Arguments = "`"$Main`""
        $lnk.WorkingDirectory = $App
        $lnk.IconLocation = $Icon
        $lnk.Description = "들리는 말을 바로 번역해요"
        $lnk.Save()
    }
}

Write-Host ""
Write-Host "✓ 설치했어요. 바탕화면의 '$AppName' 바로가기로 켤 수 있어요." -ForegroundColor Green
Write-Host "  앱이 켜지면 '다운로드' 화면에서 AI 를 받아 주세요."

if (-not $NoLaunch) { Start-Process $Pyw -ArgumentList "`"$Main`"" -WorkingDirectory $App }
exit 0
