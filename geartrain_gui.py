"""pyGearTrain Studio: an interactive GUI around pygeartrain.

Pick a gear train, tune its tooth counts and profile parameters, choose which
members are input / output / fixed, and watch it run in 2D or 3D. Extra tabs show
the symbolic kinematics and sweep the gear ratio over tooth-count ranges.
"""
import ctypes
import json
import os
import sys
import time
from collections import namedtuple
from dataclasses import dataclass, field
from typing import Callable

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor', 'pyGearTrain'))

import numpy as np
import sympy
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

import matplotlib
matplotlib.use('TkAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.path import Path
from matplotlib.patches import PathPatch, Rectangle
from matplotlib.lines import Line2D
from matplotlib.mathtext import MathTextParser
import matplotlib.ticker

from pygeartrain import planetary, compound_planetary, cycloid, compound_cycloid, nabtesco, simple
from viewer3d import Gear3DView
from involute_check import check_planetary

__version__ = '1.1.0'


# ----------------------------------------------------------------------------
# Gear train catalogue
# ----------------------------------------------------------------------------

Param = namedtuple('Param', 'name label kind default lo hi step choices', defaults=(None, None, None, None))
# layer/span place the member in the 3D view: which plate it sits in and how many plates it spans
Comp = namedtuple('Comp', 'label dof profiles ring layer span', defaults=(0, 1))


@dataclass
class GearType:
    name: str
    kin_cls: type
    description: str
    params: list
    dof_labels: dict
    default_config: tuple       # (input, output, *constraints)
    geom: Callable              # values -> dict of geometric symbols
    build: Callable             # (kinematics, values) -> GearGeometry
    components: Callable        # (values, arranged) -> [Comp]
    code: Callable              # (values, config) -> python snippet
    checks: Callable = lambda v: []
    presets: dict = field(default_factory=dict)
    sweep_axes: tuple = ()      # default (x, y) parameters for the ratio sweep
    derive: Callable = None     # values -> values with dependent tooth counts filled in
    involute: Callable = None   # values -> (S, P, R, N) for the involute manufacturability check

    @property
    def n_constraints(self):
        return len(self.kin_cls.dofs()) - len(self.kin_cls.equations) - 1


def cfg_args(cfg):
    return ', '.join(repr(c) for c in cfg)


def planetary_checks(R, P, S, N, tag=''):
    out = []
    if R != S + 2 * P:
        out.append(f'{tag}R should equal S + 2P = {S + 2 * P} for the planets to mesh with both sun and ring.')
    if N and (R + S) % N:
        out.append(f'{tag}(R + S) = {R + S} is not divisible by N = {N}: planets cannot be spaced evenly.')
    return out


PLANETARY = GearType(
    name='Planetary',
    kin_cls=planetary.Planetary,
    description='Classic single-stage epicyclic gear: sun, planets on a carrier, and a ring.',
    params=[
        Param('R', 'Ring teeth  R', 'int', 14, 3, 300),
        Param('P', 'Planet teeth  P', 'int', 4, 1, 150),
        Param('S', 'Sun teeth  S', 'int', 6, 1, 150),
        Param('N', 'Planets  N', 'int', 5, 1, 24),
        Param('b', 'Epi/hypo blend  b', 'float', 0.5, 0.05, 0.95, 0.05),
    ],
    dof_labels={'s': 'Sun', 'c': 'Carrier', 'r': 'Ring', 'p': 'Planets'},
    default_config=('s', 'c', 'r'),
    geom=lambda v: {'R': v['R'], 'P': v['P'], 'S': v['S']},
    build=lambda k, v: planetary.PlanetaryGeometry.create(k, (v['R'], v['P'], v['S']), v['N'], b=v['b']),
    components=lambda v, a: [
        Comp('Carrier', 'c', [a[3]], False, -1),
        Comp('Ring', 'r', [a[0]], True),
        Comp('Sun', 's', [a[2]], False),
        Comp('Planets', 'p', a[1], False),
    ],
    code=lambda v, c: (
        "from pygeartrain.planetary import Planetary, PlanetaryGeometry\n"
        f"kinematics = Planetary({cfg_args(c)})\n"
        f"gear = PlanetaryGeometry.create(kinematics, ({v['R']}, {v['P']}, {v['S']}), {v['N']}, b={v['b']})\n"
        "print(gear)\ngear.animate()\n"),
    checks=lambda v: planetary_checks(v['R'], v['P'], v['S'], v['N']),
    sweep_axes=('P', 'S'),
    derive=lambda v: {**v, 'R': v['S'] + 2 * v['P']},
    involute=lambda v: (v['S'], v['P'], v['R'], v['N']),
    presets={
        'Classic 14/4/6, 5 planets': ({'R': 14, 'P': 4, 'S': 6, 'N': 5, 'b': 0.8}, ('s', 'c', 'r')),
        '11/2/7, 6 planets': ({'R': 11, 'P': 2, 'S': 7, 'N': 6, 'b': 0.6}, ('s', 'c', 'r')),
        'Carrier in, ring out, sun fixed': ({'R': 14, 'P': 4, 'S': 6, 'N': 5, 'b': 0.8}, ('c', 'r', 's')),
        'Star (carrier fixed)': ({'R': 30, 'P': 9, 'S': 12, 'N': 3, 'b': 0.5}, ('s', 'r', 'c')),
    },
)


def _cp_build(k, v):
    return compound_planetary.CompoundPlanetaryGeometry.create(
        k, (v['R1'], v['P1'], v['S1']), (v['R2'], v['P2'], v['S2']), v['N'],
        b1=v['b1'], b2=v['b2'], show_carrier=v['carrier'])


COMPOUND_PLANETARY = GearType(
    name='Compound planetary',
    kin_cls=compound_planetary.CompoundPlanetary,
    description='Two stacked planetary stages sharing fused planets and carrier (Wolfrom topology).',
    params=[
        Param('R1', 'Ring 1 teeth', 'int', 22, 3, 300),
        Param('P1', 'Planet 1 teeth', 'int', 7, 1, 150),
        Param('S1', 'Sun 1 teeth', 'int', 8, 1, 150),
        Param('R2', 'Ring 2 teeth', 'int', 21, 3, 300),
        Param('P2', 'Planet 2 teeth', 'int', 6, 1, 150),
        Param('S2', 'Sun 2 teeth', 'int', 9, 1, 150),
        Param('N', 'Planets  N', 'int', 5, 1, 24),
        Param('b1', 'Blend stage 1', 'float', 0.4, 0.05, 0.95, 0.05),
        Param('b2', 'Blend stage 2', 'float', 0.6, 0.05, 0.95, 0.05),
        Param('carrier', 'Show carrier', 'bool', False),
    ],
    dof_labels={'s1': 'Sun 1', 's2': 'Sun 2', 'r1': 'Ring 1', 'r2': 'Ring 2', 'p': 'Planets', 'c': 'Carrier'},
    default_config=('s1', 'r2', 'r1'),
    geom=lambda v: {k: v[k] for k in ('R1', 'P1', 'S1', 'R2', 'P2', 'S2')},
    build=_cp_build,
    components=lambda v, a: [
        Comp('Carrier', 'c', [a[0][3]], False, -1),
        Comp('Ring 1', 'r1', [a[0][0]], True, 0),
        Comp('Ring 2', 'r2', [a[1][0]], True, 1),
        Comp('Sun 1', 's1', [a[0][2]], False, 0),
        Comp('Sun 2', 's2', [a[1][2]], False, 1),
        Comp('Planets (stage 1)', 'p', a[0][1], False, 0),
        Comp('Planets (stage 2)', 'p', a[1][1], False, 1),
    ],
    code=lambda v, c: (
        "from pygeartrain.compound_planetary import CompoundPlanetary, CompoundPlanetaryGeometry\n"
        f"kinematics = CompoundPlanetary({cfg_args(c)})\n"
        f"gear = CompoundPlanetaryGeometry.create(kinematics, ({v['R1']}, {v['P1']}, {v['S1']}), "
        f"({v['R2']}, {v['P2']}, {v['S2']}), {v['N']}, b1={v['b1']}, b2={v['b2']}, show_carrier={v['carrier']})\n"
        "print(gear)\ngear.animate()\n"),
    checks=lambda v: planetary_checks(v['R1'], v['P1'], v['S1'], v['N'], 'Stage 1: ')
                     + planetary_checks(v['R2'], v['P2'], v['S2'], v['N'], 'Stage 2: '),
    sweep_axes=('P1', 'P2'),
    derive=lambda v: {**v, 'R1': v['S1'] + 2 * v['P1'], 'R2': v['S2'] + 2 * v['P2']},
    presets={
        'README 22/7/8 + 21/6/9': ({'R1': 22, 'P1': 7, 'S1': 8, 'R2': 21, 'P2': 6, 'S2': 9, 'N': 5, 'b1': 0.4, 'b2': 0.6}, ('s1', 'r2', 'r1')),
        'Lowest tooth count 5/2/1 + 4/1/2': ({'R1': 5, 'P1': 2, 'S1': 1, 'R2': 4, 'P2': 1, 'S2': 2, 'N': 3, 'b1': 0.25, 'b2': 0.75}, ('s1', 'r2', 'r1')),
        '11/2/7 + 8/2/4, 6 planets': ({'R1': 11, 'P1': 2, 'S1': 7, 'R2': 8, 'P2': 2, 'S2': 4, 'N': 6, 'b1': 0.7, 'b2': 0.4}, ('s1', 'r2', 'r1')),
        '15/5/5 + 14/4/6': ({'R1': 15, 'P1': 5, 'S1': 5, 'R2': 14, 'P2': 4, 'S2': 6, 'N': 5, 'b1': 0.3, 'b2': 0.7}, ('s1', 'r2', 'r1')),
        'High ratio 55/21/13 + 42/16/10': ({'R1': 55, 'P1': 21, 'S1': 13, 'R2': 42, 'P2': 16, 'S2': 10, 'N': 4, 'b1': 0.55, 'b2': 0.45}, ('s1', 'r2', 'r1')),
        'GearDownForWhat 43/8/27 + 37/7/23': ({'R1': 43, 'P1': 8, 'S1': 27, 'R2': 37, 'P2': 7, 'S2': 23, 'N': 10, 'b1': 0.4, 'b2': 0.4}, ('s1', 'r2', 'r1')),
        'Backdrivable 43/19/5 + 46/19/8': ({'R1': 43, 'P1': 19, 'S1': 5, 'R2': 46, 'P2': 19, 'S2': 8, 'N': 3, 'b1': 0.5, 'b2': 0.5}, ('s1', 'r2', 'r1')),
        'Carrier-driven 15/5/5 + 14/4/6': ({'R1': 15, 'P1': 5, 'S1': 5, 'R2': 14, 'P2': 4, 'S2': 6, 'N': 5, 'b1': 0.4, 'b2': 0.7, 'carrier': True}, ('c', 'r2', 'r1')),
    },
)


def _cy_build(k, v):
    return cycloid.CycloidGeometry(kinematics=k, geometry={'P': v['P']}, P=v['P'], b=v['b'], f=v['f'],
                                   cycloid=v['cycloid'], O=v['O'])


CYCLOID = GearType(
    name='Cycloidal drive',
    kin_cls=cycloid.Cycloid,
    description='Single cycloidal disc on an eccentric (carrier) rolling inside a pin ring; '
                'optional output pins take the disc rotation out.',
    params=[
        Param('P', 'Disc lobes  P', 'int', 9, 2, 80),
        Param('cycloid', 'Profile', 'choice', 'epi', choices=('epi', 'hypo')),
        Param('O', 'Output pins  O', 'int', 6, 0, 24),
        Param('b', 'Pin size  b', 'float', 1.0, 0.1, 5.0, 0.1),
        Param('f', 'Cycloid depth  f', 'float', 0.8, 0.05, 1.0, 0.05),
    ],
    dof_labels={'c': 'Eccentric', 'p': 'Disc', 'r': 'Pin ring'},
    default_config=('c', 'p', 'r'),
    geom=lambda v: {'P': v['P']},
    build=_cy_build,
    components=lambda v, a: [
        Comp('Pin ring' if v['cycloid'] == 'epi' else 'Ring', 'r', [a[0]], v['cycloid'] == 'hypo'),
        Comp('Cycloid disc', 'p', [a[1]], False),
        Comp('Output flange', 'p', [a[3]], False, 1),
        Comp('Eccentric', 'c', [a[2]], False, 0, 2),
    ],
    code=lambda v, c: (
        "from pygeartrain.cycloid import Cycloid, CycloidGeometry\n"
        f"kinematics = Cycloid({cfg_args(c)})\n"
        f"gear = CycloidGeometry(kinematics=kinematics, geometry={{'P': {v['P']}}}, P={v['P']}, "
        f"b={v['b']}, f={v['f']}, cycloid={v['cycloid']!r}, O={v['O']})\n"
        "print(gear)\ngear.animate()\n"),
    presets={
        'Epicycloid, 9 lobes, 6 output pins': ({'P': 9, 'cycloid': 'epi', 'O': 6, 'b': 1.0, 'f': 0.8}, ('c', 'p', 'r')),
        'Epicycloid, 4 lobes': ({'P': 4, 'cycloid': 'epi', 'O': 0, 'b': 1.0, 'f': 0.8}, ('c', 'p', 'r')),
        'Hypocycloid, 4 lobes': ({'P': 4, 'cycloid': 'hypo', 'O': 0, 'b': 1.0, 'f': 0.8}, ('c', 'p', 'r')),
        'Ring output, disc held': ({'P': 11, 'cycloid': 'epi', 'O': 0, 'b': 1.0, 'f': 0.8}, ('c', 'r', 'p')),
    },
)


def _cc_build(k, v):
    return compound_cycloid.CompoundCycloidGeometry(
        kinematics=k, geometry={'P1': v['P1'], 'P2': v['P2']},
        P1=v['P1'], P2=v['P2'], b=v['b'], f=v['f'], cycloid=v['cycloid'])


COMPOUND_CYCLOID = GearType(
    name='Compound cycloid',
    kin_cls=compound_cycloid.CompoundCycloid,
    description='Two back-to-back cycloidal discs fused together, each in its own pin ring and sharing one '
                'eccentric. Very high ratios when the lobe counts differ by one.',
    params=[
        Param('P1', 'Disc 1 lobes', 'int', 8, 2, 80),
        Param('P2', 'Disc 2 lobes', 'int', 7, 2, 80),
        Param('cycloid', 'Profile', 'choice', 'epi', choices=('epi', 'hypo')),
        Param('b', 'Pin size  b', 'float', 1.2, 0.1, 5.0, 0.1),
        Param('f', 'Cycloid depth  f', 'float', 0.5, 0.05, 1.0, 0.05),
    ],
    dof_labels={'c': 'Eccentric', 'p': 'Discs', 'r1': 'Ring 1', 'r2': 'Ring 2'},
    default_config=('c', 'r2', 'r1'),
    geom=lambda v: {'P1': v['P1'], 'P2': v['P2']},
    build=_cc_build,
    components=lambda v, a: [
        Comp('Ring 1', 'r1', [a[0][0]], v['cycloid'] == 'hypo', 0),
        Comp('Ring 2', 'r2', [a[1][0]], v['cycloid'] == 'hypo', 1),
        Comp('Disc 1', 'p', [a[0][1]], False, 0),
        Comp('Disc 2', 'p', [a[1][1]], False, 1),
        Comp('Eccentric', 'c', [a[0][2]], False, 0),
        Comp('Eccentric', 'c', [a[1][2]], False, 1),
    ],
    code=lambda v, c: (
        "from pygeartrain.compound_cycloid import CompoundCycloid, CompoundCycloidGeometry\n"
        f"kinematics = CompoundCycloid({cfg_args(c)})\n"
        f"gear = CompoundCycloidGeometry.create(kinematics, P1={v['P1']}, P2={v['P2']}, b={v['b']}, "
        f"f={v['f']}, cycloid={v['cycloid']!r})\n"
        "print(gear)\ngear.animate()\n"),
    checks=lambda v: ['P1 = P2: the two stages cancel and the ratio is undefined.'] if v['P1'] == v['P2'] else [],
    sweep_axes=('P1', 'P2'),
    presets={
        'Epi 8/7 (64:1)': ({'P1': 8, 'P2': 7, 'cycloid': 'epi', 'b': 1.2, 'f': 0.5}, ('c', 'r2', 'r1')),
        'Epi 3/4 (README)': ({'P1': 3, 'P2': 4, 'cycloid': 'epi', 'b': 1.0, 'f': 1.0}, ('c', 'r2', 'r1')),
        'Hypo 6/7': ({'P1': 6, 'P2': 7, 'cycloid': 'hypo', 'b': 3.5, 'f': 0.7}, ('c', 'r2', 'r1')),
    },
)


NABTESCO = GearType(
    name='Nabtesco (RV)',
    kin_cls=nabtesco.NabtescoKinematics,
    description='RV-style reducer: an input sun drives crank gears that wobble a cycloidal disc inside a pin '
                'ring; the disc carrier is the output.',
    params=[
        Param('L', 'Disc lobes  L', 'int', 15, 3, 60),
        Param('S', 'Sun teeth  S', 'int', 8, 1, 80),
        Param('W', 'Crank gear teeth  W', 'int', 19, 1, 80),
        Param('N', 'Cranks  N', 'int', 3, 1, 8),
        Param('b', 'Pin size  b', 'float', 1.5, 0.1, 5.0, 0.1),
        Param('f', 'Cycloid depth  f', 'float', 0.8, 0.05, 1.0, 0.05),
    ],
    dof_labels={'s': 'Input sun', 'o': 'Output carrier', 'r': 'Pin ring', 'l': 'Cycloid disc', 'w': 'Cranks'},
    default_config=('s', 'o', 'r'),
    sweep_axes=('L', 'W'),
    geom=lambda v: {'L': v['L'], 'S': v['S'], 'W': v['W']},
    build=lambda k, v: nabtesco.NabtescoGeometry.create(k, L=v['L'], S=v['S'], W=v['W'], b=v['b'], f=v['f'], N=v['N']),
    components=lambda v, a: [
        Comp('Pin ring', 'r', [a[0][0]], False),
        Comp('Cycloid disc', 'l', [a[0][1]], False),
        Comp('Crank gears', 'w', a[1][1], False, 1),
        Comp('Input sun', 's', [a[1][2]], False, 1),
    ],
    code=lambda v, c: (
        "from pygeartrain.nabtesco import NabtescoKinematics, NabtescoGeometry\n"
        f"kinematics = NabtescoKinematics({cfg_args(c)})\n"
        f"gear = NabtescoGeometry.create(kinematics, L={v['L']}, S={v['S']}, W={v['W']}, b={v['b']}, "
        f"f={v['f']}, N={v['N']})\n"
        "print(gear)\ngear.animate()\n"),
    presets={
        'L15 S8 W19 (test)': ({'L': 15, 'S': 8, 'W': 19, 'N': 3, 'b': 1.5, 'f': 0.8}, ('s', 'o', 'r')),
        'L15 S10 W16, 4 cranks': ({'L': 15, 'S': 10, 'W': 16, 'N': 4, 'b': 1.5, 'f': 0.9}, ('s', 'o', 'r')),
    },
)


SIMPLE = GearType(
    name='Simple pair',
    kin_cls=simple.SimpleGear,
    description='Two external gears meshing side by side.',
    params=[
        Param('A', 'Gear A teeth', 'int', 4, 2, 60),
        Param('B', 'Gear B teeth', 'int', 5, 2, 60),
    ],
    dof_labels={'a': 'Gear A', 'b': 'Gear B'},
    default_config=('a', 'b'),
    geom=lambda v: {'A': v['A'], 'B': v['B']},
    build=lambda k, v: simple.SimpleGeometry(k, {'A': v['A'], 'B': v['B']}),
    components=lambda v, a: [Comp('Gear A', 'a', [a[0]], False), Comp('Gear B', 'b', [a[1]], False)],
    code=lambda v, c: (
        "from pygeartrain.simple import SimpleGear, SimpleGeometry\n"
        f"kinematics = SimpleGear({cfg_args(c)})\n"
        f"gear = SimpleGeometry(kinematics, {{'A': {v['A']}, 'B': {v['B']}}})\n"
        "print(gear)\ngear.animate()\n"),
)


NESTED = GearType(
    name='Nested (gerotor)',
    kin_cls=simple.NestedGear,
    description='An N-lobe rotor inside an (N+1)-lobe housing, as in a gerotor or progressive cavity pump.',
    params=[Param('N', 'Inner lobes  N', 'int', 4, 2, 40)],
    dof_labels={'a': 'Inner rotor', 'b': 'Outer rotor'},
    default_config=('a', 'b'),
    geom=lambda v: {'N': v['N']},
    build=lambda k, v: simple.NestedGeometry(k, {'N': v['N']}),
    components=lambda v, a: [Comp('Outer rotor', 'b', [a[1]], True), Comp('Inner rotor', 'a', [a[0]], False)],
    code=lambda v, c: (
        "from pygeartrain.simple import NestedGear, NestedGeometry\n"
        f"kinematics = NestedGear({cfg_args(c)})\n"
        f"gear = NestedGeometry(kinematics, {{'N': {v['N']}}})\n"
        "print(gear)\ngear.animate()\n"),
)


GEAR_TYPES = {t.name: t for t in
              [PLANETARY, COMPOUND_PLANETARY, CYCLOID, COMPOUND_CYCLOID, NABTESCO, SIMPLE, NESTED]}


# ----------------------------------------------------------------------------
# Rendering helpers: turn pygeartrain Profiles into filled matplotlib paths
# ----------------------------------------------------------------------------

THEMES = {
    'light': dict(bg='#F5F6F8', field='#FFFFFF', fg='#1F2937', muted='#5B6472', heading='#333333',
                  accent='#0072B2', warn='#B45309', err='#B91C1C', border='#C9CED6', select='#DCE7F3',
                  button='#E9ECF0', button_active='#DCE1E7', fig='#FFFFFF', axis='#333333', fill_alpha=0.28),
    'dark': dict(bg='#1F2023', field='#2B2D31', fg='#E6E8EB', muted='#9AA3AE', heading='#C9CDD3',
                 accent='#56B4E9', warn='#F2A33A', err='#F87171', border='#3A3D43', select='#34465A',
                 button='#2E3136', button_active='#3A3E44', fig='#232428', axis='#C9CDD3', fill_alpha=0.36),
}
SETTINGS_PATH = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'pyGearTrainStudio', 'settings.json')


