"""Main window: toolbar, sidebar, view/analysis tabs, animation transport, files and exports."""
import ctypes
import math
import os
import time

import numpy as np
from PySide6.QtCore import QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QFont, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QSlider, QSplitter, QTabWidget, QToolButton, QVBoxLayout,
                               QWidget, QFrame)

from gearstudio import APP_NAME, __version__
from gearstudio import io as gio
from gearstudio.catalog import GEAR_TYPES
from gearstudio.model import BuildError, Scene
from gearstudio.sizing import hob_table, unit_mm_for
from gearstudio.ui import theme as th
from gearstudio.ui.pages import CalculatorPage, KinematicsPage, SizingPage, SweepPage
from gearstudio.ui.sidebar import Sidebar
from gearstudio.ui.view2d import View2D
from gearstudio.ui.view3d import View3D

DEFAULT_TYPE = 'Compound planetary'
DEFAULT_PRESET = 'README 22/7/8 + 21/6/9'
MAX_RECENT = 8


class MainWindow(QMainWindow):
    def __init__(self, open_path=None):
        super().__init__()
        self.settings = QSettings('pyGearTrainStudio', 'pyGearTrainStudio')
        self.theme_pref = self.settings.value('theme', 'system')
        self.theme = th.THEMES['light']
        self.scene = None
        self.transforms = []
        self.path = None
        self.modified = False
        self._loading = False
        self.playing = True
        self.input_angle = 0.0
        self.last_t = time.perf_counter()
        self.sizing_state = {'alpha': 20.0, 'goal': 'od', 'goal_value': 60.0, 'series': 'Common hob stock',
                             'module': None, 'ref_d': 60.0, 'face_width': 8.0, 'backlash': 0.06,
                             'sun_steel': True}
        self.calc_state = {'rpm': 3000.0, 'torque': 1.0, 'efficiency': 100.0}

        self.setWindowIcon(th.app_icon())
        self.setAcceptDrops(True)
        self.resize(1480, 920)
        self._build_ui()
        geo = self.settings.value('geometry')
        if geo is not None:
            self.restoreGeometry(geo)
        QGuiApplication.styleHints().colorSchemeChanged.connect(
            lambda *_: self.theme_pref == 'system' and self.apply_theme())
        self.apply_theme()

        if open_path and os.path.isfile(open_path):
            self.open_design(open_path, ask=False)
        else:
            self.new_design(ask=False)

        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    # ================================================================ UI

    def _build_ui(self):
        self._build_toolbar()
        central = QWidget()
        central.setObjectName('Central')
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(4)
        outer.addWidget(split)

        self.sidebar = Sidebar()
        self.sidebar.typeChanged.connect(lambda name: self.set_type(name))
        self.sidebar.presetChosen.connect(self.apply_preset)
        self.sidebar.designEdited.connect(self.rebuild)
        self.sidebar.fixRequested.connect(self.apply_fix)
        self.sidebar.displayChanged.connect(self.restyle)
        split.addWidget(self.sidebar)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 12, 24, 16)
        rl.setSpacing(12)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(False)
        self.view2d = View2D()
        self.view3d = View3D(on_status=self.status)
        self.kin_page = KinematicsPage()
        self.calc_page = CalculatorPage(self.calc_state, self.sizing_state)
        self.sizing_page = SizingPage(self.sizing_state, self.calc_state)
        self.sweep_page = SweepPage()
        for w, name in ((self.view2d, 'Drawing'), (self.view3d, '3D model'), (self.kin_page, 'Kinematics'),
                        (self.calc_page, 'Speed && torque'), (self.sizing_page, 'Module && hob'),
                        (self.sweep_page, 'Ratio sweep')):
            self.tabs.addTab(w, name)        # '&&' shows a literal '&'
        self.tabs.currentChanged.connect(lambda *_: self.update_frame())
        self.calc_page.changed.connect(self.mark_modified)
        self.calc_page.changed.connect(self.sizing_page.refresh)      # strength check uses the input torque
        self.sizing_page.changed.connect(self.mark_modified)
        self.sizing_page.scaleChanged.connect(self.calc_page.refresh)
        self.sizing_page.scaleChanged.connect(self._title_info)
        self.sweep_page.pick.connect(self.apply_fix)
        rl.addWidget(self.tabs, 1)
        rl.addWidget(self._build_transport())
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([380, 1100])

        self.status_label = QLabel()
        self.statusBar().addWidget(self.status_label, 1)
        self.motion_label = QLabel()
        self.statusBar().addPermanentWidget(self.motion_label)

        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self.toggle_play)
        for i in range(6):
            QShortcut(QKeySequence(f'Ctrl+{i + 1}'), self, activated=lambda i=i: self.tabs.setCurrentIndex(i))

    def _build_toolbar(self):
        tb = self.addToolBar('Main')
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonIconOnly)      # quiet icon buttons; tooltips name them
        self.tb = tb
        self.actions = {}

        def act(key, text, slot, shortcut=None, tip=None):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.setToolTip(tip or text)
            self.actions[key] = a
            return a

        title = QLabel(f' {APP_NAME}   ')
        title.setObjectName('AppTitle')
        tb.addWidget(title)
        tb.addAction(act('new', 'New', lambda: self.new_design(), QKeySequence.New))
        tb.addAction(act('open', 'Open', lambda: self.open_design(), QKeySequence.Open))
        self.recent_menu = QMenu(self)
        rb = QToolButton()
        rb.setToolTip('Recent designs')
        rb.setMenu(self.recent_menu)
        rb.setPopupMode(QToolButton.InstantPopup)
        self.recent_button = rb
        tb.addWidget(rb)
        tb.addAction(act('save', 'Save', self.save, QKeySequence.Save))
        act('save_as', 'Save As…', self.save_as, QKeySequence.SaveAs)
        self.addAction(self.actions['save_as'])
        tb.addSeparator()

        export = QMenu(self)
        export.addAction(act('png', 'Image of current view (PNG)…', self.export_png, 'Ctrl+E'))
        export.addAction(act('gif', 'Animation (GIF)…', self.export_gif))
        export.addSeparator()
        export.addAction(act('stl', 'STL parts + assembly…', self.export_stl))
        export.addAction(act('dxf', 'DXF assembly drawing…', lambda: self.export_dxf(False)))
        export.addAction(act('dxf_parts', 'DXF parts laid out…', lambda: self.export_dxf(True)))
        export.addAction(act('involute', 'Involute gear set (STL + DXF)…', self.export_involute))
        export.addSeparator()
        export.addAction(act('code', 'Copy pygeartrain code', self.copy_code))
        eb = QToolButton()
        eb.setText('Export')
        eb.setObjectName('PrimaryTool')
        eb.setMenu(export)
        eb.setPopupMode(QToolButton.InstantPopup)
        eb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.export_button = eb

        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy().Expanding,
                             spacer.sizePolicy().verticalPolicy().Preferred)
        tb.addWidget(spacer)

        theme_menu = QMenu(self)
        group = QActionGroup(self)
        for key, text in (('system', 'Follow Windows'), ('light', 'Light'), ('dark', 'Dark')):
            a = QAction(text, self, checkable=True)
            a.setChecked(self.theme_pref == key)
            a.triggered.connect(lambda _=False, k=key: self.set_theme_pref(k))
            group.addAction(a)
            theme_menu.addAction(a)
        tbtn = QToolButton()
        tbtn.setToolTip('Theme')
        tbtn.setMenu(theme_menu)
        tbtn.setPopupMode(QToolButton.InstantPopup)
        self.theme_button = tbtn
        tb.addWidget(tbtn)
        tb.addAction(act('about', 'About', self.about))
        tb.addSeparator()
        tb.addWidget(eb)

    def _build_transport(self):
        bar = QFrame()
        bar.setObjectName('Transport')
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 8, 24, 8)
        row.setSpacing(12)
        self.play_btn = QToolButton()
        self.play_btn.setToolTip('Play / pause (Space)')
        self.play_btn.clicked.connect(self.toggle_play)
        self.reset_btn = QToolButton()
        self.reset_btn.setToolTip('Back to the start')
        self.reset_btn.clicked.connect(self.reset_phase)
        row.addWidget(self.play_btn)
        row.addWidget(self.reset_btn)
        row.addWidget(QLabel('Speed'))
        self.speed = QSlider(Qt.Horizontal)
        self.speed.setRange(-200, 100)           # 10^(v/100) input revolutions per second
        self.speed.setValue(-30)
        self.speed.setFixedWidth(140)
        self.speed.valueChanged.connect(self._speed_label)
        row.addWidget(self.speed)
        self.speed_lbl = QLabel()
        self.speed_lbl.setObjectName('Mono')
        self.speed_lbl.setMinimumWidth(96)
        row.addWidget(self.speed_lbl)
        row.addSpacing(10)
        row.addWidget(QLabel('Position'))
        self.pos = QSlider(Qt.Horizontal)
        self.pos.setRange(0, 10000)
        self.pos.sliderMoved.connect(self._scrub)
        self.pos.sliderPressed.connect(lambda: setattr(self, '_scrubbing', True))
        self.pos.sliderReleased.connect(lambda: setattr(self, '_scrubbing', False))
        self._scrubbing = False
        row.addWidget(self.pos, 1)
        self.hud_lbl = QLabel()
        self.hud_lbl.setObjectName('Mono')
        self.hud_lbl.setMinimumWidth(300)
        row.addWidget(self.hud_lbl)
        self._speed_label()
        return bar

    # ================================================================ theme

    def set_theme_pref(self, key):
        self.theme_pref = key
        self.settings.setValue('theme', key)
        self.apply_theme()

    def apply_theme(self):
        pref = self.theme_pref
        dark = pref == 'dark' or (pref == 'system' and
                                  QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark)
        t = self.theme = th.THEMES['dark' if dark else 'light']
        th.activate(t)
        app = QApplication.instance()
        app.setPalette(th.palette(t))
        app.setStyleSheet(th.stylesheet(t))
        rc = th.mpl_style(t)
        ic = t['ink']
        for key, name in (('new', 'new'), ('open', 'open'), ('save', 'save'), ('about', 'info')):
            self.actions[key].setIcon(th.icon(name, ic))
        self.actions['png'].setIcon(th.icon('export', ic))
        self.actions['code'].setIcon(th.icon('code', ic))
        self.recent_button.setIcon(th.icon('recent', ic))
        self.theme_button.setIcon(th.icon('theme', ic))
        self.reset_btn.setIcon(th.icon('reset', ic))
        self._play_icon()
        self.view2d.set_theme(t)
        self.view3d.set_theme(t)
        self.kin_page.set_theme(t, rc)
        self.sizing_page.set_theme(t)
        self.sweep_page.set_theme(t, rc)
        self._titlebar(dark)
        if self.scene:
            self.restyle()

    def _titlebar(self, dark):
        """Dark or light Windows 10/11 title bar to match the theme."""
        try:
            hwnd = int(self.winId())
            value = ctypes.c_int(1 if dark else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
        except (AttributeError, OSError):
            pass

    def showEvent(self, ev):
        super().showEvent(ev)
        self._titlebar(self.theme is th.THEMES['dark'])

    # ================================================================ design

    def set_type(self, name, values=None, cfg=None):
        spec = GEAR_TYPES[name]
        self.sidebar.set_type(spec)
        self.sidebar.set_design(values or spec.defaults(), cfg or spec.default_config)
        self.input_angle = 0.0
        self.rebuild(type_changed=True)

    def apply_preset(self, name):
        spec = GEAR_TYPES[self.sidebar.spec.name]
        values, cfg = spec.presets[name]
        self.sidebar.set_design({**spec.defaults(), **values}, cfg)
        self.input_angle = 0.0
        self.rebuild()

    def apply_fix(self, fix):
        values = {**self.sidebar.values(), **fix}
        self.sidebar.set_design(values, self.sidebar.config())
        self.rebuild()

    def rebuild(self, type_changed=False):
        spec = self.sidebar.spec
        t0 = time.perf_counter()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            scene = Scene(spec.name, self.sidebar.values(), self.sidebar.config())
        except BuildError as e:
            self.sidebar.show_error(str(e))
            self.status(str(e), error=True)
            return
        except Exception as e:      # pygeartrain can fail on extreme geometry; never crash the app
            self.sidebar.show_error(f'pygeartrain could not build this geometry ({e}).')
            self.status(f'Could not build: {e}', error=True)
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.scene = scene
        # a new gear type (or a design without one) gets the recommended module; a loaded file keeps its own
        if spec.sizing.kind == 'involute' and ((type_changed and not self._loading)
                                               or not self.sizing_state.get('module')):
            res = hob_table(scene, self.sizing_state['alpha'], self.sizing_state['goal'],
                            self.sizing_state['goal_value'], self.sizing_state['series'])
            self.sizing_state['module'] = res.rows[res.recommended].module if res.recommended >= 0 else 1.0
        colors = self.member_colors()
        self.view2d.set_scene(scene, colors, keep_view=not type_changed)
        self.view3d.set_scene(scene, colors)
        self.view3d.set_hidden(self.sidebar.hidden)
        self.kin_page.set_scene(scene)
        self.calc_page.set_scene(scene)
        self.sizing_page.set_scene(scene)
        self.sweep_page.set_scene(scene, type_changed)
        self.sidebar.show_result(scene)
        self.sidebar.show_issues(scene.issues())
        self.sidebar.show_members(scene, colors)
        self.restyle(rebuild_members=False)
        self.update_frame()
        n = sum(len(l) for p in scene.parts for l in p.loops)
        self._title_info()
        self.status(f'{spec.name}: {len(scene.members)} members, {len(scene.parts)} parts, {n:,} outline points, '
                    f'built in {1000 * (time.perf_counter() - t0):.0f} ms')
        self.motion_label.setText('motion: analytic' if scene.motion_exact else 'motion: pygeartrain per frame')
        if not self._loading:
            self.mark_modified()

    def _title_info(self):
        """Fields of the 2D sheet's title block."""
        if not self.scene:
            return
        r = self.scene.ratio_in
        self.view2d.title_info = {
            'design': os.path.splitext(os.path.basename(self.path))[0].replace('.gearstudio', '') if self.path
            else 'Untitled',
            'date': time.strftime('%Y-%m-%d'),
            'ratio': f'{r:,.5g} : 1' if abs(r) >= 1 else f'1 : {1 / r:,.5g}',
            'scale': self._scale_text().replace('module ', ''),
        }
        self.view2d.update()

    def member_colors(self):
        s = self.scene
        if self.sidebar.display()['color_mode'] == 'role':
            return [th.ROLE_COLORS[s.role(m.dof)] for m in s.members]
        return [th.MEMBER_COLORS[i % len(th.MEMBER_COLORS)] for i in range(len(s.members))]

    def restyle(self, rebuild_members=True):
        if not self.scene:
            return
        d = self.sidebar.display()
        colors = self.member_colors()
        v = self.view2d
        v.fill, v.show_legend, v.show_ref = d['fill'], d['legend'], d['ref']
        if d['trace'] != v.show_trace:
            v.show_trace = d['trace']
            v.clear_trace()
        v.hidden = set(self.sidebar.hidden)
        v.set_colors(colors)
        self.view3d.set_colors(colors)
        self.view3d.set_hidden(self.sidebar.hidden)
        if rebuild_members:
            self.sidebar.show_members(self.scene, colors)
            self.mark_modified()

    # ================================================================ animation

    def _speed_value(self):
        return 10 ** (self.speed.value() / 100)

    def _speed_label(self):
        self.speed_lbl.setText(f'{self._speed_value():.3g} rev/s')

    def _play_icon(self):
        self.play_btn.setIcon(th.icon('pause' if self.playing else 'play', self.theme['text']))

    def toggle_play(self):
        self.playing = not self.playing
        self.last_t = time.perf_counter()
        self._play_icon()

    def reset_phase(self):
        self.input_angle = 0.0
        self.view2d.clear_trace()
        self.update_frame()

    def _scrub(self, v):
        if self.scene:
            span = max(1.0, abs(self.scene.ratio_in))
            self.input_angle = v / 10000 * span * 2 * math.pi
            self.update_frame(sync_slider=False)

    def tick(self):
        now = time.perf_counter()
        dt = min(now - self.last_t, 0.1)
        self.last_t = now
        if self.playing and self.scene and not self._scrubbing and self.tabs.currentIndex() in (0, 1):
            self.input_angle += 2 * math.pi * self._speed_value() * dt
            self.update_frame()

    def update_frame(self, sync_slider=True):
        s = self.scene
        if s is None:
            return
        phase = s.phase_for_input(self.input_angle)
        self.transforms = s.transforms(phase)
        lab = s.spec.dof_labels
        in_rev, out_rev = self.input_angle / (2 * math.pi), phase / (2 * math.pi)
        hud = (f'{lab.get(s.cfg[0], s.cfg[0])}  {in_rev:10.3f} rev', f'{lab.get(s.cfg[1], s.cfg[1])}  {out_rev:10.4f} rev')
        self.hud_lbl.setText(f'in {in_rev:,.2f} rev  ·  out {out_rev:,.4f} rev')
        tab = self.tabs.currentIndex()
        if tab == 0:
            self.view2d.set_transforms(self.transforms, hud)
        elif tab == 1:
            self.view3d.set_transforms(self.transforms)
        if sync_slider:
            span = max(1.0, abs(s.ratio_in))
            self.pos.blockSignals(True)
            self.pos.setValue(int((in_rev % span) / span * 10000))
            self.pos.blockSignals(False)

    # ================================================================ files

    def mark_modified(self):
        if self._loading:
            return
        self.modified = True
        self._update_title()

    def _update_title(self):
        name = os.path.basename(self.path) if self.path else 'Untitled'
        self.setWindowTitle(f'{name}{" •" if self.modified else ""} — {APP_NAME}')

    def maybe_save(self):
        if not self.modified:
            return True
        r = QMessageBox.question(self, APP_NAME, 'Save changes to this design?',
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def new_design(self, ask=True):
        if ask and not self.maybe_save():
            return
        self._loading = True
        spec = GEAR_TYPES[DEFAULT_TYPE]
        values, cfg = spec.presets[DEFAULT_PRESET]
        self.sizing_state['module'] = None
        self.set_type(DEFAULT_TYPE, {**spec.defaults(), **values}, cfg)
        self._loading = False
        self.path, self.modified = None, False
        self._update_title()

    def design_dict(self):
        disp = dict(self.sidebar.display())
        disp.update(hidden=sorted(self.sidebar.hidden), thickness=self.view3d.thickness,
                    explode=self.view3d.explode, xray=self.view3d.xray)
        return gio.design_to_dict(self.sidebar.spec.name, self.sidebar.values(), self.sidebar.config(),
                                  self.sizing_state, self.calc_state, disp)

    def save(self):
        if not self.path:
            return self.save_as()
        try:
            gio.save_design(self.path, self.design_dict())
        except OSError as e:
            QMessageBox.critical(self, APP_NAME, f'Could not save:\n{e}')
            return False
        self.modified = False
        self._update_title()
        self._title_info()
        self._add_recent(self.path)
        self.status(f'Saved {self.path}')
        return True

    def save_as(self):
        start = self.path or os.path.join(self._last_dir(), 'design.gearstudio.json')
        path, _ = QFileDialog.getSaveFileName(self, 'Save design', start, gio.FILE_FILTER)
        if not path:
            return False
        if not path.lower().endswith('.json'):
            path += '.gearstudio.json'
        self.path = path
        self.settings.setValue('last_dir', os.path.dirname(path))
        return self.save()

    def open_design(self, path=None, ask=True):
        if ask and not self.maybe_save():
            return
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, 'Open design', self._last_dir(), gio.FILE_FILTER)
            if not path:
                return
        try:
            design, warnings = gio.load_design(path)
        except gio.DesignError as e:
            QMessageBox.warning(self, APP_NAME, str(e))
            self._remove_recent(path)
            return
        self._loading = True
        self.sizing_state.update({k: v for k, v in design['sizing'].items() if k in self.sizing_state})
        self.calc_state.update({k: v for k, v in design['calculator'].items() if k in self.calc_state})
        disp = design['display']
        self.sidebar.hidden = set(int(i) for i in disp.get('hidden', []) if isinstance(i, int))
        self.sidebar.set_display(disp)
        v3 = self.view3d
        v3.thick_slider.setValue(int(round(float(disp.get('thickness', v3.thickness)) * 100)))
        v3.explode_slider.setValue(int(round(float(disp.get('explode', v3.explode)) * 100)))
        v3.xray_box.setChecked(bool(disp.get('xray', v3.xray)))
        self.sizing_page.load_state()
        self.calc_page.load_state()
        self.set_type(design['gear_type'], design['values'], design['config'])
        self._loading = False
        self.path, self.modified = path, False
        self._update_title()
        self._add_recent(path)
        self.settings.setValue('last_dir', os.path.dirname(path))
        self.status(f'Opened {path}')
        if warnings:
            QMessageBox.information(self, APP_NAME, 'Some values in this file were adjusted:\n\n• '
                                    + '\n• '.join(warnings))

    def _last_dir(self):
        return self.settings.value('last_dir', os.path.expanduser('~'))

    def _recent(self):
        r = self.settings.value('recent', [])
        return [r] if isinstance(r, str) else list(r or [])

    def _add_recent(self, path):
        r = [p for p in self._recent() if os.path.normcase(p) != os.path.normcase(path)]
        self.settings.setValue('recent', [path] + r[:MAX_RECENT - 1])
        self._fill_recent()

    def _remove_recent(self, path):
        self.settings.setValue('recent', [p for p in self._recent() if p != path])
        self._fill_recent()

    def _fill_recent(self):
        m = self.recent_menu
        m.clear()
        items = self._recent()
        if not items:
            a = m.addAction('No recent designs')
            a.setEnabled(False)
        for p in items:
            a = m.addAction(os.path.basename(p))
            a.setToolTip(p)
            a.triggered.connect(lambda _=False, p=p: self.open_design(p))
        if items:
            m.addSeparator()
            m.addAction('Clear list', lambda: (self.settings.setValue('recent', []), self._fill_recent()))

    def dragEnterEvent(self, ev):
        urls = ev.mimeData().urls()
        if urls and urls[0].toLocalFile().lower().endswith('.json'):
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        self.open_design(ev.mimeData().urls()[0].toLocalFile())

    def closeEvent(self, ev):
        if not self.maybe_save():
            ev.ignore()
            return
        self.settings.setValue('geometry', self.saveGeometry())
        ev.accept()

    # ================================================================ exports

    def unit_mm(self):
        s = self.scene
        if s.spec.sizing.kind == 'involute':
            return unit_mm_for(s, module=self.sizing_state.get('module') or 1.0)
        return unit_mm_for(s, ref_d=self.sizing_state.get('ref_d', 60.0))

    def _scale_text(self):
        if self.scene.spec.sizing.kind == 'involute':
            return f'module m{self.sizing_state.get("module") or 1:g}'
        return f'{self.scene.spec.sizing.ref_label} {self.sizing_state.get("ref_d", 60):g} mm'

    def _default_name(self, ext):
        base = os.path.splitext(os.path.basename(self.path))[0].replace('.gearstudio', '') if self.path else \
            gio.safe_name(self.scene.spec.name)
        return os.path.join(self._last_dir(), base + ext)

    def export_png(self):
        if not self.scene:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Save image', self._default_name('.png'), 'PNG image (*.png)')
        if not path:
            return
        tab = self.tabs.currentIndex()
        if tab == 0:
            img = self.view2d.render_image(self.view2d.width(), self.view2d.height())
        elif tab == 1:
            img = self.view3d.grab_image()
        elif tab in (2, 5):
            page = self.kin_page if tab == 2 else self.sweep_page
            page.canvas.figure.savefig(path, dpi=160)
            self.status(f'Saved {path}')
            return
        else:
            img = self.tabs.currentWidget().grab().toImage()
        img.save(path)
        self.status(f'Saved {path}')

    def export_gif(self):
        if not self.scene:
            return
        if self.tabs.currentIndex() not in (0, 1):
            self.tabs.setCurrentIndex(0)
        frames, ok = QInputDialog.getInt(self, 'Save animation', 'Frames (30 per second, at the current speed):',
                                         90, 10, 900)
        if not ok:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Save animation', self._default_name('.gif'), 'GIF (*.gif)')
        if not path:
            return
        from PIL import Image
        was = self.playing
        self.playing = False
        start = self.input_angle
        step = 2 * math.pi * self._speed_value() / 30
        imgs = []
        three_d = self.tabs.currentIndex() == 1
        for k in range(frames):
            self.input_angle = start + k * step
            self.update_frame(sync_slider=False)
            if three_d:
                QApplication.processEvents()
                q = self.view3d.grab_image()
            else:
                q = self.view2d.render_image(self.view2d.width(), self.view2d.height(), scale=1.0)
            q = q.convertToFormat(q.Format.Format_RGBA8888)
            arr = np.frombuffer(q.constBits(), np.uint8).reshape(q.height(), q.bytesPerLine() // 4, 4)
            imgs.append(Image.fromarray(arr[:, :q.width(), :3].copy()).convert('P', palette=Image.ADAPTIVE,
                                                                               colors=96))
            if k % 10 == 0:
                self.status(f'Rendering frame {k + 1} of {frames}…')
                QApplication.processEvents()
        imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=33, loop=0, optimize=True)
        self.input_angle = start
        self.playing = was
        self.update_frame()
        self.status(f'Saved {path}')

    def export_stl(self):
        if not self.scene:
            return
        folder = QFileDialog.getExistingDirectory(self, 'Folder for STL files', self._last_dir())
        if not folder:
            return
        face = self.sizing_state.get('face_width', 8.0)
        try:
            paths = gio.export_stl(self.scene, folder, self.transforms, self.unit_mm(), face,
                                   gap_mm=face * self.view3d.explode)
        except OSError as e:
            QMessageBox.critical(self, APP_NAME, f'Could not write STL files:\n{e}')
            return
        self._exported(folder, f'Wrote {len(paths)} STL files at {self._scale_text()}, {face:g} mm thick.')

    def export_dxf(self, separate):
        if not self.scene:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Save DXF', self._default_name('_parts.dxf' if separate else '.dxf'),
                                              'DXF drawing (*.dxf)')
        if not path:
            return
        try:
            gio.export_dxf(self.scene, path, self.transforms, self.unit_mm(), separate)
        except OSError as e:
            QMessageBox.critical(self, APP_NAME, f'Could not write DXF:\n{e}')
            return
        self._exported(os.path.dirname(path), f'Wrote {os.path.basename(path)} in millimetres at {self._scale_text()}.')

    def export_involute(self):
        sets = self.sizing_page.gearsets()
        if not sets:
            QMessageBox.information(self, APP_NAME, 'Involute gear sets are available for planetary and compound '
                                    'planetary designs. pygeartrain\'s own (cycloidal) outlines can be exported '
                                    'as STL or DXF instead.')
            return
        bad = [f'{n or "Set"}: {i}' for n, gs in sets for i in gs.issues]
        if bad and QMessageBox.question(self, APP_NAME, 'The involute check reports problems:\n\n• '
                                        + '\n• '.join(bad) + '\n\nExport anyway?') != QMessageBox.Yes:
            return
        folder = QFileDialog.getExistingDirectory(self, 'Folder for the involute gear set', self._last_dir())
        if not folder:
            return
        face = self.sizing_state.get('face_width', 8.0)
        try:
            paths = gio.export_involute(folder, [gs for _, gs in sets], face)
        except OSError as e:
            QMessageBox.critical(self, APP_NAME, f'Could not write the files:\n{e}')
            return
        gs = sets[0][1]
        self._exported(folder, f'Wrote {len(paths)} files: involute m{gs.m:g}, {gs.alpha_deg:g}°, '
                               f'{face:g} mm face, backlash {gs.backlash_each:g} mm per member, planets phased.')

    def _exported(self, folder, text):
        self.status(text)
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText(text)
        open_btn = box.addButton('Open folder', QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def copy_code(self):
        if self.scene:
            QApplication.clipboard().setText(self.scene.spec.code(self.scene.values, self.scene.cfg))
            self.status('Copied an equivalent pygeartrain script to the clipboard.')

    # ================================================================ misc

    def about(self):
        QMessageBox.about(self, f'About {APP_NAME}', f'''
            <h3>{APP_NAME} {__version__}</h3>
            <p>Build, animate and analyse gear trains from
            <a href="https://github.com/EelcoHoogendoorn/pyGearTrain">pygeartrain</a>
            by Eelco Hoogendoorn (MIT licence).</p>
            <p>Built with Qt / PySide6 (LGPL v3), Qt Quick 3D, NumPy, SymPy, Shapely and Matplotlib.</p>
            <p><a href="https://github.com/SerhanSalihson/pygeartrain-studio">github.com/SerhanSalihson/pygeartrain-studio</a></p>
            <p>MIT licence.</p>''')

    def status(self, msg, error=False):
        self.status_label.setText(msg)
        self.status_label.setStyleSheet(f'color: {self.theme["bad"]};' if error else '')
