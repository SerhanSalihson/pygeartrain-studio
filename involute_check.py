"""Involute manufacturability check for a single-stage planetary.

Given tooth counts plus module, pressure angle and profile shifts, this checks
whether the set can actually be hobbed (sun, planets) and skived (ring) and
still mesh on the true involute:

* sun / planet undercut: a 2D rack-generation simulation finds where the
  generated flank really becomes an involute, and that is compared with where
  the mating tip starts contact
* ring tip vs planet root: the ring tip must not reach below the planet's
  involute (tip / root-fillet interference); a minimum ring tip diameter is given
* equal working centre distance for sun-planet and planet-ring
* tip thickness (pointed teeth) and transverse contact ratios

Conventions: standard rack 1.0 m addendum, 1.25 m dedendum, 0.25 m tip
radius. Internal x is defined so a ring with x_r == x_p meshes the planet at
the standard centre distance (x < 0: narrower ring spaces, ring tip and root
move inward by |x| m).
"""
from dataclasses import dataclass
from functools import lru_cache
import numpy as np

D2R = np.pi / 180
HA, HF, RHO = 1.0, 1.25, 0.25


def inv(a):
    return np.tan(a) - a


def inv_inverse(v):
    a = np.cbrt(3.0 * v)
    for _ in range(40):
        t = np.tan(a)
        a = a - (t - a - v) / (t * t)
    return float(a)


@dataclass
class Gear:
    z: int
    m: float
    x: float
    alpha: float            # rad
    internal: bool = False
    tip_radius: float = None

    @property
    def r0(self):
        return 0.5 * self.m * self.z

    @property
    def rb(self):
        return self.r0 * np.cos(self.alpha)

    @property
    def ra(self):
        if self.tip_radius:
            return self.tip_radius
        if self.internal:
            return self.r0 - (HA - self.x) * self.m
        return self.r0 + (HA + self.x) * self.m

    @property
    def rf(self):
        if self.internal:
            return self.r0 + (HF + self.x) * self.m
        return self.r0 - (HF - self.x) * self.m

    @property
    def s0(self):
        """Tooth thickness (external) or space width (internal) on r0."""
        return self.m * (np.pi / 2 + 2 * self.x * np.tan(self.alpha))

    @property
    def eta_b(self):
        """Half angle of the tooth space at the base circle."""
        if self.internal:
            return self.s0 / (2 * self.r0) + inv(self.alpha)
        return np.pi / self.z - self.s0 / (2 * self.r0) - inv(self.alpha)

    def roll(self, r):
        return float(np.sqrt(max(r * r - self.rb ** 2, 0.0)))

    def tip_thickness(self):
        if self.ra <= self.rb:
            return 0.0
        ar = np.arccos(self.rb / self.ra)
        eta = self.eta_b - inv(ar) if self.internal else self.eta_b + inv(ar)
        return 2 * self.ra * (np.pi / self.z - eta)


