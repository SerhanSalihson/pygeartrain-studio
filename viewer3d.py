"""3D viewer: pygeartrain profiles extruded into plates and drawn with matplotlib's mplot3d.

Each member's mesh topology (cap triangulation, side walls) is built once from its 2D
loops; per frame only the moving 2D vertices are lifted into 3D, back faces culled and
the faces shaded, so the whole train is a single depth-sorted Poly3DCollection.
"""
import time
from collections import namedtuple

import numpy as np
import shapely
from shapely.geometry import Polygon
import tkinter as tk
from tkinter import ttk, filedialog

import matplotlib.colors as mcolors
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  registers the '3d' projection
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

DETAIL = {'Low': 60, 'Medium': 120, 'High': 240}   # max vertices per profile loop
VIEWS = {'Iso': (32, -60), 'Top': (89.9, -90), 'Side': (4, -90)}

Member = namedtuple('Member', 'mesh color layer span ring index')


def _decimate(loop, max_pts):
    step = int(np.ceil(len(loop) / max_pts))
    return loop[::step] if step > 1 else loop


class ExtrudedMesh:
    """Plate topology for one member. `shape` comes from the 2D loop analysis:
    loops are oriented (solids CCW, holes CW), `parent[i]` is the enclosing solid
    loop of a hole (-1 = top level) and `circle` is the outer body of a ring gear."""

    def __init__(self, shape, profiles, max_pts, max_edge):
        self.ring = shape.circle is not None
        loops = [_decimate(l, max_pts) for l in shape.loops]
        self.U = np.concatenate(loops)
        if self.ring:
            t = np.linspace(0, 2 * np.pi, 97)[:-1]
            self.circle = np.c_[np.cos(t), np.sin(t)] * np.linalg.norm(shape.circle[0])
        else:
            self.circle = np.zeros((0, 2))
        nc = len(self.circle)
        starts = nc + np.cumsum([0] + [len(l) for l in loops[:-1]])
        local = ([np.arange(nc)] if self.ring else []) + [np.arange(s, s + len(l)) for s, l in zip(starts, loops)]
        solid = ([True] if self.ring else []) + list(shape.solid)
        if self.ring:
            parent = [-1] + [0 if p < 0 else p + 1 for p in shape.parent]
        else:
            parent = list(shape.parent)

        self.edges = np.concatenate([np.c_[L, np.roll(L, -1)] for L in local])
        self.mid_levels = []

        P0 = self.points(profiles)
        key = {tuple(np.round(p, 9)): i for i, p in enumerate(P0)}
        tris = []
        for k, (L, s) in enumerate(zip(local, solid)):
            if not s:
                continue
            holes = [P0[local[j]] for j in range(len(local)) if parent[j] == k and not solid[j]]
            poly = Polygon(P0[L], holes)
            if not poly.is_valid:
                poly = shapely.make_valid(poly)
            for t in shapely.get_parts(shapely.constrained_delaunay_triangles(poly)):
                idx = [key.get(tuple(np.round(c, 9))) for c in np.asarray(t.exterior.coords)[:3]]
                if None not in idx:
                    tris.append(idx)
        self._refine(tris, P0, max_edge)

    def _refine(self, tris, P0, max_edge):
        """Bisect long cap triangles. The painter's sort uses face centroids, so one huge
        triangle can wrongly cover a gear standing on it; small triangles sort reliably.
        New points are edge midpoints, so they stay rigidly attached to their member."""
        pts = list(P0)
        level = [0] * len(P0)
        mids = {}               # (a, b) -> index of their midpoint
        out, stack = [], list(tris)
        while stack:
            a, b, c = stack.pop()
            edges = [(a, b, c), (b, c, a), (c, a, b)]
            lengths = [np.linalg.norm(pts[i] - pts[j]) for i, j, _ in edges]
            k = int(np.argmax(lengths))
            if lengths[k] <= max_edge:
                out.append((a, b, c))
                continue
            i, j, o = edges[k]
            key = (min(i, j), max(i, j))
            if key not in mids:
                mids[key] = len(pts)
                pts.append((pts[i] + pts[j]) / 2)
                level.append(max(level[i], level[j]) + 1)
            m = mids[key]
            stack += [(i, m, o), (m, j, o)]
        self.tris = np.array(out, dtype=int).reshape(-1, 3)
        # evaluate midpoints level by level so each one's parents already exist
        self.n_base = len(P0)
        by_level = {}
        for (i, j), m in mids.items():
            by_level.setdefault(level[m], []).append((m, i, j))
        self.mid_levels = [np.array(sorted(by_level[l]), dtype=int).reshape(-1, 3) for l in sorted(by_level)]
        self.n_total = len(pts)

    def points(self, profiles):
        allv = np.concatenate([p.vertices for p in profiles])
        base = np.concatenate([self.circle, allv[self.U]])
        if not self.mid_levels:
            return base
        P = np.empty((self.n_total, 2))
        P[:self.n_base] = base
        for lv in self.mid_levels:
            P[lv[:, 0]] = (P[lv[:, 1]] + P[lv[:, 2]]) / 2
        return P

    def faces(self, P, z0, z1, view, bottom):
        """Quads (triangles repeat their last vertex) and unit normals for the visible faces."""
        polys, normals = [], []
        T = self.tris
        caps = [(z1, 1.0)] + ([(z0, -1.0)] if bottom else [])
        for z, nz in caps:
            if len(T):
                v = np.concatenate([P[T], np.full(T.shape + (1,), z)], axis=2)
                polys.append(np.concatenate([v, v[:, -1:]], axis=1))
                normals.append(np.tile([0.0, 0.0, nz], (len(T), 1)))
        a, b = P[self.edges[:, 0]], P[self.edges[:, 1]]
        d = b - a
        n = np.c_[d[:, 1], -d[:, 0], np.zeros(len(d))]
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        keep = n @ view > 0
        a, b, n = a[keep], b[keep], n[keep]
        za, zb = np.full((len(a), 1), z0), np.full((len(a), 1), z1)
        polys.append(np.stack([np.c_[a, za], np.c_[b, za], np.c_[b, zb], np.c_[a, zb]], axis=1))
        normals.append(n)
        return np.concatenate(polys), np.concatenate(normals)


