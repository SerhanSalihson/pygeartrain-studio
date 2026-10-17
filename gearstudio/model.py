"""Turn a design (gear type + values + configuration) into an animatable scene.

Every part of every pygeartrain gear train moves rigidly, spinning at a constant rate while its
centre orbits the origin at another constant rate (planets, cycloid discs), or stays put (suns,
rings, carriers, side-by-side gears). `fit_motion` recovers those rates from pygeartrain's own
`arrange()`, and the fit is checked against `arrange()` at other phases. Views then need one
rigid transform per part per frame instead of re-running pygeartrain.
"""
from collections import namedtuple
from dataclasses import dataclass, field

import numpy as np
import shapely
from matplotlib.path import Path
from shapely.geometry import Polygon

from gearstudio.catalog import GEAR_TYPES, Issue

# loops: closed vertex arrays in the part's body frame, solids CCW / holes CW
# parent: index of the enclosing loop one level up (-1: top level); ring_radius: outer body of a ring
Part = namedtuple('Part', 'member loops solid parent ring_radius c0 k_theta k_centre radius')


@dataclass
class Member:
    label: str
    dof: str
    ring: bool
    layer: int
    span: int
    parts: list = field(default_factory=list)


class BuildError(Exception):
    pass


# ---------------------------------------------------------------------------- loops

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


def analyse_profile(profile, ring):
    """Loops of one profile with nesting and orientation; None if the profile is empty.

    Returns (loops as index arrays, solid flags, parents, ring body radius or None)."""
    cubes = profile.topology.elements[-1]
    if not len(cubes):
        return None
    loops = trace_loops(cubes)
    if not loops:
        return None
    verts = profile.vertices
    polys = [verts[l] for l in loops]
    paths = [Path(p) for p in polys]
    n = len(loops)
    inside = np.zeros((n, n), dtype=bool)     # inside[i, j]: loop i lies within loop j
    for i, p in enumerate(polys):
        sample = p[np.linspace(0, len(p) - 1, 5).astype(int)]
        for j, q in enumerate(paths):
            inside[i, j] = i != j and np.sum(q.contains_points(sample)) >= 3
    depth = inside.sum(axis=1)
    ring_radius = None
    if ring:    # rings only have their toothed inner edge; give them an outer body
        ring_radius = float(np.max(np.linalg.norm(verts, axis=1))) * 1.08
        depth = depth + 1
    solid = [bool(d % 2 == 0) for d in depth]
    parent = []
    for i in range(n):
        up = [j for j in range(n) if inside[i, j] and depth[j] == depth[i] - 1]
        parent.append(up[0] if up else -1)
    oriented = [l if (signed_area(p) > 0) == s else l[::-1] for l, p, s in zip(loops, polys, solid)]
    return oriented, solid, parent, ring_radius


# ---------------------------------------------------------------------------- motion

def rot(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s], [s, c]])


def kabsch(src, dst):
    """Rotation angle and translation mapping src onto dst (rigid, least squares)."""
    cs, cd = src.mean(0), dst.mean(0)
    h = (src - cs).T @ (dst - cd)
    a = np.arctan2(h[0, 1] - h[1, 0], h[0, 0] + h[1, 1])
    return a, cd - rot(a) @ cs


def fit_motion(v0, v1, v2, d, rates):
    """(c0, k_theta, k_centre) of a rigid part from its vertices at phases 0, d and 2d.

    The part spins at k_theta while the body point c0 moves on a circle about the origin at
    k_centre. Fitted rates are snapped to the train's exact member rates when they match."""
    eq_a, eq_b, ts = [], [], []
    for v, ph in ((v1, d), (v2, 2 * d)):
        a, t = kabsch(v0, v)
        ts.append((a, t, ph))
        # body point p stays on its circle: |R p + t| = |p|  <=>  2 (R^T t) . p = -|t|^2
        eq_a.append(2 * rot(a).T @ t)
        eq_b.append(-t @ t)
    scale = max(np.max(np.abs(v0)), 1e-9)
    if max(np.linalg.norm(t) for _, t, _ in ts) < 1e-12 * scale:
        c0 = np.zeros(2)            # spins about the origin
    else:
        c0 = np.linalg.lstsq(np.array(eq_a), np.array(eq_b), rcond=None)[0]
    a1, t1, _ = ts[0]
    k_theta = a1 / d
    if np.linalg.norm(c0) < 1e-9 * scale:
        c0, k_centre = np.zeros(2), 0.0
    else:
        c1 = rot(a1) @ c0 + t1
        k_centre = (np.arctan2(c1[1], c1[0]) - np.arctan2(c0[1], c0[0]) + np.pi) % (2 * np.pi) - np.pi
        k_centre /= d

    def snap(k):
        for r in list(rates) + [0.0]:
            if abs(k - r) <= 1e-6 * max(1.0, abs(r)):
                return float(r)
        return float(k)
    return c0, snap(k_theta), snap(k_centre)


