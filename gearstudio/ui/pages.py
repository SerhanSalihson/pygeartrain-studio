"""Analysis pages: kinematics, speed & torque, sizing & hob, ratio sweep."""
from html import escape

import numpy as np
import sympy
import matplotlib
from matplotlib.lines import Line2D
from matplotlib.mathtext import MathTextParser
from matplotlib.patches import Rectangle
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QPushButton,
                               QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from gearstudio.calc import calculate
from gearstudio.involute import check_strength, sweep
from gearstudio.sizing import PRESSURE_ANGLES, SERIES, hob_table, involute_sets, pin_sizing, unit_mm_for
from gearstudio.ui.theme import ROLE_COLORS
from gearstudio.ui.widgets import Card, ChartCanvas, Table, Tile, label


def scroll_page(inner):
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setWidget(inner)
    return sa


def fmt(x, digits=4):
    if x is None:
        return '–'
    return f'{x:,.{digits}g}'


# ---------------------------------------------------------------------------- kinematics

class KinematicsPage(QWidget):
    def __init__(self):
        super().__init__()
        self.scene = None
        self.theme = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)
        self.canvas = ChartCanvas(4.4)
        lay.addWidget(self.canvas, 3)
        self.table = Table(['Member', 'Role', 'ω / ω_out  (symbolic)', 'ω / ω_out', 'ω / ω_in'], numeric=(3, 4))
        lay.addWidget(self.table)

    def set_theme(self, t, rc):
        self.theme = t
        self.canvas.restyle(rc)
        self.refresh()

    def set_scene(self, scene):
        self.scene = scene
        self.refresh()

    def refresh(self):
        s, t = self.scene, self.theme
        if s is None or t is None:
            return
        cfg = s.cfg
        lab = s.spec.dof_labels
        fig = self.canvas.figure
        fig.clf()
        gs = fig.add_gridspec(2, 1, height_ratios=[1, 3.2], hspace=0.45, left=0.2, right=0.95, top=0.93, bottom=0.12)
        tax = fig.add_subplot(gs[0])
        tax.axis('off')
        txt = (rf'$\frac{{\omega_{{{cfg[0]}}}}}{{\omega_{{{cfg[1]}}}}} = {sympy.latex(s.kin.ratio)} '
               rf'= {sympy.latex(s.ratio_exact)}$')
        if not s.ratio_exact.is_Integer:
            txt += f'   ≈ {s.ratio_in:.6g}'
        try:
            MathTextParser('path').parse(f"${txt.split('$')[1]}$")
        except Exception:
            txt = f'{cfg[0]}/{cfg[1]} = {s.kin.ratio} = {s.ratio_exact}'
        tax.text(0.0, 0.45, txt, fontsize=17, va='center', transform=tax.transAxes, color=t['text'])
        tax.set_title('Gear ratio (input / output)', loc='left', fontsize=10, color=t['muted'])

        bax = fig.add_subplot(gs[1])
        dofs = sorted(s.ratios, key=lambda d: (d != cfg[0], d != cfg[1], d))
        speeds = [s.speed_per_input(d) for d in dofs]
        colors = [ROLE_COLORS[s.role(d)] for d in dofs]
        y = np.arange(len(dofs))[::-1]
        bax.barh(y, speeds, color=colors, alpha=0.9, height=0.62)
        bax.set_yticks(y, [f'{lab.get(d, d)}  [{d}]' for d in dofs])
        bax.axvline(0, color=t['muted'], lw=0.8)
        nz = [abs(v) for v in speeds if abs(v) > 1e-12]
        if nz and max(nz) / min(nz) > 50:
            bax.set_xscale('symlog', linthresh=min(nz))
        for yi, v in zip(y, speeds):
            bax.annotate(f'{v:+.4g}', (v, yi), xytext=(5 if v >= 0 else -5, 0), textcoords='offset points',
                         ha='left' if v >= 0 else 'right', va='center', fontsize=9, color=t['text'], clip_on=False)
        if bax.get_xscale() == 'linear':
            lo, hi = min(speeds + [0]), max(speeds + [0])
            pad = (hi - lo) * 0.2 or 1
            bax.set_xlim(lo - pad, hi + pad)
        bax.set_xlabel('Revolutions per input revolution (fixed frame)')
        bax.set_title('Member speeds', loc='left', fontsize=10, color=t['muted'])
        bax.legend(handles=[Line2D([], [], color=c, lw=8, label=r) for r, c in ROLE_COLORS.items()],
                   loc='lower right', bbox_to_anchor=(1.0, 1.0), fontsize=8.5, frameon=False, ncol=4)
        for sp in ('top', 'right'):
            bax.spines[sp].set_visible(False)
        bax.grid(axis='x', alpha=0.6)
        bax.set_axisbelow(True)
        self.canvas.draw_idle()

        rows = []
        for d in dofs:
            rows.append((f'{lab.get(d, d)}  [{d}]', s.role(d), sympy.sstr(sympy.simplify(s.kin.solve[d])),
                         f'{s.ratios[d]:.6g}', f'{s.speed_per_input(d):.6g}'))
        self.table.fill(rows, colors={(r, 1): QColor(ROLE_COLORS[s.role(d)]) for r, d in enumerate(dofs)})


