"""
valentinos/games/ntv/arena_gen.py
----------------------------------
Procedural arena generation for Name That Vehicle rounds.

Design principles:
  - Robot starts at bottom-centre facing north
  - Features are placed so sensors are active within the first 2–3 seconds
  - LDR (light) vehicles: light within 0.4–0.7m of robot start
  - IR (obstacle) vehicles: robot starts 0.25–0.35m from east wall so
    RR sensor activates immediately; optional wall ahead
  - Off-centre placement ensures asymmetric, legible behaviour
"""

from __future__ import annotations
import math
import random
import copy

ARENA_W = 0.5
ARENA_H = 1.0

_BASE: dict = {
    "width":          ARENA_W,
    "height":         ARENA_H,
    "wall_thickness": 0.025,
    "light_sources":  [],
    "internal_walls": [],
    "robot_start":    {"x": 0.0, "y": -0.35, "heading_deg": 90.0},
}


def generate_arena(motive: str,
                   rng: random.Random | None = None) -> dict:
    """
    Generate one arena for an NTV round.

    motive : "light" | "obstacle" | "both"
    """
    if rng is None:
        rng = random.Random()

    arena = copy.deepcopy(_BASE)

    if motive in ("light", "both"):
        _place_light(arena, rng)
    if motive in ("obstacle", "both"):
        _place_obstacle(arena, rng)
    if motive not in ("light", "obstacle", "both"):
        if rng.random() < 0.5:
            _place_light(arena, rng)
        else:
            _place_obstacle(arena, rng)

    return arena


def _place_light(arena: dict, rng: random.Random) -> None:
    """
    Place a light source so LDR sensors read a clear gradient from startup.

    Robot start moved to y=-0.25 so sensors sit at y≈-0.19.
    Light placed at y=-0.05 to +0.15 (0.14–0.34m from sensors) and
    0.15–0.30m off-centre laterally.
    With radius 0.25–0.30m, illuminance > 0.3 from tick 1 on both sensors,
    with a clear left/right gradient.
    """
    # Full-size robot at y=-0.35 in 0.5×1.0m arena
    # Sensors at approx y=-0.29. Light 0.24-0.39m away for good gradient.
    arena["robot_start"]["y"] = -0.35

    sign  = rng.choice([-1, 1])
    x_off = rng.uniform(0.08, 0.18) * sign
    y_pos = rng.uniform(-0.05, 0.10)
    radius = rng.uniform(0.15, 0.20)
    arena["light_sources"].append({
        "x":         round(x_off, 3),
        "y":         round(y_pos, 3),
        "intensity": 1.0,
        "radius":    round(radius, 3),
    })


def _place_obstacle(arena: dict, rng: random.Random) -> None:
    """
    Place the robot near the east or west wall so IR sensors activate
    immediately, then add an optional forward obstacle.

    Robot is shifted laterally so RR or RL reads > 0 from tick 1.
    x = ±0.28–0.36 puts the boundary wall at 0.14–0.22m from the sensor
    (clearly in the 0.457m max range).
    """
    # Full-size robot: x=±0.15-0.18 puts it close to east/west wall
    # IR sensor (30° outward) hits boundary wall within 0.10-0.15m ray dist
    arena["robot_start"]["y"] = -0.35
    sign  = rng.choice([-1, 1])
    x_start = round(rng.uniform(0.15, 0.18) * sign, 3)
    arena["robot_start"]["x"] = x_start

    # Optionally add a forward wall
    if rng.random() < 0.60:
        cx    = rng.uniform(-0.10, 0.10)
        cy    = rng.uniform(0.00, 0.20)
        length = rng.uniform(0.12, 0.25)
        angle  = rng.uniform(-0.4, 0.4)
        dx     = math.cos(angle) * length / 2
        dy     = math.sin(angle) * length / 2
        arena["internal_walls"].append({
            "x0":        round(cx - dx, 3),
            "y0":        round(cy - dy, 3),
            "x1":        round(cx + dx, 3),
            "y1":        round(cy + dy, 3),
            "thickness": 0.025,
        })
