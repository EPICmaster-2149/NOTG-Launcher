import argparse
import multiprocessing
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from core.ipc import LauncherIpcServer, send_ipc_message
from core.launcher import LauncherService
from core.session_monitor import run_session_monitor
from ui.app_icon import application_icon
from ui.theme import apply_theme


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--monitor-session")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--player-name", default="")
    parser.add_argument("--restore-instance")
    parser.add_argument("--restore-page")
    return parser.parse_args()


def main():
    args = _parse_args()
    if args.monitor_session:
        if not args.pid:
            return 1
        return run_session_monitor(args.monitor_session, args.pid, args.player_name)

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    service = LauncherService()
    if getattr(sys, "frozen", False):
        from core.updater import UpdateInstaller
        try:
            UpdateInstaller(sys.executable, str(service.cache_root)).cleanup_stale_update_artifacts()
        except Exception:
            pass

    restore_request = {
        "action": "activate",
        "instance_id": args.restore_instance,
        "page": args.restore_page,
        "activate": True,
    }
    if send_ipc_message(service.launcher_ipc_file, restore_request):
        return 0

    app = QApplication([])
    app.setApplicationName("NOTG Launcher")
    app.setWindowIcon(application_icon(service.project_root))
    apply_theme(app, service.get_theme_mode())

    from ui.main_window import MainWindow

    window = MainWindow(service=service, restore_request=restore_request if args.restore_instance or args.restore_page else None)
    ipc_server = LauncherIpcServer(service.launcher_ipc_file, window)
    ipc_server.message_received.connect(window.handle_ipc_message)
    ipc_server.start()
    app.aboutToQuit.connect(ipc_server.stop)
    window.show()

    return app.exec()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
