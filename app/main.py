import multiprocessing
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


def main():
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication([])
    app.setApplicationName("NOTG Launcher")

    style_path = Path(__file__).resolve().parent / "ui" / "styles.qss"
    with style_path.open("r", encoding="utf-8") as file_handle:
        app.setStyleSheet(file_handle.read())

    window = MainWindow()
    window.show()

    app.exec()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
