"""
arena_check.py — geometric sanity checks for any PAW arena dict.

Three questions, in the order the methodology rules say to ask them:
  1. REACHABLE   is the start unblocked, and is the goal reachable from it?
  2. COMPONENTS  how much of the arena is walled off from everything?
  3. CLEARANCE   how wide is the narrowest corridor on the best path?

(3) is the one that has been missing. A corridor barely wider than the robot
makes a challenge fail for reasons that have nothing to do with control, which
silently confounds any conclusion drawn from that failure.
"""
import math
from collections import deque


def _gap(arena, x, y):
    """Distance from the robot CENTRE to the nearest wall surface."""
    d = min(arena["width"] / 2 - abs(x), arena["height"] / 2 - abs(y))
    for iw in arena.get("internal_walls", []):
        ax, ay, bx, by = iw["x0"], iw["y0"], iw["x1"], iw["y1"]
        ht = iw.get("thickness", arena.get("wall_thickness", 0.025)) / 2.0
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        t = 0.0 if seg < 1e-12 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / seg))
        d = min(d, math.hypot(x - (ax + t * dx), y - (ay + t * dy)) - ht)
    return d


def check(arena, body_radius, goal_xy=None, cell=0.005, exempt=None):
    W, H = arena["width"], arena["height"]
    nx, ny = int(W / cell) + 1, int(H / cell) + 1
    cx = lambda i: -W / 2 + i * cell
    cy = lambda j: -H / 2 + j * cell
    G = [[_gap(arena, cx(i), cy(j)) for j in range(ny)] for i in range(nx)]
    # Collision boundary matches hub._blocked(): body edge stops at the wall
    # surface, minus the 4 mm reach skin.
    free = [[G[i][j] > body_radius - 0.004 for j in range(ny)] for i in range(nx)]

    rs = arena["robot_start"]
    si, sj = int(round((rs["x"] + W / 2) / cell)), int(round((rs["y"] + H / 2) / cell))
    start_ok = 0 <= si < nx and 0 <= sj < ny and free[si][sj]

    seen = [[False] * ny for _ in range(nx)]
    n_reach = 0
    if start_ok:
        q = deque([(si, sj)])
        seen[si][sj] = True
        while q:
            i, j = q.popleft()
            n_reach += 1
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                u, v = i + di, j + dj
                if 0 <= u < nx and 0 <= v < ny and free[u][v] and not seen[u][v]:
                    seen[u][v] = True
                    q.append((u, v))
    n_free = sum(1 for i in range(nx) for j in range(ny) if free[i][j])

    out = {"start_ok": start_ok, "free_cells": n_free, "reachable_cells": n_reach,
           "stranded_frac": 0.0 if n_free == 0 else 1 - n_reach / n_free,
           "goal_reachable": None, "bottleneck": None, "clearance_mm": None}

    if goal_xy is None:
        return out
    gi = int(round((goal_xy[0] + W / 2) / cell))
    gj = int(round((goal_xy[1] + H / 2) / cell))
    out["goal_reachable"] = bool(0 <= gi < nx and 0 <= gj < ny and seen[gi][gj])
    if not out["goal_reachable"]:
        return out

    # Widest-bottleneck path: binary search on a clearance threshold. Start and
    # goal pockets are exempt — they are often deliberately in a corner, and
    # their own tightness says nothing about the corridors between them.
    ex = exempt if exempt is not None else body_radius * 1.5
    EX = [[(math.hypot(cx(i) - rs["x"], cy(j) - rs["y"]) < ex or
            math.hypot(cx(i) - goal_xy[0], cy(j) - goal_xy[1]) < ex)
           for j in range(ny)] for i in range(nx)]

    def connected(thr):
        vis = [[False] * ny for _ in range(nx)]
        q = deque([(si, sj)])
        vis[si][sj] = True
        while q:
            i, j = q.popleft()
            if (i, j) == (gi, gj):
                return True
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                u, v = i + di, j + dj
                if not (0 <= u < nx and 0 <= v < ny) or vis[u][v]:
                    continue
                if G[u][v] >= thr or (EX[u][v] and free[u][v]):
                    vis[u][v] = True
                    q.append((u, v))
        return False

    lo, hi = 0.0, max(W, H) / 2
    for _ in range(36):
        mid = (lo + hi) / 2
        if connected(mid):
            lo = mid
        else:
            hi = mid
    out["bottleneck"] = lo
    out["clearance_mm"] = (lo - body_radius) * 1000
    return out


def report(name, arena, body_radius, goal_xy=None):
    r = check(arena, body_radius, goal_xy)
    print(f"{name}")
    print(f"   start unblocked : {r['start_ok']}")
    print(f"   free / reachable: {r['free_cells']} / {r['reachable_cells']}"
          f"   ({r['stranded_frac']*100:.1f}% of free space stranded)")
    if r["goal_reachable"] is not None:
        print(f"   goal reachable  : {r['goal_reachable']}")
    if r["clearance_mm"] is not None:
        c = r["clearance_mm"]
        v = ("IMPASSABLE" if c < 0 else "razor-thin" if c < 10
             else "tight" if c < 20 else "OK")
        print(f"   corridor        : {r['bottleneck']*2*100:.1f} cm wide"
              f"  ({c:.0f} mm clear per side)  {v}")
    return r


# ── CLI ───────────────────────────────────────────────────────────────────────

def _main() -> int:
    import argparse
    import json
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    ap = argparse.ArgumentParser(
        description="Check an arena is reachable, unstranded and wide enough.")
    ap.add_argument("arena", nargs="?",
                    help="path to an arena JSON file; omit to check every "
                         "Field Trip challenge")
    ap.add_argument("--body-radius", type=float, default=None,
                    help="collision radius in metres (default: the RE robot)")
    ap.add_argument("--goal", type=float, nargs=2, metavar=("X", "Y"),
                    help="goal position, for the corridor-clearance check")
    args = ap.parse_args()

    from engine.arena.world import (SENSOR_HONEST_MIN_CORRIDOR,
                                    PROX_GRADIENT_MIN_CORRIDOR)
    br = args.body_radius
    if br is None:
        from engine.config import RobotConfig
        br = RobotConfig.from_file(
            os.path.join(os.path.dirname(__file__), "..",
                         "games", "ethology", "robot.json")).body_radius

    print(f"body_radius {br} m   "
          f"corridor floors: {SENSOR_HONEST_MIN_CORRIDOR*100:.0f} cm sensor-honest, "
          f"{PROX_GRADIENT_MIN_CORRIDOR*100:.0f} cm prox-gradient\n")

    if args.arena:
        with open(args.arena) as f:
            arena = json.load(f)
        arena.setdefault("internal_walls", [])
        arena.setdefault("light_sources", [])
        goal = tuple(args.goal) if args.goal else (
            (arena["light_sources"][0]["x"], arena["light_sources"][0]["y"])
            if arena["light_sources"] else None)
        report(os.path.basename(args.arena), arena, br, goal)
        return 0

    from engine.field_trip.challenges import ALL_CHALLENGES
    for ch in ALL_CHALLENGES:
        goal = None
        for sid in ch.required_reach:
            src = ch.source_by_id(sid)
            if src is not None and src.stype == "light":
                goal = (src.x, src.y)
                break
        report(f"{ch.id}  {ch.label}", ch.arena, br, goal)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
