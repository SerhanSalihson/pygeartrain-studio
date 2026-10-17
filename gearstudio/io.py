"""Design files (*.gearstudio.json) and CAD export (binary STL, DXF R12)."""
import json
import os
import re
import struct

import numpy as np

from gearstudio import __version__
from gearstudio.catalog import GEAR_TYPES
from gearstudio.meshing import extrude, ring_circle

FORMAT = 'pygeartrain-studio'
FILE_FILTER = 'Gear train design (*.gearstudio.json);;JSON (*.json)'


# ---------------------------------------------------------------------------- designs

def design_to_dict(type_name, values, cfg, sizing=None, calculator=None, display=None):
    return {
        'format': FORMAT,
        'format_version': 1,
        'app_version': __version__,
        'gear_type': type_name,
        'values': dict(values),
        'config': list(cfg),
        'sizing': dict(sizing or {}),
        'calculator': dict(calculator or {}),
        'display': dict(display or {}),
    }


def save_design(path, design):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(design, f, indent=2)
    os.replace(tmp, path)


class DesignError(Exception):
    pass


def load_design(path):
    """Read and validate a design file. Returns (design dict, list of warnings).

    Unknown or out-of-range values fall back to defaults with a warning instead of failing."""
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise DesignError(f'Could not read {os.path.basename(path)}: {e}')
    if not isinstance(data, dict) or data.get('format') != FORMAT:
        raise DesignError(f'{os.path.basename(path)} is not a pyGearTrain Studio design.')
    name = data.get('gear_type')
    if name not in GEAR_TYPES:
        raise DesignError(f'Unknown gear train type "{name}".')
    spec = GEAR_TYPES[name]
    warnings = []
    raw = data.get('values') if isinstance(data.get('values'), dict) else {}
    values = {}
    for p in spec.params:
        if p.name not in raw:
            values[p.name] = p.default
            warnings.append(f'{p.name} missing, using {p.default}')
            continue
        v = raw[p.name]
        ok = ((p.kind == 'int' and isinstance(v, (int, float)) and not isinstance(v, bool) and p.lo <= v <= p.hi)
              or (p.kind == 'float' and isinstance(v, (int, float)) and not isinstance(v, bool) and p.lo <= v <= p.hi)
              or (p.kind == 'bool' and isinstance(v, bool))
              or (p.kind == 'choice' and v in p.choices))
        if ok:
            values[p.name] = int(v) if p.kind == 'int' else v
        else:
            values[p.name] = p.default
            warnings.append(f'{p.name} = {v!r} is invalid, using {p.default}')
    for k in raw:
        if k not in values:
            warnings.append(f'Ignored unknown value "{k}"')
    cfg = data.get('config')
    if not (isinstance(cfg, list) and len(cfg) == 2 + spec.n_constraints and all(isinstance(c, str) for c in cfg)):
        warnings.append('Configuration missing or invalid, using the default')
        cfg = list(spec.default_config)
    out = design_to_dict(name, values, cfg,
                         data.get('sizing') if isinstance(data.get('sizing'), dict) else {},
                         data.get('calculator') if isinstance(data.get('calculator'), dict) else {},
                         data.get('display') if isinstance(data.get('display'), dict) else {})
    return out, warnings


# ---------------------------------------------------------------------------- shared helpers

def safe_name(text):
    return re.sub(r'[^A-Za-z0-9]+', '_', text).strip('_').lower() or 'part'


def unique_members(scene):
    """[(member, count)] with identical copies (planets) counted once."""
    return [(m, len(m.parts)) for m in scene.members]


def placed_triangles(scene, part, transform, unit_mm, z0, thickness, max_pts=None):
    tris, _ = extrude(part, max_pts)
    a, x, y = transform
    c, s = np.cos(a), np.sin(a)
    out = np.empty_like(tris)
    out[..., 0] = (tris[..., 0] * c - tris[..., 1] * s + x) * unit_mm
    out[..., 1] = (tris[..., 0] * s + tris[..., 1] * c + y) * unit_mm
    out[..., 2] = z0 + tris[..., 2] * thickness
    return out


