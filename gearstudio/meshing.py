"""Extrude a part's 2D loops into a closed plate mesh (unit thickness, z from 0 to 1).

Caps come from a constrained Delaunay triangulation of the loops (holes respected); side walls
follow the same loop vertices, so the mesh is watertight. Curved walls get smooth normals,
sharp corners (crease > 40 degrees) keep hard edges.
"""
import numpy as np
import shapely
from shapely.geometry import Polygon

CREASE_COS = np.cos(np.radians(40))


def decimate(loop, max_pts):
    """Thin a loop to at most max_pts vertices and drop repeated vertices (zero-length edges)."""
    if max_pts and len(loop) > max_pts:
        loop = loop[::int(np.ceil(len(loop) / max_pts))]
    step = np.linalg.norm(np.roll(loop, -1, axis=0) - loop, axis=1)
    return loop[step > 1e-9 * (np.abs(loop).max() + 1e-12)]


def ring_circle(radius, n=144):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.c_[np.cos(t), np.sin(t)] * radius


def _separate_touching_holes(loops, solid, parent):
    """Shrink holes that touch their outline (e.g. an eccentric's bore tangent to its rim).

    A touching hole makes the polygon invalid and the triangulation would add vertices the side
    walls do not have; shrinking the hole a little keeps caps and walls matching."""
    loops = list(loops)
    for k, s in enumerate(solid):
        if not s:
            continue
        kids = [j for j in range(len(loops)) if parent[j] == k and not solid[j]]
        for factor in (0.97, 0.93, 0.85):
            if Polygon(loops[k], [loops[j] for j in kids]).is_valid:
                break
            for j in kids:
                c = loops[j].mean(axis=0)
                if not Polygon(loops[k], [loops[j]]).is_valid:
                    loops[j] = c + (loops[j] - c) * factor
    return loops


def _cap_triangles(loops, solid, parent):
    """Triangles (as rows of 3 points) covering the solid regions, CCW seen from +z."""
    tris = []
    for k, s in enumerate(solid):
        if not s:
            continue
        holes = [loops[j] for j in range(len(loops)) if parent[j] == k and not solid[j]]
        poly = Polygon(loops[k], holes)
        if not poly.is_valid:
            poly = shapely.make_valid(poly)
        for t in shapely.get_parts(shapely.constrained_delaunay_triangles(poly)):
            c = np.asarray(t.exterior.coords)[:3]
            area = (c[1, 0] - c[0, 0]) * (c[2, 1] - c[0, 1]) - (c[2, 0] - c[0, 0]) * (c[1, 1] - c[0, 1])
            if abs(area) < 1e-14:
                continue
            tris.append(c if area > 0 else c[::-1])
    return np.array(tris).reshape(-1, 3, 2)


def extrude(part, max_pts=None):
    """Triangles (T, 3, 3) and per-vertex normals (T, 3, 3) of the part's plate, z in [0, 1].

    Coordinates are in the part's body frame; winding is CCW seen from outside."""
    loops = [decimate(l, max_pts) for l in part.loops]
    solid, parent = list(part.solid), list(part.parent)
    if part.ring_radius:
        # the ring body: outer circle is the top-level solid, toothed loops are its holes
        loops = [ring_circle(part.ring_radius)] + loops
        solid = [True] + solid
        parent = [-1] + [0 if p < 0 else p + 1 for p in parent]

    loops = _separate_touching_holes(loops, solid, parent)
    cap = _cap_triangles(loops, solid, parent)
    T = len(cap)
    top = np.concatenate([cap, np.ones((T, 3, 1))], axis=2)
    bottom = np.concatenate([cap[:, ::-1], np.zeros((T, 3, 1))], axis=2)
    tris = [top, bottom]
    norms = [np.tile([0.0, 0.0, 1.0], (T, 3, 1)), np.tile([0.0, 0.0, -1.0], (T, 3, 1))]

    for loop in loops:
        a = loop
        b = np.roll(loop, -1, axis=0)
        d = b - a
        n = np.c_[d[:, 1], -d[:, 0]]
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-15
        # vertex normals: average with the neighbouring edge unless the corner is sharp
        n_prev = np.roll(n, 1, axis=0)
        n_next = np.roll(n, -1, axis=0)
        smooth_start = np.sum(n * n_prev, axis=1) > CREASE_COS
        smooth_end = np.sum(n * n_next, axis=1) > CREASE_COS
        na = np.where(smooth_start[:, None], n + n_prev, n)
        nb = np.where(smooth_end[:, None], n + n_next, n)
        na /= np.linalg.norm(na, axis=1, keepdims=True) + 1e-15
        nb /= np.linalg.norm(nb, axis=1, keepdims=True) + 1e-15
        z0, z1 = np.zeros((len(a), 1)), np.ones((len(a), 1))
        a0, b0, a1, b1 = np.c_[a, z0], np.c_[b, z0], np.c_[a, z1], np.c_[b, z1]
        na3, nb3 = np.c_[na, z0], np.c_[nb, z0]
        tris += [np.stack([a0, b0, b1], 1), np.stack([a0, b1, a1], 1)]
        norms += [np.stack([na3, nb3, nb3], 1), np.stack([na3, nb3, na3], 1)]
    return np.concatenate(tris), np.concatenate(norms)


def vertex_buffer(tris, normals):
    """Interleaved float32 position+normal buffer for the GPU."""
    return np.concatenate([tris.reshape(-1, 3), normals.reshape(-1, 3)], axis=1).astype(np.float32)


def is_closed(tris, decimals=7):
    """True if every edge is shared by exactly two triangles in opposite directions."""
    v = np.round(tris, decimals)
    edges = {}
    for t in v:
        for i in range(3):
            a, b = tuple(t[i]), tuple(t[(i + 1) % 3])
            edges[(a, b)] = edges.get((a, b), 0) + 1
    return all(edges.get((b, a), 0) == c for (a, b), c in edges.items())