# ---------------------------------------------------------------------------- speed & torque

class CalculatorPage(QWidget):
    changed = Signal()

    def __init__(self, state, sizing_state):
        super().__init__()
        self.state = state
        self.sizing_state = sizing_state     # the module in use comes from the Module & hob page
        self.scene = None
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(28, 24, 28, 28)
        lay.setSpacing(20)

        card = Card('What drives it')
        row = QHBoxLayout()
        self.rpm = self._spin(0, 1e6, state.get('rpm', 3000), ' rpm', 0)
        self.torque = self._spin(0, 1e6, state.get('torque', 1.0), ' N·m', 3)
        self.eff = self._spin(1, 100, state.get('efficiency', 100), ' %', 1)
        for text, w in (('Input speed', self.rpm), ('Input torque', self.torque), ('Efficiency', self.eff)):
            box = QVBoxLayout()
            box.addWidget(label(text, 'TileLabel'))
            box.addWidget(w)
            row.addLayout(box)
        row.addStretch(1)
        card.lay.addLayout(row)
        card.add(label('Rigid gears; the efficiency applies to the train as a whole. Positive values turn the '
                       'same way as the input.', 'Hint', wrap=True))
        lay.addWidget(card)

        tiles = QGridLayout()
        tiles.setSpacing(16)
        self.t_speed = Tile('Output speed')
        self.t_torque = Tile('Output torque')
        self.t_power = Tile('Output power')
        self.t_react = Tile('Reaction torque')
        for i, t in enumerate((self.t_speed, self.t_torque, self.t_power, self.t_react)):
            tiles.addWidget(t, 0, i)
        lay.addLayout(tiles)

        card = Card('How fast each member turns')
        self.members = Table(['Member', 'Role', 'Speed (rpm)', 'Direction'], numeric=(2,))
        card.add(self.members)
        lay.addWidget(card)

        self.mesh_card = Card('At each gear mesh')
        self.mesh_hint = label('', 'Hint', wrap=True)
        self.mesh_card.add(self.mesh_hint)
        self.meshes = Table(['Mesh', 'Pitch Ø (mm)', 'Pitch-line speed (m/s)', 'Mesh frequency (Hz)',
                             'Tangential force (N)'], numeric=(1, 2, 3, 4))
        self.mesh_card.add(self.meshes)
        lay.addWidget(self.mesh_card)
        lay.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll_page(inner))

    def _spin(self, lo, hi, value, suffix, decimals):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(decimals)
        s.setValue(value)
        s.setSuffix(suffix)
        s.setMinimumWidth(150)
        s.setKeyboardTracking(False)
        s.valueChanged.connect(self._edited)
        return s

    def _edited(self):
        self.state.update(rpm=self.rpm.value(), torque=self.torque.value(), efficiency=self.eff.value())
        self.changed.emit()
        self.refresh()

    def load_state(self):
        for w, k in ((self.rpm, 'rpm'), (self.torque, 'torque'), (self.eff, 'efficiency')):
            w.blockSignals(True)
            w.setValue(self.state.get(k, w.value()))
            w.blockSignals(False)
        self.refresh()

    def set_scene(self, scene):
        self.scene = scene
        self.refresh()

    def refresh(self):
        s = self.scene
        if s is None:
            return
        module = (self.sizing_state.get('module') or 1.0) if s.spec.sizing.kind == 'involute' else None
        r = calculate(s, self.rpm.value(), self.torque.value(), self.eff.value() / 100, module)
        self.t_speed.set(f'{fmt(r.output_rpm)} rpm', f'ratio {r.ratio:,.5g} : 1')
        self.t_torque.set(f'{fmt(r.output_torque)} N·m', 'opposite sense to input' if r.output_torque < 0 else '')
        self.t_power.set(f'{fmt(r.power_out)} W', f'input {fmt(r.power_in)} W')
        self.t_react.set(f'{fmt(r.reaction)} N·m', r.reaction_label)
        self.members.fill([(m.label, m.role, f'{m.rpm:,.5g}',
                            'held' if abs(m.rpm) < 1e-9 else ('same as input' if m.rpm > 0 else 'reversed'))
                           for m in r.members],
                          colors={(i, 1): QColor(ROLE_COLORS[m.role]) for i, m in enumerate(r.members)})
        if s.spec.sizing.kind != 'involute':
            self.mesh_card.setVisible(False)
            return
        self.mesh_card.setVisible(True)
        self.mesh_hint.setText(f'Using module m{module:g} from the Module & hob page.')
        self.meshes.fill([(m.name, f'{m.pitch_d:.4g}', f'{m.speed:.4g}', f'{m.frequency:,.5g}',
                           fmt(m.force) if m.force is not None else '–') for m in r.meshes])


