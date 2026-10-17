"""3D view: Qt Quick 3D scene (PBR materials, shadows, MSAA, orbit camera) in a QQuickWidget.

Meshes are extruded once per part in its body frame and uploaded as QQuick3DGeometry; a frame
only updates each part's position and angle."""
import math
import os

from PySide6.QtCore import Property, QByteArray, QObject, Qt, QUrl, Signal, QMetaObject, Q_ARG
from PySide6.QtGui import QColor, QVector3D
from PySide6.QtQuick3D import QQuick3DGeometry
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QPushButton, QSlider, QStackedLayout, QVBoxLayout,
                               QWidget)

from gearstudio.meshing import extrude, vertex_buffer

SCENE_SIZE = 100.0       # the train is scaled to this radius in scene units
DETAIL = 360             # max vertices per loop on the GPU


def resource(name):
    # also right when frozen: PyInstaller puts module files and data under _MEIPASS/gearstudio/ui
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


class PartGeometry(QQuick3DGeometry):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.setVertexData(QByteArray(data.tobytes()))
        self.setStride(24)
        self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        self.addAttribute(QQuick3DGeometry.Attribute.PositionSemantic, 0, QQuick3DGeometry.Attribute.F32Type)
        self.addAttribute(QQuick3DGeometry.Attribute.NormalSemantic, 12, QQuick3DGeometry.Attribute.F32Type)
        pos = data[:, :3]
        self.setBounds(QVector3D(*pos.min(0)), QVector3D(*pos.max(0)))


class PartItem(QObject):
    changed = Signal()

    def __init__(self, geometry, color, parent=None):
        super().__init__(parent)
        self._geometry = geometry
        self._color = QColor(color)
        self._opacity = 1.0
        self._shown = True
        self._px = self._py = self._pz = 0.0
        self._angle = 0.0
        self._sz = 1.0

    def _get(name):
        return lambda self: getattr(self, '_' + name)

    def _set(name):
        def s(self, v):
            if getattr(self, '_' + name) != v:
                setattr(self, '_' + name, v)
                self.changed.emit()
        return s

    geometry = Property(QObject, _get('geometry'), notify=changed)
    color = Property(QColor, _get('color'), _set('color'), notify=changed)
    opacity = Property(float, _get('opacity'), _set('opacity'), notify=changed)
    shown = Property(bool, _get('shown'), _set('shown'), notify=changed)
    px = Property(float, _get('px'), _set('px'), notify=changed)
    py = Property(float, _get('py'), _set('py'), notify=changed)
    pz = Property(float, _get('pz'), _set('pz'), notify=changed)
    angle = Property(float, _get('angle'), _set('angle'), notify=changed)
    sz = Property(float, _get('sz'), _set('sz'), notify=changed)

    def move(self, x, y, angle_deg):
        # one signal per frame instead of three
        self._px, self._py, self._angle = x, y, angle_deg
        self.changed.emit()


class Bridge(QObject):
    """Scene-wide state shared with QML."""
    changed = Signal()
    partsChanged = Signal()

    def __init__(self):
        super().__init__()
        self._parts = []
        self._background = QColor('#191B20')
        self._floor_color = QColor('#22252B')
        self._floor = True
        self._shadows = True
        self._ao = True
        self._floor_z = 0.0
        self._floor_size = 40.0
        self._metal = 0.35

    def _get(name):
        return lambda self: getattr(self, '_' + name)

    def _set(name):
        def s(self, v):
            setattr(self, '_' + name, v)
            self.changed.emit()
        return s

    parts = Property('QVariantList', lambda self: self._parts, notify=partsChanged)
    background = Property(QColor, _get('background'), _set('background'), notify=changed)
    floorColor = Property(QColor, _get('floor_color'), _set('floor_color'), notify=changed)
    floor = Property(bool, _get('floor'), _set('floor'), notify=changed)
    shadows = Property(bool, _get('shadows'), _set('shadows'), notify=changed)
    ambientOcclusion = Property(bool, _get('ao'), _set('ao'), notify=changed)
    floorZ = Property(float, _get('floor_z'), _set('floor_z'), notify=changed)
    floorSize = Property(float, _get('floor_size'), _set('floor_size'), notify=changed)
    metalness = Property(float, _get('metal'), _set('metal'), notify=changed)

    def set_parts(self, parts):
        self._parts = parts
        self.partsChanged.emit()


