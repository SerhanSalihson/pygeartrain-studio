import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from involute_check import Gear, D2R, check_planetary, involute_start


def errors(issues):
    return [t for lvl, t in issues if lvl == 'error']


def test_ro80_set_needs_ring_tip_pulled_back():
    # m0.5 10/35/80, x = +0.4/-0.4/-0.4: standard ring tip (dia 38.6) hits the planet root
    issues, info = check_planetary(10, 35, 80, 3, 0.5, 20.0, 0.4, -0.4, -0.4, 0.0)
    errs = errors(issues)
    assert len(errs) == 1 and 'Ring tip' in errs[0]
    assert any('11.2500 mm' in i for i in info)


def test_ro80_set_ok_with_shortened_ring_tip():
    issues, _ = check_planetary(10, 35, 80, 3, 0.5, 20.0, 0.4, -0.4, -0.4, 38.76)
    assert not errors(issues)


def test_unshifted_10_tooth_sun_interferes():
    issues, _ = check_planetary(10, 35, 80, 3, 0.5, 20.0, 0.0, 0.0, 0.0, 39.2)
    assert any('sun involute starts' in t for t in errors(issues))


def test_centre_distance_mismatch():
    issues, _ = check_planetary(10, 35, 80, 3, 0.5, 20.0, 0.3, -0.4, -0.4, 38.76)
    assert any('centre distances differ' in t for t in errors(issues))


def test_involute_start_matches_form_circle_without_undercut():
    # planet z35 x-0.4: no undercut, so the start is the rack form point (0.821 mm)
    g = Gear(35, 0.5, -0.4, 20 * D2R)
    assert abs(involute_start(g) - 0.821) < 0.01


def test_sun_x04_undercut_stays_below_base_circle():
    # z10 x+0.4 is analytically "undercut" but the generated flank stays involute to the base circle
    g = Gear(10, 0.5, 0.4, 20 * D2R)
    assert involute_start(g) < 0.02
