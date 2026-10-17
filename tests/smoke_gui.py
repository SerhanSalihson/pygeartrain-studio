"""Drive the real window through every gear type, preset, tab and theme; report errors and frame times."""
import os, sys, time, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox
out = sys.argv[1] if len(sys.argv) > 1 else '.'
app = QApplication(sys.argv); app.setStyle('Fusion')
from gearstudio.ui import theme as _th; _th.load_fonts(); app.setFont(_th.ui_font())
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, out)        # keep the user's real settings untouched
from gearstudio.catalog import GEAR_TYPES
from gearstudio.ui.main_window import MainWindow
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Discard)
errors = []
w = MainWindow(); w.resize(1480, 920); w.show(); app.processEvents()
orig = w.status
w.status = lambda m, error=False: (errors.append((w.sidebar.spec.name, m)) if error else None, orig(m, error))
w.playing = False
for name, spec in GEAR_TYPES.items():
    w.set_type(name); app.processEvents()
    for preset in list(spec.presets) or [None]:
        try:
            if preset:
                w.apply_preset(preset); app.processEvents()
            times = {}
            for tab in range(6):
                w.tabs.setCurrentIndex(tab); app.processEvents()
                if tab in (0, 1):
                    t0 = time.perf_counter()
                    for k in range(20):
                        w.input_angle += 0.15; w.update_frame()
                        if tab == 0: w.view2d.repaint()
                        else: w.view3d.quick.grabFramebuffer() if k % 10 == 0 else app.processEvents()
                    times[tab] = (time.perf_counter() - t0) / 20 * 1000
            w.sweep_page.compute()
            print(f"{name + '|' + str(preset):56s} ratio={w.scene.ratio_in:9.4g} 2D={times[0]:5.1f}ms 3D={times[1]:5.1f}ms", flush=True)
        except Exception:
            errors.append((name, preset, traceback.format_exc()))
for theme in ('dark', 'light'):
    w.set_theme_pref(theme); app.processEvents()
    for tab in range(6):
        w.tabs.setCurrentIndex(tab); app.processEvents(); w.update_frame(); app.processEvents()
        w.grab().save(os.path.join(out, f'smoke_{theme}_{tab}.png'))
w.set_theme_pref('system')
print('ERRORS:', errors)
w.modified = False; w.close()