def load_settings():
    try:
        with open(SETTINGS_PATH, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass


def system_prefers_dark():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as k:
            return winreg.QueryValueEx(k, 'AppsUseLightTheme')[0] == 0
    except (OSError, ImportError):
        return False


MEMBER_COLORS = ['#0072B2', '#E69F00', '#009E73', '#CC79A7', '#D55E00', '#56B4E9', '#8C6D31', '#7F7F7F']
ROLE_COLORS = {'input': '#D55E00', 'output': '#0072B2', 'fixed': '#8A8A8A', 'free': '#009E73'}


def trace_loops(cubes):
    """Split the edge list of a 1-complex into closed vertex loops."""
    nxt = {int(a): int(b) for a, b in cubes}
    seen, loops = set(), []
    for start in nxt:
        if start in seen:
            continue
        loop, v = [], start
        while v not in seen and v in nxt:
            seen.add(v)
            loop.append(v)
            v = nxt[v]
        if len(loop) > 2:
            loops.append(np.array(loop))
    return loops


def signed_area(p):
    x, y = p[:, 0], p[:, 1]
    return 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)


# loops: vertex index arrays into the concatenated profile vertices, solids CCW / holes CW
# parent: for each loop the enclosing loop one level up (-1 = top level)
LoopShape = namedtuple('LoopShape', 'loops solid parent circle extent')


