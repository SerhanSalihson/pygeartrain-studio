"""Look and feel: an engineering drawing sheet.

Light is drafting vellum with ink linework; dark is a cyanotype blueprint. Labels are set in
Comic Sans MS (Barlow Semi Condensed where it is missing), every number in IBM Plex Mono. Shapes are
square and ruled like a title block. Both fonts are SIL Open Font License and ship in ui/fonts.
"""
import glob
import math
import os

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer

UI_FONT = 'Comic Sans MS'              # ships with Windows; not redistributable, so not bundled
FALLBACK_FONT = 'Barlow Semi Condensed'  # bundled, used where Comic Sans is missing
MONO_FONT = 'IBM Plex Mono'
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')

THEMES = {
    'light': dict(
        name='vellum',
        bg='#F2EFE6', surface='#F7F5EE', surface2='#ECE8DC', field='#FBFAF5', border='#D3CCBA',
        border_strong='#B3AA94', ink='#1D1D1B', hover='#E6E1D2', text='#1D1D1B', muted='#6A6353',
        faint='#9A917C', accent='#1D1D1B', accent_text='#F7F5EE', redline='#B8322A', warn='#9A5300',
        ok='#2D6A3E', bad='#B8322A', canvas='#F7F5EE', grid='#E4DFD1', grid_major='#D6CFBD',
        fill_alpha=0.22, floor='#E9E5D9', axis='#3A372F',
        members=['#1F5FA8', '#C77700', '#1B8A5A', '#B0477E', '#C2410C', '#4F8FC9', '#8C6D1F', '#5A5A5A'],
        roles={'input': '#C2410C', 'output': '#1F5FA8', 'fixed': '#7D7663', 'free': '#1B8A5A'}),
    'dark': dict(
        name='blueprint',
        bg='#0B2747', surface='#0E2E53', surface2='#12365F', field='#0A2442', border='#24507F',
        border_strong='#3B6A9C', ink='#E8F0FB', hover='#16406E', text='#E8F0FB', muted='#9AB6D8',
        faint='#6589B3', accent='#E8F0FB', accent_text='#0B2747', redline='#FF8A7A', warn='#FFC46B',
        ok='#8FE3A7', bad='#FF8A7A', canvas='#0E2E53', grid='#133A66', grid_major='#1A4777',
        fill_alpha=0.26, floor='#0D2B4F', axis='#C9DAF0',
        members=['#7CCBFF', '#FFC857', '#7BE0A8', '#F49AC2', '#FF9466', '#C3B4FF', '#E6D27A', '#D5DEEA'],
        roles={'input': '#FF9466', 'output': '#7CCBFF', 'fixed': '#9AB6D8', 'free': '#7BE0A8'}),
}

# the active sheet's gear colours; updated in place by activate() so every importer sees them
MEMBER_COLORS = list(THEMES['light']['members'])
ROLE_COLORS = dict(THEMES['light']['roles'])


def activate(t):
    MEMBER_COLORS[:] = t['members']
    ROLE_COLORS.clear()
    ROLE_COLORS.update(t['roles'])


def load_fonts():
    """Register the bundled fonts with Qt and matplotlib."""
    for path in glob.glob(os.path.join(FONT_DIR, '*.ttf')):
        QFontDatabase.addApplicationFont(path)
        try:
            from matplotlib import font_manager
            font_manager.fontManager.addfont(path)
        except Exception:
            pass


def ui_font(size=10.5, weight=QFont.Normal, caps=False, spacing=100):
    f = QFont(UI_FONT)
    f.setFamilies([UI_FONT, FALLBACK_FONT])
    f.setPointSizeF(size)
    f.setWeight(weight)
    if caps:
        f.setCapitalization(QFont.AllUppercase)
    if spacing != 100:
        f.setLetterSpacing(QFont.PercentageSpacing, spacing)
    return f


def mono_font(size=9.5, weight=QFont.Normal):
    f = QFont(MONO_FONT)
    f.setStyleHint(QFont.Monospace)
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


