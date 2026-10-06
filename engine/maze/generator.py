"""
Python port of the carrymaze/1 generator (maze.html), plus a converter that turns
a cell-grid perfect maze into PAW arena geometry (wall segments in metres).

The PRNG and carve() are ported bit-for-bit so a given seed produces the SAME
maze in the browser game and in PAW.
"""
from collections import deque
import math

N, E, S, W = 1, 2, 4, 8
DX = {N: 0, E: 1, S: 0, W: -1}
DY = {N: -1, E: 0, S: 1, W: 0}
OPP = {N: S, E: W, S: N, W: E}
M32 = 0xFFFFFFFF


def _sra(u, n):
    """JS `>>` is a SIGNED shift on the int32 reinterpretation of the value.
    Once the state exceeds 2**31 an arithmetic shift differs from a logical
    one, so this must be emulated exactly or the seeds stop agreeing."""
    i = u - (1 << 32) if u >= (1 << 31) else u
    return (i >> n) & M32


def rng(seed):
    s = [(seed & M32) or 1]

    def nxt():
        v = s[0]
        v = (v ^ ((v << 13) & M32)) & M32
        v = (v ^ _sra(v, 17)) & M32
        v = (v ^ ((v << 5) & M32)) & M32
        s[0] = v
        return v / 4294967296.0
    return nxt


def carve(w, h, rand):
    """Randomised depth-first (recursive backtracker) -> PERFECT maze."""
    open_ = [0] * (w * h)
    seen = [False] * (w * h)
    stack = [(0, 0)]
    seen[0] = True
    while stack:
        cx, cy = stack[-1]
        opts = []
        for d in (N, E, S, W):
            nx, ny = cx + DX[d], cy + DY[d]
            if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx]:
                opts.append(d)
        if not opts:
            stack.pop()
            continue
        d = opts[int(rand() * len(opts))]
        nx2, ny2 = cx + DX[d], cy + DY[d]
        open_[cy * w + cx] |= d
        open_[ny2 * w + nx2] |= OPP[d]
        seen[ny2 * w + nx2] = True
        stack.append((nx2, ny2))
    return open_


def bfs(w, h, open_, sx, sy):
    dist = [-1] * (w * h)
    prev = [-1] * (w * h)
    q = deque([sy * w + sx])
    dist[sy * w + sx] = 0
    order = []
    while q:
        c = q.popleft()
        order.append(c)
        cx, cy = c % w, c // w
        for d in (N, E, S, W):
            if not (open_[c] & d):
                continue
            nx, ny = cx + DX[d], cy + DY[d]
            n = ny * w + nx
            if dist[n] != -1:
                continue
            dist[n] = dist[c] + 1
            prev[n] = c
            q.append(n)
    return dist, prev, order


def validate_perfect(w, h, open_):
    """The same two invariants the JS validator enforces."""
    problems = []
    for y in range(h):
        for x in range(w):
            for d in (N, E, S, W):
                nx, ny = x + DX[d], y + DY[d]
                inside = 0 <= nx < w and 0 <= ny < h
                here = bool(open_[y * w + x] & d)
                if not inside and here:
                    problems.append(f"opening off grid at {x},{y}")
                if inside and here != bool(open_[ny * w + nx] & OPP[d]):
                    problems.append(f"walls disagree {x},{y}<->{nx},{ny}")
    dist, _, order = bfs(w, h, open_, 0, 0)
    if len(order) != w * h:
        problems.append("not fully connected")
    edges = sum(bin(m).count("1") for m in open_)
    if edges // 2 != w * h - 1:
        problems.append(f"has loops ({edges // 2} edges)")
    return problems


# ── cell grid -> PAW arena geometry ──────────────────────────────────────────

def to_arena(w, h, open_, corridor, thickness, spawn, exit_cell,
             light_radius=0.4, light_intensity=1.4, heading=90.0):
    """Emit a PAW arena dict. Cell (0,0) is the maze's TOP-LEFT (JS convention,
    y grows downward); PAW's y grows upward, so rows are flipped on the way out.

    Arena span uses the boundary in place of the outermost walls, so every
    corridor — including the outer ones — is exactly `corridor` metres wide.
    """
    pitch = corridor + thickness
    span_x = w * corridor + (w - 1) * thickness
    span_y = h * corridor + (h - 1) * thickness

    def X(k):   # x of grid line k (k=0..w), lines 0 and w are the boundary
        return -span_x / 2 - thickness / 2 + k * pitch

    def Y(k):
        return -span_y / 2 - thickness / 2 + k * pitch

    def cell_centre(i, j):
        # j is a JS row index (0 = top); flip to PAW y
        jj = h - 1 - j
        return (-span_x / 2 + i * pitch + corridor / 2,
                -span_y / 2 + jj * pitch + corridor / 2)

    def clampx(v): return max(-span_x / 2, min(span_x / 2, v))
    def clampy(v): return max(-span_y / 2, min(span_y / 2, v))

    # Collect every closed interior edge as a unit segment on the lattice.
    vert = set()   # (k, jj) : vertical wall on grid line k spanning row jj
    horiz = set()  # (i, k)  : horizontal wall on grid line k spanning column i
    for j in range(h):
        for i in range(w):
            jj = h - 1 - j
            c = j * w + i
            if i + 1 < w and not (open_[c] & E):
                vert.add((i + 1, jj))
            if j + 1 < h and not (open_[c] & S):      # S in JS = downward = lower PAW y
                horiz.add((i, jj))
    # Merge collinear runs so the arena carries whole walls, not unit stubs.
    walls = []
    for k in sorted({v[0] for v in vert}):
        rows = sorted(r for kk, r in vert if kk == k)
        run = []
        for r in rows + [None]:
            if run and r == run[-1] + 1:
                run.append(r)
                continue
            if run:
                walls.append({"x0": round(X(k), 6), "y0": round(clampy(Y(run[0])), 6),
                              "x1": round(X(k), 6), "y1": round(clampy(Y(run[-1] + 1)), 6),
                              "thickness": thickness})
            run = [r] if r is not None else []
    for k in sorted({hh[1] for hh in horiz}):
        cols = sorted(c for c, kk in horiz if kk == k)
        run = []
        for c in cols + [None]:
            if run and c == run[-1] + 1:
                run.append(c)
                continue
            if run:
                walls.append({"x0": round(clampx(X(run[0])), 6), "y0": round(Y(k), 6),
                              "x1": round(clampx(X(run[-1] + 1)), 6), "y1": round(Y(k), 6),
                              "thickness": thickness})
            run = [c] if c is not None else []

    sx, sy = cell_centre(*spawn)
    gx, gy = cell_centre(*exit_cell)
    return {
        "width": round(span_x, 6),
        "height": round(span_y, 6),
        "wall_thickness": thickness,
        "light_sources": [{"x": round(gx, 6), "y": round(gy, 6),
                           "color": "white", "radius": light_radius,
                           "intensity": light_intensity}],
        "internal_walls": walls,
        "robot_start": {"x": round(sx, 6), "y": round(sy, 6),
                        "heading_deg": heading},
    }


def build(w, h, seed, corridor, thickness):
    open_ = carve(w, h, rng(seed))
    problems = validate_perfect(w, h, open_)
    dist, prev, _ = bfs(w, h, open_, 0, 0)
    exit_idx = max(range(w * h), key=lambda i: dist[i])
    path = []
    c = exit_idx
    while c != -1:
        path.append(c)
        c = prev[c]
    path.reverse()
    arena = to_arena(w, h, open_, corridor, thickness,
                     (0, 0), (exit_idx % w, exit_idx // w))
    return open_, problems, path, dist, arena
