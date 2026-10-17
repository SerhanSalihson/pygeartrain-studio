"""Screenshots of chosen tabs for one preset: python tests/shots.py OUT TYPE PRESET THEME TAB[,TAB..] [explode]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication
out, type_name, preset, theme, tabs = sys.argv[1:6]
explode = float(sys.argv[6]) if len(sys.argv) > 6 else 0
app = QApplication(sys.argv); app.setStyle('Fusion')
from gearstudio.ui import theme as _th; _th.load_fonts(); app.setFont(_th.ui_font())
QSettings.setDefaultFormat(QSettings.IniFormat); QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, out)
from gearstudio.ui.main_window import MainWindow
w = MainWindow(); w.resize(1480, 920); w.show()
w.set_type(type_name); w.apply_preset(preset); w.set_theme_pref(theme); w.playing = False
w.input_angle = 2.0
w.view3d.explode_slider.setValue(int(explode * 100))
tabs = [int(t) for t in tabs.split(',')]
def shoot(i=0):
    if i:
        w.grab().save(os.path.join(out, f'shot_{theme}_{tabs[i - 1]}.png'))
    if i == len(tabs):
        w.modified = False; w.close(); app.quit(); return
    w.tabs.setCurrentIndex(tabs[i]); w.update_frame()
    if tabs[i] == 5: w.sweep_page.compute()
    QTimer.singleShot(1500, lambda: shoot(i + 1))
QTimer.singleShot(800, shoot)
app.exec()
