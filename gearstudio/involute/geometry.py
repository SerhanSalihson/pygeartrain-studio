"""Involute tooth geometry: the one implementation used by Gear Studio and actgen.

Ported from actgen (itself a 1:1 port of the P10 Inventor library, tools/lib.ps1) and verified to
1e-6 against the built P10 actuator. Conventions:
  * external gear: a tooth is centred on angle 0 (+X); ext_space() is ONE tooth space centred on
    pi/z, cut from the root circle out to r_out (beyond the tip);
  * internal gear (ring): a tooth SPACE is centred on angle 0 (+X); int_space() is that space, from
    r_in (inside the tip bore) out to the root.
All lengths in mm, angles in radians unless the name says _deg.
"""
from __future__ import annotations

import math

import numpy as np


def inv(a: float) -> float:
    """Involute function inv(a) = tan(a) - a."""
    return math.tan(a) - a


def undercut_shift(z: int, alpha: float) -> float:
    """Smallest profile shift that avoids undercut when a rack cutter (hob) cuts z teeth."""
    return max(0.0, 1 - z * math.sin(alpha) ** 2 / 2)


def half_angle(thk: float, rp: float, rb: float, alpha: float, rho: float) -> float:
    """Half the angular thickness of a tooth (external) or space (internal) at radius rho;
    clamped at the base circle."""
    rr = max(rho, rb)
    return thk / (2 * rp) + inv(alpha) - inv(math.acos(rb / rr))


def thickness(m: float, alpha: float, x: float, backlash: float = 0.0) -> float:
    """Circular tooth thickness on the pitch circle, thinned by `backlash`."""
    return m * (math.pi / 2 + 2 * x * math.tan(alpha)) - backlash


def ring_space(m: float, alpha: float, x_ring: float, backlash: float = 0.0) -> float:
    """Circular space width of a ring on the pitch circle, widened by `backlash`."""
    return m * (math.pi / 2 + 2 * x_ring * math.tan(alpha)) + backlash


def ext_space(z: int, m: float, alpha: float, s: float, r_root: float, r_tip: float, r_out: float) -> np.ndarray:
    """One external tooth space as a closed (N, 2) polyline."""
    rp = m * z / 2
    rb = rp * math.cos(alpha)
    pitch = 2 * math.pi / z
    n = 14
    rs = [r_root + (r_tip - r_root) * i / n for i in range(n + 1)]
    pts = []
    for rho in rs:
        t = half_angle(s, rp, rb, alpha, rho)
        pts.append((rho * math.cos(t), rho * math.sin(t)))
    t_tip = half_angle(s, rp, rb, alpha, r_tip)
    pts.append((r_out * math.cos(t_tip), r_out * math.sin(t_tip)))
    for k in range(1, 6):
        t = t_tip + (pitch - 2 * t_tip) * k / 6
        pts.append((r_out * math.cos(t), r_out * math.sin(t)))
    pts.append((r_out * math.cos(pitch - t_tip), r_out * math.sin(pitch - t_tip)))
    for rho in reversed(rs):
        t = pitch - half_angle(s, rp, rb, alpha, rho)
        pts.append((rho * math.cos(t), rho * math.sin(t)))
    t_r = half_angle(s, rp, rb, alpha, r_root)
    for k in range(5, 0, -1):
        t = t_r + (pitch - 2 * t_r) * k / 6
        pts.append((r_root * math.cos(t), r_root * math.sin(t)))
    return np.array(pts)


def int_space(z: int, m: float, alpha: float, e: float, r_in: float, r_tip: float, r_root: float) -> np.ndarray:
    """One internal (ring) tooth space as a closed (N, 2) polyline."""
    rp = m * z / 2
    rb = rp * math.cos(alpha)
    n = 14
    rs = [r_tip + (r_root - r_tip) * i / n for i in range(n + 1)]
    t_in = half_angle(e, rp, rb, alpha, r_tip)
    pts = [(r_in * math.cos(-t_in), r_in * math.sin(-t_in))]
    for rho in rs:
        t = -half_angle(e, rp, rb, alpha, rho)
        pts.append((rho * math.cos(t), rho * math.sin(t)))
    t_r = half_angle(e, rp, rb, alpha, r_root)
    for k in range(1, 4):
        t = -t_r + 2 * t_r * k / 4
        pts.append((r_root * math.cos(t), r_root * math.sin(t)))
    for rho in reversed(rs):
        t = half_angle(e, rp, rb, alpha, rho)
        pts.append((rho * math.cos(t), rho * math.sin(t)))
    pts.append((r_in * math.cos(t_in), r_in * math.sin(t_in)))
    return np.array(pts)


def tooth_chord(z: int, m: float, alpha: float, s: float, rho: float) -> float:
    """Chordal tooth thickness of an external gear at radius rho (mm)."""
    rp = m * z / 2
    rb = rp * math.cos(alpha)
    return 2 * rho * math.sin(half_angle(s, rp, rb, alpha, rho))


