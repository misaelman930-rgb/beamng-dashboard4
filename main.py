"""
BeamNG Radio — точка входа.

Запуск:  python main.py

Если приложение не запускается, причина записывается в crash.log
(папка настроек: %APPDATA%\\BeamNGRadio) и показывается окном.
"""
import os
import sys
import traceback
from datetime import datetime


def _prepare_vlc_path() -> None:
    """
    python-vlc ищет libvlc сам, но на нестандартных установках и в .exe
    надёжнее явно добавить папку VLC в пути поиска DLL.
    """
    if not sys.platform.startswith("win"):
        return
    candidates = [
        os.environ.get("VLC_PATH", ""),
        r"C:\Program Files\VideoLAN\VLC",
        r"C:\Program Files (x86)\VideoLAN\VLC",
    ]
    for c in candidates:
        if c and os.path.exists(os.path.join(c, "libvlc.dll")):
            os.environ["PATH"] = c + os.pathsep + os.environ.get("PATH", "")
            os.environ.setdefault("PYTHON_VLC_LIB_PATH", os.path.join(c, "libvlc.dll"))
            os.environ.setdefault("PYTHON_VLC_MODULE_PATH", os.path.join(c, "plugins"))
            try:
                os.add_dll_directory(c)
            except (AttributeError, OSError):
                pass
            break


def _report_fatal(text: str) -> None:
    """Пишет crash.log и показывает окно (если Qt уже работает)."""
    log_path = None
    try:
        from radio.settings import config_dir
        log_path = config_dir() / "crash.log"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} ===\n{text}\n")
    except Exception:                      # noqa: BLE001
        pass
    print(text, file=sys.stderr)
    where = f"\n\nЛог: {log_path}" if log_path else ""
    message = text[-3000:] + where
    if sys.platform.startswith("win"):
        # Нативное окно Windows: работает даже когда PySide6 не установлен.
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, "BeamNG Radio — ошибка запуска", 0x10)
            return
        except Exception:                  # noqa: BLE001
            pass
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is None:
            QApplication(sys.argv)
        QMessageBox.critical(None, "BeamNG Radio — ошибка запуска", message)
    except Exception:                      # noqa: BLE001
        pass


def main() -> int:
    _prepare_vlc_path()
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        _report_fatal("PySide6 не установлен. Выполните: pip install -r requirements.txt\n"
                      + traceback.format_exc())
        return 1
    try:
        from radio.controller import Controller
        from radio.settings import Settings
        from radio.stations import StationStore
        from radio.ui.main_window import MainWindow
        from radio.ui.styles import QSS

        app = QApplication(sys.argv)
        app.setApplicationName("BeamNG Radio")
        app.setStyleSheet(QSS)

        settings = Settings()
        store = StationStore()
        ctrl = Controller(settings, store)
        win = MainWindow(ctrl)
        win.show()
        ctrl.start()
        return app.exec()
    except Exception:                      # noqa: BLE001 — любой сбой на старте
        _report_fatal(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
