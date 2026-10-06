"""
engine/arena/world.py — the shared arena canvas.

THE ONE PLACE arena dimensions are defined. Every game is beholden to these; no
game declares its own floor size.

WHY THIS EXISTS
---------------
The suite had four arena sizes and three wall thicknesses:

    Robot Ethology   1.5  x 2.5   wall 0.05
    Valentino's      1.2  x 1.6   wall 0.025
    Field Trip       0.99 x 1.32  wall 0.041
    NTV arena_gen    0.5  x 1.0

An arena meant something different in each game, so a robot proven in one did
not transfer to another and an arena could not be shared. RE's figures win
because RE was developed most directly from the physical lab: 1.5 x 2.5 m is the
real floor, and its robot is the real robot.

WHAT SCALES AND WHAT DOES NOT
-----------------------------
Scaled  : wall endpoints, light positions and radii, robot start position.
          These are *layout* — where things are relative to each other.
NOT scaled:
  - wall THICKNESS. A wall is a physical block; it is 5 cm because the block is
    5 cm. Scaling it would make the same wall a different object per game.
  - the robot. Its size is a property of the chassis (see
    robot_builder.chassis_collision_radius), not of the floor it stands on.
  - sensor response curves. A sensor's 10 cm is 10 cm in any arena. This is the
    whole reason a bigger arena is a genuinely different problem rather than the
    same one drawn larger: scaling the floor moves walls INTO the sensors'
    honest range, or out of it.

The fit is UNIFORM (single factor, min of the two axes). A non-uniform stretch
would distort angles and make horizontal corridors a different width from
vertical ones — a robot that fits one way would not fit the other.
"""
from __future__ import annotations
import copy
import math

# ── The canvas ────────────────────────────────────────────────────────────────
CANVAS_W = 1.5        # metres — the physical lab floor
CANVAS_H = 2.5
WALL_THICKNESS = 0.05  # metres — the physical wall block
GRID_M = 0.25          # metres — builder placement grid (tools/arena_builder.py)

# ── Constraints, for validators and generators ────────────────────────────────
# Below ~10 cm a Sharp GP2Y0A21 folds back: it reports a DISTANT surface while
# touching a near one. A side-mounted sensor sits roughly corridor/2 from the
# wall, so corridors much under this are read dishonestly whatever the robot.
SENSOR_HONEST_MIN_CORRIDOR = 0.30
# RE's CogProximity.getData() saturates at 18 cm, so a hierarchy robot centred in
# a corridor narrower than this has both sensors pinned and no gradient to steer
# on. Stricter than the above; applies to proximity-driven control.
PROX_GRADIENT_MIN_CORRIDOR = 0.36


def fit_to_canvas(arena: dict,
                  canvas_w: float = CANVAS_W,
                  canvas_h: float = CANVAS_H,
                  wall_thickness: float = WALL_THICKNESS) -> tuple[dict, float]:
    """Scale an arena's layout uniformly to fit the shared canvas.

    Returns (new_arena, factor). The returned arena's boundary IS the canvas —
    content is centred, so a layout with a different aspect ratio leaves a
    margin on one axis rather than being stretched to fill.
    """
    w, h = arena.get("width"), arena.get("height")
    if not w or not h:
        raise ValueError("arena has no width/height to fit")
    k = min(canvas_w / w, canvas_h / h)

    a = copy.deepcopy(arena)
    for ls in a.get("light_sources", []):
        ls["x"] *= k
        ls["y"] *= k
        if "radius" in ls:
            ls["radius"] *= k
    for iw in a.get("internal_walls", []):
        for key in ("x0", "y0", "x1", "y1"):
            iw[key] *= k
        iw["thickness"] = wall_thickness      # physical block, never scaled
    rs = a.get("robot_start")
    if rs:
        rs["x"] *= k
        rs["y"] *= k                          # heading is an angle — untouched

    a["width"] = canvas_w
    a["height"] = canvas_h
    a["wall_thickness"] = wall_thickness
    return a, k


def conforms(arena: dict) -> list[str]:
    """Return a list of ways this arena departs from the shared canvas.
    Empty list means it conforms."""
    problems = []
    if abs(arena.get("width", 0) - CANVAS_W) > 1e-6:
        problems.append(f"width {arena.get('width')} != {CANVAS_W}")
    if abs(arena.get("height", 0) - CANVAS_H) > 1e-6:
        problems.append(f"height {arena.get('height')} != {CANVAS_H}")
    wt = arena.get("wall_thickness")
    if wt is not None and abs(wt - WALL_THICKNESS) > 1e-6:
        problems.append(f"wall_thickness {wt} != {WALL_THICKNESS}")
    for i, iw in enumerate(arena.get("internal_walls", [])):
        t = iw.get("thickness")
        if t is not None and abs(t - WALL_THICKNESS) > 1e-6:
            problems.append(f"internal_walls[{i}].thickness {t} != {WALL_THICKNESS}")
    return problems
