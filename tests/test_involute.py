"""Involute back end, checked against the built P10 actuator (8/28/64, m0.75, 25 deg, xs +0.3)."""
import math
import os
import sys

import numpy as np
import pytest
from shapely.geometry import Polygon

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gearstudio import sizing  # noqa: E402
from gearstudio.involute import (check_strength, design_gearset, enumerate_sets, external_outline,  # noqa: E402
                                 gear_polygon_external, gear_polygon_internal, internal_outline, inv, planet_phases,
                                 ring_space, sweep, thickness, undercut_shift)

# the P10 layout.json 'gear' block, as built and measured
P10 = {'m': 0.75, 'alpha_deg': 25.0, 'zs': 8, 'zp': 28, 'zr': 64, 'xs': 0.3, 'xp': -0.3, 'backlash_each': 0.06,
       'a': 13.5, 'n_planets': 3, 'sun_tip_r': 3.7, 'sun_root_r': 2.2875, 'planet_tip_r': 11.025,
       'planet_root_r': 9.3375, 'ring_tip_r': 23.1, 'ring_root_r': 24.75, 'planet_rot_deg': 6.428571,
       'ring_rot_deg': 2.8125}


@pytest.fixture(scope='module')
def gs():
    return design_gearset(0.75, 8, 28, 64, 3, stator_bore_d=55.0, journal_r=2.0)


@pytest.mark.parametrize('key', list(P10))
def test_p10_gear_values_reproduced(gs, key):
    assert gs.as_layout_gear()[key] == pytest.approx(P10[key], abs=1e-6)


def test_p10_set_is_feasible(gs):
    assert gs.ok, gs.issues
    assert gs.ratio == 9.0
    assert gs.planet_rot_deg == [pytest.approx(6.428571)] * 3


def test_p10_mesh_sweep_clean_with_p10_backlash(gs):
    worst, gap_sun, gap_ring = sweep(gs, steps=9)
    assert worst < 1e-6
    # P10 measured 0.054..0.056 mm per flank in Inventor (= backlash / 2 * cos 25)
    assert 0.050 < gap_sun < 0.060 and 0.050 < gap_ring < 0.060


def test_p10_strength_in_expected_range(gs):
    st = check_strength(gs, face_width=16.0, motor_torque_Nm=1.3)
    assert st.ft_per_mesh_N == pytest.approx(173.3, abs=0.5)
    assert st.limiting == 'planet'
    assert 40 < st.sigma_planet_MPa < 65


def test_enumeration_finds_p10():
    sets = enumerate_sets(9.0, 0.3, stator_bore_d=55.0, modules=(0.75,), planets=(3,), keep=50)
    assert (8, 28, 64) in {(g.zs, g.zp, g.zr) for g, _ in sets}


def test_phasing_four_planets():
    angles, rots, ring = planet_phases(12, 30, 72, 4)
    assert len(rots) == 4 and all(0 <= r < 360 / 30 for r in rots)


def test_bad_sets_are_rejected():
    assert not design_gearset(0.75, 8, 28, 65, 3).ok                       # not coaxial
    assert not design_gearset(0.75, 9, 28, 65, 3, stator_bore_d=55).ok     # (9+65)/3 not whole
    assert not design_gearset(1.0, 8, 28, 64, 3, stator_bore_d=55).ok      # m1 ring does not fit a D55 bore


def test_sizing_uses_the_same_formulas():
    a = math.radians(20)
    assert sizing.inv is inv
    assert sizing.min_shift(12, 20) == pytest.approx(undercut_shift(12, a))
    assert undercut_shift(12, a) == pytest.approx(1 - 12 * math.sin(a) ** 2 / 2)


def test_outlines_match_the_shapely_gears(gs):
    al = math.radians(gs.alpha_deg)
    s = thickness(gs.m, al, gs.xs, gs.backlash_each)
    out = Polygon(external_outline(gs.zs, gs.m, al, s, gs.sun_root_r, gs.sun_tip_r, flank_pts=40, arc_pts=24))
    ref = gear_polygon_external(gs.zs, gs.m, al, s, gs.sun_root_r, gs.sun_tip_r)
    assert out.is_valid and out.exterior.is_ccw
    assert out.symmetric_difference(ref).area < 0.01 * ref.area
    # tooth 0 is centred on +X: the outline reaches the tip radius on the +X axis
    pts = np.asarray(out.exterior.coords)
    assert np.max(pts[:, 0]) == pytest.approx(gs.sun_tip_r, rel=1e-3)

    e = ring_space(gs.m, al, gs.xr, gs.backlash_each)
    bore = internal_outline(gs.zr, gs.m, al, e, gs.ring_tip_r, gs.ring_root_r, flank_pts=30, arc_pts=12)
    ring = Polygon(np.c_[np.cos(np.linspace(0, 2 * np.pi, 720)), np.sin(np.linspace(0, 2 * np.pi, 720))]
                   * (gs.ring_root_r + 3), [bore])
    ref = gear_polygon_internal(gs.zr, gs.m, al, e, gs.ring_tip_r, gs.ring_root_r)
    assert ring.is_valid
    assert ring.symmetric_difference(ref).area < 0.01 * ref.area
    # a tooth space is centred on +X: the bore reaches the root radius on the +X axis
    assert np.max(bore[:, 0]) == pytest.approx(gs.ring_root_r, rel=1e-3)


def test_involute_export_is_closed(gs, tmp_path):
    from gearstudio import io as gio
    from gearstudio.meshing import is_closed
    paths = gio.export_involute(str(tmp_path), [gs], face_width=16.0)
    names = sorted(os.path.basename(p) for p in paths)
    assert names == ['involute_set.dxf', 'planet_x3.stl', 'ring.stl', 'sun.stl']
    for p in paths:
        if p.endswith('.stl'):
            tris = gio.read_stl(p)
            assert is_closed(tris, decimals=3)
            assert tris[..., 2].max() == pytest.approx(16.0)
    layers = gio.read_dxf_polylines(paths[-1])
    assert len(layers['PLANETS']) == 3 and len(layers['RING']) == 2