def involute_start(g, tol_um=0.5, n_roll=250, n_levels=600):
    """Roll length (mm) above which the rack-generated flank of external gear
    g is a true involute: the larger of the analytic form point of the
    straight rack flank and the simulated point where the flank stays within
    tol_um of the involute (the latter catches undercut)."""
    m, a, z = g.m, g.alpha, g.z
    r0, rb = g.r0, g.rb
    ta = np.tan(a)
    # rack cutting tooth: y lateral, d depth below the shifted reference line
    w = lambda d: np.pi * m / 4 - d * ta
    rf0 = RHO * m
    d_t = HF * m
    d_c = d_t - rf0
    y_c = w(d_c) - rf0 / np.cos(a)
    d_top = -(HA + g.x) * m - 0.3 * m          # above the blank tip
    d_ft = d_c + rf0 * np.sin(a)        # flank / fillet tangency depth
    n = 40
    ang1 = np.linspace(np.pi + a, 1.5 * np.pi, n)       # left fillet
    ang2 = np.linspace(1.5 * np.pi, 2 * np.pi - a, n)   # right fillet
    tooth_y = np.r_[np.linspace(-np.pi * m / 2, -w(d_top), 5),
                    np.linspace(-w(d_top), -w(d_ft), 60),
                    -y_c + rf0 * np.cos(ang1),
                    y_c + rf0 * np.cos(ang2),
                    np.linspace(w(d_ft), w(d_top), 60),
                    np.linspace(w(d_top), np.pi * m / 2, 5)]
    tooth_d = np.r_[np.full(5, d_top),
                    np.linspace(d_top, d_ft, 60),
                    d_c - rf0 * np.sin(ang1),
                    d_c - rf0 * np.sin(ang2),
                    np.linspace(d_ft, d_top, 60),
                    np.full(5, d_top)]
    zone = np.sqrt(max(g.ra ** 2 - g.rf ** 2, 0))
    J = int(np.ceil(zone / (np.pi * m))) + 1
    ys = np.concatenate([tooth_y + j * np.pi * m for j in range(-J, J + 1)])
    ds = np.tile(tooth_d, 2 * J + 1)

    L_tip = g.roll(g.ra)
    L = np.linspace(0, L_tip, n_levels)
    r_lev = np.sqrt(rb ** 2 + L ** 2)
    lo = np.full(n_levels, np.inf)

    s = np.linspace(-np.pi * m / 2, np.pi * m / 2, n_roll)[:, None]
    phi = s / r0
    X = r0 + g.x * m - ds[None, :]
    Y = ys[None, :] + s
    c, sn = np.cos(phi), np.sin(phi)
    xg, yg = c * X + sn * Y, -sn * X + c * Y                 # into gear frame
    x0, x1 = xg[:, :-1].ravel(), xg[:, 1:].ravel()
    y0, y1 = yg[:, :-1].ravel(), yg[:, 1:].ravel()
    ra_, rb_ = np.hypot(x0, y0), np.hypot(x1, y1)
    near = np.minimum(ra_, rb_) < r_lev[-1]
    x0, x1, y0, y1, ra_, rb_ = x0[near], x1[near], y0[near], y1[near], ra_[near], rb_[near]
    i_lo = np.searchsorted(r_lev, np.minimum(ra_, rb_), 'left')
    i_hi = np.searchsorted(r_lev, np.maximum(ra_, rb_), 'right') - 1
    cnt = np.maximum(i_hi - i_lo + 1, 0)
    seg = np.repeat(np.arange(cnt.size), cnt)
    if seg.size == 0:
        return L_tip
    i = i_lo[seg] + np.arange(seg.size) - np.repeat(np.cumsum(cnt) - cnt, cnt)
    dr = rb_[seg] - ra_[seg]
    t = np.where(np.abs(dr) > 1e-15, (r_lev[i] - ra_[seg]) / np.where(np.abs(dr) > 1e-15, dr, 1), 0.5)
    th = np.arctan2(y0[seg] + t * (y1[seg] - y0[seg]), x0[seg] + t * (x1[seg] - x0[seg]))
    P = 2 * np.pi / z
    th = th - np.round(th / P) * P
    np.minimum.at(lo, i, th)

    # left flank of the space centred on 0: base angle should be -eta_b
    phiL = lo + inv(np.arccos(np.clip(rb / r_lev, -1, 1)))
    dev_um = rb * (phiL + g.eta_b) * 1e3
    bad = ~np.isfinite(dev_um) | (np.abs(dev_um) > tol_um)
    bad &= L < 0.7 * L_tip
    L_sim = float(L[bad].max()) if bad.any() else 0.0
    L_form = r0 * np.sin(a) - (HF - g.x - RHO * (1 - np.sin(a))) * m / np.sin(a)
    return max(L_sim, L_form)


