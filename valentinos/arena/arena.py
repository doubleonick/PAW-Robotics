"""
valentinos/arena/arena.py
--------------------------
Arena data model and canvas renderer for Valentino's Vehicles.

The arena JSON format is identical to robosim's so the same arena builder
tool (tools/arena_builder.py) can be used directly.  This module handles:
  - Loading / saving arena JSON
  - Rendering the arena onto a pygame surface
  - World ↔ screen coordinate conversion
  - Collision detection (wall + light source proximity)

Arena JSON schema:
  width, height        : metres
  wall_thickness       : metres
  light_sources        : [{x, y, radius}]
  internal_walls       : [{x0,y0,x1,y1,thickness}]
  robot_start          : {x, y, heading_deg}
"""

from __future__ import annotations
import json
import math
import os
from dataclasses import dataclass, field
from typing import Optional

import pygame

# ── Colours (shared with wiring editor palette) ────────────────────────────────

BG           = (10,  12,  10)
FLOOR        = (10,  18,  10)
WALL_COL     = (40,  90,  40)
LIGHT_COL    = (255, 200,  50)
BORDER       = (30,  58,  30)
PHOSPHOR     = ( 51, 255,  87)
TEXT_DIM     = ( 70, 110,  70)
AMBER        = (255, 149,   0)
WHITE_GREEN  = (220, 255, 220)

MARGIN = 28


# ── Default arena ─────────────────────────────────────────────────────────────

DEFAULT_ARENA: dict = {
    "width":          1.5,
    "height":         1.5,
    "wall_thickness": 0.05,
    "light_sources":  [],
    "internal_walls": [],
    "robot_start":    {"x": 0.0, "y": 0.0, "heading_deg": 90.0},
}


# ── Load / save ───────────────────────────────────────────────────────────────

def load_arena(path: str) -> dict:
    if not os.path.exists(path):
        return dict(DEFAULT_ARENA)
    with open(path) as f:
        data = json.load(f)
    arena = dict(DEFAULT_ARENA)
    arena.update(data)
    for key in ("light_sources", "internal_walls"):
        if key not in arena:
            arena[key] = []
    if "robot_start" not in arena:
        arena["robot_start"] = {"x": 0.0, "y": 0.0, "heading_deg": 90.0}
    return arena