def top_tip_for_land(z: int, m: float, alpha: float, s: float, r_tip_full: float, land_min: float,
                     step: float = 0.05) -> float:
    """Largest tip radius (rounded down to `step`) at which the tooth tip land is still >= land_min."""
    r = r_tip_full
    if tooth_chord(z, m, alpha, s, r) >= land_min:
        return r_tip_full
    r = math.floor(r_tip_full / step) * step
    while r > m * z / 2 and tooth_chord(z, m, alpha, s, r) < land_min:
        r = round(r - step, 6)
    return r


# ---------------------------------------------------------------- exact outlines (for drawing and CAD)

def _flank(z, m, alpha, s, r0, r1, n):
    rp = m * z / 2
    rb = rp * math.cos(alpha)
    rs = np.linspace(r0, r1, n)
    return rs, np.array([half_angle(s, rp, rb, alpha, r) for r in rs])


def external_outline(z: int, m: float, alpha: float, s: float, r_root: float, r_tip: float, rot: float = 0.0,
                     flank_pts: int = 16, arc_pts: int = 6) -> np.ndarray:
    """Closed CCW outline of a whole external gear in mm, tooth 0 centred on +X (then turned by rot rad)."""
    pitch = 2 * math.pi / z
    rs, half = _flank(z, m, alpha, s, r_root, r_tip, flank_pts)
    pts = []
    for k in range(z):
        c = k * pitch
        # root arc from the previous tooth's flank to this tooth's rising flank
        a0, a1 = c - pitch + half[0], c - half[0]
        for t in np.linspace(a0, a1, arc_pts + 2)[1:-1]:
            pts.append((r_root * math.cos(t), r_root * math.sin(t)))
        for r, h in zip(rs, half):                       # rising flank (clockwise side)
            pts.append((r * math.cos(c - h), r * math.sin(c - h)))
        for t in np.linspace(c - half[-1], c + half[-1], arc_pts + 2)[1:-1]:
            pts.append((r_tip * math.cos(t), r_tip * math.sin(t)))
        for r, h in zip(rs[::-1], half[::-1]):           # falling flank
            pts.append((r * math.cos(c + h), r * math.sin(c + h)))
    p = np.array(pts)
    if rot:
        cr, sr = math.cos(rot), math.sin(rot)
        p = p @ np.array([[cr, sr], [-sr, cr]])
    return p


def internal_outline(z: int, m: float, alpha: float, e: float, r_tip: float, r_root: float, rot: float = 0.0,
                     flank_pts: int = 16, arc_pts: int = 6) -> np.ndarray:
    """Closed outline of a ring's toothed bore in mm, tooth space 0 centred on +X (then turned by rot rad).

    Returned CW, i.e. ready to be a hole in the ring body."""
    pitch = 2 * math.pi / z
    rs, half = _flank(z, m, alpha, e, r_tip, r_root, flank_pts)      # half-angle of the SPACE
    pts = []
    for k in range(z):
        c = k * pitch
        for r, h in zip(rs, half):                       # space side going out to the root
            pts.append((r * math.cos(c - h), r * math.sin(c - h)))
        for t in np.linspace(c - half[-1], c + half[-1], arc_pts + 2)[1:-1]:
            pts.append((r_root * math.cos(t), r_root * math.sin(t)))
        for r, h in zip(rs[::-1], half[::-1]):           # back in to the tip
            pts.append((r * math.cos(c + h), r * math.sin(c + h)))
        for t in np.linspace(c + half[0], c + pitch - half[0], arc_pts + 2)[1:-1]:   # tooth tip land
            pts.append((r_tip * math.cos(t), r_tip * math.sin(t)))
    p = np.array(pts)[::-1]
    if rot:
        cr, sr = math.cos(rot), math.sin(rot)
        p = p @ np.array([[cr, sr], [-sr, cr]])
    return p


# ---------------------------------------------------------------- shapely polygons (for mesh checks)

def gear_polygon_external(z: int, m: float, alpha: float, s: float, r_root: float, r_tip: float, rot: float = 0.0):
    """Shapely polygon of the whole external gear (tip disc minus z spaces), rotated by `rot` (rad)."""
    from shapely import affinity
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union
    sp = Polygon(ext_space(z, m, alpha, s, r_root, r_tip, r_tip + 0.6))
    spaces = [affinity.rotate(sp, k * 2 * math.pi / z, origin=(0, 0), use_radians=True) for k in range(z)]
    g = Point(0, 0).buffer(r_tip, 256).difference(unary_union(spaces))
    return affinity.rotate(g, rot, origin=(0, 0), use_radians=True) if rot else g


def gear_polygon_internal(z: int, m: float, alpha: float, e: float, r_tip: float, r_root: float, rot: float = 0.0,
                          rim: float = 3.0):
    """Shapely polygon of the ring (annulus tip..root+rim minus z spaces), rotated by `rot` (rad)."""
    from shapely import affinity
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union
    sp = Polygon(int_space(z, m, alpha, e, r_tip - 0.5, r_tip, r_root))
    spaces = [affinity.rotate(sp, k * 2 * math.pi / z, origin=(0, 0), use_radians=True) for k in range(z)]
    ring = Point(0, 0).buffer(r_root + rim, 512).difference(Point(0, 0).buffer(r_tip, 512)).difference(
        unary_union(spaces))
    return affinity.rotate(ring, rot, origin=(0, 0), use_radians=True) if rot else ring
