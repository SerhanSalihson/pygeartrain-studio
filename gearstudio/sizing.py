"""Physical sizing: which standard module (hob) suits a design, or which pin size for cycloids.

pygeartrain draws cycloidal tooth profiles. A hob cuts involute teeth, so this module sizes the
involute-equivalent gear on the same pitch circle (same tooth count, module and centre distance).
Formulas follow ISO 21771 / DIN 3960 for standard spur gears (addendum m, dedendum 1.25 m).
"""
import math
from dataclasses import dataclass, field

from gearstudio.involute.geometry import inv, undercut_shift

ISO_I = [0.1, 0.12, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
ISO_II = [0.11, 0.14, 0.18, 0.22, 0.28, 0.35, 0.45, 0.55, 0.7, 0.75, 0.9, 1.125, 1.375, 1.75, 2.25, 2.75,
          3.5, 4.5, 5.5, 7.0, 9.0]
SERIES = {
    'Common hob stock': [0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0],
    'ISO 54 series I': ISO_I,
    'ISO 54 series I + II': sorted(ISO_I + ISO_II),
}
DOWEL_PINS = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 20.0, 25.0]   # ISO 2338
PRESSURE_ANGLES = [20.0, 14.5, 25.0]
CAVEAT = ('pygeartrain draws cycloidal teeth. Hob sizes here are for the involute equivalent on the same '
          'pitch circle (same tooth count, module and centre distance); a hob cuts involute teeth.')



def inv_inverse(y):
    """Angle whose involute function is y (Newton iteration)."""
    a = (3 * y) ** (1 / 3) if y > 0 else 0.0
    for _ in range(50):
        f = inv(a) - y
        a -= f / math.tan(a) ** 2 if a > 0 else 0
        if abs(f) < 1e-15:
            break
    return a


def z_min(alpha_deg):
    """Fewest teeth a rack-type cutter (hob) produces without undercut, no profile shift."""
    return 2 / math.sin(math.radians(alpha_deg)) ** 2


def min_shift(z, alpha_deg):
    """Profile shift coefficient that avoids undercut for z teeth (0 if none is needed)."""
    return undercut_shift(z, math.radians(alpha_deg))


@dataclass
class GearDims:
    name: str
    z: int
    internal: bool
    m: float
    d: float      # pitch diameter
    da: float     # tip diameter
    df: float     # root diameter


def gear_dims(name, z, m, internal, x=0.0):
    d = m * z
    if internal:
        return GearDims(name, z, True, m, d, d - 2 * m * (1 - x), d + 2 * m * (1.25 + x))
    return GearDims(name, z, False, m, d, d + 2 * m * (1 + x), d - 2 * m * (1.25 - x))


def shift_for_centre(z1, z2, m, alpha_deg, a, internal=False):
    """Profile shift needed for gears z1, z2 (module m) to run at centre distance a.

    External pair: returns x1 + x2. Internal pair (z1 inside ring z2): returns x2 - x1.
    None if the distance is out of reach."""
    alpha = math.radians(alpha_deg)
    zs = (z2 - z1) if internal else (z1 + z2)
    if zs <= 0 or a <= 0:
        return None
    c = (m * zs / 2) / a * math.cos(alpha)
    if not -1 < c < 1:
        return None
    aw = math.acos(c)
    return (inv(aw) - inv(alpha)) * zs / (2 * math.tan(alpha))


def nearest(values, x):
    return min(values, key=lambda v: abs(v - x))


@dataclass
class Row:
    module: float
    dp: float
    stage_modules: list
    gears: list
    centre: float
    envelope: float
    fits: bool
    shift: float = None          # profile shift sum needed (centre-distance goal)
    notes: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)


@dataclass
class HobResult:
    rows: list
    recommended: int             # index into rows, or -1
    exact_module: float          # module that meets the goal exactly (None for a fixed module)
    notes: list
    gear_notes: list