# ---------------------------------------------------------------------------- sizing & hob

GOALS = [('od', 'Fit inside a diameter', ' mm'), ('centre', 'Hit a centre distance', ' mm'),
         ('module', 'Use a module', '')]


class SizingPage(QWidget):
    changed = Signal()
    scaleChanged = Signal()

    def __init__(self, state, calc_state=None):
        super().__init__()
        self.state = state
        self.calc_state = calc_state if calc_state is not None else {}   # input torque for the strength check
        self.scene = None
        self.theme = None
        self.result = None
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(28, 24, 28, 28)
        lay.setSpacing(20)

        # --- involute inputs
        self.inv_card = Card('Which module, which hob')
        form = QHBoxLayout()
        self.alpha = QComboBox()
        for a in PRESSURE_ANGLES:
            self.alpha.addItem(f'{a:g}°', a)
        self.goal = QComboBox()
        for key, text, _ in GOALS:
            self.goal.addItem(text, key)
        self.value = QDoubleSpinBox()
        self.value.setRange(0.05, 5000)
        self.value.setDecimals(3)
        self.value.setKeyboardTracking(False)
        self.series = QComboBox()
        self.series.addItems(list(SERIES))
        for text, w in (('Pressure angle', self.alpha), ('Sizing goal', self.goal), ('Target', self.value),
                        ('Module series', self.series)):
            box = QVBoxLayout()
            box.addWidget(label(text, 'TileLabel'))
            box.addWidget(w)
            form.addLayout(box)
        form.addStretch(1)
        self.inv_card.lay.addLayout(form)
        lay.addWidget(self.inv_card)

        self.banner = QWidget()
        self.banner.setObjectName('BannerWrap')
        b = QHBoxLayout(self.banner)
        b.setContentsMargins(0, 0, 0, 0)
        frame = QFrame()
        frame.setObjectName('Banner')
        fl = QHBoxLayout(frame)
        fl.setContentsMargins(24, 18, 24, 18)
        txt = QVBoxLayout()
        self.rec_title = label('', 'TileValue')
        self.rec_sub = label('', 'Muted', wrap=True)
        txt.addWidget(self.rec_title)
        txt.addWidget(self.rec_sub)
        fl.addLayout(txt, 1)
        self.use_btn = QPushButton('Use this module')
        self.use_btn.setObjectName('Primary')
        self.use_btn.clicked.connect(self._use_recommended)
        fl.addWidget(self.use_btn)
        b.addWidget(frame)
        lay.addWidget(self.banner)

        self.table_card = Card('Every standard module')
        self.table_hint = label('Double-click a row to use that module. The module in use sets the scale of '
                                'STL/DXF exports and the speeds on the Speed & torque page.', 'Hint', wrap=True)
        self.table_card.add(self.table_hint)
        self.table = Table([])
        self.table.cellDoubleClicked.connect(self._use_row)
        self.table_card.add(self.table)
        lay.addWidget(self.table_card)

        # --- pin-type inputs
        self.pin_card = Card('Pin ring size')
        row = QHBoxLayout()
        self.ref_d = QDoubleSpinBox()
        self.ref_d.setRange(1, 5000)
        self.ref_d.setDecimals(2)
        self.ref_d.setSuffix(' mm')
        self.ref_d.setKeyboardTracking(False)
        self.ref_label = label('Pin circle Ø', 'TileLabel')
        box = QVBoxLayout()
        box.addWidget(self.ref_label)
        box.addWidget(self.ref_d)
        row.addLayout(box)
        row.addStretch(1)
        self.pin_card.lay.addLayout(row)
        tiles = QGridLayout()
        self.p_pin, self.p_dowel, self.p_ecc, self.p_env = (Tile('Pin Ø'), Tile('Nearest dowel pin'),
                                                            Tile('Eccentricity'), Tile('Envelope Ø'))
        for i, t in enumerate((self.p_pin, self.p_dowel, self.p_ecc, self.p_env)):
            tiles.addWidget(t, 0, i)
        self.pin_card.lay.addLayout(tiles)
        self.pin_table = Table(['Dowel pin Ø (mm)', 'Pin circle Ø for an exact fit (mm)'], numeric=(0, 1))
        self.pin_table.cellDoubleClicked.connect(self._use_dowel)
        self.pin_hint = self.pin_card.add(label('Double-click a row to size the drive around that dowel pin.',
                                                'Hint'))
        self.pin_card.add(self.pin_table)
        lay.addWidget(self.pin_card)

        # --- common
        card = Card('Part thickness')
        row = QHBoxLayout()
        self.face = QDoubleSpinBox()
        self.face.setRange(0.1, 1000)
        self.face.setDecimals(2)
        self.face.setSuffix(' mm')
        self.face.setKeyboardTracking(False)
        box = QVBoxLayout()
        box.addWidget(label('Face width (plate thickness for STL)', 'TileLabel'))
        box.addWidget(self.face)
        row.addLayout(box)
        row.addStretch(1)
        card.lay.addLayout(row)
        self.scale_label = label('', 'Muted', wrap=True)
        card.add(self.scale_label)
        lay.addWidget(card)

        # --- involute check (planetary types): gearstudio.involute, shared with actgen
        self.check_card = Card('Involute set at this module')
        row = QHBoxLayout()
        self.backlash = QDoubleSpinBox()
        self.backlash.setRange(0, 1)
        self.backlash.setDecimals(3)
        self.backlash.setSingleStep(0.01)
        self.backlash.setSuffix(' mm')
        self.backlash.setKeyboardTracking(False)
        self.sun_mat = QComboBox()
        self.sun_mat.addItem('Steel, cut', True)
        self.sun_mat.addItem('Printed', False)
        for text, w in (('Backlash per member', self.backlash), ('Sun material (tip land)', self.sun_mat)):
            box = QVBoxLayout()
            box.addWidget(label(text, 'TileLabel'))
            box.addWidget(w)
            row.addLayout(box)
        row.addStretch(1)
        self.sweep_btn = QPushButton('Sweep one tooth pitch')
        self.sweep_btn.clicked.connect(self._run_sweep)
        row.addWidget(self.sweep_btn, 0, Qt.AlignBottom)
        self.check_card.lay.addLayout(row)
        self.check_table = Table(['', 'Shift x  sun / planet / ring', 'Tip r  sun / planet', 'Ring tip / root r',
                                  'Contact  s–p / p–r', 'Planet gap', 'Planet phase', 'Ring offset'],
                                 numeric=range(1, 8))
        self.check_card.add(self.check_table)
        self.check_text = label('', wrap=True)
        self.check_text.setTextFormat(Qt.RichText)
        self.check_card.add(self.check_text)
        self.check_card.add(label('Zero-sum profile shift (sun +x, planet and ring −x), tips topped to a minimum land, '
                                  'planets phased for assembly. Strength: Lewis bending with the form factor '
                                  'measured on the generated tooth, load shared over the planets.', 'Hint', wrap=True))
        lay.addWidget(self.check_card)
        self.sweep_result = {}

        self.notes_card = Card('How to make these gears')
        self.notes = label('', wrap=True)
        self.notes.setTextFormat(Qt.RichText)
        self.notes_card.add(self.notes)
        lay.addWidget(self.notes_card)
        lay.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll_page(inner))

        self.load_state()
        for w in (self.alpha, self.goal, self.series):
            w.currentIndexChanged.connect(self._edited)
        for w in (self.value, self.ref_d, self.face, self.backlash):
            w.valueChanged.connect(self._edited)
        self.sun_mat.currentIndexChanged.connect(self._edited)

    # ---------------- state

    def load_state(self):
        st = self.state
        widgets = (self.alpha, self.goal, self.series, self.value, self.ref_d, self.face, self.backlash, self.sun_mat)
        for w in widgets:
            w.blockSignals(True)
        self.alpha.setCurrentIndex(max(0, self.alpha.findData(st.get('alpha', 20.0))))
        self.goal.setCurrentIndex(max(0, self.goal.findData(st.get('goal', 'od'))))
        self.series.setCurrentText(st.get('series', 'Common hob stock'))
        self.value.setValue(st.get('goal_value', 60.0))
        self.ref_d.setValue(st.get('ref_d', 60.0))
        self.face.setValue(st.get('face_width', 8.0))
        self.backlash.setValue(st.get('backlash', 0.06))
        self.sun_mat.setCurrentIndex(0 if st.get('sun_steel', True) else 1)
        for w in widgets:
            w.blockSignals(False)
        self._goal_suffix()
        self.refresh()

    def _goal_suffix(self):
        self.value.setSuffix(dict((k, s) for k, _, s in GOALS)[self.goal.currentData()])
        self.value.setPrefix('m' if self.goal.currentData() == 'module' else '')

    def _edited(self):
        goal_before = self.state.get('goal')
        self.state.update(alpha=self.alpha.currentData(), goal=self.goal.currentData(),
                          series=self.series.currentText(), goal_value=self.value.value(),
                          ref_d=self.ref_d.value(), face_width=self.face.value(),
                          backlash=self.backlash.value(), sun_steel=self.sun_mat.currentData())
        self.sweep_result = {}
        if goal_before != self.state['goal']:
            self._goal_suffix()
        self.changed.emit()
        self.refresh()
        self.scaleChanged.emit()

    def set_theme(self, t):
        self.theme = t
        self.refresh()

    def set_scene(self, scene):
        self.scene = scene
        self.refresh()

    def _use_recommended(self):
        if self.result and self.result.recommended >= 0:
            self._use_module(self.result.rows[self.result.recommended].module)

    def _use_row(self, r, c):
        if self.result:
            self._use_module(self.result.rows[r].module)

    def _use_module(self, m):
        self.state['module'] = m
        self.changed.emit()
        self.scaleChanged.emit()
        self.refresh()

    def _use_dowel(self, r, c):
        item = self.pin_table.item(r, 1)
        if item:
            self.ref_d.setValue(float(item.text().replace(',', '')))

    # ---------------- view

    def refresh(self):
        s, t = self.scene, self.theme
        if s is None or t is None:
            return
        involute = s.spec.sizing.kind == 'involute'
        for w in (self.inv_card, self.banner, self.table_card):
            w.setVisible(involute)
        self.pin_card.setVisible(not involute)
        self._refresh_check(s)
        notes = []
        if involute:
            notes += self._refresh_involute(s, t)
        else:
            notes += self._refresh_pins(s, t)
        self.notes.setText('<ul style="margin-left:-20px">' + ''.join(f'<li style="margin-bottom:6px">{escape(n)}</li>'
                                                                       for n in notes) + '</ul>')

    def _refresh_involute(self, s, t):
        st = self.state
        res = self.result = hob_table(s, st.get('alpha', 20.0), st.get('goal', 'od'), st.get('goal_value', 60.0),
                                      st.get('series', 'Common hob stock'))
        sz = s.spec.sizing
        gears = sz.gears(s.values)
        multi_stage = len(sz.stage_factors(s.values)) > 1
        goal = st.get('goal', 'od')
        headers = ['', 'Module', 'DP'] + (['Stage 2 m'] if multi_stage else []) + ['Centre dist.', 'Envelope Ø']
        headers += [f'{g.name} d / tip' for g in gears]
        if goal == 'centre':
            headers += ['Shift x₁+x₂']
        extra_keys = list(res.rows[0].extra) if res.rows and res.rows[0].extra else []
        headers += extra_keys
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.numeric = set(range(1, len(headers)))
        in_use = st.get('module')
        rows, colors = [], {}
        muted, accent = QColor(t['muted']), QColor(t['accent'])
        for i, r in enumerate(res.rows):
            mark = ('in use' if in_use is not None and abs(r.module - in_use) < 1e-9 else
                    'best' if i == res.recommended else '')
            row = [mark, f'm{r.module:g}', f'{r.dp:.4g}']
            if multi_stage:
                row.append(f'{r.stage_modules[1]:.4g}')
            row += [f'{r.centre:.3f}', f'{r.envelope:.2f}']
            row += [f'{g.d:.3g} / {g.da:.3g}' for g in r.gears]
            if goal == 'centre':
                row.append('–' if r.shift is None else f'{r.shift:+.3f}')
            row += [f'{r.extra[k]:.3g}' for k in extra_keys]
            rows.append(row)
            if not r.fits:
                for c in range(len(row)):
                    colors[(i, c)] = muted
            if i == res.recommended:
                colors[(i, 0)] = accent
        self.table.fill(rows, bold_row=res.recommended, colors=colors)

        if res.recommended >= 0:
            r = res.rows[res.recommended]
            self.rec_title.setText(f'm{r.module:g} hob   ·   DP {r.dp:.3g}')
            target = st.get('goal_value', 60)
            if goal == 'od':
                why = f'largest standard module whose envelope fits Ø{target:g} mm'
            elif goal == 'centre':
                why = f'needs the least profile shift ({r.shift:+.3f}) for a {target:g} mm centre distance'
            else:
                why = 'the module you chose'
            self.rec_sub.setText(f'{why[0].upper() + why[1:]}. Envelope Ø{r.envelope:.1f} mm, centre distance '
                                 f'{r.centre:.2f} mm.' + (f' Exact module for the goal: {res.exact_module:.4g}.'
                                                          if res.exact_module else ''))
            self.use_btn.setText(f'Use m{r.module:g}')
            self.use_btn.setEnabled(True)
        else:
            self.rec_title.setText('No standard module meets this goal')
            self.rec_sub.setText(f'Exact module needed: {res.exact_module:.4g}. Try another series or goal.'
                                 if res.exact_module else 'Try another series or goal.')
            self.use_btn.setEnabled(False)

        m = st.get('module')
        if m:
            unit = unit_mm_for(s, module=m)
            self.scale_label.setText(f'In use: <b>m{m:g}</b>, envelope Ø{2 * s.extent * unit:.1f} mm. Exports '
                                     f'and the Speed & torque page use this scale.')
        else:
            self.scale_label.setText('Pick a module (double-click a row, or Use) to set the physical scale.')
        notes = list(res.gear_notes)
        chosen = next((r for r in res.rows if m and abs(r.module - m) < 1e-9), None) or \
            (res.rows[res.recommended] if res.recommended >= 0 else None)
        if chosen:
            notes += chosen.notes
        notes += res.notes
        return notes

    def gearsets(self):
        """The current design's involute gear sets at the module in use ([] for non-planetary types)."""
        s, st = self.scene, self.state
        if s is None or s.spec.sizing.kind != 'involute':
            return []
        return involute_sets(s, st.get('module') or 1.0, st.get('alpha', 20.0), st.get('backlash', 0.06),
                             st.get('sun_steel', True))

    def _refresh_check(self, s):
        sets = self.gearsets()
        self.check_card.setVisible(bool(sets))
        if not sets:
            return
        rows, colors = [], {}
        lines = []
        bad = QColor(self.theme['redline'])
        for i, (name, gs) in enumerate(sets):
            rows.append((name or f'm{gs.m:g}', f'{gs.xs:+.2f} / {gs.xp:+.2f} / {gs.xr:+.2f}',
                         f'{gs.sun_tip_r:.3f} / {gs.planet_tip_r:.3f}', f'{gs.ring_tip_r:.3f} / {gs.ring_root_r:.3f}',
                         f'{gs.eps_sp:.2f} / {gs.eps_pr:.2f}', f'{gs.neighbour_gap:.2f} mm',
                         f'{gs.planet_rot_deg[0]:.4f}°', f'{gs.ring_rot_deg:.4f}°'))
            if gs.issues:
                colors.update({(i, c): bad for c in range(8)})
            tag = f'{name}: ' if name else ''
            lines += [f'<span style="color:{self.theme["redline"]}">{escape(tag + x)}</span>' for x in gs.issues]
            lines += [escape(tag + x) for x in gs.warnings]
            sw = self.sweep_result.get(i)
            if sw:
                worst, g_sp, g_pr = sw
                lines.append(f'{tag}mesh sweep: worst overlap {worst:.4f} mm², backlash per flank '
                             f'sun–planet {g_sp:.3f} mm, planet–ring {g_pr:.3f} mm')
        self.check_table.fill(rows, colors=colors)
        sun_in = s.cfg[0] in ('s', 's1')
        torque = self.calc_state.get('torque', 1.0)
        if sun_in:
            st = check_strength(sets[0][1], self.state.get('face_width', 8.0), torque,
                                allow={'sun': 250.0 if self.state.get('sun_steel', True) else 30.0,
                                       'planet': 30.0, 'ring': 30.0})
            lines.append(f'Strength at {torque:g} N·m on the sun, {self.state.get("face_width", 8.0):g} mm face: '
                         f'{st.ft_per_mesh_N:.0f} N per mesh; bending sun {st.sigma_sun_MPa:.0f}, planet '
                         f'{st.sigma_planet_MPa:.0f}, ring {st.sigma_ring_MPa:.0f} MPa. Limiting: {st.limiting}, '
                         f'margin {st.margin:.2f} (allowable: steel 250, printed 30 MPa). Sun torque limit '
                         f'{st.motor_torque_allow_Nm:.2f} N·m.')
        else:
            lines.append('Strength check: make the sun the input to rate the teeth for the input torque.')
        self.check_text.setText('<br>'.join(lines) if lines else 'The involute set passes every check.')

    def _run_sweep(self):
        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.sweep_result = {i: sweep(gs, steps=9) for i, (_, gs) in enumerate(self.gearsets())}
        finally:
            QApplication.restoreOverrideCursor()
        if self.scene is not None:
            self._refresh_check(self.scene)

    def _refresh_pins(self, s, t):
        sz = s.spec.sizing
        self.ref_label.setText(sz.ref_label)
        res = pin_sizing(s, self.ref_d.value())
        self.p_pin.set(f'{res.pin_d:.3g} mm' if res.pin_d else '–')
        self.p_dowel.set(f'Ø{res.dowel:g} mm' if res.dowel else '–',
                         f'{(res.dowel - res.pin_d) / res.pin_d * 100:+.1f} % from exact' if res.dowel else '')
        self.p_ecc.set(f'{res.ecc:.3g} mm' if res.ecc else '–')
        self.p_env.set(f'{res.envelope:.1f} mm')
        self.pin_table.fill([(f'{dw:g}', f'{d:,.2f}') for dw, d in res.exact_ref_for_dowels])
        self.pin_table.setVisible(bool(res.exact_ref_for_dowels))
        self.pin_hint.setVisible(bool(res.exact_ref_for_dowels))
        self.scale_label.setText(f'{sz.ref_label} {res.ref_d:g} mm sets the scale of exports '
                                 f'({res.unit_mm:.4g} mm per drawing unit).')
        return res.notes


