// 로컬 번역기.exe: 설치 폴더의 가상환경으로 앱을 켜는 작은 실행 파일.
// 시작 메뉴·바탕화면·작업 표시줄 고정이 이 파일을 가리킨다 (python 이 아니라 앱 이름과 아이콘으로 보이게).
//
//   <설치 폴더>\LocalTranslator.exe   ← 이것
//   <설치 폴더>\app\app.py
//   <설치 폴더>\venv\Scripts\pythonw.exe
//
// 빌드: tools/build_installer.ps1 (Windows 에 들어 있는 csc.exe 로 컴파일)
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("로컬 번역기")]
[assembly: AssemblyProduct("로컬 번역기")]
[assembly: AssemblyDescription("들리는 말을 바로 번역해요")]

static class Launcher
{
    [STAThread]
    static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string pythonw = Path.Combine(root, "venv", "Scripts", "pythonw.exe");
        string appDir = Path.Combine(root, "app");
        string main = Path.Combine(appDir, "app.py");
        if (!File.Exists(pythonw) || !File.Exists(main))
        {
            MessageBox.Show("설치가 끝나지 않았어요.\n설치 프로그램을 다시 실행해 주세요.\n\n(" + root + ")",
                            "로컬 번역기", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        var psi = new ProcessStartInfo(pythonw, "\"" + main + "\"");
        psi.WorkingDirectory = appDir;
        psi.UseShellExecute = false;
        try
        {
            Process.Start(psi);
        }
        catch (Exception e)
        {
            MessageBox.Show("앱을 켜지 못했어요: " + e.Message, "로컬 번역기", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        return 0;
    }
}