def save_arena(arena: dict, path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(arena, f, indent=4)


# ── Coordinate helpers ────────────────────────────────────────────────────────

def world_to_screen(wx: float, wy: float,
                    canvas_rect: pygame.Rect,
                    arena: dict) -> tuple[int, int]:
    aw  = arena["width"]
    ah  = arena["height"]
    scl = min((canvas_rect.width  - MARGIN * 2) / aw,
              (canvas_rect.height - MARGIN * 2) / ah)
    cx  = canvas_rect.left + canvas_rect.width  // 2
    cy  = canvas_rect.top  + canvas_rect.height // 2
    return (int(cx + wx * scl), int(cy - wy * scl))


def screen_to_world(sx: int, sy: int,
                    canvas_rect: pygame.Rect,
                    arena: dict) -> tuple[float, float]:
    aw  = arena["width"]
    ah  = arena["height"]
    scl = min((canvas_rect.width  - MARGIN * 2) / aw,
              (canvas_rect.height - MARGIN * 2) / ah)
    cx  = canvas_rect.left + canvas_rect.width  // 2
    cy  = canvas_rect.top  + canvas_rect.height // 2
    return ((sx - cx) / scl, (cy - sy) / scl)


def arena_scale(canvas_rect: pygame.Rect, arena: dict) -> float:
    aw  = arena["width"]
    ah  = arena["height"]
    return min((canvas_rect.width  - MARGIN * 2) / aw,
               (canvas_rect.height - MARGIN * 2) / ah)


# ── Renderer ──────────────────────────────────────────────────────────────────

def draw_arena(surf: pygame.Surface,
               canvas_rect: pygame.Rect,
               arena: dict,
               robot_states: list | None = None,
               traces: dict | None = None,
               font_sm=None) -> None:
    """
    Draw the arena onto surf within canvas_rect.

    robot_states : list of RobotState objects (from engine.robot_body)
    traces       : dict label→list of (x,y) world positions for path trails
    font_sm      : pygame font for labels
    """
    scl = arena_scale(canvas_rect, arena)
    aw  = arena["width"]
    ah  = arena["height"]

    def w2s(wx, wy):
        return world_to_screen(wx, wy, canvas_rect, arena)

    # Canvas background
    pygame.draw.rect(surf, BG, canvas_rect)

    # Floor
    tl = w2s(-aw / 2,  ah / 2)
    br = w2s( aw / 2, -ah / 2)
    pygame.draw.rect(surf, FLOOR,
                     pygame.Rect(tl[0], tl[1], br[0]-tl[0], br[1]-tl[1]))

    # Light sources — amber glow
    for ls in arena["light_sources"]:
        cx_s, cy_s = w2s(ls["x"], ls["y"])
        r_px = max(4, int(ls["radius"] * scl))
        for ring in range(r_px, 0, -max(1, r_px // 8)):
            alpha = int(70 * (1.0 - ring / r_px))
            s = pygame.Surface((ring * 2, ring * 2), pygame.SRCALPHA)
            pygame.draw.circle(s, (255, 180, 0, alpha), (ring, ring), ring)
            surf.blit(s, (cx_s - ring, cy_s - ring))
        pygame.draw.circle(surf, LIGHT_COL, (cx_s, cy_s), max(3, r_px // 6))

    # Internal walls
    for iw in arena["internal_walls"]:
        p0 = w2s(iw["x0"], iw["y0"])
        p1 = w2s(iw["x1"], iw["y1"])
        wt = max(2, int(iw.get("thickness", 0.05) * scl))
        gs = pygame.Surface((canvas_rect.width, canvas_rect.height),
                            pygame.SRCALPHA)
        p0g = (p0[0] - canvas_rect.left, p0[1] - canvas_rect.top)
        p1g = (p1[0] - canvas_rect.left, p1[1] - canvas_rect.top)
        pygame.draw.line(gs, (*WALL_COL, 60), p0g, p1g, wt + 4)
        surf.blit(gs, (canvas_rect.left, canvas_rect.top))
        pygame.draw.line(surf, WALL_COL, p0, p1, wt)

    # Boundary walls
    wt = max(3, int(arena["wall_thickness"] * scl))
    t  = arena["wall_thickness"]
    for p0w, p1w in [
        ((-aw/2-t,  ah/2+t), ( aw/2+t,  ah/2+t)),
        ((-aw/2-t, -ah/2-t), ( aw/2+t, -ah/2-t)),
        (( aw/2,   -ah/2  ), ( aw/2,    ah/2  )),
        ((-aw/2-t, -ah/2  ), (-aw/2-t,  ah/2  )),
    ]:
        p0s = w2s(*p0w)
        p1s = w2s(*p1w)
        gs  = pygame.Surface((canvas_rect.width, canvas_rect.height),
                              pygame.SRCALPHA)
        p0g = (p0s[0] - canvas_rect.left, p0s[1] - canvas_rect.top)
        p1g = (p1s[0] - canvas_rect.left, p1s[1] - canvas_rect.top)
        pygame.draw.line(gs, (*PHOSPHOR, 40), p0g, p1g, wt + 6)
        surf.blit(gs, (canvas_rect.left, canvas_rect.top))
        pygame.draw.line(surf, WALL_COL, p0s, p1s, wt)

    # Path traces
    if traces:
        TRACE_COLORS = [(255, 120, 60), (60, 160, 255), (180, 255, 100)]
        for ci, (label, pts) in enumerate(traces.items()):
            col = TRACE_COLORS[ci % len(TRACE_COLORS)]
            if len(pts) >= 2:
                screen_pts = [w2s(x, y) for x, y in pts]
                pygame.draw.lines(surf, (*col, 160), False, screen_pts, 1)

    # Robots
    if robot_states:
        from valentinos.engine.robot_body import (
            BODY_FRONT, BODY_WIDTH, BODY_LENGTH, AXLE_FROM_FRONT
        )
        ROBOT_COLORS = [(255, 120, 60), (60, 160, 255), (180, 255, 100)]
        for ci, state in enumerate(robot_states):
            col    = ROBOT_COLORS[ci % len(ROBOT_COLORS)]
            r_px   = max(5, int(0.047 * scl))  # ~half body width
            cx_s, cy_s = w2s(state.x, state.y)

            # Body outline (4 corners)
            corners = state.body_corners()
            screen_corners = [w2s(bx, by) for bx, by in corners]
            pygame.draw.polygon(surf, (*col, 120),
                                screen_corners)
            pygame.draw.polygon(surf, col, screen_corners, 2)

            # Heading arrow
            h  = state.heading
            hx = cx_s + int(math.cos(h) * r_px * 1.4)
            hy = cy_s - int(math.sin(h) * r_px * 1.4)
            pygame.draw.line(surf, WHITE_GREEN, (cx_s, cy_s), (hx, hy), 2)
            pygame.draw.circle(surf, WHITE_GREEN, (hx, hy), 3)


# ── Collision helpers ─────────────────────────────────────────────────────────

def wall_segments(arena: dict) -> list[tuple]:
    """Return list of ((x0,y0),(x1,y1)) boundary + internal wall segments."""
    aw = arena["width"]
    ah = arena["height"]
    t  = arena["wall_thickness"]
    segs = [
        ((-aw/2-t, ah/2+t), ( aw/2+t,  ah/2+t)),
        ((-aw/2-t,-ah/2-t), ( aw/2+t, -ah/2-t)),
        (( aw/2,  -ah/2  ), ( aw/2,    ah/2  )),
        ((-aw/2-t,-ah/2  ), (-aw/2-t,  ah/2  )),
    ]
    for iw in arena["internal_walls"]:
        segs.append(((iw["x0"], iw["y0"]), (iw["x1"], iw["y1"])))
    return segs


def ray_distance(ox: float, oy: float, angle: float,
                 arena: dict, max_range: float = 2.0) -> float:
    """
    Cast a ray from (ox,oy) at world angle, return distance to nearest wall.
    Used for IR sensor simulation.
    """
    dx = math.cos(angle)
    dy = math.sin(angle)
    best = max_range

    for (ax, ay), (bx, by) in wall_segments(arena):
        # Ray vs segment intersection
        rdx = bx - ax
        rdy = by - ay
        denom = dx * rdy - dy * rdx
        if abs(denom) < 1e-10:
            continue
        t_seg = ((ax - ox) * rdy - (ay - oy) * rdx) / denom
        t_wall = ((ax - ox) * dy  - (ay - oy) * dx) / denom
        if 0.0 <= t_wall <= 1.0 and 0.0 < t_seg < best:
            best = t_seg

    return best


def light_at(wx: float, wy: float, arena: dict) -> float:
    """
    Return combined normalized light intensity at world position (wx, wy).
    Sums contributions from all light sources, clamped to [0, 1].
    """
    total = 0.0
    for ls in arena["light_sources"]:
        dist = math.hypot(wx - ls["x"], wy - ls["y"])
        r    = max(0.01, ls["radius"])
        if dist < r * 3:
            total += max(0.0, 1.0 - dist / (r * 2))
    return min(1.0, total)
