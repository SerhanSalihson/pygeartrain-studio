"""2D mesh verification with shapely: overlaps over a motion sweep and the backlash per flank."""
from __future__ import annotations

import math

from shapely import affinity

from gearstudio.involute import geometry as inv
from gearstudio.involute.planetary import GearSet


def members(gs: GearSet):
    """Shapely polygons of sun, planet and ring at their home positions (before phasing)."""
    al = math.radians(gs.alpha_deg)
    sun = inv.gear_polygon_external(gs.zs, gs.m, al, inv.thickness(gs.m, al, gs.xs, gs.backlash_each),
                                    gs.sun_root_r, gs.sun_tip_r)
    pl = inv.gear_polygon_external(gs.zp, gs.m, al, inv.thickness(gs.m, al, gs.xp, gs.backlash_each),
                                   gs.planet_root_r, gs.planet_tip_r)
    ring = inv.gear_polygon_internal(gs.zr, gs.m, al, inv.ring_space(gs.m, al, gs.xr, gs.backlash_each),
                                     gs.ring_tip_r, gs.ring_root_r)
    return sun, pl, ring


def sweep(gs: GearSet, steps: int = 13, span_sun_teeth: float = 1.0):
    """Turn the sun across `span_sun_teeth` tooth pitches (ring fixed). Returns the worst overlap
    area (mm^2) and the smallest sun-planet and planet-ring gaps (mm) seen over the sweep."""
    sun, pl, ring = members(gs)
    ring = affinity.rotate(ring, gs.ring_rot_deg, origin=(0, 0))
    worst, gaps_s, gaps_r = 0.0, [], []
    for i in range(steps):
        ts = span_sun_teeth * 360.0 / gs.zs * i / max(steps - 1, 1)
        tc = ts / gs.ratio
        S = affinity.rotate(sun, ts, origin=(0, 0))
        for k, th in enumerate(gs.planet_angles_deg):
            spin = gs.planet_rot_deg[k] + tc * (1 - gs.zr / gs.zp)
            c = math.radians(th + tc)
            P = affinity.translate(affinity.rotate(pl, spin, origin=(0, 0)), gs.a * math.cos(c), gs.a * math.sin(c))
            o1, o2 = P.intersection(S).area, P.intersection(ring).area
            worst = max(worst, o1, o2)
            gaps_s.append(P.distance(S) if o1 < 1e-9 else 0.0)
            gaps_r.append(P.distance(ring) if o2 < 1e-9 else 0.0)
    return worst, min(gaps_s), min(gaps_r)
