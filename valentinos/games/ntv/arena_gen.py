"""
valentinos/games/ntv/arena_gen.py
----------------------------------
Procedural arena generation for Name That Vehicle rounds.

Each round gets a fresh arena with:
  - Fixed outer boundary: 1.4m × 1.4m square
  - Robot start: bottom-centre, heading up (north)
  - One feature: EITHER a light source OR an internal wall, chosen at random
  - Feature is placed slightly off-centre to make behavior legible
    (a centred feature would produce symmetric, uninformative behavior)

Feature placement rules:
  Light source: 0.2–0.4m off centreline laterally, 0.3–0.5m forward of start
  Internal wall: short horizontal or diagonal segment, offset from centre
"""

from __future__ import annotations
import math
import random
import copy



# ── Base arena ────────────────────────────────────────────────────────────────

# Canonical Valentino's arena dimensions — matches valentinos_arena.json
ARENA_W = 1.0 #2.0
ARENA_H = 2.0 #4.0

_BASE: dict = {
    "width":          ARENA_W,
    "height":         ARENA_H,
    "wall_thickness": 0.05,
    "light_sources":  [],
    "internal_walls": [],
    "robot_start":    {"x": 0.0, "y": -0.50, "heading_deg": 90.0},
}


def generate_arena(motive: str,
                   rng: random.Random | None = None) -> dict:
    """
    Generate one arena for an NTV round.

    motive : "light" | "obstacle" | "both"
      light    → always place a light source
      obstacle → always place an internal wall
      both     → place both (or pick randomly for each)
    """
    if rng is None:
        rng = random.Random()

    arena = copy.deepcopy(_BASE)

    if motive in ("light", "both"):
        arena["light_sources"].append(_random_light(rng))

    if motive in ("obstacle", "both"):
        arena["internal_walls"].append(_random_wall(rng))

    if motive not in ("light", "obstacle", "both"):
        # Fallback: pick one
        if rng.random() < 0.5:
            arena["light_sources"].append(_random_light(rng))
        else:
            arena["internal_walls"].append(_random_wall(rng))

    return arena


def _random_light(rng: random.Random) -> dict:
    """
    Place a light source off-centre so the robot responds asymmetrically.
    x: ±0.15–0.45m  (never on centreline)
    y: -0.10 to 0.40m ahead of start (start is at y=-0.50)
    """
    sign  = rng.choice([-1, 1])
    half  = ARENA_W / 2
    x_off = rng.uniform(0.15, half * 0.85) * sign
    y_pos = rng.uniform(-0.10, 0.40)
    return {
        "x":         round(x_off, 3),
        "y":         round(y_pos, 3),
        "intensity": 1.0,
        "radius":    round(rng.uniform(0.20, 0.35), 2),
    }


def _random_wall(rng: random.Random) -> dict:
    """
    Place a short wall slightly off-centre, always reachable from start.
    """
    sign   = rng.choice([-1, 1])
    half   = ARENA_W / 2
    cx     = rng.uniform(0.05, half * 0.70) * sign
    cy     = rng.uniform(-0.10, 0.40)
    length = rng.uniform(0.15, 0.38)
    angle  = rng.uniform(-0.3, 0.3)
    dx     = math.cos(angle) * length / 2
    dy     = math.sin(angle) * length / 2
    return {
        "x0":        round(cx - dx, 3),
        "y0":        round(cy - dy, 3),
        "x1":        round(cx + dx, 3),
        "y1":        round(cy + dy, 3),
        "thickness": 0.05,
    }
