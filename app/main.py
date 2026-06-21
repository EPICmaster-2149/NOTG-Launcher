import argparse
import multiprocessing
import sys
from pathlib import Path

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
    parser.add_argument("--run-updater")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--player-name", default="")
    parser.add_argument("--restore-instance")
    parser.add_argument("--restore-page")
    parser.add_argument("--skip-startup-intro", action="store_true")
    return parser.parse_args()


def main():
    args = _parse_args()
    if args.monitor_session:
        if not args.pid:
            return 1
        return run_session_monitor(args.monitor_session, args.pid, args.player_name)

    try:
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    except AttributeError:
        QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if args.run_updater:
        app = QApplication([])
        app.setApplicationName("NOTG Launcher Updater")
        from ui.startup_screen import run_update_manifest

        return run_update_manifest(Path(args.run_updater))

    service = LauncherService()
    if getattr(sys, "frozen", False):
        from core.updater import UpdateInstaller
        try:
            UpdateInstaller(sys.executable, str(service.cache_root)).cleanup_stale_update_artifacts()
        except Exception:
            # Startup should continue even if a previous update left locked files.
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

    from ui.startup_screen import DEVELOPER_ACCOUNT_NAME, run_startup_intro_with_preload, should_show_startup_intro

    developer_mode = service.get_player_name() == DEVELOPER_ACCOUNT_NAME
    restore_payload = restore_request if args.restore_instance or args.restore_page else None

    def build_main_window():
        from ui.main_window import MainWindow

        return MainWindow(service=service, restore_request=restore_payload)

    if not args.skip_startup_intro and should_show_startup_intro(service, developer_mode):
        run_startup_intro_with_preload(service, developer_mode=developer_mode, preload=lambda: True)
    window = build_main_window()

    ipc_server = LauncherIpcServer(service.launcher_ipc_file, window)
    ipc_server.message_received.connect(window.handle_ipc_message)
    ipc_server.start()
    app.aboutToQuit.connect(ipc_server.stop)
    window.show()

    return app.exec()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