def hob_table(scene, alpha_deg=20.0, goal='od', value=60.0, series='Common hob stock'):
    """Rows of standard modules with dimensions and whether each meets the sizing goal.

    goal: 'od' - envelope diameter must not exceed value (mm); recommend the largest module.
          'centre' - first mesh must run at centre distance value (mm); recommend least shift.
          'module' - use module value."""
    spec, v = scene.spec, scene.values
    sz = spec.sizing
    gears = sz.gears(v)
    factors = sz.stage_factors(v)
    k = sz.unit_k(v)
    meshes = sz.meshes(v)
    by_name = {g.name: g for g in gears}
    first = meshes[0] if meshes else None
    standard = set(SERIES['ISO 54 series I + II'] + SERIES['Common hob stock'])

    def centre_of(m):
        if first is None:
            return 0.0
        ga, gb = by_name[first.a], by_name[first.b]
        mm = m * factors[ga.stage]
        return mm * ((gb.z - ga.z) if gb.internal else (ga.z + gb.z)) / 2

    modules = list(SERIES[series])
    if goal == 'module' and all(abs(m - value) > 1e-9 for m in modules):
        modules = sorted(modules + [value])
    rows = []
    for m in modules:
        dims = [gear_dims(g.name, g.z, m * factors[g.stage], g.internal) for g in gears]
        unit_mm = m * k
        row = Row(m, 25.4 / m, [m * f for f in factors], dims, centre_of(m), 2 * scene.extent * unit_mm, True)
        if goal == 'od':
            row.fits = row.envelope <= value + 1e-9
        elif goal == 'centre' and first is not None:
            ga, gb = by_name[first.a], by_name[first.b]
            row.shift = shift_for_centre(ga.z, gb.z, m * factors[ga.stage], alpha_deg, value, gb.internal)
            row.fits = row.shift is not None and -0.5 <= row.shift <= 1.0
        elif goal == 'module':
            row.fits = abs(m - value) < 1e-9
        # a second stage tied to the same carrier usually lands on a non-standard module
        for si, f in enumerate(factors[1:], start=1):
            m2 = m * f
            if all(abs(m2 - s) > 1e-6 for s in standard):
                std = nearest(sorted(standard), m2)
                row.notes.append(_stage_note(si + 1, m2, std, gears, si, alpha_deg, centre_of(m), by_name, meshes))
        if sz.pin_stage:
            ref_r, pin_r, ecc = sz.pin_stage(v)
            row.extra = {'Pin circle Ø': 2 * ref_r * unit_mm, 'Pin Ø': 2 * pin_r * unit_mm,
                         'Eccentricity': ecc * unit_mm}
        rows.append(row)

    fitting = [i for i, r in enumerate(rows) if r.fits]
    if not fitting:
        rec = -1
    elif goal == 'centre':
        rec = min(fitting, key=lambda i: (abs(rows[i].shift), -rows[i].module))
    else:
        rec = max(fitting, key=lambda i: rows[i].module)

    exact = None
    if goal == 'od' and scene.extent > 0:
        exact = value / (2 * scene.extent * k)
    elif goal == 'centre' and first is not None:
        ga, gb = by_name[first.a], by_name[first.b]
        zs = (gb.z - ga.z) if gb.internal else (ga.z + gb.z)
        exact = 2 * value / zs / factors[ga.stage]

    gear_notes = []
    for g in gears:
        if g.internal:
            gear_notes.append(f'{g.name} (z = {g.z}) is an internal gear: it cannot be hobbed. Cut it with a '
                              'gear shaper (pinion cutter), broach it, or use wire EDM.')
        elif g.z < z_min(alpha_deg):
            x = min_shift(g.z, alpha_deg)
            alt = [a for a in PRESSURE_ANGLES if a > alpha_deg and g.z >= z_min(a)]
            tip = f' or a {alt[0]:g}° pressure angle (z_min {z_min(alt[0]):.1f})' if alt else ''
            gear_notes.append(f'{g.name} (z = {g.z}) is below z_min = {z_min(alpha_deg):.1f} for {alpha_deg:g}°: '
                              f'a standard hob undercuts it. Use a profile shift x ≥ {x:.2f}{tip}.')
    return HobResult(rows, rec, exact, [CAVEAT], gear_notes)