def analyse_component(comp):
    """Work out loop structure, nesting and orientation of a member's profiles.

    Rigid motion preserves all of this, so it is done once and reused every frame."""
    verts0 = [p.vertices for p in comp.profiles]
    offsets = np.cumsum([0] + [len(v) for v in verts0])
    loops = []
    for p, off in zip(comp.profiles, offsets):
        cubes = p.topology.elements[-1]
        if len(cubes):
            loops.extend(l + off for l in trace_loops(cubes))
    if not loops:
        return None
    allv = np.concatenate(verts0)

    polys = [allv[l] for l in loops]
    paths = [Path(p) for p in polys]
    n = len(loops)
    inside = np.zeros((n, n), dtype=bool)     # inside[i, j]: loop i lies within loop j
    for i, p in enumerate(polys):
        sample = p[np.linspace(0, len(p) - 1, 5).astype(int)]
        for j, q in enumerate(paths):
            inside[i, j] = i != j and np.sum(q.contains_points(sample)) >= 3
    depth = inside.sum(axis=1)

    # rings have only their toothed inner edge; give them an outer body
    circle = None
    radius = np.max(np.linalg.norm(allv, axis=1))
    if comp.ring:
        t = np.linspace(0, 2 * np.pi, 181)
        circle = np.c_[np.cos(t), np.sin(t)] * radius * 1.08
        depth = depth + 1
    solid = [d % 2 == 0 for d in depth]
    parent = []
    for i in range(n):
        up = [j for j in range(n) if inside[i, j] and depth[j] == depth[i] - 1]
        parent.append(up[0] if up else -1)
    oriented = [l if (signed_area(p) > 0) == sd else l[::-1] for l, p, sd in zip(loops, polys, solid)]
    return LoopShape(oriented, solid, parent, circle, radius * (1.08 if comp.ring else 1.0))


class ComponentArtist:
    """One gear member drawn as a single compound PathPatch; every frame only gathers
    the transformed vertices into the precomputed path layout, which keeps animation cheap."""

    def __init__(self, ax, comp, color, fill=True, alpha=0.28):
        self.comp = comp
        self.shape = analyse_component(comp)
        self.empty = self.shape is None
        if self.empty:
            return
        self.circle = self.shape.circle
        self.extent = self.shape.extent
        idx, codes = [], []
        if self.circle is not None:
            codes += [Path.MOVETO] + [Path.LINETO] * 179 + [Path.CLOSEPOLY]
        for l in self.shape.loops:
            idx.append(np.r_[l, l[:1]])
            codes += [Path.MOVETO] + [Path.LINETO] * (len(l) - 1) + [Path.CLOSEPOLY]
        self.idx = np.concatenate(idx)
        self.codes = np.array(codes, dtype=np.uint8)
        self.patch = PathPatch(self._path(comp.profiles), lw=1.3, joinstyle='round')
        self.set_style(color, fill, alpha)
        ax.add_patch(self.patch)

    def _path(self, profiles):
        v = np.concatenate([p.vertices for p in profiles])[self.idx]
        if self.circle is not None:
            v = np.concatenate([self.circle, v])
        return Path(v, self.codes)

    def set_style(self, color, fill, alpha=0.28):
        self.patch.set_edgecolor(color)
        self.patch.set_facecolor(matplotlib.colors.to_rgba(color, alpha if fill else 0.0))

    def update(self, profiles):
        if not self.empty:
            self.patch.set_path(self._path(profiles))


# ----------------------------------------------------------------------------
# The application
# ----------------------------------------------------------------------------