@lru_cache(maxsize=256)
def check_planetary(S, P, R, N, m, alpha_deg, x_s, x_p, x_r, ring_tip_dia=0.0):
    """Returns (issues, info): issues = ((level, text), ...), level 'error'/'warn'."""
    issues, info = [], []
    if m <= 0:
        return [('error', 'Module must be positive.')], info
    a = alpha_deg * D2R
    sun, pl = Gear(S, m, x_s, a), Gear(P, m, x_p, a)
    ring = Gear(R, m, x_r, a, internal=True,
                tip_radius=ring_tip_dia / 2 if ring_tip_dia else None)
    if R - P <= 0 or S <= 0 or P <= 0:
        return [('error', 'Tooth counts must satisfy R > P > 0, S > 0.')], info

    # working centre distances
    aw_e = inv_inverse(inv(a) + 2 * np.tan(a) * (x_s + x_p) / (S + P))
    a_e = (S + P) * m * np.cos(a) / (2 * np.cos(aw_e))
    aw_i = inv_inverse(inv(a) + 2 * np.tan(a) * (x_r - x_p) / (R - P))
    a_i = (R - P) * m * np.cos(a) / (2 * np.cos(aw_i))
    info.append(f'Centre distance: sun–planet {a_e:.4f} mm, planet–ring {a_i:.4f} mm')
    if abs(a_e - a_i) > 1e-3:
        issues.append(('error', f'Sun–planet and planet–ring centre distances differ by '
                                f'{(a_e - a_i) * 1e3:+.1f} µm. Adjust shifts (zero-sum: x_p = −x_s, '
                                f'x_r = x_p) or the ring will not fit.'))

    pb = np.pi * m * np.cos(a)
    La_s, La_p = sun.roll(sun.ra), pl.roll(pl.ra)
    La_r = ring.roll(ring.ra)
    base_e, base_i = a_e * np.sin(aw_e), a_i * np.sin(aw_i)
    eps_sp = (La_s + La_p - base_e) / pb
    eps_pr = (La_p - La_r + base_i) / pb
    info.append(f'Contact ratio εα: sun–planet {eps_sp:.2f}, planet–ring {eps_pr:.2f}')
    for name, e in (('sun–planet', eps_sp), ('planet–ring', eps_pr)):
        if e < 1.1:
            issues.append(('error', f'{name} contact ratio {e:.2f} < 1.1: tooth pairs lose contact.'))
        elif e < 1.25:
            issues.append(('warn', f'{name} contact ratio {e:.2f} is low (< 1.25).'))

    # where the hobbed flanks really become involutes
    Ls_start, Lp_start = involute_start(sun), involute_start(pl)
    Ls_contact = base_e - La_p                       # planet tip on sun
    Lp_contact = min(base_e - La_s, La_r - base_i)   # sun tip / ring tip on planet
    if Ls_contact < Ls_start:
        issues.append(('error', f'Planet tip meets the sun at roll {Ls_contact:.3f} mm, below where the '
                                f'sun involute starts ({Ls_start:.3f} mm, undercut/fillet): '
                                f'interference. Raise x_s or shorten the planet tip.'))
    if base_e - La_s < Lp_start:
        issues.append(('error', f'Sun tip meets the planet below its involute start '
                                f'({base_e - La_s:.3f} < {Lp_start:.3f} mm).'))
    # ring tip: must not dig into the planet's root fillet
    L_need = Lp_start + 0.05 * m + base_i
    ra_min = np.sqrt(ring.rb ** 2 + L_need ** 2)
    if La_r - base_i < Lp_start + 0.05 * m:
        issues.append(('error', f'Ring tip (Ø{2 * ring.ra:.3f}) reaches the planet below its involute: '
                                f'tip/root interference. Use ring tip Ø ≥ {2 * ra_min:.3f} mm.'))
    info.append(f'Ring tip Ø {2 * ring.ra:.3f} mm (minimum for planet root clearance Ø {2 * ra_min:.3f})')
    if ring.ra <= ring.rb:
        issues.append(('error', 'Ring tip is inside its base circle: no involute there.'))
    if ring.ra >= ring.rf:
        issues.append(('error', 'Ring tip diameter is not smaller than its root diameter.'))

    for name, g in (('Sun', sun), ('Planet', pl)):
        sa = g.tip_thickness() / m
        if sa < 0.25:
            issues.append(('warn' if sa > 0 else 'error',
                           f'{name} tip thickness {sa:.2f}·m is pointed (< 0.25 m; '
                           f'aim ≥ 0.4 m if case-hardened).'))
        elif sa < 0.4:
            info.append(f'{name} tip thickness {sa:.2f}·m (≥ 0.4 m preferred if case-hardened)')
    info.append(f'Involute start (roll from base): sun {Ls_start:.3f} mm, planet {Lp_start:.3f} mm; '
                f'first contact: sun {Ls_contact:.3f}, planet {Lp_contact:.3f}')
    return tuple(issues), tuple(info)
