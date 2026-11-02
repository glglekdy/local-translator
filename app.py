"""로컬 번역기 진입점."""
import sys
import threading

from lt import presync

presync.run()       # 업데이트로 패키지 목록이 바뀌었으면, 패키지를 불러오기 전에 맞춘다

from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lt import NAME, engine, setup_ai, theme  # noqa: E402
from lt.main_window import MainWindow  # noqa: E402


def main() -> None:
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