def palette(t):
    p = QPalette()
    c = QColor
    p.setColor(QPalette.Window, c(t['bg']))
    p.setColor(QPalette.WindowText, c(t['text']))
    p.setColor(QPalette.Base, c(t['field']))
    p.setColor(QPalette.AlternateBase, c(t['surface2']))
    p.setColor(QPalette.Text, c(t['text']))
    p.setColor(QPalette.Button, c(t['surface']))
    p.setColor(QPalette.ButtonText, c(t['text']))
    p.setColor(QPalette.Highlight, c(t['ink']))
    p.setColor(QPalette.HighlightedText, c(t['bg']))
    p.setColor(QPalette.ToolTipBase, c(t['surface']))
    p.setColor(QPalette.ToolTipText, c(t['text']))
    p.setColor(QPalette.PlaceholderText, c(t['faint']))
    p.setColor(QPalette.Link, c(t['ink']))
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        p.setColor(QPalette.Disabled, role, c(t['faint']))
    return p


def stylesheet(t):
    ui, mono = UI_FONT, MONO_FONT
    return f'''
    QMainWindow, QWidget#Central {{ background: {t['bg']}; }}
    QWidget {{ color: {t['text']}; font-family: "{ui}", "{FALLBACK_FONT}"; font-size: 10pt; }}
    QToolTip {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['ink']}; border-radius: 0;
                padding: 6px 8px; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}

    /* ruled cells, square corners, like a title block */
    QFrame#Card {{ background: transparent; border: none; border-top: 1px solid {t['border']}; border-radius: 0; }}
    QFrame#Section {{ background: transparent; border: none; border-bottom: 1px solid {t['border']};
                      border-radius: 0; }}
    QFrame#Tile {{ background: transparent; border: none; border-radius: 0; }}
    QFrame#Banner {{ background: {t['surface2']}; border: 1px solid {t['ink']}; border-radius: 0; }}
    QFrame#Issue {{ background: {t['surface2']}; border: none; border-radius: 0; }}
    QFrame#Transport {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 0; }}

    QLabel {{ background: transparent; }}
    QLabel#CardTitle {{ color: {t['text']}; font-size: 12pt; font-weight: 600; }}
    QLabel#AppTitle {{ font-size: 12.5pt; font-weight: 600; }}
    QLabel#Muted, QLabel#Hint, QLabel#TileLabel, QLabel#Chip {{ color: {t['muted']}; }}
    QLabel#Hint, QLabel#TileLabel {{ font-size: 9.5pt; }}
    QLabel#Chip {{ font-family: "{mono}"; font-size: 8.5pt; }}
    QLabel#Ratio {{ font-family: "{mono}"; font-size: 27pt; font-weight: 600; }}
    QLabel#TileValue {{ font-family: "{mono}"; font-size: 16pt; font-weight: 600; }}
    QLabel#IssueText {{ color: {t['redline']}; }}
    QLabel#Mono {{ font-family: "{mono}"; color: {t['muted']}; font-size: 9pt; }}

    QToolBar {{ background: {t['bg']}; border: none; border-bottom: 1px solid {t['ink']}; spacing: 6px;
                padding: 8px 20px; }}
    QToolBar::separator {{ background: {t['border']}; width: 1px; margin: 4px 8px; }}
    QToolButton {{ border: 1px solid transparent; border-radius: 0; padding: 5px; }}
    QToolButton:hover {{ border: 1px solid {t['ink']}; }}
    QToolButton:pressed, QToolButton:checked {{ background: {t['hover']}; }}
    QToolButton::menu-indicator {{ image: none; width: 0; }}
    QToolButton#PrimaryTool {{ background: {t['ink']}; color: {t['accent_text']}; border: 1px solid {t['ink']};
                               font-weight: 600; padding: 5px 16px; }}
    QToolButton#PrimaryTool:hover {{ background: {t['muted']}; }}

    QPushButton {{ background: transparent; border: 1px solid {t['ink']}; border-radius: 0; padding: 7px 18px; }}
    QPushButton:hover {{ background: {t['hover']}; }}
    QPushButton:pressed {{ background: {t['surface2']}; }}
    QPushButton:disabled {{ color: {t['faint']}; border-color: {t['border']}; }}
    QPushButton#Primary {{ background: {t['ink']}; color: {t['accent_text']}; font-weight: 600; }}
    QPushButton#Primary:hover {{ background: {t['muted']}; border-color: {t['muted']}; }}
    QPushButton#Primary:disabled {{ background: transparent; color: {t['faint']}; border-color: {t['border']}; }}
    QPushButton#Small {{ padding: 4px 12px; font-size: 9.5pt; }}
    QPushButton#Segment {{ border: 1px solid {t['border_strong']}; color: {t['muted']}; padding: 4px 14px; }}
    QPushButton#Segment:checked {{ background: {t['ink']}; color: {t['accent_text']}; border-color: {t['ink']}; }}

    QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
        background: {t['field']}; border: none; border-bottom: 1px solid {t['border_strong']}; border-radius: 0;
        padding: 6px 8px; min-height: 22px; selection-background-color: {t['ink']}; selection-color: {t['bg']}; }}
    QSpinBox, QDoubleSpinBox {{ font-family: "{mono}"; font-size: 10pt; }}
    QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover {{ border-bottom: 1px solid {t['ink']}; }}
    QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{ border-bottom: 2px solid {t['ink']}; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['ink']}; outline: none;
                                   selection-background-color: {t['hover']}; selection-color: {t['text']}; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{
        border: none; width: 0; }}

    QCheckBox, QRadioButton {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 13px; height: 13px; border: 1px solid {t['ink']}; border-radius: 0;
                            background: {t['field']}; }}
    QCheckBox::indicator:checked {{ background: {t['ink']}; }}

    QSlider::groove:horizontal {{ height: 1px; background: {t['ink']}; }}
    QSlider::sub-page:horizontal {{ background: {t['ink']}; height: 3px; }}
    QSlider::handle:horizontal {{ background: {t['bg']}; border: 1px solid {t['ink']}; width: 8px; height: 16px;
                                  margin: -8px 0; border-radius: 0; }}

    QTabWidget::pane {{ border: 1px solid {t['ink']}; background: {t['surface']}; border-radius: 0; top: -1px; }}
    QTabBar {{ qproperty-drawBase: 0; }}
    QTabBar::tab {{ background: transparent; color: {t['muted']}; padding: 8px 20px; margin-right: -1px;
                    border: 1px solid transparent; border-bottom: none; border-radius: 0; }}
    QTabBar::tab:hover {{ color: {t['text']}; }}
    QTabBar::tab:selected {{ background: {t['surface']}; color: {t['text']}; font-weight: 600; border: 1px solid {t['ink']};
                             border-bottom: 1px solid {t['surface']}; }}

    QTableWidget {{ background: transparent; border: none; gridline-color: {t['border']};
                    selection-background-color: {t['hover']}; selection-color: {t['text']};
                    font-family: "{mono}"; font-size: 9.5pt; }}
    QHeaderView::section {{ background: transparent; color: {t['muted']}; border: none;
                            border-bottom: 1px solid {t['ink']}; padding: 8px 8px; font-family: "{ui}";
                            font-size: 9pt; }}
    QTableCornerButton::section {{ background: transparent; border: none; }}

    QScrollBar:vertical {{ background: transparent; width: 9px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {t['border_strong']}; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {t['muted']}; }}
    QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: {t['border_strong']}; min-width: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QSplitter::handle {{ background: transparent; }}
    QStatusBar {{ background: {t['bg']}; border-top: 1px solid {t['border']}; }}
    QStatusBar QLabel {{ color: {t['muted']}; font-family: "{mono}"; font-size: 8.5pt; padding: 0 10px; }}
    QStatusBar::item {{ border: none; }}
    QMenu {{ background: {t['surface']}; border: 1px solid {t['ink']}; border-radius: 0; padding: 4px; }}
    QMenu::item {{ padding: 8px 28px 8px 14px; }}
    QMenu::item:selected {{ background: {t['hover']}; }}
    QMenu::item:disabled {{ color: {t['faint']}; }}
    QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 6px; }}
    QMessageBox, QInputDialog, QDialog {{ background: {t['surface']}; }}
    '''