def _stage_note(stage_no, m2, std, gears, stage, alpha_deg, centre, by_name, meshes):
    ext = next((ms for ms in meshes if by_name[ms.a].stage == stage and not by_name[ms.b].internal), None)
    text = (f'Stage {stage_no} shares the carrier, so it needs m = {m2:.4g}, which is not a standard module. '
            f'With a standard m{std:g} hob')
    if ext:
        ga, gb = by_name[ext.a], by_name[ext.b]
        x = shift_for_centre(ga.z, gb.z, std, alpha_deg, centre)
        text += (f', profile-shift the {ga.name.lower()} and {gb.name.lower()} by x₁ + x₂ = {x:+.2f} '
                 f'to keep the {centre:.2f} mm centre distance.' if x is not None else
                 ', the centre distance cannot be matched by profile shift.')
    else:
        text += '.'
    return text


@dataclass
class PinResult:
    unit_mm: float
    ref_d: float
    pin_d: float
    ecc: float
    envelope: float
    dowel: float
    exact_ref_for_dowels: list    # (dowel Ø, pin-circle Ø that makes the pin exactly that dowel)
    notes: list


def pin_sizing(scene, ref_d_mm):
    sz, v = scene.spec.sizing, scene.values
    ref_r = sz.ref_radius(v)
    unit = ref_d_mm / (2 * ref_r)
    pin_r = sz.pin_radius(v) if sz.pin_radius else None
    pin_d = 2 * pin_r * unit if pin_r else None
    ecc = sz.eccentricity(v) * unit if sz.eccentricity else None
    dowel = nearest(DOWEL_PINS, pin_d) if pin_d else None
    exact = []
    if pin_r:
        i = DOWEL_PINS.index(dowel)
        for dw in DOWEL_PINS[max(0, i - 1):i + 2]:
            exact.append((dw, dw / (2 * pin_r) * 2 * ref_r))
    notes = ['Cycloidal and gerotor profiles are not hobbed: cut the discs or rotors on a CNC mill, by wire '
             'EDM or laser, or 3D-print them.']
    if pin_r:
        notes.append('Use ISO 2338 hardened dowel pins for the pin ring; rollers or sleeves on the pins cut '
                     'friction a lot.')
    return PinResult(unit, ref_d_mm, pin_d, ecc, 2 * scene.extent * unit, dowel, exact, notes)


def unit_mm_for(scene, module=None, ref_d=None):
    """mm per pygeartrain unit for the chosen module (involute types) or reference Ø (pin types)."""
    sz = scene.spec.sizing
    if sz.kind == 'involute':
        return (module or 1.0) * sz.unit_k(scene.values)
    return (ref_d or 50.0) / (2 * sz.ref_radius(scene.values))


def involute_sets(scene, module, alpha_deg=20.0, backlash=0.06, sun_steel=True):
    """The design's planetary stage(s) as involute gear sets: [(label, GearSet)], [] for other types.

    Uses gearstudio.involute (zero-sum profile shift, tip topping, phasing, contact ratio and clearance
    checks); a compound's second stage runs at the module its shared carrier forces."""
    from gearstudio.involute import GearRules, design_gearset
    v = scene.values
    rules = GearRules(alpha_deg=alpha_deg, backlash_each=backlash)
    if scene.spec.name == 'Planetary':
        stages = [('', v['S'], v['P'], v['R'], module)]
    elif scene.spec.name == 'Compound planetary':
        m2 = module * (v['S1'] + v['P1']) / (v['S2'] + v['P2'])
        stages = [('Stage 1', v['S1'], v['P1'], v['R1'], module), ('Stage 2', v['S2'], v['P2'], v['R2'], m2)]
    else:
        return []
    return [(label, design_gearset(m, zs, zp, zr, v['N'], rules, sun_steel=sun_steel, planet_bore_r=None))
            for label, zs, zp, zr, m in stages]