class Gear3DView(ttk.Frame):
    def __init__(self, master, on_status=lambda msg: None):
        super().__init__(master)
        self.on_status = on_status
        self.members = []
        self.profiles = []
        self.shapes = []
        self.extent = 1.0
        self.zoom = 1.4
        self._last_motion = 0.0

        self.fig = Figure(figsize=(8, 7), dpi=100)
        self.ax = self.fig.add_axes([0, 0, 1, 1], projection='3d')
        self.ax.set_proj_type('ortho')
        self.ax.set_axis_off()
        self.ax.view_init(*VIEWS['Iso'])
        # one collection per plate layer, stacked in draw order by hand (see redraw)
        self.ax.computed_zorder = False
        self.layer_colls = {}
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill='both', expand=True)
        self.canvas.mpl_connect('motion_notify_event', self._on_motion)
        self.canvas.mpl_connect('button_release_event', lambda e: self.redraw())
        self.canvas.mpl_connect('scroll_event', self._on_scroll)

        bar = ttk.Frame(self, padding=(6, 6))
        bar.pack(fill='x')
        self.thick_var = tk.DoubleVar(value=0.16)
        self.explode_var = tk.DoubleVar(value=0.0)
        self.detail_var = tk.StringVar(value='Medium')
        self.xray_var = tk.BooleanVar(value=True)
        ttk.Label(bar, text='Thickness').pack(side='left')
        ttk.Scale(bar, from_=0.03, to=0.5, variable=self.thick_var, length=110,
                  command=lambda e: self._relayout()).pack(side='left', padx=(2, 10))
        ttk.Label(bar, text='Explode').pack(side='left')
        ttk.Scale(bar, from_=0.0, to=4.0, variable=self.explode_var, length=110,
                  command=lambda e: self._relayout()).pack(side='left', padx=(2, 10))
        ttk.Label(bar, text='Detail').pack(side='left')
        cb = ttk.Combobox(bar, textvariable=self.detail_var, values=list(DETAIL), state='readonly', width=8)
        cb.pack(side='left', padx=(2, 10))
        cb.bind('<<ComboboxSelected>>', lambda e: self._rebuild_meshes())
        ttk.Checkbutton(bar, text='X-ray rings', variable=self.xray_var, command=self.redraw).pack(side='left')
        ttk.Button(bar, text='Save PNG', command=self.save_png).pack(side='right', padx=2)
        for name in reversed(list(VIEWS)):
            ttk.Button(bar, text=name, width=5, command=lambda n=name: self.set_view(n)).pack(side='right', padx=2)
        ttk.Label(bar, text='Drag to rotate · scroll to zoom', style='Muted.TLabel').pack(side='right', padx=8)

    # ---------------- scene ----------------

    def set_scene(self, items, extent):
        """items: list of (shape, profiles, color, layer, span, ring)."""
        self.shapes = [(s, c, l, sp, r) for s, _, c, l, sp, r in items]
        self.profiles = [p for _, p, *_ in items]
        self.extent = extent
        self._rebuild_meshes(redraw=False)
        self._relayout(redraw=False)

    def _rebuild_meshes(self, redraw=True):
        t0 = time.perf_counter()
        max_pts = DETAIL[self.detail_var.get()]
        self.members = []
        for i, ((shape, color, layer, span, ring), prof) in enumerate(zip(self.shapes, self.profiles)):
            try:
                mesh = ExtrudedMesh(shape, prof, max_pts, 0.3 * self.extent)
            except Exception as e:      # a member that cannot be meshed is skipped, not fatal
                self.on_status(f'3D: skipped a member ({e})')
                continue
            self.members.append(Member(mesh, color, layer, span, ring, i))
        self.build_ms = 1000 * (time.perf_counter() - t0)
        if redraw:
            self.redraw()

    def set_colors(self, colors):
        self.members = [m._replace(color=colors[m.index]) for m in self.members]
        self.shapes = [(s, c, l, sp, r) for (s, _, l, sp, r), c in zip(self.shapes, colors)]

    def update_profiles(self, profiles):
        self.profiles = profiles

    def _layer_z(self, layer, span):
        h = self.thick_var.get() * self.extent
        gap = self.explode_var.get() * h
        z0 = layer * (h + gap)
        return z0, z0 + span * h + (span - 1) * gap

    def _relayout(self, redraw=True):
        if not self.shapes:
            return
        zs = [z for _, _, l, sp, _ in self.shapes for z in self._layer_z(l, sp)]
        lo, hi = min(zs), max(zs)
        lim = self.extent
        self.ax.set_xlim(-lim, lim)
        self.ax.set_ylim(-lim, lim)
        self.ax.set_zlim(lo, hi)
        self.ax.set_box_aspect((2 * lim, 2 * lim, max(hi - lo, 1e-6)), zoom=self.zoom)
        if redraw:
            self.redraw()

    # ---------------- drawing ----------------

    def redraw(self):
        if not self.members:
            return
        elev, azim = np.radians(self.ax.elev), np.radians(self.ax.azim)
        view = np.array([np.cos(elev) * np.cos(azim), np.cos(elev) * np.sin(azim), np.sin(elev)])
        light = view + np.array([0.3, 0.2, 0.9])
        light /= np.linalg.norm(light)
        xray = self.xray_var.get()
        groups = {}
        for m in self.members:
            z0, z1 = self._layer_z(m.layer, m.span)
            V, N = m.mesh.faces(m.mesh.points(self.profiles[m.index]), z0, z1, view, elev < 0)
            shade = 0.42 + 0.58 * np.clip(N @ light, 0, 1)
            rgb = np.asarray(mcolors.to_rgb(m.color))
            c = np.empty((len(V), 4))
            c[:, :3] = np.clip(rgb[None] * shade[:, None], 0, 1)
            c[:, 3] = 0.32 if (m.ring and xray) else 1.0
            g = groups.setdefault(m.layer, ([], []))
            g[0].append(V)
            g[1].append(c)
        # Seen from above, nothing in a lower plate can hide anything in a higher one, so plates
        # are drawn bottom-up (top-down from below) and only sorted by depth within a plate.
        # That avoids the painter's-algorithm errors of one global centroid sort.
        order = sorted(set(groups) | set(self.layer_colls), reverse=elev < 0)
        for rank, layer in enumerate(order):
            coll = self.layer_colls.get(layer)
            if coll is None:
                # no antialiasing: adjacent faces then meet without hairline seams
                coll = Poly3DCollection(np.zeros((0, 4, 3)), linewidths=0.6, antialiaseds=False)
                self.ax.add_collection3d(coll)
                self.layer_colls[layer] = coll
            coll.set_zorder(rank + 1)
            if layer not in groups:
                coll.set_verts(np.zeros((0, 4, 3)))
                continue
            cols = np.concatenate(groups[layer][1])
            edges = cols.copy()
            edges[edges[:, 3] < 1, 3] = 0       # translucent faces get no outline
            coll.set_verts(np.concatenate(groups[layer][0]))
            coll.set_facecolor(cols)
            coll.set_edgecolor(edges)
        self.canvas.draw_idle()

    def set_view(self, name):
        self.ax.view_init(*VIEWS[name])
        self.redraw()

    def _on_motion(self, ev):
        # mplot3d rotates the camera itself; re-cull and re-shade for the new angle, throttled
        if ev.button and ev.inaxes is self.ax and time.perf_counter() - self._last_motion > 0.06:
            self._last_motion = time.perf_counter()
            self.redraw()

    def _on_scroll(self, ev):
        self.zoom = float(np.clip(self.zoom * (1.12 if ev.button == 'up' else 1 / 1.12), 0.3, 6))
        self._relayout()

    def apply_theme(self, t):
        self.fig.set_facecolor(t['fig'])
        self.ax.set_facecolor(t['fig'])
        self.canvas.draw_idle()

    def save_png(self):
        fn = filedialog.asksaveasfilename(defaultextension='.png', filetypes=[('PNG image', '*.png')],
                                          initialfile='gear_train_3d.png')
        if fn:
            self.fig.savefig(fn, dpi=150, facecolor=self.fig.get_facecolor())
            self.on_status(f'Saved {fn}')
