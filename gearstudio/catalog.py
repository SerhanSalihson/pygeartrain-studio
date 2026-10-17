"""Catalogue of gear trains: parameters, kinematics, geometry builders, checks and sizing data."""
from collections import namedtuple
from dataclasses import dataclass, field
from typing import Callable

import gearstudio  # noqa: F401  (puts the vendored pygeartrain on sys.path)
from pygeartrain import planetary, compound_planetary, cycloid, compound_cycloid, nabtesco, simple

Param = namedtuple('Param', 'name label kind default lo hi step choices', defaults=(None, None, None, None))
# layer/span place the member in the 3D view: which plate it sits in and how many plates it spans
Comp = namedtuple('Comp', 'label dof profiles ring layer span', defaults=(0, 1))
# a problem with the current values, optionally with a one-click fix (dict of new values)
Issue = namedtuple('Issue', 'message fix fix_label', defaults=(None, None))

# involute-equivalent gear for sizing: name, teeth, internal?, stage (module factor index), dof, member label
SizingGear = namedtuple('SizingGear', 'name z internal stage dof member')
# a gear mesh: two gear names and the dof of the carrier their axes ride on (None = fixed axes)
Mesh = namedtuple('Mesh', 'a b carrier')


@dataclass
class Sizing:
    """How to put a design on a physical scale.

    kind 'involute': unit_k(v) is mm per pygeartrain unit for module 1 (mm/unit = m * unit_k).
    kind 'pins': ref_radius(v) is the reference pin-circle radius in pygeartrain units; the user
    gives its diameter in mm.
    """
    kind: str
    unit_k: Callable = None
    gears: Callable = lambda v: []
    meshes: Callable = lambda v: []
    stage_factors: Callable = lambda v: [1.0]
    ref_radius: Callable = None
    ref_label: str = 'Pin circle Ø'
    pin_radius: Callable = None        # pin radius in units (None: no pins)
    eccentricity: Callable = None      # eccentricity in units
    pin_stage: Callable = None         # nabtesco: (ref radius, pin radius, eccentricity) of its cycloid stage


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
    sizing: Sizing
    issues: Callable = lambda v: []
    presets: dict = field(default_factory=dict)
    sweep_axes: tuple = ()      # default (x, y) parameters for the ratio sweep
    derive: Callable = None     # values -> values with dependent tooth counts filled in

    @property
    def n_constraints(self):
        return len(self.kin_cls.dofs()) - len(self.kin_cls.equations) - 1

    def defaults(self):
        return {p.name: p.default for p in self.params}

    def param(self, name):
        return next(p for p in self.params if p.name == name)

    def checks(self, v):
        return [i.message for i in self.issues(v)]


def cfg_args(cfg):
    return ', '.join(repr(c) for c in cfg)


def planetary_issues(R, P, S, N, tag='', keys=('R', 'P', 'S'), others=()):
    """Mesh and spacing problems of one planetary stage (clearance is checked on the real
    geometry in model.py). `others` holds (R, S, P) of stages sharing the same planet count,
    so suggested N values work for every stage."""
    out = []
    kR = keys[0]
    if R != S + 2 * P:
        out.append(Issue(f'{tag}Ring should have S + 2P = {S + 2 * P} teeth for the planets to mesh '
                         f'with both sun and ring (now {R}).', {kR: S + 2 * P}, f'Set {kR} = {S + 2 * P}'))
    stages = [(R, S, P)] + list(others)
    ok = lambda n: all((r + s) % n == 0 for r, s, p in stages)
    if N and not ok(N):
        problem = f'{tag}(R + S) = {R + S} is not divisible by N = {N}: planets cannot be spaced evenly.'
        cands = [n for n in range(1, 25) if ok(n)]
        if cands:
            best = min(cands, key=lambda n: (abs(n - N), -n))
            out.append(Issue(problem, {'N': best}, f'Use N = {best}'))
        else:
            out.append(Issue(problem))
    return out


# ----------------------------------------------------------------------------

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
    sizing=Sizing(
        'involute',
        unit_k=lambda v: (v['S'] + v['P']) / 2,
        gears=lambda v: [SizingGear('Sun', v['S'], False, 0, 's', 'Sun'),
                         SizingGear('Planet', v['P'], False, 0, 'p', 'Planets'),
                         SizingGear('Ring', v['R'], True, 0, 'r', 'Ring')],
        meshes=lambda v: [Mesh('Sun', 'Planet', 'c'), Mesh('Planet', 'Ring', 'c')],
    ),
    issues=lambda v: planetary_issues(v['R'], v['P'], v['S'], v['N']),
    sweep_axes=('P', 'S'),
    derive=lambda v: {**v, 'R': v['S'] + 2 * v['P']},
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


