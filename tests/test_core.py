import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gearstudio import io as gio  # noqa: E402
from gearstudio.calc import calculate  # noqa: E402
from gearstudio.catalog import GEAR_TYPES  # noqa: E402
from gearstudio.meshing import extrude, is_closed  # noqa: E402
from gearstudio.model import BuildError, Scene  # noqa: E402
from gearstudio.sizing import (gear_dims, hob_table, min_shift, pin_sizing, shift_for_centre,  # noqa: E402
                               unit_mm_for, z_min)

# input/output ratios of every preset, as computed by pygeartrain (and shown by v1.x)
EXPECTED = {
    ('Planetary', 'Classic 14/4/6, 5 planets'): 10 / 3,
    ('Planetary', '11/2/7, 6 planets'): 18 / 7,
    ('Planetary', 'Carrier in, ring out, sun fixed'): 0.7,
    ('Planetary', 'Star (carrier fixed)'): -2.5,
    ('Compound planetary', 'README 22/7/8 + 21/6/9'): 36.75,
    ('Compound planetary', 'Lowest tooth count 5/2/1 + 4/1/2'): 16,
    ('Compound planetary', '11/2/7 + 8/2/4, 6 planets'): -48 / 7,
    ('Compound planetary', '15/5/5 + 14/4/6'): 28,
    ('Compound planetary', 'High ratio 55/21/13 + 42/16/10'): 29988 / 13,
    ('Compound planetary', 'GearDownForWhat 43/8/27 + 37/7/23'): -4144 / 27,
    ('Compound planetary', 'Backdrivable 43/19/5 + 46/19/8'): 147.2,
    ('Compound planetary', 'Carrier-driven 15/5/5 + 14/4/6'): 7,
    ('Cycloidal drive', 'Epicycloid, 9 lobes, 6 output pins'): -9,
    ('Cycloidal drive', 'Epicycloid, 4 lobes'): -4,
    ('Cycloidal drive', 'Hypocycloid, 4 lobes'): -4,
    ('Cycloidal drive', 'Ring output, disc held'): 12,
    ('Compound cycloid', 'Epi 8/7 (64:1)'): 64,
    ('Compound cycloid', 'Epi 3/4 (README)'): -15,
    ('Compound cycloid', 'Hypo 6/7'): -48,
    ('Nabtesco (RV)', 'L15 S8 W19 (test)'): 39,
    ('Nabtesco (RV)', 'L15 S10 W16, 4 cranks'): 26.6,
}


def preset_scene(type_name, preset):
    spec = GEAR_TYPES[type_name]
    values, cfg = spec.presets[preset]
    return Scene(type_name, {**spec.defaults(), **values}, cfg)


@pytest.mark.parametrize('key', list(EXPECTED))
def test_preset_ratio_and_motion(key):
    s = preset_scene(*key)
    assert s.ratio_in == pytest.approx(EXPECTED[key], rel=1e-9)
    assert s.motion_exact, 'analytic motion must match pygeartrain arrange()'
    assert not s.issues()


def test_defaults_build_for_every_type():
    for name, spec in GEAR_TYPES.items():
        s = Scene(name, spec.defaults(), spec.default_config)
        assert s.parts and s.extent > 0


def test_motion_matches_arrange_at_odd_phase():
    s = preset_scene('Compound planetary', 'High ratio 55/21/13 + 42/16/10')
    phase = 0.0123
    fast = s.transforms(phase)
    s.motion_exact = False          # force the slow path that asks pygeartrain directly
    slow = s.transforms(phase)
    for part, a, b in zip(s.parts, fast, slow):
        pa = s.world_loops(part, a)[0]
        pb = s.world_loops(part, b)[0]
        assert np.max(np.abs(pa - pb)) < 1e-6 * s.extent


def test_bad_inputs_raise_readable_errors():
    with pytest.raises(BuildError):
        Scene('Planetary', {**GEAR_TYPES['Planetary'].defaults(), 'R': 99999}, ('s', 'c', 'r'))
    with pytest.raises(BuildError):
        Scene('Planetary', GEAR_TYPES['Planetary'].defaults(), ('s', 's', 'r'))


def test_issue_fixes_resolve_the_issue():
    spec = GEAR_TYPES['Planetary']
    v = {**spec.defaults(), 'R': 15}
    issues = spec.issues(v)
    assert issues and issues[0].fix == {'R': 14}
    assert not spec.issues({**v, **issues[0].fix})


@pytest.mark.parametrize('name', list(GEAR_TYPES))
def test_meshes_are_watertight(name):
    spec = GEAR_TYPES[name]
    s = Scene(name, spec.defaults(), spec.default_config)
    for p in s.parts:
        tris, normals = extrude(p, 200)
        assert is_closed(tris)
        assert np.allclose(np.linalg.norm(normals, axis=2), 1, atol=1e-6)


# ---------------------------------------------------------------------------- sizing

def test_standard_gear_dimensions():
    g = gear_dims('g', 20, 1.0, False)
    assert (g.d, g.da, g.df) == (20.0, 22.0, 17.5)
    r = gear_dims('r', 60, 0.5, True)
    assert (r.d, r.da, r.df) == (30.0, 29.0, 31.25)


def test_undercut_limit():
    assert z_min(20) == pytest.approx(17.097, abs=1e-3)
    assert min_shift(20, 20) == 0
    assert min_shift(12, 20) == pytest.approx((17.097 - 12) / 17.097, abs=1e-3)


