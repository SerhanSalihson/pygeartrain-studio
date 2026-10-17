"""Entry point: `python -m gearstudio [design.gearstudio.json] [--tab=2d|3d|kinematics|torque|sizing|sweep]`."""
import ctypes
import os
import sys


def _install_crash_log():
    """A windowed app has no console: send native faults and uncaught exceptions to a log file,
    and show Python errors in a dialog instead of exiting silently."""
    import faulthandler
    import traceback
    folder = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'pyGearTrainStudio')
    try:
        os.makedirs(folder, exist_ok=True)
        log = open(os.path.join(folder, 'crash.log'), 'w', encoding='utf-8')
    except OSError:
        return
    faulthandler.enable(file=log)
    if sys.stderr is None:
        sys.stderr = log

    def hook(kind, value, tb):
        text = ''.join(traceback.format_exception(kind, value, tb))
        log.write(text)
        log.flush()
        try:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(None, 'pyGearTrain Studio', f'pyGearTrain Studio hit an error it could not '
                                 f'recover from:\n\n{value}\n\nThe full report is in {log.name}')
        except Exception:
            pass
    sys.excepthook = hook

    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    verbose = bool(os.environ.get('GS_DEBUG'))      # GS_DEBUG=1 logs every Qt message

    def qt_messages(kind, context, message):   # Qt's own warnings and fatal errors bypass Python
        if verbose or kind in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg, QtMsgType.QtWarningMsg):
            log.write(f'[qt {kind.name}] {message}\n')
            log.flush()
    qInstallMessageHandler(qt_messages)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    _install_crash_log()
    try:    # own taskbar group and icon on Windows instead of python.exe's
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('pyGearTrainStudio.App')
    except (AttributeError, OSError):
        pass
    from PySide6.QtWidgets import QApplication
    app = QApplication(argv)
    app.setApplicationName('pyGearTrain Studio')
    app.setOrganizationName('pyGearTrainStudio')
    app.setStyle('Fusion')
    from gearstudio.ui import theme
    theme.load_fonts()
    app.setFont(theme.ui_font())
    from gearstudio.ui.main_window import MainWindow
    app.setWindowIcon(theme.app_icon())
    tabs = {'2d': 0, '3d': 1, 'kinematics': 2, 'torque': 3, 'sizing': 4, 'sweep': 5}
    tab = next((tabs.get(a.split('=', 1)[1].lower()) for a in argv[1:] if a.startswith('--tab=')), None)
    path = next((a for a in argv[1:] if not a.startswith('--') and os.path.isfile(a)), None)
    win = MainWindow(path)
    if tab is not None:
        win.tabs.setCurrentIndex(tab)
    win.show()
    win._fill_recent()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
