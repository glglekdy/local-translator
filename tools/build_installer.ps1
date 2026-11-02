# 릴리스 파일 만들기 → dist\
#   LocalTranslator-Setup-<버전>.exe   설치 프로그램 (사용자가 받는 것)
#   LocalTranslator-<버전>.zip         앱 안의 업데이트가 받는 것
#
# 커밋된 코드(HEAD)로 만든다. 필요한 것: git, Inno Setup 6 (winget install JRSoftware.InnoSetup)
# 쓰는 법: powershell -ExecutionPolicy Bypass -File tools\build_installer.ps1
#
# 이 파일은 UTF-8 BOM 으로 저장한다 (Windows PowerShell 5.1 이 한글을 바르게 읽게).

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

$Version = (Select-String -Path "lt\__init__.py" -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
if (-not $Version) { throw "lt\__init__.py 에서 버전을 찾지 못했어요" }
Write-Host "로컬 번역기 $Version 빌드" -ForegroundColor White
if (git status --porcelain) { Write-Host "! 커밋 안 한 변경이 있어요. 커밋된 코드(HEAD)로 만들어요" -ForegroundColor Yellow }

$Dist = Join-Path $Repo "dist"
$Stage = Join-Path $Dist "stage"
Remove-Item $Stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

# 1. 앱 파일: 업데이트용 zip 을 만들고, 그것을 풀어 설치 프로그램에도 똑같이 넣는다
$Zip = Join-Path $Dist "LocalTranslator-$Version.zip"
git archive --format=zip --prefix=LocalTranslator/ -o $Zip HEAD
if ($LASTEXITCODE -ne 0) { throw "git archive 실패" }
Expand-Archive $Zip -DestinationPath $Stage -Force
Rename-Item (Join-Path $Stage "LocalTranslator") "app"

# 2. 실행 파일 (Windows 에 들어 있는 C# 컴파일러)
$Csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
& $Csc /nologo /target:winexe /optimize+ /codepage:65001 "/win32icon:$Stage\app\lt\assets\icon.ico" `
    /r:System.Windows.Forms.dll "/out:$Stage\LocalTranslator.exe" "installer\launcher.cs"
if ($LASTEXITCODE -ne 0) { throw "실행 파일 컴파일 실패" }

# 3. 설치 프로그램
$Iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) { throw "Inno Setup 6 이 없어요: winget install JRSoftware.InnoSetup" }
& $Iscc /Q "/DMyAppVersion=$Version" "/DStage=$Stage" "installer\LocalTranslator.iss"
if ($LASTEXITCODE -ne 0) { throw "설치 프로그램 만들기 실패" }

Remove-Item $Stage -Recurse -Force
Write-Host ""
Get-ChildItem $Dist -File | Where-Object { $_.Name -like "*$Version*" } |
    ForEach-Object { Write-Host ("✓ {0}  ({1:N1} MB)" -f $_.Name, ($_.Length / 1MB)) -ForegroundColor Green }