class View3D(QWidget):
    def __init__(self, on_status=lambda msg: None, parent=None):
        super().__init__(parent)
        self.on_status = on_status
        self.scene = None
        self.items = []
        self.bridge = Bridge()
        self.thickness = 0.16       # plate thickness as a fraction of the train radius
        self.explode = 0.0          # gap between plates, in plate thicknesses
        self.xray = True
        self.hidden = set()
        self.colors = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.stack = QStackedLayout()
        lay.addLayout(self.stack, 1)
        self.quick = QQuickWidget()
        self.quick.setResizeMode(QQuickWidget.SizeRootObjectToView)
        self.quick.setClearColor(QColor('#191B20'))
        self.quick.rootContext().setContextProperty('bridge', self.bridge)
        self.quick.setSource(QUrl.fromLocalFile(resource('view3d.qml')))
        self.error = QLabel()
        self.error.setAlignment(Qt.AlignCenter)
        self.error.setWordWrap(True)
        self.error.setObjectName('Muted')
        self.stack.addWidget(self.quick)
        self.stack.addWidget(self.error)
        errs = [e.toString() for e in self.quick.errors()]
        self.ok = self.quick.status() == QQuickWidget.Ready and not errs
        if not self.ok:
            self.error.setText('The 3D model needs Direct3D 11 or OpenGL graphics, which this computer did not '
                               'provide (common over remote desktop). The drawing and every other page still '
                               'work.\n\n' + '\n'.join(errs[:5]))
            self.stack.setCurrentWidget(self.error)

        bar = QWidget()
        bar.setObjectName('Bar3D')
        row = QHBoxLayout(bar)
        row.setContentsMargins(20, 12, 20, 12)
        row.setSpacing(12)

        def slider(label, lo, hi, value, cb):
            row.addWidget(QLabel(label))
            s = QSlider(Qt.Horizontal)
            s.setRange(lo, hi)
            s.setValue(value)
            s.setFixedWidth(110)
            s.valueChanged.connect(cb)
            row.addWidget(s)
            return s
        self.thick_slider = slider('Thickness', 3, 50, 16, lambda v: self._set('thickness', v / 100))
        self.explode_slider = slider('Explode', 0, 300, 0, lambda v: self._set('explode', v / 100))
        self.xray_box = QCheckBox('X-ray rings')
        self.xray_box.setChecked(True)
        self.xray_box.toggled.connect(lambda v: self._set('xray', v))
        row.addWidget(self.xray_box)
        self.shadow_box = QCheckBox('Shadows')
        self.shadow_box.setChecked(True)
        self.shadow_box.toggled.connect(self._shadows)
        row.addWidget(self.shadow_box)
        row.addStretch(1)
        for name in ('Iso', 'Top', 'Front'):
            b = QPushButton(name)
            b.setObjectName('Small')
            b.clicked.connect(lambda _=False, n=name.lower(): self.set_view(n))
            row.addWidget(b)
        hint = QLabel('Drag to orbit · right-drag to pan · scroll to zoom')
        hint.setObjectName('Hint')
        row.addWidget(hint)
        lay.addWidget(bar)

    # ---------------- scene

    def set_theme(self, t):
        self.bridge.background = QColor(t['canvas'])
        self.bridge.floorColor = QColor(t['floor'])
        self.quick.setClearColor(QColor(t['canvas']))

    def set_scene(self, scene, colors):
        self.scene = scene
        self.colors = colors
        if not self.ok:
            return
        S = SCENE_SIZE / scene.extent
        items = []
        for part in scene.parts:
            tris, normals = extrude(part, DETAIL)
            data = vertex_buffer(tris, normals)
            data[:, :2] *= S
            geom = PartGeometry(data)       # kept alive by its PartItem
            items.append(PartItem(geom, colors[part.member], self))
        for old in self.items:
            old.deleteLater()
        self.items = items
        self.bridge.set_parts(items)
        self._layout()
        self._apply_styles()

    def set_colors(self, colors):
        self.colors = colors
        self._apply_styles()

    def set_hidden(self, hidden):
        self.hidden = set(hidden)
        self._apply_styles()

    def _set(self, name, value):
        setattr(self, name, value)
        if name == 'xray':
            self._apply_styles()
        else:
            self._layout()

    def _shadows(self, on):
        self.bridge.shadows = on
        self.bridge.floor = on
        self.bridge.ambientOcclusion = on

    def _apply_styles(self):
        if not self.scene:
            return
        for part, item in zip(self.scene.parts, self.items):
            item.color = QColor(self.colors[part.member])
            item.opacity = 0.32 if (part.ring_radius and self.xray) else 1.0
            item.shown = part.member not in self.hidden

    def _layout(self):
        """z position and thickness of every plate from its layer, the thickness and explode gap."""
        if not self.scene or not self.items:
            return
        h = self.thickness * SCENE_SIZE
        gap = self.explode * h
        layers = [self.scene.members[p.member].layer for p in self.scene.parts]
        low = min(layers)
        for part, item in zip(self.scene.parts, self.items):
            m = self.scene.members[part.member]
            item.pz = (m.layer - low) * (h + gap)
            item.sz = m.span * h + (m.span - 1) * gap
        top = max(item.pz + item.sz for item in self.items)
        self.bridge.floorSize = 40.0
        # keep the stack centred vertically around the orbit point
        for item in self.items:
            item.pz = item.pz - top / 2
        self.bridge.floorZ = -top / 2 - 0.6

    def set_transforms(self, transforms):
        if not self.ok or not self.items:
            return
        S = SCENE_SIZE / self.scene.extent
        for item, (a, x, y) in zip(self.items, transforms):
            item.move(x * S, y * S, math.degrees(a))

    def set_view(self, name):
        root = self.quick.rootObject()
        if root is not None:
            QMetaObject.invokeMethod(root, 'setView', Q_ARG('QVariant', name))

    def grab_image(self):
        return self.quick.grabFramebuffer()
