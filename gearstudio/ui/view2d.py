"""2D view, drawn as an engineering drawing sheet. Each part's outline is a cached QPainterPath in its body frame; a frame only sets
one transform per part. Wheel zooms about the cursor, drag pans, double-click refits."""
import math
from collections import deque

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import QToolTip, QWidget

from gearstudio.ui.theme import mono_font, ui_font


def loops_to_path(loops, ring_radius=None):
    path = QPainterPath()
    path.setFillRule(Qt.OddEvenFill)
    if ring_radius:
        path.addEllipse(QPointF(0, 0), ring_radius, ring_radius)
    for loop in loops:
        path.addPolygon(QPolygonF([QPointF(float(x), float(y)) for x, y in loop]))
        path.closeSubpath()
    return path


class View2D(QWidget):
    hovered = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(320, 320)
        self.scene = None
        self.paths = []
        self.transforms = []
        self.colors = []
        self.hidden = set()
        self.theme = None
        self.fill = True
        self.show_ref = False
        self.show_trace = False
        self.show_legend = True
        self.hud = ('', '')
        self.title_info = {}
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self._drag = None
        self.trace = deque(maxlen=2400)
        self.trace_part = None
        self.trace_point = None

    # ---------------- data

    def set_theme(self, t):
        self.theme = t
        self.update()

    def set_scene(self, scene, colors, keep_view=False):
        self.scene = scene
        self.paths = [loops_to_path(p.loops, p.ring_radius) for p in scene.parts]
        self.colors = colors
        self.order = sorted(range(len(scene.parts)),
                            key=lambda i: (scene.members[scene.parts[i].member].layer,
                                           -(scene.parts[i].ring_radius or 0), scene.parts[i].member))
        self.ref = scene.ref_circles()
        self._pick_trace_point()
        if not keep_view:
            self.zoom, self.pan = 1.0, QPointF(0, 0)
        self.update()

    def _pick_trace_point(self):
        """Trace a tooth tip of the first orbiting part (planet, disc), else of the input member."""
        self.trace.clear()
        sc = self.scene
        cand = [i for i, p in enumerate(sc.parts) if p.k_centre != 0 and np.linalg.norm(p.c0) > 0]
        if not cand:
            cand = [i for i, p in enumerate(sc.parts) if sc.members[p.member].dof == sc.cfg[0] and not p.ring_radius]
        if not cand:
            self.trace_part = None
            return
        i = cand[0]
        loop = sc.parts[i].loops[0]
        self.trace_part = i
        self.trace_point = loop[int(np.argmax(np.linalg.norm(loop, axis=1)))]

    def set_colors(self, colors):
        self.colors = colors
        self.update()

    def set_transforms(self, transforms, hud=None):
        self.transforms = transforms
        if hud:
            self.hud = hud
        if self.show_trace and self.trace_part is not None and transforms:
            a, x, y = transforms[self.trace_part]
            px, py = self.trace_point
            c, s = math.cos(a), math.sin(a)
            self.trace.append((px * c - py * s + x, px * s + py * c + y))
        self.update()

    def clear_trace(self):
        self.trace.clear()
        self.update()

    # ---------------- geometry

    FRAME = 12          # paper margin to the outer border line, px
    BAND = 18           # zone-marker band between outer and inner border, px

    def sheet(self, w, h):
        """Outer border and inner drawing area of the sheet, in widget pixels."""
        outer = QRectF(self.FRAME, self.FRAME, w - 2 * self.FRAME, h - 2 * self.FRAME)
        return outer, outer.adjusted(self.BAND, self.BAND, -self.BAND, -self.BAND)

    def base_transform(self, w, h):
        _, inner = self.sheet(w, h)
        ext = self.scene.extent if self.scene else 1.0
        s = min(inner.width(), inner.height()) / (2 * ext * 1.1) * self.zoom
        t = QTransform()
        t.translate(inner.center().x() + self.pan.x(), inner.center().y() + self.pan.y())
        t.scale(s, -s)
        return t

    @staticmethod
    def part_transform(tr):
        a, x, y = tr
        t = QTransform()
        t.translate(x, y)
        t.rotateRadians(a)
        return t

    # ---------------- painting

    def paintEvent(self, ev):
        p = QPainter(self)
        self.paint(p, self.width(), self.height())
        p.end()

    def _pen(self, color, width=1.0, style=Qt.SolidLine):
        pen = QPen(QColor(color), width, style)
        pen.setCosmetic(True)
        pen.setCapStyle(Qt.FlatCap)
        return pen

    def paint(self, p, w, h, legend=None):
        t = self.theme
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(0, 0, w, h, QColor(t['bg']))
        outer, inner = self.sheet(w, h)
        p.fillRect(inner, QColor(t['canvas']))
        self._paint_grid(p, inner)
        if self.scene and self.transforms:
            p.save()
            p.setClipRect(inner)
            self._paint_drawing(p, w, h)
            p.restore()
        self._paint_frame(p, outer, inner)
        if self.scene:
            self._paint_hud(p, inner)
            if legend if legend is not None else self.show_legend:
                self._paint_legend(p, inner)
            self._paint_title_block(p, inner)

    def _paint_grid(self, p, inner):
        """Engineering-paper ruling: fine lines every 8 px, heavier every 5th."""
        t = self.theme
        step = 8
        for k, x in enumerate(range(int(inner.left()), int(inner.right()), step)):
            p.setPen(self._pen(t['grid_major'] if k % 5 == 0 else t['grid'], 1))
            p.drawLine(QPointF(x, inner.top()), QPointF(x, inner.bottom()))
        for k, y in enumerate(range(int(inner.top()), int(inner.bottom()), step)):
            p.setPen(self._pen(t['grid_major'] if k % 5 == 0 else t['grid'], 1))
            p.drawLine(QPointF(inner.left(), y), QPointF(inner.right(), y))

    def _paint_drawing(self, p, w, h):
        t = self.theme
        base = self.base_transform(w, h)
        # centre lines through the origin, drafting style: long dash, short dash
        p.setTransform(base)
        centre = self._pen(t['muted'], 0.8, Qt.CustomDashLine)
        centre.setDashPattern([18, 4, 3, 4])
        p.setPen(centre)
        e = self.scene.extent * 1.12
        p.drawLine(QPointF(-e, 0), QPointF(e, 0))
        p.drawLine(QPointF(0, -e), QPointF(0, e))

        for i in self.order:
            part = self.scene.parts[i]
            if part.member in self.hidden:
                continue
            color = QColor(self.colors[part.member])
            p.setTransform(self.part_transform(self.transforms[i]) * base)
            if self.fill:
                fc = QColor(color)
                fc.setAlphaF(t['fill_alpha'])
                p.fillPath(self.paths[i], fc)
            pen = self._pen(color, 1.4)
            pen.setJoinStyle(Qt.MiterJoin)
            p.strokePath(self.paths[i], pen)

        if self.show_ref:
            ref = self._pen(t['ink'], 0.8, Qt.CustomDashLine)
            ref.setDashPattern([10, 3, 2, 3])
            p.setPen(ref)
            p.setBrush(Qt.NoBrush)
            for pi, r in self.ref:
                if pi is not None and self.scene.parts[pi].member in self.hidden:
                    continue
                p.setTransform(base if pi is None else self.part_transform(self.transforms[pi]) * base)
                p.drawEllipse(QPointF(0, 0), r, r)

        if self.show_trace and len(self.trace) > 1:
            p.setTransform(base)
            col = QColor(t['redline'])
            pts = list(self.trace)
            n = len(pts)
            for k in range(0, n - 1, 6):           # fade older segments
                col.setAlphaF(0.15 + 0.85 * k / n)
                p.setPen(self._pen(col.name(QColor.HexArgb), 1.3))
                p.drawPolyline(QPolygonF([QPointF(*q) for q in pts[k:k + 7]]))
        p.resetTransform()

    def _paint_frame(self, p, outer, inner):
        """Border lines with zone markers 1-8 across and A-F down, as on a drawing sheet."""
        t = self.theme
        p.setBrush(Qt.NoBrush)
        p.setPen(self._pen(t['ink'], 0.8))
        p.drawRect(outer)
        p.setPen(self._pen(t['ink'], 1.8))
        p.drawRect(inner)
        p.setFont(ui_font(8, QFont.DemiBold))
        p.setPen(self._pen(t['muted'], 0.8))
        cols, rows = 8, 6
        for i in range(cols):
            x0 = inner.left() + inner.width() * i / cols
            x1 = inner.left() + inner.width() * (i + 1) / cols
            if i:
                p.drawLine(QPointF(x0, outer.top()), QPointF(x0, inner.top()))
                p.drawLine(QPointF(x0, inner.bottom()), QPointF(x0, outer.bottom()))
            for y in (outer.top(), inner.bottom()):
                p.drawText(QRectF(x0, y, x1 - x0, self.BAND), Qt.AlignCenter, str(i + 1))
        for j in range(rows):
            y0 = inner.top() + inner.height() * j / rows
            y1 = inner.top() + inner.height() * (j + 1) / rows
            if j:
                p.drawLine(QPointF(outer.left(), y0), QPointF(inner.left(), y0))
                p.drawLine(QPointF(inner.right(), y0), QPointF(outer.right(), y0))
            for x in (outer.left(), inner.right()):
                p.drawText(QRectF(x, y0, self.BAND, y1 - y0), Qt.AlignCenter, 'ABCDEF'[j])

    def _paint_hud(self, p, inner):
        t = self.theme
        p.setFont(mono_font(9))
        p.setPen(QColor(t['muted']))
        y = inner.top() + 26
        for line in self.hud:
            if line:
                p.drawText(QPointF(inner.left() + 18, y), line)
                y += 20

    def _paint_legend(self, p, inner):
        t = self.theme
        seen, rows = set(), []
        for i, m in enumerate(self.scene.members):
            if (m.label, m.dof) in seen or i in self.hidden:
                continue
            seen.add((m.label, m.dof))
            rows.append((self.colors[i], m.label, self.scene.role(m.dof)))
        p.setFont(ui_font(9.5))
        fm = p.fontMetrics()
        width = max(fm.horizontalAdvance(f'{a}   {b}') for _, a, b in rows) + 40
        x0, y0 = inner.right() - width - 18, inner.top() + 16
        for i, (c, name, role) in enumerate(rows):
            yy = y0 + 22 * i
            p.fillRect(QRectF(x0, yy + 5, 16, 3), QColor(c))
            p.setPen(QColor(t['text']))
            p.drawText(QPointF(x0 + 24, yy + 12), name)
            p.setPen(QColor(t['muted']))
            p.drawText(QPointF(x0 + 24 + fm.horizontalAdvance(name + '   '), yy + 12), role)

    def _paint_title_block(self, p, inner):
        """Title block in the lower right corner: design, ratio, scale, date."""
        t = self.theme
        info = self.title_info
        w, rh = 400, 28
        x0, y0 = inner.right() - w, inner.bottom() - 4 * rh
        rows = [[('DESIGN', info.get('design', 'Untitled'), 0.62), ('DATE', info.get('date', ''), 0.38)],
                [('GEAR TRAIN', self.scene.spec.name, 1.0)],
                [('RATIO', info.get('ratio', ''), 0.5), ('SCALE', info.get('scale', ''), 0.5)],
                [('DRAWN WITH', 'pyGearTrain Studio', 0.62), ('SHEET', '1 / 1', 0.38)]]
        p.fillRect(QRectF(x0, y0, w, 4 * rh), QColor(t['canvas']))
        for r, cells in enumerate(rows):
            x = x0
            for label, value, frac in cells:
                cw = w * frac
                cell = QRectF(x, y0 + r * rh, cw, rh)
                p.setPen(self._pen(t['ink'], 1.0))
                p.drawRect(cell)
                p.setFont(ui_font(6.5, QFont.DemiBold, caps=True, spacing=110))
                p.setPen(QColor(t['muted']))
                p.drawText(cell.adjusted(6, 3, -6, 0), Qt.AlignLeft | Qt.AlignTop, label)
                p.setFont(mono_font(8.5) if label in ('RATIO', 'SCALE', 'DATE', 'SHEET') else ui_font(9.5))
                p.setPen(QColor(t['text']))
                p.drawText(cell.adjusted(6, 0, -8, -3), Qt.AlignRight | Qt.AlignBottom, value)
                x += cw
        p.setPen(self._pen(t['ink'], 1.8))
        p.drawRect(QRectF(x0, y0, w, 4 * rh))

    def render_image(self, w, h, scale=2.0, legend=True):
        img = QImage(int(w * scale), int(h * scale), QImage.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(scale)
        p = QPainter(img)
        self.paint(p, w, h, legend)
        p.end()
        return img

    # ---------------- interaction

    def wheelEvent(self, ev):
        f = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
        new = min(max(self.zoom * f, 0.2), 40)
        f = new / self.zoom
        c = QPointF(self.width() / 2, self.height() / 2) + self.pan
        self.pan = self.pan + (ev.position() - c) * (1 - f)
        self.zoom = new
        self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag = (ev.position(), QPointF(self.pan))
            self.setCursor(Qt.ClosedHandCursor)

    def mouseReleaseEvent(self, ev):
        self._drag = None
        self.setCursor(Qt.ArrowCursor)

    def mouseDoubleClickEvent(self, ev):
        self.fit()

    def fit(self):
        self.zoom, self.pan = 1.0, QPointF(0, 0)
        self.update()

    def mouseMoveEvent(self, ev):
        if self._drag:
            start, pan0 = self._drag
            self.pan = pan0 + (ev.position() - start)
            self.update()
            return
        name = self.hit(ev.position())
        if name:
            QToolTip.showText(ev.globalPosition().toPoint(), name, self)
        else:
            QToolTip.hideText()

    def hit(self, pos):
        if not self.scene or not self.transforms:
            return None
        base = self.base_transform(self.width(), self.height())
        for i in reversed(self.order):
            part = self.scene.parts[i]
            if part.member in self.hidden:
                continue
            inv, ok = (self.part_transform(self.transforms[i]) * base).inverted()
            if ok and self.paths[i].contains(inv.map(pos)):
                m = self.scene.members[part.member]
                sp = self.scene.speed_per_input(m.dof)
                return (f'<b>{m.label}</b><br>{self.scene.role(m.dof)} · {sp:+.4g} rev per input rev'
                        + (f'<br>{len(m.parts)} copies' if len(m.parts) > 1 else ''))
        return None
