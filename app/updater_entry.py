from __future__ import annotations

import argparse
import multiprocessing
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from ui.startup_screen import run_update_manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NOTG Launcher silent updater")
    parser.add_argument("--manifest", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication([])
    app.setApplicationName("NOTG Launcher Updater")
    return run_update_manifest(Path(args.manifest))


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())