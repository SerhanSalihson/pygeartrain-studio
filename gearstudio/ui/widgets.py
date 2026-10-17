"""Small shared widgets: cards, KPI tiles, tables and a themed matplotlib canvas."""
import matplotlib
matplotlib.use('QtAgg')
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from gearstudio.ui.theme import ui_font
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHeaderView, QLabel, QSizePolicy, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)


class Card(QFrame):
    """A filled panel, or with flat=True a borderless sidebar section separated by a hairline."""

    def __init__(self, title=None, parent=None, flat=False):
        super().__init__(parent)
        self.setObjectName('Section' if flat else 'Card')
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(4, 16, 4, 20) if flat else self.lay.setContentsMargins(0, 18, 0, 22)
        self.lay.setSpacing(12 if not flat else 10)
        if title:
            t = QLabel(title)
            t.setObjectName('CardTitle')
            self.lay.addWidget(t)

    def add(self, w, stretch=0):
        self.lay.addWidget(w, stretch)
        return w


class Tile(QFrame):
    """A KPI: small label above a large value, with an optional sub-line."""

    def __init__(self, label, parent=None):
        super().__init__(parent)
        self.setObjectName('Tile')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 14)
        lay.setSpacing(4)
        self.label = QLabel(label)
        self.label.setObjectName('TileLabel')
        self.value = QLabel('–')
        self.value.setObjectName('TileValue')
        self.sub = QLabel('')
        self.sub.setObjectName('Hint')
        for w in (self.label, self.value, self.sub):
            lay.addWidget(w)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set(self, value, sub=''):
        self.value.setText(value)
        self.sub.setText(sub)
        self.sub.setVisible(bool(sub))


def clear_layout(layout):
    """Remove and delete every widget in a layout right away (deleteLater alone leaves them
    painted until the event loop gets round to it)."""
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def label(text, name=None, wrap=False):
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    return w


class Table(QTableWidget):
    def __init__(self, headers, numeric=(), parent=None):
        super().__init__(0, len(headers), parent)
        self.setHorizontalHeaderLabels(headers)
        self.numeric = set(numeric)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setFocusPolicy(Qt.NoFocus)
        h = self.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Stretch)
        h.setHighlightSections(False)
        self.verticalHeader().setDefaultSectionSize(32)

    def fill(self, rows, bold_row=None, colors=None):
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                it = QTableWidgetItem(str(val))
                if c in self.numeric:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if r == bold_row:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                if colors and (r, c) in colors:
                    it.setForeground(colors[(r, c)])
                self.setItem(r, c, it)
        self.setFixedHeight(min(40 + 32 * len(rows), 40 + 32 * 12))


class ChartCanvas(FigureCanvasQTAgg):
    def __init__(self, height=4.0):
        self.figure = Figure(figsize=(7, height), dpi=100)
        super().__init__(self.figure)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def restyle(self, rc):
        matplotlib.rcParams.update(rc)
        self.figure.set_facecolor(rc['figure.facecolor'])
