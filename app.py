"""로컬 번역기 진입점."""
import sys
import threading

from lt import presync

presync.run()       # 업데이트로 패키지 목록이 바뀌었으면, 패키지를 불러오기 전에 맞춘다

from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lt import NAME, engine, setup_ai, theme  # noqa: E402
from lt.main_window import MainWindow  # noqa: E402


APP_USER_MODEL_ID = "LocalTranslator.App"   # 설치 프로그램의 바로가기와 같은 값 (installer/LocalTranslator.iss)


def main() -> None:
    if sys.platform == "win32":
        # 작업 표시줄이 python 이 아니라 이 앱으로 묶고, 고정하면 바로가기(LocalTranslator.exe)로 다시 켜게
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except (AttributeError, OSError):
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(NAME)
    app.setWindowIcon(QIcon(str(theme.ASSETS / "icon.svg")))
    theme.apply(app)
    if engine.load_config()["engine"] == "ollama":
        # Ollama 가 꺼져 있으면 미리 켜 둔다 (기다리지 않음)
        threading.Thread(target=setup_ai.start_ollama, kwargs={"wait": 0}, daemon=True).start()
    win = MainWindow()
    win.show()
    win.check_setup_later()
    win.check_updates_later()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
