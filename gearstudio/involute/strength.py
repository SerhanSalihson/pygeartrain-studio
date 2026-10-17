"""Tooth bending strength (Lewis) with the form factor measured on the generated involute tooth."""
from __future__ import annotations

import math
from dataclasses import dataclass

from gearstudio.involute import geometry as inv
from gearstudio.involute.planetary import GearRules, GearSet


def lewis_Y(z: int, m: float, alpha: float, s: float, r_root: float, r_tip: float, samples: int = 200) -> float:
    """Inscribed-parabola Lewis factor for a tip load: Y = (2/3) * min_r( t(r)^2 / (4 (r_tip - r)) ) / m."""
    best = float("inf")
    for i in range(samples):
        r = r_root + (r_tip - r_root) * i / samples
        if r_tip - r < 1e-6:
            continue
        t = inv.tooth_chord(z, m, alpha, s, max(r, r_root))
        best = min(best, t * t / (4 * (r_tip - r)))
    return 2 * best / (3 * m)


@dataclass
class StrengthReport:
    ft_per_mesh_N: float
    sigma_sun_MPa: float
    sigma_planet_MPa: float
    sigma_ring_MPa: float
    Y_sun: float
    Y_planet: float
    allow_sun_MPa: float
    allow_planet_MPa: float
    allow_ring_MPa: float
    margin: float                  # min allowable / stress
    limiting: str
    motor_torque_allow_Nm: float   # input (sun) torque at which the limiting member reaches its allowable
    output_torque_allow_Nm: float


def check_strength(gs: GearSet, face_width: float, motor_torque_Nm: float, rules: GearRules = GearRules(),
                   allow=None, kv: float = 1.0) -> StrengthReport:
    """Bending stress of sun, planet and ring for a sun torque. allow: member -> allowable bending stress in
    MPa (printed PPA-CF ~30, steel ~250). The load per mesh includes the load-sharing factor k_gamma."""
    allow = allow or {"sun": 250.0, "planet": 30.0, "ring": 30.0}
    al = math.radians(gs.alpha_deg)
    kg = rules.k_gamma.get(gs.n, 1.4)
    r_ws = gs.m * gs.zs / 2                                     # zero-sum shift -> working pitch = pitch
    ft = motor_torque_Nm * 1000.0 / (gs.n * r_ws) * kg
    s_sun = inv.thickness(gs.m, al, gs.xs, gs.backlash_each)
    s_pl = inv.thickness(gs.m, al, gs.xp, gs.backlash_each)
    y_s = lewis_Y(gs.zs, gs.m, al, s_sun, gs.sun_root_r, gs.sun_tip_r)
    y_p = lewis_Y(gs.zp, gs.m, al, s_pl, gs.planet_root_r, gs.planet_tip_r)
    y_r = 1.3 * y_p                                              # internal teeth are thicker at the root
    sig = {k: ft * kv / (face_width * gs.m * y) for k, y in (("sun", y_s), ("planet", y_p), ("ring", y_r))}
    margins = {k: allow[k] / sig[k] for k in sig}
    lim = min(margins, key=margins.get)
    mt_allow = motor_torque_Nm * margins[lim]
    return StrengthReport(ft_per_mesh_N=ft, sigma_sun_MPa=sig["sun"], sigma_planet_MPa=sig["planet"],
                          sigma_ring_MPa=sig["ring"], Y_sun=y_s, Y_planet=y_p, allow_sun_MPa=allow["sun"],
                          allow_planet_MPa=allow["planet"], allow_ring_MPa=allow["ring"], margin=margins[lim],
                          limiting=lim, motor_torque_allow_Nm=mt_allow,
                          output_torque_allow_Nm=mt_allow * gs.ratio * 0.95)