class GearStudio(tk.Tk):
    FPS = 30

    def __init__(self):
        super().__init__()
        self.title('pyGearTrain Studio')
        self.geometry('1360x860')
        self.minsize(1000, 680)
        icon = os.path.join(getattr(sys, '_MEIPASS', HERE), 'build_assets', 'gear.ico')
        if os.path.exists(icon):
            self.iconbitmap(icon)
        self.settings = load_settings()
        self.theme_pref = tk.StringVar(value=self.settings.get('theme', 'system'))
        self.theme = THEMES['dark' if self._wants_dark() else 'light']
        self.sweep_meta = None
        self._style()

        self.kin_cache = {}
        self.spec = None
        self.gear = None
        self.kin = None
        self.artists = []
        self.playing = True
        self.input_angle = 0.0
        self.last_t = time.perf_counter()
        self._suspend = False
        self._pending = None
        self._scrubbing = False

        self._build_layout()
        self.apply_theme(redraw=False)
        self.type_var.set(PLANETARY.name)
        self.on_type_change()
        self.after(int(1000 / self.FPS), self.tick)
        self.bind('<space>', lambda e: self.toggle_play() if not isinstance(e.widget, (tk.Entry, ttk.Entry, ttk.Spinbox)) else None)

    # ---------------- layout ----------------

    def _wants_dark(self):
        pref = self.theme_pref.get()
        return pref == 'dark' or (pref == 'system' and system_prefers_dark())

    def _style(self):
        """Theme colours for every ttk widget; called again whenever the theme changes."""
        t = self.theme
        s = ttk.Style(self)
        s.theme_use('clam')
        self.configure(bg=t['bg'])
        s.configure('.', background=t['bg'], foreground=t['fg'], font=('Segoe UI', 10), fieldbackground=t['field'],
                    bordercolor=t['border'], lightcolor=t['bg'], darkcolor=t['bg'], troughcolor=t['field'],
                    selectbackground=t['select'], selectforeground=t['fg'], insertcolor=t['fg'], arrowcolor=t['fg'])
        s.configure('TFrame', background=t['bg'])
        s.configure('Side.TFrame', background=t['bg'])
        s.configure('TLabelframe', background=t['bg'], bordercolor=t['border'])
        s.configure('TLabelframe.Label', background=t['bg'], font=('Segoe UI Semibold', 10), foreground=t['heading'])
        s.configure('TLabel', background=t['bg'], foreground=t['fg'])
        s.configure('Title.TLabel', font=('Segoe UI Semibold', 16), foreground=t['fg'])
        s.configure('Muted.TLabel', foreground=t['muted'], font=('Segoe UI', 9))
        s.configure('Ratio.TLabel', font=('Segoe UI Semibold', 20), foreground=t['accent'])
        s.configure('Warn.TLabel', foreground=t['warn'], font=('Segoe UI', 9))
        s.configure('Err.TLabel', foreground=t['err'], font=('Segoe UI', 9))
        s.configure('TButton', background=t['button'], foreground=t['fg'], bordercolor=t['border'])
        s.map('TButton', background=[('pressed', t['button_active']), ('active', t['button_active'])])
        s.configure('Accent.TButton', font=('Segoe UI Semibold', 10))
        for w in ('TCombobox', 'TSpinbox', 'TEntry'):
            s.configure(w, fieldbackground=t['field'], background=t['button'], foreground=t['fg'],
                        arrowcolor=t['fg'], bordercolor=t['border'])
        s.map('TCombobox', fieldbackground=[('readonly', t['field'])], foreground=[('readonly', t['fg'])],
              selectbackground=[('readonly', t['field'])], selectforeground=[('readonly', t['fg'])],
              background=[('active', t['button_active'])])
        s.map('TSpinbox', background=[('active', t['button_active'])])
        for w in ('TCheckbutton', 'TRadiobutton'):
            s.configure(w, background=t['bg'], foreground=t['fg'], indicatorbackground=t['field'],
                        indicatorforeground=t['fg'])
            s.map(w, background=[('active', t['bg'])], indicatorbackground=[('pressed', t['select'])])
        s.configure('TNotebook', background=t['bg'], bordercolor=t['border'])
        s.configure('TNotebook.Tab', background=t['button'], foreground=t['muted'], padding=(10, 4),
                    bordercolor=t['border'])
        s.map('TNotebook.Tab', background=[('selected', t['field'])], foreground=[('selected', t['fg'])])
        s.configure('Treeview', rowheight=24, background=t['field'], fieldbackground=t['field'], foreground=t['fg'])
        s.map('Treeview', background=[('selected', t['select'])], foreground=[('selected', t['fg'])])
        s.configure('Treeview.Heading', background=t['button'], foreground=t['fg'], bordercolor=t['border'])
        s.map('Treeview.Heading', background=[('active', t['button_active'])])
        s.configure('Horizontal.TScale', background=t['button'], troughcolor=t['field'], bordercolor=t['border'])
        s.configure('Vertical.TScrollbar', background=t['button'], troughcolor=t['bg'], bordercolor=t['bg'],
                    arrowcolor=t['fg'])
        s.configure('TPanedwindow', background=t['border'])
        # drop-down lists of comboboxes are plain Tk widgets, styled through the option database
        for opt, key in (('background', 'field'), ('foreground', 'fg'),
                         ('selectBackground', 'select'), ('selectForeground', 'fg')):
            self.option_add(f'*TCombobox*Listbox.{opt}', t[key])

    def on_theme_change(self):
        self.settings['theme'] = self.theme_pref.get()
        save_settings(self.settings)
        self.theme = THEMES['dark' if self._wants_dark() else 'light']
        self._style()
        self.apply_theme()

    def apply_theme(self, redraw=True):
        """Push the current theme into the sidebar canvas, the title bar and every figure."""
        t = self.theme
        self.side_canvas.configure(bg=t['bg'])
        matplotlib.rcParams.update({
            'figure.facecolor': t['fig'], 'axes.facecolor': t['fig'], 'savefig.facecolor': t['fig'],
            'text.color': t['fg'], 'axes.labelcolor': t['fg'], 'axes.edgecolor': t['axis'],
            'xtick.color': t['axis'], 'ytick.color': t['axis'],
        })
        for fig in (self.fig, self.kfig, self.sfig):
            fig.set_facecolor(t['fig'])
        self.readout.set_color(t['fg'])
        self.view3d.apply_theme(t)
        self.after(10, self._titlebar)
        if redraw and self.gear is not None:
            self.restyle(redraw=False)
            self.update_kinematics_tab()
            if self.sweep_meta:
                self.compute_sweep()
            self.update_frame(sync_slider=False)
            self.canvas.draw_idle()

    def _titlebar(self):
        """Ask Windows 10/11 for a dark or light title bar to match the theme."""
        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            value = ctypes.c_int(1 if self.theme is THEMES['dark'] else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
            # SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED: repaint the frame now
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x1 | 0x2 | 0x4 | 0x20)
        except (AttributeError, OSError):
            pass

    def _build_layout(self):
        paned = ttk.PanedWindow(self, orient='horizontal')
        paned.pack(fill='both', expand=True)

        # scrollable sidebar
        side_outer = ttk.Frame(paned, style='Side.TFrame', width=330)
        canvas = tk.Canvas(side_outer, bg=self.theme['bg'], highlightthickness=0, width=320)
        self.side_canvas = canvas
        sb = ttk.Scrollbar(side_outer, orient='vertical', command=canvas.yview)
        self.side = ttk.Frame(canvas, style='Side.TFrame', padding=(14, 12))
        self.side.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=self.side, anchor='nw')
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        canvas.bind_all('<MouseWheel>', lambda e: canvas.yview_scroll(-e.delta // 120, 'units')
                        if str(e.widget).startswith(str(side_outer)) else None)
        paned.add(side_outer, weight=0)

        main = ttk.Frame(paned)
        paned.add(main, weight=1)

        s = self.side
        ttk.Label(s, text='pyGearTrain Studio', style='Title.TLabel').pack(anchor='w')
        ttk.Label(s, text=f'v{__version__} · gear train kinematics & profiles',
                  style='Muted.TLabel').pack(anchor='w', pady=(0, 10))

        f = ttk.LabelFrame(s, text='Gear train', padding=8)
        f.pack(fill='x', pady=4)
        self.type_var = tk.StringVar()
        cb = ttk.Combobox(f, textvariable=self.type_var, values=list(GEAR_TYPES), state='readonly')
        cb.pack(fill='x')
        cb.bind('<<ComboboxSelected>>', lambda e: self.on_type_change())
        self.desc_lbl = ttk.Label(f, style='Muted.TLabel', wraplength=280, justify='left')
        self.desc_lbl.pack(fill='x', pady=(6, 6))
        ttk.Label(f, text='Preset').pack(anchor='w')
        self.preset_var = tk.StringVar()
        self.preset_cb = ttk.Combobox(f, textvariable=self.preset_var, state='readonly')
        self.preset_cb.pack(fill='x')
        self.preset_cb.bind('<<ComboboxSelected>>', lambda e: self.apply_preset())

        f = ttk.LabelFrame(s, text='Result', padding=8)
        f.pack(fill='x', pady=4)
        self.ratio_lbl = ttk.Label(f, text='–', style='Ratio.TLabel')
        self.ratio_lbl.pack(anchor='w')
        self.ratio_sub = ttk.Label(f, style='Muted.TLabel', wraplength=280, justify='left')
        self.ratio_sub.pack(anchor='w', fill='x')
        self.warn_lbl = ttk.Label(f, style='Warn.TLabel', wraplength=280, justify='left')
        self.warn_lbl.pack(anchor='w', fill='x', pady=(6, 0))
        self.result_frame = f
        self._build_involute_frame(s)

        self.param_frame = ttk.LabelFrame(s, text='Geometry', padding=8)
        self.param_frame.pack(fill='x', pady=4)
        self.config_frame = ttk.LabelFrame(s, text='Configuration', padding=8)
        self.config_frame.pack(fill='x', pady=4)

        f = ttk.LabelFrame(s, text='Display', padding=8)
        f.pack(fill='x', pady=4)
        self.color_mode = tk.StringVar(value='member')
        row = ttk.Frame(f)
        row.pack(fill='x')
        ttk.Label(row, text='Colour by').pack(side='left')
        for val, txt in (('member', 'Member'), ('role', 'Role')):
            ttk.Radiobutton(row, text=txt, value=val, variable=self.color_mode,
                            command=self.restyle).pack(side='left', padx=4)
        self.fill_var = tk.BooleanVar(value=True)
        self.legend_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text='Filled shapes', variable=self.fill_var, command=self.restyle).pack(anchor='w')
        ttk.Checkbutton(f, text='Legend', variable=self.legend_var, command=self.restyle).pack(anchor='w')
        row = ttk.Frame(f)
        row.pack(fill='x', pady=(4, 0))
        ttk.Label(row, text='Theme').pack(side='left')
        for val, txt in (('system', 'System'), ('light', 'Light'), ('dark', 'Dark')):
            ttk.Radiobutton(row, text=txt, value=val, variable=self.theme_pref,
                            command=self.on_theme_change).pack(side='left', padx=4)


        # tabs
        self.nb = ttk.Notebook(main)
        self.nb.pack(fill='both', expand=True, padx=(4, 8), pady=8)
        self.nb.bind('<<NotebookTabChanged>>', lambda e: self.update_frame(sync_slider=False))
        self._build_anim_tab()
        self._build_3d_tab()
        self._build_kin_tab()
        self._build_sweep_tab()

        self.status = ttk.Label(self, text='', style='Muted.TLabel', anchor='w', padding=(10, 2))
        self.status.pack(fill='x', side='bottom')

    def _build_anim_tab(self):
        tab = ttk.Frame(self.nb)
        self.anim_tab = tab
        self.nb.add(tab, text='  Animation  ')
        self.fig = Figure(figsize=(8, 7), dpi=100)
        self.ax = self.fig.add_axes([0.02, 0.03, 0.70, 0.88])
        self.readout = self.fig.text(0.02, 0.965, '', fontsize=10, family='monospace', va='top')
        self.canvas = FigureCanvasTkAgg(self.fig, master=tab)
        self.canvas.get_tk_widget().pack(fill='both', expand=True)

        bar = ttk.Frame(tab, padding=(6, 6))
        bar.pack(fill='x')
        self.play_btn = ttk.Button(bar, text='❚❚ Pause', width=10, command=self.toggle_play, style='Accent.TButton')
        self.play_btn.pack(side='left')
        ttk.Button(bar, text='⟲ Reset', command=self.reset_phase).pack(side='left', padx=4)

        ttk.Label(bar, text='Speed').pack(side='left', padx=(12, 2))
        self.speed_var = tk.DoubleVar(value=np.log10(0.5))
        ttk.Scale(bar, from_=-2.5, to=1.0, variable=self.speed_var, length=130,
                  command=lambda e: self._speed_label()).pack(side='left')
        self.speed_lbl = ttk.Label(bar, width=13, style='Muted.TLabel')
        self.speed_lbl.pack(side='left')
        self._speed_label()

        ttk.Label(bar, text='Input position').pack(side='left', padx=(8, 2))
        self.pos_var = tk.DoubleVar(value=0)
        self.pos_scale = ttk.Scale(bar, from_=0, to=1, variable=self.pos_var, command=self.on_scrub)
        self.pos_scale.pack(side='left', fill='x', expand=True)
        self.pos_scale.bind('<ButtonPress-1>', lambda e: setattr(self, '_scrubbing', True))
        self.pos_scale.bind('<ButtonRelease-1>', lambda e: setattr(self, '_scrubbing', False))

        ttk.Button(bar, text='Copy code', command=self.copy_code).pack(side='right', padx=2)
        ttk.Button(bar, text='Save GIF', command=self.save_gif).pack(side='right', padx=2)
        ttk.Button(bar, text='Save PNG', command=self.save_png).pack(side='right', padx=2)

    def _build_3d_tab(self):
        self.view3d = Gear3DView(self.nb, on_status=self.set_status)
        self.nb.add(self.view3d, text='  3D view  ')

    def visible_view(self):
        current = self.nb.select()
        if current == str(self.anim_tab):
            return '2d'
        if current == str(self.view3d):
            return '3d'
        return None

    def _build_kin_tab(self):
        tab = ttk.Frame(self.nb, padding=8)
        self.nb.add(tab, text='  Kinematics  ')
        self.kfig = Figure(figsize=(8, 4.6), dpi=100)
        self.kcanvas = FigureCanvasTkAgg(self.kfig, master=tab)
        self.kcanvas.get_tk_widget().pack(fill='both', expand=True)
        cols = ('member', 'role', 'sym', 'out', 'in')
        self.tree = ttk.Treeview(tab, columns=cols, show='headings', height=7)
        for c, txt, w in zip(cols, ('Member', 'Role', 'ω / ω_out  (symbolic)', 'ω / ω_out', 'ω / ω_in'),
                             (150, 80, 360, 110, 110)):
            self.tree.heading(c, text=txt)
            self.tree.column(c, width=w, anchor='w' if c in ('member', 'role', 'sym') else 'e')
        self.tree.pack(fill='x', pady=(8, 0))

    def _build_sweep_tab(self):
        tab = ttk.Frame(self.nb, padding=8)
        self.nb.add(tab, text='  Ratio sweep  ')
        ctl = ttk.Frame(tab)
        ctl.pack(fill='x')
        self.sx_var, self.sy_var = tk.StringVar(), tk.StringVar()
        self.sx_lo, self.sx_hi = tk.StringVar(), tk.StringVar()
        self.sy_lo, self.sy_hi = tk.StringVar(), tk.StringVar()
        ttk.Label(ctl, text='X').pack(side='left')
        self.sx_cb = ttk.Combobox(ctl, textvariable=self.sx_var, state='readonly', width=6)
        self.sx_cb.pack(side='left', padx=2)
        ttk.Spinbox(ctl, textvariable=self.sx_lo, from_=1, to=500, width=5).pack(side='left')
        ttk.Label(ctl, text='to').pack(side='left', padx=2)
        ttk.Spinbox(ctl, textvariable=self.sx_hi, from_=1, to=500, width=5).pack(side='left')
        ttk.Label(ctl, text='    Y').pack(side='left')
        self.sy_cb = ttk.Combobox(ctl, textvariable=self.sy_var, state='readonly', width=6)
        self.sy_cb.pack(side='left', padx=2)
        ttk.Spinbox(ctl, textvariable=self.sy_lo, from_=1, to=500, width=5).pack(side='left')
        ttk.Label(ctl, text='to').pack(side='left', padx=2)
        ttk.Spinbox(ctl, textvariable=self.sy_hi, from_=1, to=500, width=5).pack(side='left')
        self.derive_var = tk.BooleanVar(value=True)
        self.derive_chk = ttk.Checkbutton(ctl, text='Keep rings meshing (R = S + 2P)', variable=self.derive_var)
        self.derive_chk.pack(side='left', padx=(12, 0))
        self.valid_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(ctl, text='Only geometrically valid', variable=self.valid_only).pack(side='left', padx=12)
        ttk.Button(ctl, text='Compute', style='Accent.TButton', command=self.compute_sweep).pack(side='left')
        ttk.Label(tab, text='Uses the symbolic ratio of the current configuration. Click a point or cell to load '
                            'those tooth counts.', style='Muted.TLabel').pack(anchor='w', pady=(4, 0))
        self.sfig = Figure(figsize=(8, 6), dpi=100)
        self.scanvas = FigureCanvasTkAgg(self.sfig, master=tab)
        self.scanvas.get_tk_widget().pack(fill='both', expand=True)
        self.scanvas.mpl_connect('button_press_event', self.on_sweep_click)

    # ---------------- parameter & config widgets ----------------

    def on_type_change(self):
        self.spec = GEAR_TYPES[self.type_var.get()]
        spec = self.spec
        self.desc_lbl.configure(text=spec.description)
        if spec.involute:
            self.inv_frame.pack(fill='x', pady=4, after=self.result_frame)
        else:
            self.inv_frame.pack_forget()
        self.preset_cb.configure(values=list(spec.presets) or ['(none)'])
        self.preset_var.set('')

        for w in self.param_frame.winfo_children():
            w.destroy()
        self.param_vars = {}
        self._suspend = True
        for i, p in enumerate(spec.params):
            ttk.Label(self.param_frame, text=p.label).grid(row=i, column=0, sticky='w', pady=2)
            if p.kind == 'bool':
                var = tk.BooleanVar(value=p.default)
                w = ttk.Checkbutton(self.param_frame, variable=var)
            elif p.kind == 'choice':
                var = tk.StringVar(value=p.default)
                w = ttk.Combobox(self.param_frame, textvariable=var, values=p.choices, state='readonly', width=9)
            else:
                var = tk.StringVar(value=str(p.default))
                w = ttk.Spinbox(self.param_frame, textvariable=var, from_=p.lo, to=p.hi,
                                increment=p.step or 1, width=9)
            w.grid(row=i, column=1, sticky='e', pady=2)
            var.trace_add('write', lambda *a: self.schedule_rebuild())
            self.param_vars[p.name] = var
        self.param_frame.columnconfigure(0, weight=1)

        for w in self.config_frame.winfo_children():
            w.destroy()
        dofs = sorted(spec.kin_cls.dofs())
        names = [f'{d} – {spec.dof_labels.get(d, d)}' for d in dofs]
        self.cfg_vars = []
        rows = ['Input', 'Output'] + ['Fixed / constraint'] * spec.n_constraints
        for i, (lab, val) in enumerate(zip(rows, spec.default_config)):
            ttk.Label(self.config_frame, text=lab).grid(row=i, column=0, sticky='w', pady=2)
            var = tk.StringVar(value=self._dof_display(val))
            cb = ttk.Combobox(self.config_frame, textvariable=var, values=names, width=17,
                              state='readonly' if i < 2 else 'normal')
            cb.grid(row=i, column=1, sticky='e', pady=2)
            cb.bind('<<ComboboxSelected>>', lambda e: self.schedule_rebuild(10))
            cb.bind('<Return>', lambda e: self.schedule_rebuild(10))
            cb.bind('<FocusOut>', lambda e: self.schedule_rebuild(10))
            self.cfg_vars.append(var)
        if spec.n_constraints:
            ttk.Label(self.config_frame, style='Muted.TLabel', wraplength=280, justify='left',
                      text='A member name means it is held fixed. You can also type a linear constraint, '
                           'e.g. "r1-r2" to fuse two members.').grid(row=len(rows), column=0, columnspan=2,
                                                                     sticky='w', pady=(4, 0))
        self.config_frame.columnconfigure(0, weight=1)

        ints = [p.name for p in spec.params if p.kind == 'int']
        self.sx_cb.configure(values=ints)
        self.sy_cb.configure(values=['(none)'] + ints)
        ax = spec.sweep_axes or tuple(ints[:2])
        self.sx_var.set(ax[0])
        self.sy_var.set(ax[1] if len(ax) > 1 else '(none)')
        self.derive_chk.configure(state='normal' if spec.derive else 'disabled')
        self._set_sweep_ranges()

        self._suspend = False
        self.input_angle = 0.0
        self.rebuild()

    def _dof_display(self, d):
        return f'{d} – {self.spec.dof_labels[d]}' if d in self.spec.dof_labels else d

    def _set_sweep_ranges(self):
        for name, lo, hi in ((self.sx_var.get(), self.sx_lo, self.sx_hi), (self.sy_var.get(), self.sy_lo, self.sy_hi)):
            p = next((p for p in self.spec.params if p.name == name), None)
            if p is None:
                continue
            v = p.default
            lo.set(str(max(p.lo, v - 10)))
            hi.set(str(min(p.hi, v + 10)))

    def apply_preset(self):
        pr = self.spec.presets.get(self.preset_var.get())
        if not pr:
            return
        values, cfg = pr
        self._suspend = True
        for p in self.spec.params:
            v = values.get(p.name, p.default)
            self.param_vars[p.name].set(v if p.kind == 'bool' else str(v))
        for var, val in zip(self.cfg_vars, cfg):
            var.set(self._dof_display(val))
        self._suspend = False
        self.input_angle = 0.0
        self.rebuild()

    def read_values(self):
        vals = {}
        for p in self.spec.params:
            raw = self.param_vars[p.name].get()
            if p.kind == 'int':
                v = int(float(raw))
                if not p.lo <= v <= p.hi:
                    raise ValueError(f'{p.name} must be between {p.lo} and {p.hi}')
            elif p.kind == 'float':
                v = float(raw)
                if not p.lo <= v <= p.hi:
                    raise ValueError(f'{p.name} must be between {p.lo} and {p.hi}')
            else:
                v = raw
            vals[p.name] = v
        return vals

    def read_config(self):
        cfg = []
        for var in self.cfg_vars:
            t = var.get().split('–')[0].strip()
            if not t:
                raise ValueError('Every configuration slot needs a value')
            cfg.append(t)
        if cfg[0] == cfg[1]:
            raise ValueError('Input and output must differ')
        return tuple(cfg)

    def get_kinematics(self, cfg):
        key = (self.spec.name, cfg)
        if key not in self.kin_cache:
            kin = self.spec.kin_cls(*cfg)
            _ = kin.solve
            self.kin_cache[key] = kin
        return self.kin_cache[key]

    # ---------------- rebuild ----------------

    def schedule_rebuild(self, delay=350):
        if self._suspend:
            return
        if self._pending:
            self.after_cancel(self._pending)
        self._pending = self.after(delay, self.rebuild)

    def rebuild(self):
        self._pending = None
        spec = self.spec
        try:
            vals = self.read_values()
            cfg = self.read_config()
        except ValueError as e:
            self.set_status(str(e), error=True)
            return
        self.config(cursor='watch')
        self.update_idletasks()
        try:
            try:
                kin = self.get_kinematics(cfg)
            except Exception:
                raise ValueError('This configuration does not determine a unique motion. '
                                 'Pick a different input/output/fixed combination.')
            gear = spec.build(kin, vals)
            try:
                ratios = gear.ratios_f
            except (TypeError, ZeroDivisionError):
                raise ValueError('Degenerate geometry: the ratio is infinite for these tooth counts.')
            if not np.isfinite(ratios[cfg[0]]) or ratios[cfg[0]] == 0:
                raise ValueError('The input member does not move in this configuration.')
            arranged = gear.arrange(0)
            comps = spec.components(vals, arranged)
        except Exception as e:
            self.config(cursor='')
            self.set_status(f'Could not build gear train: {e}', error=True)
            return
        self.config(cursor='')

        self.vals, self.cfg, self.kin, self.gear = vals, cfg, kin, gear
        self.ratio_in = ratios[cfg[0]]

        self.ax.cla()
        self.ax.set_aspect('equal')
        self.ax.axis('off')
        self.artists = []
        t0 = time.perf_counter()
        for i, comp in enumerate(comps):
            a = ComponentArtist(self.ax, comp, MEMBER_COLORS[i % len(MEMBER_COLORS)], self.fill_var.get(),
                                self.theme['fill_alpha'])
            if not a.empty:
                a.zorder_index = i
                self.artists.append(a)
        lim = max([a.extent for a in self.artists] + [1e-6]) * 1.04
        self.ax.set_xlim(-lim, lim)
        self.ax.set_ylim(-lim, lim)
        self.view3d.set_scene([(a.shape, a.comp.profiles, MEMBER_COLORS[0], a.comp.layer, a.comp.span, a.comp.ring)
                               for a in self.artists], lim)
        self.restyle(redraw=False)

        rmax = abs(self.ratio_in)
        self.pos_scale.configure(to=max(1.0, rmax))
        self.update_sidebar()
        self.update_kinematics_tab()
        self.update_frame()
        n_pts = sum(len(a.idx) for a in self.artists)
        self.set_status(f'{spec.name}: {len(self.artists)} members, {n_pts} profile vertices '
                        f'(prepared in {1000 * (time.perf_counter() - t0):.0f} ms). Space = play/pause.')

    def role_of(self, dof):
        cfg = self.cfg
        if dof == cfg[0]:
            return 'input'
        if dof == cfg[1]:
            return 'output'
        if abs(self.gear.ratios_f.get(dof, 1)) < 1e-12:
            return 'fixed'
        return 'free'

    def member_color(self, artist):
        if self.color_mode.get() == 'role':
            return ROLE_COLORS[self.role_of(artist.comp.dof)]
        return MEMBER_COLORS[artist.zorder_index % len(MEMBER_COLORS)]

    def restyle(self, redraw=True):
        if not self.artists:
            return
        for a in self.artists:
            a.set_style(self.member_color(a), self.fill_var.get(), self.theme['fill_alpha'])
        self.view3d.set_colors([self.member_color(a) for a in self.artists])
        leg = self.ax.get_legend()
        if leg:
            leg.remove()
        if self.legend_var.get():
            handles, seen = [], set()
            for a in self.artists:
                role = self.role_of(a.comp.dof)
                label = f'{a.comp.label}  ({role})'
                if label in seen:
                    continue
                seen.add(label)
                handles.append(Line2D([], [], color=self.member_color(a), lw=6, alpha=0.8, label=label))
            self.ax.legend(handles=handles, loc='upper left', bbox_to_anchor=(1.01, 1.0), frameon=False,
                           fontsize=9, title='Members', title_fontsize=10, alignment='left')
        if redraw:
            self.canvas.draw_idle()
            self.update_kinematics_tab()
            if self.visible_view() == '3d':
                self.view3d.redraw()

    def update_sidebar(self):
        g, kin, cfg = self.gear, self.kin, self.cfg
        r = self.ratio_in
        self.ratio_lbl.configure(text=f'{r:,.4g} : 1' if abs(r) >= 1 else f'1 : {1 / r:,.4g}')
        sym = sympy.sstr(kin.ratio)
        exact = sympy.sstr(g.ratio)
        lab = self.spec.dof_labels
        fixed = ', '.join(lab.get(c, c) for c in cfg[2:]) or 'none'
        self.ratio_sub.configure(text=f'{lab.get(cfg[0], cfg[0])} → {lab.get(cfg[1], cfg[1])}  (fixed: {fixed})\n'
                                      f'{cfg[0]}/{cfg[1]} = {sym} = {exact}'
                                      + ('\nNegative: output turns opposite to input.' if r < 0 else ''))
        warns = self.spec.checks(self.vals)
        self.warn_lbl.configure(text='\n'.join('⚠ ' + w for w in warns))
        self.update_involute()

    # ---------------- involute check ----------------

    INV_FIELDS = (('m', 'Module m [mm]', 0.5, 0.05, 20, 0.05),
                  ('alpha', 'Pressure angle α [°]', 20.0, 14.5, 30, 0.5),
                  ('xs', 'Profile shift x sun', 0.0, -1.0, 1.5, 0.05),
                  ('xp', 'Profile shift x planet', 0.0, -1.5, 1.5, 0.05),
                  ('xr', 'Profile shift x ring', 0.0, -1.5, 1.5, 0.05),
                  ('ring_tip', 'Ring tip Ø [mm] (0 = std)', 0.0, 0.0, 5000, 0.01))

    def _build_involute_frame(self, parent):
        f = ttk.LabelFrame(parent, text='Involute check (hob / skive)', padding=8)
        self.inv_frame = f
        self._inv_pending = None
        saved = self.settings.get('involute', {})
        self.inv_vars, self.inv_widgets = {}, {}
        for i, (k, lab, d, lo, hi, st) in enumerate(self.INV_FIELDS):
            ttk.Label(f, text=lab).grid(row=i, column=0, sticky='w', pady=2)
            var = tk.StringVar(value=str(saved.get(k, d)))
            w = ttk.Spinbox(f, textvariable=var, from_=lo, to=hi, increment=st, width=9)
            w.grid(row=i, column=1, sticky='e', pady=2)
            var.trace_add('write', lambda *a: self.schedule_involute())
            self.inv_vars[k], self.inv_widgets[k] = var, w
        n = len(self.INV_FIELDS)
        self.inv_zero_sum = tk.BooleanVar(value=saved.get('zero_sum', True))
        ttk.Checkbutton(f, text='Zero-sum shifts (x_p = −x_s, x_r = x_p)', variable=self.inv_zero_sum,
                        command=self.schedule_involute).grid(row=n, column=0, columnspan=2, sticky='w')
        self.inv_err = ttk.Label(f, style='Err.TLabel', wraplength=280, justify='left')
        self.inv_warn = ttk.Label(f, style='Warn.TLabel', wraplength=280, justify='left')
        self.inv_info = ttk.Label(f, style='Muted.TLabel', wraplength=280, justify='left')
        for i, w in enumerate((self.inv_err, self.inv_warn, self.inv_info)):
            w.grid(row=n + 1 + i, column=0, columnspan=2, sticky='w', pady=(4, 0))
        ttk.Label(f, style='Muted.TLabel', wraplength=280, justify='left',
                  text='Treats the tooth counts as involute gears, hobbed (sun, planets) and '
                       'skived (ring): undercut, ring tip / planet root interference, centre '
                       'distance, contact ratio, pointed tips. Independent of the epi/hypo '
                       'profiles drawn here.'
                  ).grid(row=n + 4, column=0, columnspan=2, sticky='w', pady=(6, 0))
        f.columnconfigure(0, weight=1)

    def schedule_involute(self, delay=300):
        if self._inv_pending:
            self.after_cancel(self._inv_pending)
        self._inv_pending = self.after(delay, self.update_involute)

    def update_involute(self):
        self._inv_pending = None
        spec = self.spec
        if not spec or not spec.involute or self.gear is None:
            return
        zs = self.inv_zero_sum.get()
        for k in ('xp', 'xr'):
            self.inv_widgets[k].configure(state='disabled' if zs else 'normal')
        try:
            v = {k: float(var.get()) for k, var in self.inv_vars.items()}
        except ValueError:
            self.inv_err.configure(text='⛔ Enter a number in every involute field.')
            self.inv_warn.configure(text='')
            self.inv_info.configure(text='')
            return
        if zs:
            v['xp'] = -v['xs']
            v['xr'] = v['xp']
            for k in ('xp', 'xr'):
                txt = f"{v[k]:g}"
                if self.inv_vars[k].get() != txt:
                    self.inv_vars[k].set(txt)
        S, P, R, N = spec.involute(self.vals)
        try:
            issues, info = check_planetary(S, P, R, N, v['m'], v['alpha'], v['xs'], v['xp'], v['xr'],
                                           v['ring_tip'])
        except Exception as e:
            issues, info = (('error', f'Check failed: {e}'),), ()
        self.inv_err.configure(text='\n'.join('⛔ ' + t for lvl, t in issues if lvl == 'error'))
        self.inv_warn.configure(text='\n'.join('⚠ ' + t for lvl, t in issues if lvl == 'warn'))
        ok = '' if issues else '✓ Works as involute gears (hob + skive).\n'
        self.inv_info.configure(text=ok + '\n'.join(info))
        for w in (self.inv_err, self.inv_warn):
            w.grid() if w.cget('text') else w.grid_remove()
        self.settings['involute'] = {**v, 'zero_sum': zs}
        save_settings(self.settings)

    # ---------------- animation ----------------

    def _speed(self):
        return 10 ** self.speed_var.get()

    def _speed_label(self):
        self.speed_lbl.configure(text=f'{self._speed():.3g} in-rev/s')

    def toggle_play(self):
        self.playing = not self.playing
        self.play_btn.configure(text='❚❚ Pause' if self.playing else '▶ Play')
        self.last_t = time.perf_counter()

    def reset_phase(self):
        self.input_angle = 0.0
        self.update_frame()

    def on_scrub(self, _=None):
        if self._scrubbing or not self.playing:
            self.input_angle = self.pos_var.get() * 2 * np.pi
            self.update_frame(sync_slider=False)

    def tick(self):
        now = time.perf_counter()
        dt = min(now - self.last_t, 0.2)
        self.last_t = now
        if self.playing and self.gear is not None and not self._scrubbing:
            self.input_angle += 2 * np.pi * self._speed() * dt
            if self.visible_view():
                self.update_frame()
        self.after(int(1000 / self.FPS), self.tick)

    def update_frame(self, sync_slider=True):
        if self.gear is None or not self.artists:
            return
        phase = self.input_angle / self.ratio_in
        try:
            comps = self.spec.components(self.vals, self.gear.arrange(phase))
        except Exception as e:
            self.set_status(f'Animation error: {e}', error=True)
            self.playing = False
            return
        profiles = [comps[a.zorder_index].profiles for a in self.artists]
        for a, prof in zip(self.artists, profiles):
            a.update(prof)
        self.view3d.update_profiles(profiles)
        in_rev = self.input_angle / (2 * np.pi)
        out_rev = phase / (2 * np.pi)
        lab = self.spec.dof_labels
        self.readout.set_text(f'{lab.get(self.cfg[0], self.cfg[0]):>14}: {in_rev:9.3f} rev\n'
                              f'{lab.get(self.cfg[1], self.cfg[1]):>14}: {out_rev:9.4f} rev')
        if sync_slider:
            span = max(1.0, abs(self.ratio_in))
            self.pos_var.set(in_rev % span)
        view = self.visible_view()
        if view == '2d':
            self.canvas.draw_idle()
        elif view == '3d':
            self.view3d.redraw()

    # ---------------- kinematics tab ----------------

    def update_kinematics_tab(self):
        if self.gear is None:
            return
        g, kin, cfg = self.gear, self.kin, self.cfg
        lab = self.spec.dof_labels
        self.kfig.clf()
        gs = self.kfig.add_gridspec(2, 1, height_ratios=[1, 3.2], hspace=0.35, left=0.2, right=0.95, top=0.95, bottom=0.1)
        tax = self.kfig.add_subplot(gs[0])
        tax.axis('off')
        sym = sympy.latex(kin.ratio)
        exact = sympy.latex(g.ratio)
        txt = rf'$\frac{{\omega_{{{cfg[0]}}}}}{{\omega_{{{cfg[1]}}}}} = {sym} = {exact}$'
        if not g.ratio.is_Integer:
            txt += f'   ≈ {self.ratio_in:.6g}'
        try:
            MathTextParser('path').parse(f"${txt.split('$')[1]}$")
        except Exception:
            txt = f'{cfg[0]}/{cfg[1]} = {kin.ratio} = {g.ratio}'
        tax.text(0.0, 0.5, txt, fontsize=17, va='center', transform=tax.transAxes)
        tax.set_title('Gear ratio (input / output)', loc='left', fontsize=11, color=self.theme['muted'])

        bax = self.kfig.add_subplot(gs[1])
        dofs = sorted(g.ratios_f, key=lambda d: (d != cfg[0], d != cfg[1], d))
        speeds = [g.ratios_f[d] / self.ratio_in for d in dofs]
        colors = [ROLE_COLORS[self.role_of(d)] for d in dofs]
        y = np.arange(len(dofs))[::-1]
        bax.barh(y, speeds, color=colors, alpha=0.85, height=0.6)
        bax.set_yticks(y, [f'{lab.get(d, d)}  [{d}]' for d in dofs])
        bax.axvline(0, color=self.theme['axis'], lw=0.8)
        nz = [abs(s) for s in speeds if abs(s) > 1e-12]
        if nz and max(nz) / min(nz) > 50:
            bax.set_xscale('symlog', linthresh=min(nz))
        for yi, s in zip(y, speeds):
            bax.annotate(f'{s:+.4g}', (s, yi), xytext=(4 if s >= 0 else -4, 0), textcoords='offset points',
                         ha='left' if s >= 0 else 'right', va='center', fontsize=9, color=self.theme['fg'], clip_on=False)
        lo, hi = min(speeds + [0]), max(speeds + [0])
        pad = (hi - lo) * 0.18 or 1
        if bax.get_xscale() == 'linear':
            bax.set_xlim(lo - pad, hi + pad)
        bax.set_xlabel('Revolutions per input revolution (fixed-frame)')
        bax.set_title('Member speeds', loc='left', fontsize=11, color=self.theme['muted'])
        bax.legend(handles=[Line2D([], [], color=c, lw=8, label=r) for r, c in ROLE_COLORS.items()],
                   loc='lower right', bbox_to_anchor=(1.0, 1.0), fontsize=8, frameon=False, ncol=4)
        for sp in ('top', 'right'):
            bax.spines[sp].set_visible(False)
        self.kcanvas.draw_idle()

        self.tree.delete(*self.tree.get_children())
        for d in dofs:
            expr = sympy.sstr(sympy.simplify(kin.solve[d]))
            self.tree.insert('', 'end', values=(f'{lab.get(d, d)}  [{d}]', self.role_of(d), expr,
                                                f'{g.ratios_f[d]:.6g}', f'{g.ratios_f[d] / self.ratio_in:.6g}'))

    # ---------------- sweep tab ----------------

    def sweep_values(self, xn, xv, yn=None, yv=None):
        v = dict(self.vals)
        v[xn] = int(xv)
        if yn:
            v[yn] = int(yv)
        if self.spec.derive and self.derive_var.get():
            v = self.spec.derive(v)
        return v

    def compute_sweep(self):
        if self.kin is None:
            return
        spec, kin = self.spec, self.kin
        try:
            xs = np.arange(int(self.sx_lo.get()), int(self.sx_hi.get()) + 1)
            two_d = self.sy_var.get() not in ('', '(none)') and self.sy_var.get() != self.sx_var.get()
            ys = np.arange(int(self.sy_lo.get()), int(self.sy_hi.get()) + 1) if two_d else np.array([0])
        except ValueError:
            self.set_status('Sweep ranges must be integers', error=True)
            return
        if len(xs) < 1 or len(ys) < 1 or len(xs) * len(ys) > 40000:
            self.set_status('Sweep range empty or too large (max 40 000 points)', error=True)
            return
        names = sorted(str(s) for s in kin.ratio.free_symbols)
        f = sympy.lambdify([sympy.Symbol(n) for n in names], kin.ratio, 'math')
        xn, yn = self.sx_var.get(), self.sy_var.get()
        Z = np.full((len(ys), len(xs)), np.nan)
        valid = np.ones_like(Z, dtype=bool)
        for j, yv in enumerate(ys):
            for i, xv in enumerate(xs):
                v = self.sweep_values(xn, xv, yn if two_d else None, yv)
                geo = spec.geom(v)
                try:
                    Z[j, i] = float(f(*[geo[n] for n in names]))
                except (ZeroDivisionError, OverflowError, ValueError):
                    pass
                valid[j, i] = not spec.checks(v)
        if self.valid_only.get():
            Z[~valid] = np.nan

        self.sfig.clf()
        ax = self.sfig.add_subplot(111)
        cur = (self.vals[xn], self.vals[yn] if two_d else None)
        if not two_d:
            z = Z[0]
            ax.plot(xs, z, color='#9CA3AF', lw=1, zorder=1)
            ax.scatter(xs[valid[0]], z[valid[0]], color=self.theme['accent'], s=28, zorder=2, label='valid geometry')
            ax.scatter(xs[~valid[0]], z[~valid[0]], facecolor=self.theme['fig'], edgecolor='#9CA3AF', s=28, zorder=2,
                       label='mesh constraint violated')
            if xs[0] <= cur[0] <= xs[-1]:
                ax.scatter([cur[0]], [self.ratio_in], color='#D55E00', s=90, marker='*', zorder=3, label='current')
            fin = np.abs(z[np.isfinite(z) & (z != 0)])
            if len(fin) and fin.max() / fin.min() > 100:
                ax.set_yscale('symlog', linthresh=max(1.0, fin.min()))
            ax.set_xlabel(xn)
            ax.set_ylabel(f'ratio  {self.cfg[0]}/{self.cfg[1]}')
            ax.grid(alpha=0.3)
            ax.legend(frameon=False, fontsize=9)
            for sp in ('top', 'right'):
                ax.spines[sp].set_visible(False)
        else:
            A = np.log10(np.abs(Z))
            A[~np.isfinite(A)] = np.nan
            ext = [xs[0] - 0.5, xs[-1] + 0.5, ys[0] - 0.5, ys[-1] + 0.5]
            im = ax.imshow(A, origin='lower', extent=ext, cmap='viridis', aspect='auto', interpolation='nearest')
            cb = self.sfig.colorbar(im, ax=ax)
            cb.set_label('log10 |ratio|')
            if not self.valid_only.get() and (~valid).any():
                shade = np.zeros(Z.shape + (4,))
                shade[~valid] = (*matplotlib.colors.to_rgb(self.theme['fig']), 0.7)
                ax.imshow(shade, origin='lower', extent=ext, aspect='auto', interpolation='nearest')
            if Z.size <= 150:
                for j, yv in enumerate(ys):
                    for i, xv in enumerate(xs):
                        if np.isfinite(Z[j, i]):
                            ax.text(xv, yv, f'{Z[j, i]:.3g}', ha='center', va='center', fontsize=7,
                                    color='white' if (A[j, i] < np.nanmean(A)) else 'black')
            if xs[0] <= cur[0] <= xs[-1] and ys[0] <= cur[1] <= ys[-1]:
                ax.add_patch(Rectangle((cur[0] - 0.5, cur[1] - 0.5), 1, 1, fill=False, ec='#D55E00', lw=2.5))
            ax.set_xlabel(xn)
            ax.set_ylabel(yn)
            ax.set_title('Faded cells violate a mesh constraint' if (~valid).any() and not self.valid_only.get()
                         else '', fontsize=9, color=self.theme['muted'], loc='left')
        self.sfig.suptitle(f'{spec.name}: ratio {self.cfg[0]}/{self.cfg[1]} = {sympy.sstr(kin.ratio)}',
                           fontsize=11, x=0.02, ha='left')
        ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
        if two_d:
            ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
        self.sweep_meta = (ax, xn, yn if two_d else None)
        self.scanvas.draw_idle()

    def on_sweep_click(self, ev):
        if not self.sweep_meta or ev.inaxes is not self.sweep_meta[0] or ev.xdata is None:
            return
        ax, xn, yn = self.sweep_meta
        self._suspend = True
        v = self.sweep_values(xn, round(ev.xdata), yn, round(ev.ydata) if yn else None)
        for k, val in v.items():
            if val != self.vals.get(k):
                self.param_vars[k].set(str(val))
        self._suspend = False
        self.rebuild()
        self.compute_sweep()

    # ---------------- export ----------------

    def save_png(self):
        fn = filedialog.asksaveasfilename(defaultextension='.png', filetypes=[('PNG image', '*.png')],
                                          initialfile=f'{self.spec.name.replace(" ", "_").lower()}.png')
        if fn:
            self.fig.savefig(fn, dpi=150, facecolor=self.fig.get_facecolor())
            self.set_status(f'Saved {fn}')

    def save_gif(self):
        if self.gear is None:
            return
        frames = simpledialog.askinteger('Save GIF', 'Number of frames (30 fps, at the current speed):',
                                         initialvalue=90, minvalue=10, maxvalue=600, parent=self)
        if not frames:
            return
        fn = filedialog.asksaveasfilename(defaultextension='.gif', filetypes=[('GIF animation', '*.gif')],
                                          initialfile=f'{self.spec.name.replace(" ", "_").lower()}.gif')
        if not fn:
            return
        from PIL import Image
        was_playing = self.playing
        self.playing = False
        start = self.input_angle
        imgs = []
        step = 2 * np.pi * self._speed() / 30
        for k in range(frames):
            self.input_angle = start + k * step
            self.update_frame(sync_slider=False)
            self.canvas.draw()
            buf = np.asarray(self.canvas.buffer_rgba())
            imgs.append(Image.fromarray(buf[..., :3]).convert('P', palette=Image.ADAPTIVE, colors=64))
            self.set_status(f'Rendering GIF frame {k + 1}/{frames}…')
            self.update_idletasks()
        imgs[0].save(fn, save_all=True, append_images=imgs[1:], duration=33, loop=0, optimize=True)
        self.input_angle = start
        self.playing = was_playing
        self.set_status(f'Saved {fn}')

    def copy_code(self):
        if self.gear is None:
            return
        code = self.spec.code(self.vals, self.cfg)
        self.clipboard_clear()
        self.clipboard_append(code)
        self.set_status('Copied an equivalent pygeartrain script to the clipboard.')

    def set_status(self, msg, error=False):
        self.status.configure(text=msg, foreground=self.theme['err'] if error else self.theme['muted'])


if __name__ == '__main__':
    GearStudio().mainloop()
