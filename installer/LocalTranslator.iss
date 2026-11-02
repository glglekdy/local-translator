; 로컬 번역기 설치 프로그램 (Inno Setup 6). 빌드: tools/build_installer.ps1
;
; 설치 폴더(기본 %LOCALAPPDATA%\LocalTranslator, 관리자 권한 필요 없음):
;   LocalTranslator.exe   실행 파일 (launcher.cs)
;   app\                  앱 (앱 안의 업데이트도 여기에)
;   venv\ python\ uv\     설치 마지막에 tools/install.ps1 이 만든다 (Python + 기본 패키지)
; 무거운 AI(PyTorch·음성 인식·Ollama·번역 모델)는 앱의 '다운로드' 화면에서 받는다.
;
; 이 파일은 UTF-8 BOM 으로 저장한다 (Inno Setup 이 한글을 바르게 읽게).

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef Stage
  #define Stage "..\dist\stage"
#endif
#define MyAppName "로컬 번역기"
#define MyAppExe "LocalTranslator.exe"
#define MyAppId "LocalTranslator.App"

[Setup]
AppId={{219F21F5-D627-41E5-8794-36393974E5A7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=glglekdy
AppPublisherURL=https://github.com/glglekdy/local-translator
AppSupportURL=https://github.com/glglekdy/local-translator/issues
AppUpdatesURL=https://github.com/glglekdy/local-translator/releases
VersionInfoVersion={#MyAppVersion}
DefaultDirName={localappdata}\LocalTranslator
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=LocalTranslator-Setup-{#MyAppVersion}
SetupIconFile={#Stage}\app\lt\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
; Inno Setup 6.7 부터 기본으로 켜는 RedirectionGuard 는 일반 사용자가 만든 폴더 링크(junction)를 막는다.
; 설치 마지막에 uv 가 Python 을 설치하며 그런 링크를 만들고 쓰므로 끈다 (제거할 때 그 링크를 지우는 데도 필요).
; 관리자 권한으로 도는 설치 프로그램을 노린 공격을 막는 기능이라, 사용자 권한으로만 도는 이 설치에는 해당 없음
RedirectionGuard=no
LicenseFile={#Stage}\app\LICENSE

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "바로가기:"

[Files]
Source: "{#Stage}\{#MyAppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Stage}\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}\app"; AppUserModelID: "{#MyAppId}"; Comment: "들리는 말을 바로 번역해요"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}\app"; AppUserModelID: "{#MyAppId}"; Comment: "들리는 말을 바로 번역해요"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "로컬 번역기 실행"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 설치 뒤에 생긴 것들 (가상환경, Python, 앱 업데이트·설정, 받은 AI 라이브러리)
Type: filesandordirs; Name: "{app}\venv"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\uv"
Type: filesandordirs; Name: "{app}\uv-cache"
Type: filesandordirs; Name: "{app}\app"
Type: files; Name: "{app}\install.log"

[Code]
function IsAscii(const S: String): Boolean;
var
  I: Integer;
begin
  Result := True;
  for I := 1 to Length(S) do
    if Ord(S[I]) > 127 then
    begin
      Result := False;
      Exit;
    end;
end;

procedure InitializeWizard();
begin
  { 사용자 이름이 한글이면 기본 폴더에 한글이 들어간다: 의존성 하나가 한글 경로를 못 읽으므로 C:\ 아래로 }
  if not IsAscii(WizardForm.DirEdit.Text) then
    WizardForm.DirEdit.Text := ExpandConstant('{sd}\LocalTranslator');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpSelectDir) and not IsAscii(WizardDirValue) then
  begin
    MsgBox('설치 폴더 경로에 한글 등 영문이 아닌 글자가 있으면 안 돼요.' + #13#10 +
           '예: C:\LocalTranslator', mbError, MB_OK);
    Result := False;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Code: Integer;
  Dirs: array of String;
  I: Integer;
  Path: String;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  { [UninstallDelete] 가 못 지운 것 정리: PyTorch 처럼 경로가 아주 깊은 파일(260자 넘음)은
    \\?\ 접두어를 붙인 rd 로만 지워진다 }
  Dirs := ['venv', 'python', 'uv', 'uv-cache', 'app'];
  for I := 0 to GetArrayLength(Dirs) - 1 do
  begin
    Path := ExpandConstant('{app}\') + Dirs[I];
    if DirExists(Path) then
      Exec(ExpandConstant('{cmd}'), '/c rd /s /q "\\?\' + Path + '"', '', SW_HIDE, ewWaitUntilTerminated, Code);
  end;
  RemoveDir(ExpandConstant('{app}'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
  Params, Log: String;
begin
  if CurStep <> ssPostInstall then
    Exit;
  Log := ExpandConstant('{app}\install.log');
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\app\tools\install.ps1') +
            '" -Root "' + ExpandConstant('{app}') + '" -NoShortcut -NoLaunch -LogFile "' + Log + '"';
  WizardForm.StatusLabel.Caption := 'Python 과 기본 패키지를 설치하는 중… (인터넷 필요, 1~3분)';
  WizardForm.FilenameLabel.Caption := '';
  WizardForm.ProgressGauge.Style := npbstMarquee;
  try
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params, '', SW_HIDE,
                ewWaitUntilTerminated, Code) then
      Code := -1;
  finally
    WizardForm.ProgressGauge.Style := npbstNormal;
  end;
  if Code <> 0 then
    SuppressibleMsgBox('Python 과 기본 패키지를 설치하지 못했어요 (코드 ' + IntToStr(Code) + ').' + #13#10 +
                       '인터넷 연결을 확인하고 설치 프로그램을 다시 실행해 주세요.' + #13#10#13#10 +
                       '기록: ' + Log, mbError, MB_OK, IDOK);
end;