def mpl_style(t):
    """rcParams for matplotlib charts on this sheet."""
    return {
        'figure.facecolor': t['surface'], 'axes.facecolor': t['surface'], 'savefig.facecolor': t['surface'],
        'text.color': t['text'], 'axes.labelcolor': t['muted'], 'axes.edgecolor': t['ink'],
        'xtick.color': t['muted'], 'ytick.color': t['muted'], 'grid.color': t['grid_major'],
        'font.family': [UI_FONT, FALLBACK_FONT, 'DejaVu Sans'], 'font.size': 10, 'axes.titleweight': 'semibold',
        'axes.titlesize': 10,
    }


# ---------------------------------------------------------------------------- icons
# 24x24 line icons with square caps, drawn in the theme's ink colour ({c})

_SVG = {
    'new': '<path d="M14 3H5v18h14V8z"/><path d="M14 3v5h5"/><path d="M12 11v6M9 14h6"/>',
    'open': '<path d="M3 6h6l2 2h10v11H3z"/>',
    'save': '<path d="M4 4h12l4 4v12H4z"/><path d="M8 4v5h7V4"/><path d="M8 20v-6h8v6"/>',
    'export': '<path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M4 17v4h16v-4"/>',
    'play': '<path d="M7 4l13 8-13 8z" fill="{c}"/>',
    'pause': '<rect x="6" y="4" width="4" height="16" fill="{c}"/><rect x="14" y="4" width="4" height="16" fill="{c}"/>',
    'reset': '<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/>',
    'theme': '<rect x="4" y="4" width="16" height="16"/><path d="M4 20L20 4v16z" fill="{c}"/>',
    'info': '<rect x="4" y="4" width="16" height="16"/><path d="M12 11v6"/><path d="M12 7.5v.5"/>',
    'code': '<path d="M9 7l-5 5 5 5M15 7l5 5-5 5"/>',
    'recent': '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
}


