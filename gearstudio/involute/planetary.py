"""Involute planetary gear-set design: zero-sum profile shift, tip topping, phasing and checks.

Ported from actgen; reproduces the hand-tuned P10 set exactly (8/28/64 m0.75 a25 xs+0.3):
  zero-sum shift xp = -xs, ring takes the planet's shift, a = m(zs+zp)/2
  external tip  = m(z/2 + 1 + x), root = m(z/2 - 1.25 + x)
  ring tip      = a + planet_root + c_ring_tip*m      (0.35 m)
  ring root     = a + planet_tip  + c_ring_root*m     (0.30 m)
  sun tip topped so the tip land >= land_min (steel sun: 3.975 -> 3.70)
  planet phase  = per planet, from the assembly geometry; ring offset pi/zr when the planet shows a space outward
The actuator-specific checks (stator bore, journal, planet bore) only apply when those arguments are given.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Optional

from gearstudio.involute import geometry as inv


@dataclass
class GearRules:
    alpha_deg: float = 25.0
    backlash_each: float = 0.06          # mm thinning per member
    c_ring_tip: float = 0.35             # x m, ring tip clearance to the planet root circle
    c_ring_root: float = 0.30            # x m, ring root clearance to the planet tip circle
    land_min_steel: float = 0.50         # mm tip land for a steel (cut) sun
    land_min_printed: float = 0.35       # mm tip land for printed teeth
    shift_step: float = 0.05
    eps_min: float = 1.05                # contact ratio hard limit
    eps_warn: float = 1.2                # below this: warning only
    neighbour_gap_min: float = 1.0       # mm between adjacent planet tips
    planet_rim_min: float = 1.5          # mm wall between planet root and its bearing bore
    ring_wall_min: float = 2.5           # mm wall from ring root to the ring OD
    nose_fit: float = 0.05               # mm radial gap nose -> stator bore
    zr_minus_zp_min: int = 10            # internal tip-interference rule of thumb
    journal_gap_min: float = 0.3         # mm, sun journal to planet tips
    min_printable_module: float = 0.8    # printed teeth below this module get a warning
    k_gamma: dict = field(default_factory=lambda: {3: 1.2, 4: 1.3, 5: 1.35, 6: 1.4})


@dataclass
class GearSet:
    m: float
    alpha_deg: float
    zs: int
    zp: int
    zr: int
    n: int
    xs: float
    xp: float
    xr: float
    a: float
    ratio: float
    sun_tip_r: float
    sun_root_r: float
    planet_tip_r: float
    planet_root_r: float
    ring_tip_r: float
    ring_root_r: float
    backlash_each: float
    planet_angles_deg: list
    planet_rot_deg: list
    ring_rot_deg: float
    eps_sp: float
    eps_pr: float
    neighbour_gap: float
    ring_outer_need_r: float              # ring root + wall
    journal_r_max: float                  # largest sun journal radius that clears the planets
    planet_bore_r_max: float              # largest planet bore radius that keeps the rim
    issues: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    placement: str = "inside"            # actuator: ring 'inside' the stator bore or 'front' of it

    @property
    def ok(self) -> bool:
        return not self.issues

    def as_layout_gear(self) -> dict:
        """The P10 layout.json 'gear' block for this set."""
        return dict(m=self.m, alpha_deg=self.alpha_deg, zs=self.zs, zp=self.zp, zr=self.zr, xs=self.xs, xp=self.xp,
                    backlash_each=self.backlash_each, a=self.a, n_planets=self.n,
                    sun_tip_r=self.sun_tip_r, sun_root_r=self.sun_root_r, planet_tip_r=self.planet_tip_r,
                    planet_root_r=self.planet_root_r, ring_tip_r=self.ring_tip_r, ring_root_r=self.ring_root_r,
                    planet_rot_deg=self.planet_rot_deg[0], ring_rot_deg=self.ring_rot_deg)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ok"] = self.ok
        return d


def _ceil_step(x: float, step: float) -> float:
    return round(math.ceil(round(x / step, 9)) * step, 6)


def min_shift(z: int, alpha: float, step: float) -> float:
    """Smallest positive profile shift (rounded up to `step`) that avoids undercut for a rack-cut gear."""
    return max(0.0, _ceil_step(1 - z * math.sin(alpha) ** 2 / 2, step))


def planet_phases(zs: int, zp: int, zr: int, n: int, angles_deg: Optional[list] = None):
    """Self-rotation of each planet (deg) and the ring offset (deg): sun tooth on +X, planet tooth at
    local angle 0 when rot = 0, ring space centred on 0."""
    pitch = 2 * math.pi / zp
    angles = angles_deg if angles_deg is not None else [360.0 * k / n for k in range(n)]
    phi0 = (math.pi - math.pi / zp) % pitch                    # planet 0 must show a space to the sun tooth
    rots = []
    for th in angles:
        phik = (phi0 + math.radians(th) * (1 + zs / zp)) % pitch
        rots.append(round(math.degrees(phik), 6))
    shows_space_out = abs(phi0 - math.pi / zp) < 1e-9
    ring = round(180.0 / zr, 6) if shows_space_out else 0.0
    return angles, rots, ring


def design_gearset(m: float, zs: int, zp: int, zr: int, n: int = 3, rules: GearRules = GearRules(),
                   xs: Optional[float] = None, sun_steel: bool = True, planet_bore_r: Optional[float] = 6.0,
                   stator_bore_d: Optional[float] = None, journal_r: Optional[float] = None,
                   placement: str = "inside", ring_r_max: Optional[float] = None) -> GearSet:
    al = math.radians(rules.alpha_deg)
    issues = []
    warnings = []
    if zr - zs != 2 * zp:
        issues.append(f"tooth counts not coaxial: zr - zs = {zr - zs} != 2*zp = {2 * zp}")
    if (zs + zr) % n:
        issues.append(f"assembly condition: (zs+zr)/n = {(zs + zr) / n:.2f} is not whole")
    if xs is None:
        xs = min_shift(zs, al, rules.shift_step)
    xp = -xs
    xr = xp
    if xp < 1 - zp * math.sin(al) ** 2 / 2 - 1e-9:
        issues.append(f"planet undercut: xp {xp:+.2f} below {1 - zp * math.sin(al) ** 2 / 2:+.2f}")
    a = m * (zs + zp) / 2
    rp_s, rp_p, rp_r = m * zs / 2, m * zp / 2, m * zr / 2
    sun_tip_full = m * (zs / 2 + 1 + xs)
    s_sun = inv.thickness(m, al, xs, rules.backlash_each)
    s_pl = inv.thickness(m, al, xp, rules.backlash_each)
    sun_tip = inv.top_tip_for_land(zs, m, al, s_sun, sun_tip_full,
                                   rules.land_min_steel if sun_steel else rules.land_min_printed)
    sun_root = m * (zs / 2 - 1.25 + xs)
    pl_tip_full = m * (zp / 2 + 1 + xp)
    pl_tip = inv.top_tip_for_land(zp, m, al, s_pl, pl_tip_full, rules.land_min_printed)
    pl_root = m * (zp / 2 - 1.25 + xp)
    ring_tip = a + pl_root + rules.c_ring_tip * m
    ring_root = a + pl_tip + rules.c_ring_root * m
    rb_s, rb_p, rb_r = rp_s * math.cos(al), rp_p * math.cos(al), rp_r * math.cos(al)
    pb = math.pi * m * math.cos(al)
    L = a * math.sin(al)
    g_s = math.sqrt(max(sun_tip ** 2 - rb_s ** 2, 0))
    g_p = math.sqrt(max(pl_tip ** 2 - rb_p ** 2, 0))
    eps_sp = (g_s + g_p - L) / pb
    if ring_tip <= rb_r:
        issues.append(f"ring tip r {ring_tip:.3f} inside its base circle {rb_r:.3f}")
        eps_pr = float("nan")
    else:
        g_r = math.sqrt(ring_tip ** 2 - rb_r ** 2)
        eps_pr = (g_p - g_r + L) / pb
    for name, e in (("sun-planet", eps_sp), ("planet-ring", eps_pr)):
        if not (e >= rules.eps_min):
            issues.append(f"contact ratio {name} {e:.2f} < {rules.eps_min}")
        elif e < rules.eps_warn:
            warnings.append(f"contact ratio {name} {e:.2f} is low (< {rules.eps_warn}); check the mesh sweep")
    if zr - zp < rules.zr_minus_zp_min:
        issues.append(f"internal tip interference risk: zr - zp = {zr - zp} < {rules.zr_minus_zp_min}")
    gap = 2 * a * math.sin(math.pi / n) - 2 * pl_tip if n > 1 else float("inf")
    if gap < rules.neighbour_gap_min:
        issues.append(f"planets collide: neighbour gap {gap:.2f} mm < {rules.neighbour_gap_min}")
    bore_r_max = pl_root - rules.planet_rim_min
    if planet_bore_r is not None and planet_bore_r > bore_r_max + 1e-9:
        issues.append(f"planet rim: bore r {planet_bore_r} leaves {pl_root - planet_bore_r:.2f} mm "
                      f"< {rules.planet_rim_min}")
    ring_need = ring_root + rules.ring_wall_min
    if placement == "inside" and stator_bore_d is not None and ring_need > stator_bore_d / 2 - rules.nose_fit + 1e-9:
        issues.append(f"ring does not fit the stator bore: needs r {ring_need:.2f}, "
                      f"nose r {stator_bore_d / 2 - rules.nose_fit:.2f}")
    if placement == "front" and ring_r_max is not None and ring_need > ring_r_max + 1e-9:
        issues.append(f"ring does not fit the actuator envelope: needs r {ring_need:.2f}, max r {ring_r_max:.2f}")
    if placement == "front" and stator_bore_d is not None and a + pl_tip < stator_bore_d / 2:
        warnings.append("stage would also fit inside the stator bore")
    j_max = a - pl_tip - rules.journal_gap_min
    if journal_r is not None and journal_r > j_max + 1e-9:
        issues.append(f"sun journal r {journal_r} hits the planets (max {j_max:.2f})")
    if journal_r is not None and j_max <= 0.75:
        issues.append(f"no room for a sun journal/pilot bearing (max r {j_max:.2f})")
    if m < rules.min_printable_module:
        warnings.append(f"module {m} is below the printable minimum {rules.min_printable_module} "
                        "for printed planets/ring")
    angles, rots, ring_rot = planet_phases(zs, zp, zr, n)
    r6 = lambda v: round(v, 6)
    return GearSet(m=m, alpha_deg=rules.alpha_deg, zs=zs, zp=zp, zr=zr, n=n, xs=xs, xp=xp, xr=xr, a=r6(a),
                   ratio=r6(1 + zr / zs), sun_tip_r=r6(sun_tip), sun_root_r=r6(sun_root), planet_tip_r=r6(pl_tip),
                   planet_root_r=r6(pl_root), ring_tip_r=r6(ring_tip), ring_root_r=r6(ring_root),
                   backlash_each=rules.backlash_each, planet_angles_deg=angles, planet_rot_deg=rots,
                   ring_rot_deg=ring_rot, eps_sp=r6(eps_sp), eps_pr=r6(eps_pr), neighbour_gap=r6(gap),
                   ring_outer_need_r=r6(ring_need), journal_r_max=r6(j_max), planet_bore_r_max=r6(bore_r_max),
                   placement=placement, issues=issues, warnings=warnings)


def enumerate_sets(target_ratio: float, ratio_tol: float, stator_bore_d: float,
                   modules=(0.5, 0.6, 0.7, 0.75, 0.8, 1.0), planets=(3, 4, 5), rules: GearRules = GearRules(),
                   planet_bore_r: float = 6.0, zs_range=(6, 40), strength_fn=None, keep: int = 8,
                   front_ring_r_max: Optional[float] = None, placements=("inside", "front")):
    """All feasible sets (sun in, ring fixed, carrier out) within the ratio window, ranked.

    The ring goes 'inside' the stator bore when it fits there, otherwise 'front' (ring up to
    front_ring_r_max). strength_fn(gs) -> min safety margin (optional)."""
    out = []
    lo, hi = target_ratio - ratio_tol, target_ratio + ratio_tol
    for placement in placements:
        if placement == "front" and front_ring_r_max is None:
            continue
        for m in modules:
            for n in planets:
                for zs in range(zs_range[0], zs_range[1] + 1):
                    zr_lo = math.ceil(zs * (lo - 1))
                    zr_hi = math.floor(zs * (hi - 1))
                    for zr in range(max(zr_lo, zs + 2), zr_hi + 1):
                        if (zr - zs) % 2 or (zs + zr) % n:
                            continue
                        zp = (zr - zs) // 2
                        gs = design_gearset(m, zs, zp, zr, n, rules, planet_bore_r=planet_bore_r,
                                            stator_bore_d=stator_bore_d, placement=placement,
                                            ring_r_max=front_ring_r_max)
                        if not gs.ok or (placement == "front"
                                         and "stage would also fit inside the stator bore" in gs.warnings):
                            continue
                        margin = strength_fn(gs) if strength_fn else None
                        out.append((gs, margin))

    def key(item):
        gs, margin = item
        strong = margin if margin is not None else 1.0
        return (strong < 1.0, gs.m < rules.min_printable_module, gs.placement != "inside",
                abs(gs.ratio - target_ratio) > 0.15, -gs.m, -min(strong, 3.0), round(gs.ring_outer_need_r, 1))
    out.sort(key=key)
    return out[:keep]


def explain_infeasible(target_ratio: float, ratio_tol: float, stator_bore_d: float, rules: GearRules = GearRules(),
                       modules=(0.5, 0.6, 0.7, 0.75, 0.8, 1.0), planets=(3, 4), planet_bore_r: float = 6.0,
                       front_ring_r_max: Optional[float] = None, placements=("inside", "front"),
                       zs_range=(6, 40)) -> dict:
    """Why no set passes: counts of each failing check over every candidate, plus the closest candidate."""
    from collections import Counter
    counts, closest, tried = Counter(), None, 0
    lo, hi = target_ratio - ratio_tol, target_ratio + ratio_tol
    for placement in placements:
        if placement == "front" and front_ring_r_max is None:
            continue
        for m in modules:
            for n in planets:
                for zs in range(zs_range[0], zs_range[1] + 1):
                    for zr in range(max(math.ceil(zs * (lo - 1)), zs + 2), math.floor(zs * (hi - 1)) + 1):
                        if (zr - zs) % 2:
                            continue
                        gs = design_gearset(m, zs, (zr - zs) // 2, zr, n, rules, planet_bore_r=planet_bore_r,
                                            stator_bore_d=stator_bore_d, placement=placement,
                                            ring_r_max=front_ring_r_max)
                        tried += 1
                        for iss in gs.issues:
                            counts[iss.split(":")[0]] += 1
                        if closest is None or len(gs.issues) < len(closest.issues):
                            closest = gs
    return {"feasible": False if closest is None or closest.issues else True, "candidates_tried": tried,
            "failure_counts": counts.most_common(), "closest": closest.to_dict() if closest else None}


def outlines(gs: GearSet, flank_pts: int = 24, arc_pts: int = 8) -> dict:
    """Exact closed outlines of the set in mm, assembled and phased.

    sun: CCW outline at the origin (tooth 0 on +X); planets: one CCW outline per planet, placed and
    turned by its phase; planet_part: one planet at the origin, unphased; ring_bore: the toothed bore
    (CW, space 0 on +X before the ring offset); ring_outer_r: ring body radius (root + wall)."""
    al = math.radians(gs.alpha_deg)
    s_sun = inv.thickness(gs.m, al, gs.xs, gs.backlash_each)
    s_pl = inv.thickness(gs.m, al, gs.xp, gs.backlash_each)
    e_ring = inv.ring_space(gs.m, al, gs.xr, gs.backlash_each)
    sun = inv.external_outline(gs.zs, gs.m, al, s_sun, gs.sun_root_r, gs.sun_tip_r, 0.0, flank_pts, arc_pts)
    planet = inv.external_outline(gs.zp, gs.m, al, s_pl, gs.planet_root_r, gs.planet_tip_r, 0.0, flank_pts, arc_pts)
    planets = []
    for th, rot in zip(gs.planet_angles_deg, gs.planet_rot_deg):
        c, r = math.radians(th), math.radians(rot)
        cr, sr = math.cos(r), math.sin(r)
        p = planet @ [[cr, sr], [-sr, cr]]
        planets.append(p + (gs.a * math.cos(c), gs.a * math.sin(c)))
    bore = inv.internal_outline(gs.zr, gs.m, al, e_ring, gs.ring_tip_r, gs.ring_root_r,
                                math.radians(gs.ring_rot_deg), flank_pts, arc_pts)
    return {'sun': sun, 'planets': planets, 'planet_part': planet, 'ring_bore': bore,
            'ring_outer_r': gs.ring_outer_need_r}