# ---------------------------------------------------------------------------- scene

_KIN_CACHE = {}


def get_kinematics(spec, cfg):
    key = (spec.name, tuple(cfg))
    if key not in _KIN_CACHE:
        kin = spec.kin_cls(*cfg)
        _ = kin.solve
        _KIN_CACHE[key] = kin
    return _KIN_CACHE[key]


def validate_values(spec, values):
    """Typed, range-checked values; raises BuildError with a readable message."""
    out = {}
    for p in spec.params:
        raw = values.get(p.name, p.default)
        try:
            if p.kind == 'int':
                v = int(round(float(raw)))
            elif p.kind == 'float':
                v = float(raw)
            elif p.kind == 'bool':
                v = bool(raw)
            else:
                v = str(raw)
        except (TypeError, ValueError):
            raise BuildError(f'{p.label.strip()}: "{raw}" is not a valid value')
        if p.kind in ('int', 'float') and not p.lo <= v <= p.hi:
            raise BuildError(f'{p.label.strip()} must be between {p.lo} and {p.hi}')
        if p.kind == 'choice' and v not in p.choices:
            raise BuildError(f'{p.label.strip()} must be one of {", ".join(p.choices)}')
        out[p.name] = v
    return out


class Scene:
    """A built design: kinematics, members/parts with motion, and per-frame transforms."""

    def __init__(self, type_name, values, cfg):
        if type_name not in GEAR_TYPES:
            raise BuildError(f'Unknown gear train "{type_name}"')
        spec = self.spec = GEAR_TYPES[type_name]
        self.values = validate_values(spec, values)
        cfg = self.cfg = tuple(str(c).strip() for c in cfg)
        if len(cfg) != 2 + spec.n_constraints or not all(cfg):
            raise BuildError('Every configuration slot needs a value')
        if cfg[0] == cfg[1]:
            raise BuildError('Input and output must differ')
        try:
            self.kin = get_kinematics(spec, cfg)
        except Exception:
            raise BuildError('This configuration does not determine a unique motion. '
                             'Pick a different input/output/fixed combination.')
        self.gear = spec.build(self.kin, self.values)
        try:
            self.ratios = dict(self.gear.ratios_f)
        except (TypeError, ZeroDivisionError):
            raise BuildError('Degenerate geometry: the ratio is infinite for these tooth counts.')
        if not all(np.isfinite(list(self.ratios.values()))):
            raise BuildError('Degenerate geometry: the ratio is infinite for these tooth counts.')
        self.ratio_in = self.ratios[cfg[0]]
        if self.ratio_in == 0:
            raise BuildError('The input member does not move in this configuration.')
        self.ratio_exact = self.gear.ratio
        self._build_parts()

    # -- construction

    def _comps(self, phase):
        return self.spec.components(self.values, self.gear.arrange(phase))

    def _build_parts(self):
        rates = [abs(r) for r in self.ratios.values()] + [1e-12]
        d = 0.05 / max(rates)
        c0s, c1s, c2s = self._comps(0.0), self._comps(d), self._comps(2 * d)
        signed = list(self.ratios.values())
        self.members, self.parts = [], []
        self._profile_index = []    # (component, profile, loop index arrays) for each part
        for ci, (comp, comp1, comp2) in enumerate(zip(c0s, c1s, c2s)):
            member = Member(comp.label, comp.dof, comp.ring, comp.layer, comp.span)
            for pi, (prof, p1, p2) in enumerate(zip(comp.profiles, comp1.profiles, comp2.profiles)):
                info = analyse_profile(prof, comp.ring)
                if info is None:
                    continue
                idx_loops, solid, parent, ring_radius = info
                c0, kt, kc = fit_motion(prof.vertices, p1.vertices, p2.vertices, d, signed)
                body = [prof.vertices[l] - c0 for l in idx_loops]
                radius = max(float(np.max(np.linalg.norm(b, axis=1))) for b in body)
                part = Part(len(self.members), body, solid, parent, ring_radius, c0, kt, kc, radius)
                self._profile_index.append((ci, pi, idx_loops))
                member.parts.append(part)
                self.parts.append(part)
            if member.parts:
                self.members.append(member)
        if not self.parts:
            raise BuildError('This design produced no geometry.')
        self.extent = max(max(np.linalg.norm(p.c0) + p.radius, p.ring_radius or 0) for p in self.parts)
        self.motion_exact = self._validate_motion(max(rates))

    def _validate_motion(self, max_rate):
        tol = 1e-6 * self.extent
        for phase in np.array([0.37, -2.13, 7.71, 63.1]) / max_rate:
            comps = self._comps(phase)
            for part, (ci, pi, idx_loops) in zip(self.parts, self._profile_index):
                world = comps[ci].profiles[pi].vertices
                a, x, y = self._analytic(part, phase)
                R = rot(a)
                for body, l in zip(part.loops, idx_loops):
                    pred = body @ R.T + (x, y)
                    if np.max(np.abs(pred - world[l])) > tol:
                        return False
        return True

    # -- per frame

    @staticmethod
    def _analytic(part, phase):
        c = rot(part.k_centre * phase) @ part.c0
        return part.k_theta * phase, c[0], c[1]

    def transforms(self, phase):
        """(angle, x, y) per part: body frame -> world at this phase (output radians)."""
        if self.motion_exact:
            return [self._analytic(p, phase) for p in self.parts]
        # fallback: ask pygeartrain and fit each part (always correct, slower)
        comps = self._comps(phase)
        out = []
        for part, (ci, pi, idx_loops) in zip(self.parts, self._profile_index):
            world = comps[ci].profiles[pi].vertices[np.concatenate(idx_loops)]
            body = np.concatenate(part.loops)
            a, t = kabsch(body, world)
            out.append((a, t[0], t[1]))
        return out

    def phase_for_input(self, input_angle):
        return input_angle / self.ratio_in

    def world_loops(self, part, transform):
        a, x, y = transform
        R = rot(a)
        return [b @ R.T + (x, y) for b in part.loops]

    # -- derived information

    def role(self, dof):
        if dof == self.cfg[0]:
            return 'input'
        if dof == self.cfg[1]:
            return 'output'
        if abs(self.ratios.get(dof, 1.0)) < 1e-12:
            return 'fixed'
        return 'free'

    def speed_per_input(self, dof):
        return self.ratios[dof] / self.ratio_in

    def issues(self):
        return list(self.spec.issues(self.values)) + self._overlap_issues()

    def _overlap_issues(self):
        """Copies of an orbiting member (planets, cranks) that collide with each other."""
        out = []
        for m in self.members:
            orbiting = [p for p in m.parts if np.linalg.norm(p.c0) > 1e-9]
            if len(orbiting) < 2:
                continue
            polys = [shapely.make_valid(Polygon(p.loops[0] + p.c0)) for p in orbiting]
            hit = any(polys[i].intersection(polys[(i + 1) % len(polys)]).area > 1e-6 * self.extent ** 2
                      for i in range(len(polys)))
            if hit and 'N' in self.values:
                p = orbiting[0]
                rc, r = float(np.linalg.norm(p.c0)), p.radius
                fits = [n for n in range(1, len(orbiting)) if n == 1 or 2 * rc * np.sin(np.pi / n) > 2 * r]
                ok = [n for n in fits if not self.spec.issues({**self.values, 'N': n})]
                best = max(ok) if ok else (max(fits) if fits else None)
                out.append(Issue(f'{m.label}: neighbouring copies overlap. Use fewer of them.',
                                 {'N': best} if best else None, f'Use N = {best}' if best else None))
        return out

    def ref_circles(self):
        """Pitch circles (involute types) or the reference pin circle, for the 2D overlay.

        Returns [(part index or None, radius in units)]: part circles follow that part."""
        sz = self.spec.sizing
        v = self.values
        out = []
        if sz.kind == 'involute':
            factors = sz.stage_factors(v)
            k = sz.unit_k(v)
            for g in sz.gears(v):
                radius = factors[g.stage] * g.z / (2 * k)
                for i, p in enumerate(self.parts):
                    if self.members[p.member].label == g.member:
                        out.append((i, radius))
        else:
            out.append((None, float(sz.ref_radius(v))))
        return out
