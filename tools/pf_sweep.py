#!/usr/bin/env python3
"""
pf_sweep.py — headless push/pull solvability sweep for Field Trip challenges.

WHY THIS EXISTS
---------------
Every solvability claim in FUTURE_WORK.md ("33 of 729 configs solve", "2 of
729") came from a heredoc that was never committed, so none of them could be
re-run or audited. This is that harness, made permanent.

It reproduces `Hub.tick()` exactly — same MOTOR_SPEED, same PHYS_DT, same
force_to_motors, same sliding-contact collision — so a config that solves here
solves in the game.

THE CONFIG SPACE
----------------
Reconstructed from the shipped FT_CP*_solution.json prefabs, which between them
use lateral offsets {-0.04, 0, +0.04} and mounting angles drawn from
{-90,-70,-45,-20,0,+20,+45,+70,+90}. That is 27 mountings per sensor, and with
one LDR·Seek plus one IR·Flee, 27 x 27 = 729 pairs — matching the "of 729"
figure quoted throughout. Forward offsets are fixed at the prefab values
(LDR 0.060, IR 0.050).

Tangential is held at 0.0 throughout: the user playtests with Push/Pull only,
and a solvability claim made outside that space is not about their game.

USAGE
-----
    python tools/pf_sweep.py --challenge cp3
    python tools/pf_sweep.py --challenge cp1,cp2,cp3,cp4,cp5 --foldback both
    python tools/pf_sweep.py --arena path/to/maze.json --duration 75
"""
from __future__ import annotations
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.sensor_physics import set_ir_foldback              # noqa: E402
from engine.field_trip.field_physics import (                  # noqa: E402
    FieldSensor, FieldSource, ATTRACT, REPEL,
    compute_force, force_to_motors,
    check_reach_light, check_reach_wall,
)

# ── constants, kept in step with games/field_trip/hub.py ──────────────────────
from engine.field_trip.challenges import BODY_RADIUS       # noqa: E402
MOTOR_SPEED = 0.35
PHYS_DT     = 1 / 60

# ── the config grid ───────────────────────────────────────────────────────────
ANGLES  = (-90.0, -70.0, -45.0, -20.0, 0.0, 20.0, 45.0, 70.0, 90.0)
OFFSETS = (-0.04, 0.0, 0.04)
LDR_X, IR_X = 0.060, 0.050


def mountings():
    for a in ANGLES:
        for y in OFFSETS:
            yield a, y


def make_sensors(ldr_ang, ldr_y, ir_ang, ir_y):
    return [
        FieldSensor("LDR·F", "LDR", "W", LDR_X, ldr_y, ldr_ang, ATTRACT, 0.0),
        FieldSensor("IR·F",  "IR",  "W", IR_X,  ir_y,  ir_ang,  REPEL,   0.0),
    ]


# ── collision, identical to Hub._blocked ──────────────────────────────────────
def blocked(arena, x, y):
    aw = arena["width"] / 2 - BODY_RADIUS
    ah = arena["height"] / 2 - BODY_RADIUS
    if x < -aw or x > aw or y < -ah or y > ah:
        return True
    for iw in arena.get("internal_walls", []):
        ax, ay, bx, by = iw["x0"], iw["y0"], iw["x1"], iw["y1"]
        half_t = iw.get("thickness", arena.get("wall_thickness", 0.025)) / 2.0
        block_d = BODY_RADIUS + half_t - 0.004
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        if seg < 1e-12:
            continue
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / seg))
        if math.hypot(x - (ax + t * dx), y - (ay + t * dy)) < block_d:
            return True
    return False