# ---------------------------------------------------------------------------- STL

def write_stl(path, tris, name='gear'):
    tris = np.asarray(tris, dtype=np.float64)
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-30
    rec = np.zeros(len(tris), dtype=[('n', '<f4', 3), ('v', '<f4', (3, 3)), ('attr', '<u2')])
    rec['n'] = n
    rec['v'] = tris
    with open(path, 'wb') as f:
        f.write(f'{name} - pyGearTrain Studio'.encode('ascii', 'replace')[:80].ljust(80, b' '))
        f.write(struct.pack('<I', len(tris)))
        f.write(rec.tobytes())


def read_stl(path):
    with open(path, 'rb') as f:
        f.read(80)
        n = struct.unpack('<I', f.read(4))[0]
        rec = np.frombuffer(f.read(n * 50), dtype=[('n', '<f4', 3), ('v', '<f4', (3, 3)), ('attr', '<u2')])
    return rec['v'].astype(np.float64)


def export_stl(scene, folder, transforms, unit_mm, thickness_mm, gap_mm=0.0, assembly=True):
    """One STL per member (first copy, at the origin) plus an optional assembly at the current
    phase with plates stacked by layer. Returns the written paths."""
    os.makedirs(folder, exist_ok=True)
    paths = []
    for m, count in unique_members(scene):
        part = m.parts[0]
        tris = placed_triangles(scene, part, (0.0, 0.0, 0.0), unit_mm, 0.0, thickness_mm * m.span)
        name = safe_name(m.label) + (f'_x{count}' if count > 1 else '')
        path = os.path.join(folder, name + '.stl')
        write_stl(path, tris, m.label)
        paths.append(path)
    if assembly:
        layers = sorted({m.layer for m in scene.members})
        allt = []
        for part, tr in zip(scene.parts, transforms):
            m = scene.members[part.member]
            z0 = (m.layer - layers[0]) * (thickness_mm + gap_mm)
            allt.append(placed_triangles(scene, part, tr, unit_mm, z0,
                                         thickness_mm * m.span + gap_mm * (m.span - 1)))
        path = os.path.join(folder, 'assembly.stl')
        write_stl(path, np.concatenate(allt), 'assembly')
        paths.append(path)
    return paths


# ---------------------------------------------------------------------------- DXF

_ACI = [5, 30, 3, 6, 1, 4, 34, 8]   # AutoCAD colour index per member, close to the app palette


def _dxf_layers(names):
    out = ['0', 'TABLE', '2', 'LAYER', '70', str(len(names))]
    for i, n in enumerate(names):
        out += ['0', 'LAYER', '2', n, '70', '0', '62', str(_ACI[i % len(_ACI)]), '6', 'CONTINUOUS']
    return out + ['0', 'ENDTAB']


def _dxf_polyline(layer, pts):
    out = ['0', 'POLYLINE', '8', layer, '66', '1', '70', '1', '10', '0.0', '20', '0.0', '30', '0.0']
    for x, y in pts:
        out += ['0', 'VERTEX', '8', layer, '10', f'{x:.6f}', '20', f'{y:.6f}', '30', '0.0']
    return out + ['0', 'SEQEND', '8', layer]


def write_dxf(path, layered_loops):
    """layered_loops: {layer name: [closed loop arrays in mm]}. Writes DXF R12 in millimetres."""
    names = list(layered_loops)
    out = ['0', 'SECTION', '2', 'HEADER', '9', '$ACADVER', '1', 'AC1009', '9', '$INSUNITS', '70', '4',
           '0', 'ENDSEC', '0', 'SECTION', '2', 'TABLES'] + _dxf_layers(names) + ['0', 'ENDSEC',
           '0', 'SECTION', '2', 'ENTITIES']
    for layer, loops in layered_loops.items():
        for loop in loops:
            out += _dxf_polyline(layer, loop)
    out += ['0', 'ENDSEC', '0', 'EOF']
    with open(path, 'w', encoding='ascii', newline='\r\n') as f:
        f.write('\n'.join(out) + '\n')