def icon(name, color, size=20):
    body = _SVG[name].replace('{c}', color)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.6" stroke-linecap="square" stroke-linejoin="miter">{body}</svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    ic = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.transparent)
        pm.setDevicePixelRatio(scale)
        p = QPainter(pm)
        renderer.render(p)
        p.end()
        ic.addPixmap(pm)
    return ic


def app_icon():
    """Window icon: two meshing gears, ink on blueprint."""
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
           '<rect width="64" height="64" fill="#0B2747"/>'
           '<g fill="none" stroke="#E8F0FB" stroke-width="2.4" stroke-linejoin="miter">'
           + _gear_path(25, 27, 17, 10) + _gear_path(46, 45, 12, 8) + '</g>'
           '<circle cx="25" cy="27" r="4.5" fill="none" stroke="#E8F0FB" stroke-width="2.4"/>'
           '<circle cx="46" cy="45" r="3.2" fill="none" stroke="#E8F0FB" stroke-width="2.4"/></svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        renderer.render(p)
        p.end()
        ic.addPixmap(pm)
    return ic


def _gear_path(cx, cy, r, n):
    pts = []
    for i in range(n * 4):
        a = 2 * math.pi * i / (n * 4)
        rr = r if (i % 4) in (0, 1) else r * 0.78
        pts.append(f'{cx + rr * math.cos(a):.2f},{cy + rr * math.sin(a):.2f}')
    return f'<polygon points="{" ".join(pts)}"/>'