def run_one(arena, sources, sensors, duration_s, goal, start,
            dwell_zone=None, dwell_s=0.0):
    """One headless run. Returns (solved, time_s, path_len_m)."""
    x, y = start["x"], start["y"]
    heading = math.radians(start.get("heading_deg", 90.0))
    t = 0.0
    dist = 0.0
    dwell_acc = 0.0
    steps = int(duration_s / PHYS_DT)
    for _ in range(steps):
        fx, fy = compute_force(sensors, sources, x, y, heading, arena)
        left, right = force_to_motors(fx, fy, heading)
        v = (left + right) * 0.5 * MOTOR_SPEED
        omega = (right - left) * MOTOR_SPEED / (BODY_RADIUS * 2)
        heading = heading + omega * PHYS_DT
        px = x + v * math.cos(heading) * PHYS_DT
        py = y + v * math.sin(heading) * PHYS_DT
        # sliding contact, exactly as the hub does it
        if not blocked(arena, px, py):
            nx, ny = px, py
        elif not blocked(arena, px, y):
            nx, ny = px, y
        elif not blocked(arena, x, py):
            nx, ny = x, py
        else:
            nx, ny = x, y
        dist += math.hypot(nx - x, ny - y)
        x, y = nx, ny
        t += PHYS_DT

        if goal is not None:
            src = goal
            hit = (check_reach_light(x, y, BODY_RADIUS, src)
                   if src.stype == "light"
                   else check_reach_wall(x, y, BODY_RADIUS, src))
            if hit:
                return True, t, dist
        if dwell_zone is not None:
            gx, gy = dwell_zone["pos"]
            if math.hypot(x - gx, y - gy) <= dwell_zone["outer"]:
                dwell_acc += PHYS_DT
                if dwell_acc >= dwell_s:
                    return True, t, dist
            else:
                dwell_acc = 0.0
    return False, t, dist


def sweep(arena, sources, duration_s, goal, start, dwell_zone=None,
          dwell_s=0.0, verbose=False):
    hits = []
    total = 0
    for la, ly in mountings():
        for ia, iy in mountings():
            total += 1
            sensors = make_sensors(la, ly, ia, iy)
            ok, t, d = run_one(arena, sources, sensors, duration_s,
                               goal, start, dwell_zone, dwell_s)
            if ok:
                hits.append((t, la, ly, ia, iy, d))
    hits.sort()
    return hits, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--challenge", default="cp1,cp2,cp3,cp4,cp5",
                    help="comma-separated challenge ids from ALL_CHALLENGES")
    ap.add_argument("--foldback", default="both",
                    choices=("off", "on", "both"))
    ap.add_argument("--duration", type=float, default=None,
                    help="override the challenge's duration_s")
    ap.add_argument("--show", type=int, default=3,
                    help="how many best configs to print")
    args = ap.parse_args()

    from engine.field_trip.challenges import ALL_CHALLENGES
    CH = {c.id: c for c in ALL_CHALLENGES}

    modes = {"off": [False], "on": [True], "both": [False, True]}[args.foldback]

    print(f"config grid: {len(ANGLES)} angles x {len(OFFSETS)} offsets "
          f"per sensor = {len(ANGLES)*len(OFFSETS)}^2 = "
          f"{(len(ANGLES)*len(OFFSETS))**2} pairs, tangential fixed at 0.0\n")

    for cid in args.challenge.split(","):
        ch = CH.get(cid.strip())
        if ch is None:
            print(f"!! unknown challenge {cid}")
            continue
        dur = args.duration or ch.duration_s
        goal = None
        for sid in ch.required_reach:
            goal = ch.source_by_id(sid)
            break
        dz = ch.dwell_zone if (ch.dwell_zone and "pos" in ch.dwell_zone) else None
        dwell_s = (ch.dwell_zone or {}).get("seconds", 0.0) if dz else 0.0

        print(f"── {ch.id}  {ch.label}   ({dur:.0f} s budget)")
        for fb in modes:
            set_ir_foldback(fb)
            hits, total = sweep(ch.arena, ch.sources, dur, goal,
                                ch.arena["robot_start"], dz, dwell_s)
            tag = "fold-back ON " if fb else "fold-back OFF"
            print(f"   {tag}: {len(hits):4d} / {total} solve", end="")
            if hits:
                print(f"   best {hits[0][0]:.1f} s")
                for t, la, ly, ia, iy, d in hits[:args.show]:
                    print(f"        {t:5.1f}s  LDR {la:+6.1f}deg y={ly:+.2f}"
                          f"   IR {ia:+6.1f}deg y={iy:+.2f}   ({d:.1f} m)")
            else:
                print()
        set_ir_foldback(False)
        print()


if __name__ == "__main__":
    main()