def read_dxf_polylines(path):
    """Minimal reader used by the tests: {layer: [loop arrays]} of closed POLYLINEs."""
    with open(path, encoding='ascii') as f:
        tok = [t.strip() for t in f.read().splitlines()]
    pairs = list(zip(tok[0::2], tok[1::2]))
    out, i = {}, 0
    while i < len(pairs):
        if pairs[i] == ('0', 'POLYLINE'):
            layer, closed, pts = None, False, []
            i += 1
            while pairs[i][0] != '0':
                if pairs[i][0] == '8':
                    layer = pairs[i][1]
                if pairs[i][0] == '70':
                    closed = int(pairs[i][1]) & 1 == 1
                i += 1
            while pairs[i] == ('0', 'VERTEX'):
                i += 1
                x = y = None
                while pairs[i][0] != '0':
                    if pairs[i][0] == '10':
                        x = float(pairs[i][1])
                    if pairs[i][0] == '20':
                        y = float(pairs[i][1])
                    i += 1
                pts.append((x, y))
            if closed:
                out.setdefault(layer, []).append(np.array(pts))
        else:
            i += 1
    return out


def _part_outline_loops(part):
    loops = list(part.loops)
    if part.ring_radius:
        loops = [ring_circle(part.ring_radius, 360)] + loops
    return loops


def export_dxf(scene, path, transforms, unit_mm, separate=False):
    """Assembly drawing at the current phase (one layer per member), or with separate=True one
    copy of each member laid out side by side. Returns the written path."""
    layered = {}
    if separate:
        x_off = 0.0
        for m, count in unique_members(scene):
            part = m.parts[0]
            r = max(part.radius, part.ring_radius or 0) * unit_mm
            x_off += r
            name = safe_name(m.label).upper() + (f'_X{count}' if count > 1 else '')
            layered[name] = [l * unit_mm + (x_off, 0.0) for l in _part_outline_loops(part)]
            x_off += r * 1.2
    else:
        for part, (a, x, y) in zip(scene.parts, transforms):
            m = scene.members[part.member]
            c, s = np.cos(a), np.sin(a)
            R = np.array([[c, -s], [s, c]])
            layer = safe_name(m.label).upper()
            layered.setdefault(layer, []).extend(
                ((l @ R.T) + (x, y)) * unit_mm for l in _part_outline_loops(part))
    write_dxf(path, layered)
    return path


# ---------------------------------------------------------------------------- involute gear sets

def export_involute(folder, gearsets, face_width, gap=0.0):
    """True involute parts of one or more planetary stages (gearstudio.involute GearSets), in mm.

    Writes per stage sun / planet / ring STLs (planets once, count in the name) and one DXF with
    every stage assembled and phased. Returns the written paths."""
    from collections import namedtuple
    from gearstudio.involute import outlines
    Body = namedtuple('Body', 'loops solid parent ring_radius')
    os.makedirs(folder, exist_ok=True)
    paths, layered = [], {}
    for i, gs in enumerate(gearsets):
        tag = f'stage{i + 1}_' if len(gearsets) > 1 else ''
        o = outlines(gs)
        parts = [('sun', Body([o['sun']], [True], [-1], None), 1),
                 ('planet', Body([o['planet_part']], [True], [-1], None), gs.n),
                 ('ring', Body([o['ring_bore']], [False], [-1], o['ring_outer_r']), 1)]
        for name, body, count in parts:
            tris, _ = extrude(body)
            tris = tris.copy()
            tris[..., 2] *= face_width
            path = os.path.join(folder, f'{tag}{name}' + (f'_x{count}' if count > 1 else '') + '.stl')
            write_stl(path, tris, f'{tag}{name}')
            paths.append(path)
        layered[f'{tag.upper()}SUN'] = [o['sun']]
        layered[f'{tag.upper()}PLANETS'] = o['planets']
        layered[f'{tag.upper()}RING'] = [ring_circle(o['ring_outer_r'], 360), o['ring_bore']]
    path = os.path.join(folder, 'involute_set.dxf')
    write_dxf(path, layered)
    paths.append(path)
    return paths