def test_profile_shift_textbook_example():
    # KHK gear technical reference: m3, z 12/24, x 0.6/0.36, 20 deg -> centre distance 56.4999 mm
    assert shift_for_centre(12, 24, 3, 20, 56.4999) == pytest.approx(0.96, abs=1e-3)
    assert shift_for_centre(12, 24, 3, 20, 54.0) == pytest.approx(0.0, abs=1e-9)


def test_hob_table_recommends_largest_fitting_module():
    s = preset_scene('Planetary', 'Classic 14/4/6, 5 planets')
    res = hob_table(s, 20, 'od', 25.0)
    rec = res.rows[res.recommended]
    assert rec.fits and rec.envelope <= 25.0
    assert all(not r.fits for r in res.rows if r.module > rec.module)
    text = ' '.join(res.gear_notes)
    assert 'cannot be hobbed' in text and 'Sun (z = 6)' in text
    assert rec.centre == pytest.approx(rec.module * 5)          # m (S + P) / 2


def test_compound_stage_module_note():
    s = preset_scene('Compound planetary', '11/2/7 + 8/2/4, 6 planets')   # (7+2)/(4+2) = 1.5
    res = hob_table(s, 20, 'module', 0.5)
    row = res.rows[res.recommended]
    assert row.stage_modules == pytest.approx([0.5, 0.75])
    assert not row.notes                                          # m0.75 is a standard module
    row = hob_table(s, 20, 'module', 0.6).rows
    assert any('not a standard module' in n for r in row for n in r.notes)


def test_pin_sizing_suggests_dowel():
    s = preset_scene('Cycloidal drive', 'Epicycloid, 9 lobes, 6 output pins')
    res = pin_sizing(s, 60.0)            # pin circle radius 10 units -> 3 mm per unit
    assert res.unit_mm == pytest.approx(3.0)
    assert res.pin_d == pytest.approx(6.0) and res.dowel == 6.0


# ---------------------------------------------------------------------------- calculator

def test_torque_balance_planetary():
    s = preset_scene('Planetary', 'Classic 14/4/6, 5 planets')
    r = calculate(s, 3000, 2.0, 1.0, module=1.0)
    assert r.output_rpm == pytest.approx(900)
    assert r.output_torque == pytest.approx(2.0 * 10 / 3)
    assert r.reaction == pytest.approx(2.0 * 7 / 3)               # the ring holds the difference
    assert r.power_out == pytest.approx(r.power_in)
    sun = r.meshes[0]
    assert sun.pitch_d == pytest.approx(6.0)
    assert sun.force == pytest.approx(2.0 / 0.003 / 5)            # T / r per planet


def test_calculator_efficiency():
    s = preset_scene('Compound planetary', 'README 22/7/8 + 21/6/9')
    r = calculate(s, 1000, 1.0, 0.9)
    assert r.power_out == pytest.approx(0.9 * r.power_in)
    assert r.output_torque == pytest.approx(0.9 * 36.75)


# ---------------------------------------------------------------------------- files

def test_design_round_trip(tmp_path):
    spec = GEAR_TYPES['Nabtesco (RV)']
    d = gio.design_to_dict(spec.name, spec.defaults(), spec.default_config,
                           {'module': 0.5}, {'rpm': 1500}, {'theme': 'dark'})
    p = str(tmp_path / 'x.gearstudio.json')
    gio.save_design(p, d)
    back, warnings = gio.load_design(p)
    assert back == d and not warnings


def test_design_loader_falls_back_on_bad_values(tmp_path):
    spec = GEAR_TYPES['Planetary']
    d = gio.design_to_dict(spec.name, {**spec.defaults(), 'R': -5, 'bogus': 1}, ['s', 'c', 'r'])
    p = str(tmp_path / 'bad.gearstudio.json')
    gio.save_design(p, d)
    back, warnings = gio.load_design(p)
    assert back['values']['R'] == spec.param('R').default
    assert any('R' in w for w in warnings) and any('bogus' in w for w in warnings)
    with open(p, 'w') as f:
        f.write('{"hello": 1}')
    with pytest.raises(gio.DesignError):
        gio.load_design(p)


def test_stl_export_is_closed(tmp_path):
    s = preset_scene('Planetary', 'Classic 14/4/6, 5 planets')
    unit = unit_mm_for(s, module=1.0)
    paths = gio.export_stl(s, str(tmp_path), s.transforms(0.3), unit, 6.0)
    names = sorted(os.path.basename(p) for p in paths)
    assert 'planets_x5.stl' in names and 'assembly.stl' in names
    for p in paths:
        if 'assembly' not in p:
            assert is_closed(gio.read_stl(p), decimals=3)


def test_dxf_export_reads_back(tmp_path):
    s = preset_scene('Planetary', 'Classic 14/4/6, 5 planets')
    p = gio.export_dxf(s, str(tmp_path / 'a.dxf'), s.transforms(0.0), unit_mm_for(s, module=1.0))
    layers = gio.read_dxf_polylines(p)
    assert set(layers) == {'CARRIER', 'RING', 'SUN', 'PLANETS'}
    assert len(layers['PLANETS']) == sum(len(pt.loops) for pt in s.parts if s.members[pt.member].label == 'Planets')
    ring = s.members[[m.label for m in s.members].index('Ring')].parts[0]
    assert max(np.linalg.norm(l, axis=1).max() for l in layers['RING']) == pytest.approx(ring.ring_radius * 5, rel=1e-6)
