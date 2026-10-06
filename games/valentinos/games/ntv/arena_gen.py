"""
valentinos/games/ntv/arena_gen.py
----------------------------------
Procedural arena generation for Name That Vehicle rounds.

Design principles:
  - Robot starts at bottom-centre facing north (heading_deg=90)
  - Features placed so sensors are active within the first 2-3 seconds
  - LDR vehicles: light offset laterally so left/right gradient is clear
  - IR vehicles: robot near a boundary wall so IR activates immediately
  - Compound (both): robot near one wall, light on the opposite side
    so both sensors are stimulated simultaneously from the start
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

    if motive == "light":
        _place_light(arena, rng)
    elif motive == "obstacle":
        _place_obstacle(arena, rng)
    elif motive == "both":
        _place_compound(arena, rng)
    else:
        if rng.random() < 0.5:
            _place_light(arena, rng)
        else:
            _place_obstacle(arena, rng)

    # Every game is beholden to the same floor (engine/arena/world.py). This
    # generator authors at 0.5 x 1.0 and was the last producer of a
    # non-conforming arena — VV's intro screens draw these directly, bypassing
    # load_arena(), which is why the intro arena rendered at aspect 0.5 while
    # every other arena in the suite rendered at 0.6.
    #
    # CAVEAT: the fit is x2.5, so this file's design principle that "sensors
    # are active within the first 2-3 seconds" needs re-checking. Placement
    # scales; sensor RANGES do not.
    from engine.arena.world import fit_to_canvas, conforms
    if conforms(arena):
        arena, _k = fit_to_canvas(arena)
    return arena


def _place_light(arena: dict, rng: random.Random) -> None:
    """
    Place one light source with a clear lateral gradient.
    Robot centred at x=0, light offset 0.08-0.18m to one side
    and 0.20-0.45m ahead of the robot start.
    """
    arena["robot_start"]["x"] = 0.0
    arena["robot_start"]["y"] = -0.35

    sign   = rng.choice([-1, 1])
    x_off  = rng.uniform(0.08, 0.18) * sign
    y_pos  = rng.uniform(-0.05, 0.10)
    radius = rng.uniform(0.15, 0.20)
    arena["light_sources"].append({
        "x":         round(x_off, 3),
        "y":         round(y_pos, 3),
        "intensity": 1.0,
        "radius":    round(radius, 3),
    })


def _place_obstacle(arena: dict, rng: random.Random) -> None:
    """
    Place robot near one boundary wall so IR activates immediately.
    Optionally add a forward internal wall for richer behavior.
    """
    arena["robot_start"]["y"] = -0.35
    sign    = rng.choice([-1, 1])
    x_start = round(rng.uniform(0.13, 0.17) * sign, 3)
    arena["robot_start"]["x"] = x_start

    # Optional forward wall
    if rng.random() < 0.60:
        cx     = rng.uniform(-0.08, 0.08)
        cy     = rng.uniform(0.00, 0.20)
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


def _place_compound(arena: dict, rng: random.Random) -> None:
    """
    Place robot near one boundary wall AND a light on the opposite side.

    Constraints:
    - Robot near east or west boundary wall (IR active from tick 1)
    - Robot not so close that it immediately bounces (x = ±0.10-0.14m)
    - Light placed on the OPPOSITE side from the wall so LDR gradient
      is clear and pulls the robot toward open space
    - Light is ahead of the robot (y > robot_y) so it's in the field
      of view from the start
    - Light radius large enough to reach the robot from the opposite side
    - Optional forward internal wall for additional IR stimulation
    """
    arena["robot_start"]["y"] = -0.35

    # Wall side: robot near east (+x) or west (-x) boundary
    wall_sign = rng.choice([-1, 1])
    x_start   = round(rng.uniform(0.10, 0.14) * wall_sign, 3)
    arena["robot_start"]["x"] = x_start

    # Light on the OPPOSITE side — robot faces it asymmetrically
    # x_off is opposite sign to wall, 0.10-0.20m from centre
    light_sign = -wall_sign
    x_off  = round(rng.uniform(0.05, 0.15) * light_sign, 3)
    y_pos  = round(rng.uniform(-0.05, 0.15), 3)
    # Radius must be large enough to reach robot across the arena
    # Robot is ~0.10-0.14m from centre on wall side, light is
    # 0.05-0.15m from centre on open side — distance ~0.15-0.29m
    # Use radius 0.20-0.28 for strong signal across full width
    radius = round(rng.uniform(0.20, 0.28), 3)
    arena["light_sources"].append({
        "x":         x_off,
        "y":         y_pos,
        "intensity": 1.0,
        "radius":    radius,
    })

    # Optional forward internal wall — keeps the robot from escaping
    # and adds ongoing IR stimulation in the open direction
    if rng.random() < 0.50:
        # Place wall ahead and slightly to the open (light) side
        cx     = round(rng.uniform(-0.05, 0.10) * light_sign, 3)
        cy     = round(rng.uniform(0.10, 0.25), 3)
        length = round(rng.uniform(0.10, 0.20), 3)
        angle  = rng.uniform(-0.3, 0.3)
        dx     = math.cos(angle) * length / 2
        dy     = math.sin(angle) * length / 2
        arena["internal_walls"].append({
            "x0":        round(cx - dx, 3),
            "y0":        round(cy - dy, 3),
            "x1":        round(cx + dx, 3),
            "y1":        round(cy + dy, 3),
            "thickness": 0.025,
        })