def _cp_issues(v):
    s1 = (v['R1'], v['S1'], v['P1'])
    s2 = (v['R2'], v['S2'], v['P2'])
    out = planetary_issues(v['R1'], v['P1'], v['S1'], v['N'], 'Stage 1: ', ('R1', 'P1', 'S1'), [s2])
    out += planetary_issues(v['R2'], v['P2'], v['S2'], v['N'], 'Stage 2: ', ('R2', 'P2', 'S2'), [s1])
    # the same N problem is reported once per stage; keep the first
    seen, uniq = set(), []
    for i in out:
        key = i.fix_label if i.fix and 'N' in i.fix else i.message
        if key not in seen:
            seen.add(key)
            uniq.append(i)
    return uniq


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
    sizing=Sizing(
        'involute',
        unit_k=lambda v: (v['S1'] + v['P1']) / 2,
        # both stages share the carrier, so stage 2 runs at m2 = m1 (S1 + P1) / (S2 + P2)
        stage_factors=lambda v: [1.0, (v['S1'] + v['P1']) / (v['S2'] + v['P2'])],
        gears=lambda v: [SizingGear('Sun 1', v['S1'], False, 0, 's1', 'Sun 1'),
                         SizingGear('Planet 1', v['P1'], False, 0, 'p', 'Planets (stage 1)'),
                         SizingGear('Ring 1', v['R1'], True, 0, 'r1', 'Ring 1'),
                         SizingGear('Sun 2', v['S2'], False, 1, 's2', 'Sun 2'),
                         SizingGear('Planet 2', v['P2'], False, 1, 'p', 'Planets (stage 2)'),
                         SizingGear('Ring 2', v['R2'], True, 1, 'r2', 'Ring 2')],
        meshes=lambda v: [Mesh('Sun 1', 'Planet 1', 'c'), Mesh('Planet 1', 'Ring 1', 'c'),
                          Mesh('Sun 2', 'Planet 2', 'c'), Mesh('Planet 2', 'Ring 2', 'c')],
    ),
    issues=_cp_issues,
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
    sizing=Sizing('pins', ref_radius=lambda v: v['P'] + 1, ref_label='Pin circle Ø',
                  pin_radius=lambda v: v['b'], eccentricity=lambda v: v['f']),
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
    sizing=Sizing('pins', ref_radius=lambda v: v['P1'] + 1, ref_label='Ring 1 pin circle Ø',
                  pin_radius=lambda v: v['b'], eccentricity=lambda v: v['f']),
    issues=lambda v: ([Issue('P1 = P2: the two stages cancel and the ratio is undefined.',
                             {'P2': max(2, v['P1'] - 1)}, f"Set P2 = {max(2, v['P1'] - 1)}")]
                      if v['P1'] == v['P2'] else []),
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
    sizing=Sizing(
        'involute',
        unit_k=lambda v: (v['S'] + v['W']) / 2,
        gears=lambda v: [SizingGear('Input sun', v['S'], False, 0, 's', 'Input sun'),
                         SizingGear('Crank gear', v['W'], False, 0, 'w', 'Crank gears')],
        meshes=lambda v: [Mesh('Input sun', 'Crank gear', 'o')],
        # the cycloid stage is drawn at scale 1.9 / L: pins of radius b sit on a circle of radius L + 1
        pin_stage=lambda v: ((v['L'] + 1) * 1.9 / v['L'], v['b'] * 1.9 / v['L'], v['f'] * 1.9 / v['L']),
    ),
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
    sizing=Sizing(
        'involute',
        unit_k=lambda v: 0.5,           # gear A is drawn with pitch radius A units
        gears=lambda v: [SizingGear('Gear A', v['A'], False, 0, 'a', 'Gear A'),
                         SizingGear('Gear B', v['B'], False, 0, 'b', 'Gear B')],
        meshes=lambda v: [Mesh('Gear A', 'Gear B', None)],
    ),
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
    sizing=Sizing('pins', ref_radius=lambda v: v['N'] + 1, ref_label='Outer rotor pitch Ø',
                  eccentricity=lambda v: 1.0),
)


GEAR_TYPES = {t.name: t for t in
              [PLANETARY, COMPOUND_PLANETARY, CYCLOID, COMPOUND_CYCLOID, NABTESCO, SIMPLE, NESTED]}