# ---------------------------------------------------------------------------- ratio sweep

class SweepPage(QWidget):
    pick = Signal(dict)

    def __init__(self):
        super().__init__()
        self.scene = None
        self.theme = None
        self.meta = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)
        ctl = QHBoxLayout()
        self.xn, self.yn = QComboBox(), QComboBox()
        self.x0, self.x1, self.y0, self.y1 = (QSpinBox() for _ in range(4))
        for sb in (self.x0, self.x1, self.y0, self.y1):
            sb.setRange(1, 500)
        ctl.addWidget(label('X'))
        for w in (self.xn, self.x0, label('to'), self.x1):
            ctl.addWidget(w)
        ctl.addSpacing(14)
        ctl.addWidget(label('Y'))
        for w in (self.yn, self.y0, label('to'), self.y1):
            ctl.addWidget(w)
        ctl.addSpacing(14)
        self.derive = QCheckBox('Keep rings meshing (R = S + 2P)')
        self.derive.setChecked(True)
        self.valid = QCheckBox('Only valid geometry')
        ctl.addWidget(self.derive)
        ctl.addWidget(self.valid)
        ctl.addStretch(1)
        go = QPushButton('Plot ratios')
        go.setObjectName('Primary')
        go.clicked.connect(self.compute)
        ctl.addWidget(go)
        lay.addLayout(ctl)
        lay.addWidget(label('Uses the symbolic ratio of the current configuration. Click a point or cell to load '
                            'those tooth counts.', 'Hint'))
        self.canvas = ChartCanvas(5)
        self.canvas.mpl_connect('button_press_event', self._click)
        lay.addWidget(self.canvas, 1)

    def set_theme(self, t, rc):
        self.theme = t
        self.canvas.restyle(rc)
        if self.meta:
            self.compute()
        else:
            self._empty_state()

    def set_scene(self, scene, type_changed):
        self.scene = scene
        if type_changed:
            spec = scene.spec
            ints = [p.name for p in spec.params if p.kind == 'int']
            for cb, items in ((self.xn, ints), (self.yn, ['(none)'] + ints)):
                cb.blockSignals(True)
                cb.clear()
                cb.addItems(items)
                cb.blockSignals(False)
            axes = spec.sweep_axes or tuple(ints[:2])
            self.xn.setCurrentText(axes[0])
            self.yn.setCurrentText(axes[1] if len(axes) > 1 else '(none)')
            for name, a, b in ((self.xn.currentText(), self.x0, self.x1), (self.yn.currentText(), self.y0, self.y1)):
                p = next((p for p in spec.params if p.name == name), None)
                if p:
                    a.setRange(p.lo, p.hi)
                    b.setRange(p.lo, p.hi)
                    a.setValue(max(p.lo, p.default - 10))
                    b.setValue(min(p.hi, p.default + 10))
            self.derive.setEnabled(spec.derive is not None)
            self.meta = None
            self._empty_state()

    def _empty_state(self):
        fig = self.canvas.figure
        fig.clf()
        t = self.theme or {}
        fig.text(0.5, 0.55, 'How does the ratio change with the tooth counts?', ha='center', fontsize=13,
                 color=t.get('text', 'black'))
        fig.text(0.5, 0.47, 'Pick one or two tooth counts above and press Plot ratios. '
                 'Click a point on the plot to load that design.', ha='center', fontsize=10,
                 color=t.get('muted', 'gray'))
        self.canvas.draw_idle()

    def values_for(self, xn, xv, yn=None, yv=None):
        v = dict(self.scene.values)
        v[xn] = int(xv)
        if yn:
            v[yn] = int(yv)
        if self.scene.spec.derive and self.derive.isChecked():
            v = self.scene.spec.derive(v)
        return v

    def compute(self):
        s, t = self.scene, self.theme
        if s is None:
            return
        spec, kin = s.spec, s.kin
        xn, yn = self.xn.currentText(), self.yn.currentText()
        two_d = yn not in ('', '(none)') and yn != xn
        xs = np.arange(self.x0.value(), self.x1.value() + 1)
        ys = np.arange(self.y0.value(), self.y1.value() + 1) if two_d else np.array([0])
        if len(xs) < 1 or len(ys) < 1:
            return
        names = sorted(str(sym) for sym in kin.ratio.free_symbols)
        f = sympy.lambdify([sympy.Symbol(n) for n in names], kin.ratio, 'math')
        Z = np.full((len(ys), len(xs)), np.nan)
        valid = np.ones_like(Z, dtype=bool)
        for j, yv in enumerate(ys):
            for i, xv in enumerate(xs):
                v = self.values_for(xn, xv, yn if two_d else None, yv)
                geo = spec.geom(v)
                try:
                    Z[j, i] = float(f(*[geo[n] for n in names]))
                except (ZeroDivisionError, OverflowError, ValueError):
                    pass
                valid[j, i] = not spec.issues(v)
        if self.valid.isChecked():
            Z[~valid] = np.nan

        fig = self.canvas.figure
        fig.clf()
        ax = fig.add_subplot(111)
        cur_x = s.values[xn]
        cur_y = s.values[yn] if two_d else None
        if not two_d:
            z = Z[0]
            ax.plot(xs, z, color=t['muted'], lw=1, zorder=1)
            ax.scatter(xs[valid[0]], z[valid[0]], color=t['accent'], s=30, zorder=2, label='valid geometry')
            ax.scatter(xs[~valid[0]], z[~valid[0]], facecolor=t['surface'], edgecolor=t['muted'], s=30, zorder=2,
                       label='mesh constraint violated')
            if xs[0] <= cur_x <= xs[-1]:
                ax.scatter([cur_x], [s.ratio_in], color='#D55E00', s=110, marker='*', zorder=3, label='current')
            fin = np.abs(z[np.isfinite(z) & (z != 0)])
            if len(fin) and fin.max() / fin.min() > 100:
                ax.set_yscale('symlog', linthresh=max(1.0, fin.min()))
            ax.set_xlabel(xn)
            ax.set_ylabel(f'ratio  {s.cfg[0]}/{s.cfg[1]}')
            ax.grid(alpha=0.6)
            ax.legend(frameon=False, fontsize=9)
            for sp in ('top', 'right'):
                ax.spines[sp].set_visible(False)
        else:
            A = np.log10(np.abs(Z))
            A[~np.isfinite(A)] = np.nan
            ext = [xs[0] - 0.5, xs[-1] + 0.5, ys[0] - 0.5, ys[-1] + 0.5]
            im = ax.imshow(A, origin='lower', extent=ext, cmap='viridis', aspect='auto', interpolation='nearest')
            cb = fig.colorbar(im, ax=ax)
            cb.set_label('log10 |ratio|')
            cb.outline.set_visible(False)
            if not self.valid.isChecked() and (~valid).any():
                shade = np.zeros(Z.shape + (4,))
                shade[~valid] = (*matplotlib.colors.to_rgb(t['surface']), 0.72)
                ax.imshow(shade, origin='lower', extent=ext, aspect='auto', interpolation='nearest')
            if Z.size <= 150:
                for j, yv in enumerate(ys):
                    for i, xv in enumerate(xs):
                        if np.isfinite(Z[j, i]):
                            ax.text(xv, yv, f'{Z[j, i]:.3g}', ha='center', va='center', fontsize=7,
                                    color='white' if A[j, i] < np.nanmean(A) else 'black')
            if xs[0] <= cur_x <= xs[-1] and ys[0] <= cur_y <= ys[-1]:
                ax.add_patch(Rectangle((cur_x - 0.5, cur_y - 0.5), 1, 1, fill=False, ec='#D55E00', lw=2.5))
            ax.set_xlabel(xn)
            ax.set_ylabel(yn)
            if (~valid).any() and not self.valid.isChecked():
                ax.set_title('Faded cells break a mesh rule', fontsize=9, color=t['muted'], loc='left')
            for sp in ax.spines.values():
                sp.set_visible(False)
        fig.suptitle(f'{spec.name}: ratio {s.cfg[0]}/{s.cfg[1]} = {sympy.sstr(kin.ratio)}', fontsize=10.5,
                     x=0.02, ha='left', color=t['text'])
        ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
        if two_d:
            ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
        self.meta = (ax, xn, yn if two_d else None)
        self.canvas.draw_idle()

    def _click(self, ev):
        if not self.meta or ev.inaxes is not self.meta[0] or ev.xdata is None:
            return
        ax, xn, yn = self.meta
        v = self.values_for(xn, round(ev.xdata), yn, round(ev.ydata) if yn else None)
        self.pick.emit(v)
