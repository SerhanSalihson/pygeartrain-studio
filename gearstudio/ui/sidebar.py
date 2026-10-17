"""Left sidebar: gear train, result, checks with one-click fixes, geometry, configuration, members."""
import sympy
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from gearstudio.catalog import GEAR_TYPES
from gearstudio.ui.theme import ui_font
from gearstudio.ui.widgets import Card, clear_layout, label


def swatch(color, size=12):
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(0, 0, size, size, 3, 3)
    p.end()
    return pm


class Sidebar(QScrollArea):
    typeChanged = Signal(str)
    presetChosen = Signal(str)
    designEdited = Signal()          # values or configuration changed by the user
    fixRequested = Signal(dict)
    displayChanged = Signal()

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(360)
        self.setMaximumWidth(420)
        inner = QWidget()
        self.lay = QVBoxLayout(inner)
        self.lay.setContentsMargins(24, 8, 16, 24)
        self.lay.setSpacing(4)
        self.setWidget(inner)
        self.spec = None
        self.param_widgets = {}
        self.cfg_boxes = []
        self.hidden = set()
        self._quiet = False
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(220)
        self._debounce.timeout.connect(self.designEdited.emit)

        # --- gear train
        card = Card('Gear train', flat=True)
        self.type_box = QComboBox()
        self.type_box.addItems(list(GEAR_TYPES))
        self.type_box.currentTextChanged.connect(lambda t: None if self._quiet else self.typeChanged.emit(t))
        card.add(self.type_box)
        self.desc = card.add(label('', 'Hint', wrap=True))
        self.preset_box = QComboBox()
        self.preset_box.activated.connect(self._preset)
        card.add(self.preset_box)
        self.lay.addWidget(card)

        # --- result
        card = Card(flat=True)
        head = QHBoxLayout()
        title = label('Gear ratio', 'CardTitle')
        head.addWidget(title)
        head.addStretch(1)
        self.direction = label('', 'Chip')
        head.addWidget(self.direction)
        card.lay.addLayout(head)
        self.ratio = card.add(label('–', 'Ratio'))
        self.ratio.setTextFormat(Qt.RichText)
        self.ratio.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.path = card.add(label('', 'Muted', wrap=True))
        self.formula = card.add(label('', 'Hint', wrap=True))
        self.formula.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lay.addWidget(card)

        # --- checks
        self.issues_card = Card('Checks', flat=True)
        self.issues_box = QVBoxLayout()
        self.issues_box.setSpacing(8)
        self.issues_card.lay.addLayout(self.issues_box)
        self.lay.addWidget(self.issues_card)
        self.issues_card.hide()

        # --- geometry
        self.geo_card = Card('Geometry', flat=True)
        self.geo_grid = QGridLayout()
        self.geo_grid.setHorizontalSpacing(10)
        self.geo_grid.setVerticalSpacing(10)
        self.geo_card.lay.addLayout(self.geo_grid)
        self.lay.addWidget(self.geo_card)

        # --- configuration
        self.cfg_card = Card('Configuration', flat=True)
        self.cfg_grid = QGridLayout()
        self.cfg_grid.setHorizontalSpacing(10)
        self.cfg_grid.setVerticalSpacing(10)
        self.cfg_card.lay.addLayout(self.cfg_grid)
        self.cfg_hint = self.cfg_card.add(label('A member name holds it fixed. You can also type a linear '
                                                'constraint, e.g. r1-r2, to lock two members together.', 'Hint',
                                                wrap=True))
        self.lay.addWidget(self.cfg_card)

        # --- members & display
        card = Card('Members', flat=True)
        self.members_box = QVBoxLayout()
        self.members_box.setSpacing(8)
        card.lay.addLayout(self.members_box)
        card.lay.addSpacing(6)
        seg = QHBoxLayout()
        seg.setSpacing(0)
        seg.addWidget(label('Colour by'))
        seg.addStretch(1)
        self.color_group = QButtonGroup(self)
        for i, text in enumerate(('Member', 'Role')):
            b = QPushButton(text)
            b.setObjectName('Segment')
            b.setCheckable(True)
            b.setChecked(i == 0)
            self.color_group.addButton(b, i)
            seg.addWidget(b)
        self.color_group.idToggled.connect(lambda i, on: on and self.displayChanged.emit())
        card.lay.addLayout(seg)
        grid = QGridLayout()
        self.fill_box = QCheckBox('Filled shapes')
        self.legend_box = QCheckBox('Legend')
        self.ref_box = QCheckBox('Pitch circles')
        self.trace_box = QCheckBox('Trace a tooth tip')
        self.fill_box.setChecked(True)
        self.legend_box.setChecked(True)
        for i, b in enumerate((self.fill_box, self.legend_box, self.ref_box, self.trace_box)):
            grid.addWidget(b, i // 2, i % 2)
            b.toggled.connect(self.displayChanged.emit)
        card.lay.addLayout(grid)
        self.lay.addWidget(card)
        self.lay.addStretch(1)

    # ---------------- building

    def set_type(self, spec):
        self.spec = spec
        self._quiet = True
        self.type_box.setCurrentText(spec.name)
        self.desc.setText(spec.description)
        self.preset_box.clear()
        self.preset_box.addItem('Start from a preset')
        self.preset_box.addItems(list(spec.presets))
        self.preset_box.setEnabled(bool(spec.presets))

        clear_layout(self.geo_grid)
        self.param_widgets = {}
        for i, p in enumerate(spec.params):
            self.geo_grid.addWidget(QLabel(p.label.replace('  ', ' ')), i, 0)
            if p.kind == 'int':
                w = QSpinBox()
                w.setRange(p.lo, p.hi)
                w.valueChanged.connect(self._edited)
            elif p.kind == 'float':
                w = QDoubleSpinBox()
                w.setRange(p.lo, p.hi)
                w.setSingleStep(p.step or 0.1)
                w.setDecimals(2)
                w.valueChanged.connect(self._edited)
            elif p.kind == 'bool':
                w = QCheckBox()
                w.toggled.connect(self._edited)
            else:
                w = QComboBox()
                w.addItems(list(p.choices))
                w.currentTextChanged.connect(self._edited)
            if p.kind in ('int', 'float'):
                w.setMinimumWidth(96)
                w.setAlignment(Qt.AlignRight)
            self.geo_grid.addWidget(w, i, 1, Qt.AlignRight)
            self.param_widgets[p.name] = w
        self.geo_grid.setColumnStretch(0, 1)

        clear_layout(self.cfg_grid)
        self.cfg_boxes = []
        dofs = sorted(spec.kin_cls.dofs())
        names = [f'{d} – {spec.dof_labels.get(d, d)}' for d in dofs]
        rows = ['Input', 'Output'] + ['Fixed'] * spec.n_constraints
        for i, text in enumerate(rows):
            self.cfg_grid.addWidget(QLabel(text), i, 0)
            cb = QComboBox()
            cb.addItems(names)
            cb.setEditable(i >= 2)
            cb.setMinimumWidth(170)
            if i >= 2:
                cb.lineEdit().editingFinished.connect(self._edited)
            cb.activated.connect(self._edited)
            self.cfg_grid.addWidget(cb, i, 1, Qt.AlignRight)
            self.cfg_boxes.append(cb)
        self.cfg_grid.setColumnStretch(0, 1)
        self.cfg_hint.setVisible(spec.n_constraints > 0)
        self._quiet = False

    def _dof_text(self, d):
        return f'{d} – {self.spec.dof_labels[d]}' if d in self.spec.dof_labels else d

    def set_design(self, values, cfg):
        self._quiet = True
        for p in self.spec.params:
            w = self.param_widgets[p.name]
            v = values.get(p.name, p.default)
            if p.kind in ('int', 'float'):
                w.setValue(v)
            elif p.kind == 'bool':
                w.setChecked(bool(v))
            else:
                w.setCurrentText(str(v))
        for cb, c in zip(self.cfg_boxes, cfg):
            cb.setCurrentText(self._dof_text(c))
        self._quiet = False

    def values(self):
        out = {}
        for p in self.spec.params:
            w = self.param_widgets[p.name]
            out[p.name] = (w.value() if p.kind in ('int', 'float') else
                           w.isChecked() if p.kind == 'bool' else w.currentText())
        return out

    def config(self):
        return tuple(cb.currentText().split('–')[0].strip() for cb in self.cfg_boxes)

    def _edited(self, *_):
        if not self._quiet:
            self._debounce.start()

    def _preset(self, index):
        if index > 0:
            self.presetChosen.emit(self.preset_box.itemText(index))
        self.preset_box.setCurrentIndex(0)

    # ---------------- results

    def show_result(self, scene):
        r = scene.ratio_in
        small = '<span style="font-size:15pt">'
        self.ratio.setText(f'{r:,.5g}{small}&thinsp;:&thinsp;1</span>' if abs(r) >= 1 else
                           f'{small}1&thinsp;:&thinsp;</span>{1 / r:,.5g}')
        lab = scene.spec.dof_labels
        fixed = ', '.join(lab.get(c, c) for c in scene.cfg[2:])
        self.path.setText(f'{lab.get(scene.cfg[0], scene.cfg[0])} → {lab.get(scene.cfg[1], scene.cfg[1])}'
                          + (f'   ·   {fixed} fixed' if fixed else ''))
        self.formula.setText(f'{scene.cfg[0]}/{scene.cfg[1]} = {sympy.sstr(scene.kin.ratio)} = '
                             f'{sympy.sstr(scene.ratio_exact)}')
        self.direction.setText('reverses' if r < 0 else 'same direction')
        self.direction.setVisible(True)

    def show_error(self, message):
        self.ratio.setText('—')
        self.path.setText(message)
        self.formula.setText('')
        self.direction.setVisible(False)

    def show_issues(self, issues):
        clear_layout(self.issues_box)
        for iss in issues:
            box = QFrame()
            box.setObjectName('Issue')
            row = QHBoxLayout(box)
            row.setContentsMargins(12, 10, 10, 10)
            text = label(iss.message, 'IssueText', wrap=True)
            row.addWidget(text, 1)
            if iss.fix:
                b = QPushButton(iss.fix_label or 'Fix')
                b.setObjectName('Small')
                b.clicked.connect(lambda _=False, f=iss.fix: self.fixRequested.emit(f))
                row.addWidget(b, 0, Qt.AlignTop)
            self.issues_box.addWidget(box)
        self.issues_card.setVisible(bool(issues))

    def show_members(self, scene, colors):
        clear_layout(self.members_box)
        self.hidden &= set(range(len(scene.members)))
        for i, m in enumerate(scene.members):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            cb = QCheckBox()
            cb.setChecked(i not in self.hidden)
            cb.toggled.connect(lambda on, i=i: self._toggle_member(i, on))
            h.addWidget(cb)
            sw = QLabel()
            sw.setPixmap(swatch(colors[i]))
            h.addWidget(sw)
            name = m.label + (f'  ×{len(m.parts)}' if len(m.parts) > 1 else '')
            h.addWidget(QLabel(name), 1)
            h.addWidget(label(scene.role(m.dof), 'Chip'))
            self.members_box.addWidget(row)

    def _toggle_member(self, i, on):
        if on:
            self.hidden.discard(i)
        else:
            self.hidden.add(i)
        self.displayChanged.emit()

    # ---------------- display options

    def display(self):
        return {'color_mode': 'role' if self.color_group.checkedId() == 1 else 'member',
                'fill': self.fill_box.isChecked(), 'legend': self.legend_box.isChecked(),
                'ref': self.ref_box.isChecked(), 'trace': self.trace_box.isChecked()}

    def set_display(self, d):
        self.color_group.button(1 if d.get('color_mode') == 'role' else 0).setChecked(True)
        for key, box in (('fill', self.fill_box), ('legend', self.legend_box), ('ref', self.ref_box),
                         ('trace', self.trace_box)):
            if key in d:
                box.setChecked(bool(d[key]))
