# engine/arena — arena drawing and utility functions
"""
engine/arena/__init__.py  (the only arena module)
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

# ── Colours — always read from engine.theme ────────────────────────────────────

MARGIN = 28

def _colours():
    """Return current theme colours. Called at draw time so theme changes apply."""
    try:
        import engine.theme as _t
        return _t
    except Exception:
        pass
    # Phosphor fallback
    class _F:
        BG          = (10,  12,  10)
        FLOOR       = (10,  18,  10)
        WALL_COLOR  = (40,  90,  40)
        LIGHT_COLOR = (255, 200,  50)
        BORDER      = (30,  58,  30)
        PHOSPHOR    = ( 51, 255,  87)
        TEXT_DIM    = ( 70, 110,  70)
        AMBER       = (255, 149,   0)
        WHITE_GREEN = (220, 255, 220)
    return _F()


# ── Default arena ─────────────────────────────────────────────────────────────

DEFAULT_ARENA: dict = {
    "width":          1.0,
    "height":         2.0,
    "wall_thickness": 0.05,
    "light_sources":  [],
    "internal_walls": [],
    "robot_start":    {"x": 0.0, "y": 0.0, "heading_deg": 90.0},
}


# ── Load / save ───────────────────────────────────────────────────────────────


def _probe_emit(line: str) -> None:
    """Print AND append to render_probe.txt in the repo root.

    Console output proved unreliable to capture (subprocess launches swallow it,
    and it is easy to miss among pygame's banner), so the probe also writes a
    file that can simply be sent on.
    """
    print(line, flush=True)
    try:
        import os
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        with open(os.path.join(root, "render_probe.txt"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_arena(path: str) -> dict:
    if not os.path.exists(path):
        # Fit the fallback too — an early return here skipped the canvas fit
        # and handed callers a 1.0 x 2.0 arena while every real one was 1.5x2.5.
        from engine.arena.world import fit_to_canvas, conforms
        d = dict(DEFAULT_ARENA)
        return fit_to_canvas(d)[0] if conforms(d) else d
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    arena = dict(DEFAULT_ARENA)
    arena.update(data)
    for key in ("light_sources", "internal_walls"):
        if key not in arena:
            arena[key] = []
    if "robot_start" not in arena:
        arena["robot_start"] = {"x": 0.0, "y": 0.0, "heading_deg": 90.0}
    # Every game is beholden to the same floor. Arenas authored against an
    # older, smaller canvas are fitted uniformly here; ones already at
    # 1.5 x 2.5 pass through untouched. See engine/arena/world.py.
    from engine.arena.world import fit_to_canvas, conforms
    if conforms(arena):
        arena, _k = fit_to_canvas(arena)
    return arena


def save_arena(arena: dict, path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(arena, f, indent=4)


# ── Coordinate helpers ────────────────────────────────────────────────────────


# Fraction of the available canvas an arena is allowed to occupy. Below 1.0 so
# the OUTER walls sit clear of the window edge instead of flush against it —
# without it the bottom wall reads as clipped, especially against a taskbar.
ARENA_FIT = 0.92


def arena_rect(canvas_rect: pygame.Rect, arena: dict,
               fit: float = ARENA_FIT) -> pygame.Rect:
    """Shrink a canvas rect to the arena's aspect ratio, centred, with a margin.

    THE shared derivation — every game must use this so an arena is the same
    size on screen in all of them.

    Field Trip had this privately as Hub._arena_rect() and was the only game
    with it, which is why FT showed all four walls comfortably inset while Robot
    Ethology and Valentino's ran to the window edge. Same arena data, same
    scale formula; the difference was entirely this step. Measured: FT drew at
    291 px/m into a (685, 36, 493, 822) rect while RE drew at 336 px/m into
    (455, 0, 969, 896) of the same 1424x896 window.

    Pass the result to draw_arena()/world_to_screen(), which apply MARGIN inside
    it — the two insets compose deliberately.
    """
    aw = arena["width"]
    ah = arena["height"]
    scl = min(canvas_rect.width / aw, canvas_rect.height / ah) * fit
    pw, ph = int(aw * scl), int(ah * scl)
    ox = canvas_rect.x + (canvas_rect.width - pw) // 2
    oy = canvas_rect.y + (canvas_rect.height - ph) // 2
    return pygame.Rect(ox, oy, pw, ph)


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

    # ── Render probe ──────────────────────────────────────────────────────────
    # Set PAW_RENDER_PROBE=1 to print, once per distinct (rect, arena) pair,
    # exactly what geometry reaches the renderer. Added because FT, VV and RE
    # compute near-identical scales in isolation, yet RE and VV clip on screen
    # while FT does not — so the divergence is in what is PASSED here, not in
    # arena_scale(). Cheap, off by default, and prints at most a few lines.
    import os as _os
    if _os.environ.get("PAW_RENDER_PROBE"):
        _k = (canvas_rect.x, canvas_rect.y, canvas_rect.w, canvas_rect.h,
              round(arena.get("width", 0), 4), round(arena.get("height", 0), 4))
        _seen = getattr(draw_arena, "_probe_seen", None)
        if _seen is None:
            _seen = set(); draw_arena._probe_seen = _seen
        if _k not in _seen:
            _seen.add(_k)
            _s = arena_scale(canvas_rect, arena)
            _aw, _ah = arena["width"] * _s, arena["height"] * _s
            _cx = canvas_rect.left + canvas_rect.width // 2
            _cy = canvas_rect.top + canvas_rect.height // 2
            _probe_emit(f"[RENDER-PROBE] surf={surf.get_size()} rect={tuple(canvas_rect)} "
                  f"arena={arena.get('width')}x{arena.get('height')} "
                  f"wall_t={arena.get('wall_thickness')} "
                  f"scale={_s:.1f}px/m box={_aw:.0f}x{_ah:.0f} "
                  f"top={_cy - _ah/2:.0f} bottom={_cy + _ah/2:.0f} "
                  f"left={_cx - _aw/2:.0f} right={_cx + _aw/2:.0f} "
                  f"[via engine.arena.draw_arena]")

    scl = arena_scale(canvas_rect, arena)
    aw  = arena["width"]
    ah  = arena["height"]

    def w2s(wx, wy):
        return world_to_screen(wx, wy, canvas_rect, arena)

    # Resolve current theme colours
    C   = _colours()
    BG          = C.BG
    FLOOR       = C.FLOOR
    WALL_COL    = C.WALL_COLOR
    LIGHT_COL   = C.LIGHT_COLOR
    PHOSPHOR    = C.PHOSPHOR
    WHITE_GREEN = C.WHITE_GREEN

    # Canvas background
    pygame.draw.rect(surf, BG, canvas_rect)

    # Floor
    tl = w2s(-aw / 2,  ah / 2)
    br = w2s( aw / 2, -ah / 2)
    pygame.draw.rect(surf, FLOOR,
                     pygame.Rect(tl[0], tl[1], br[0]-tl[0], br[1]-tl[1]))

    # Shadow rendering — delegated to shared engine module
    try:
        from engine.render_shadows import draw_shadows as _draw_shadows
        _draw_shadows(surf, arena, w2s, scl, canvas_rect)
    except Exception:
        pass

    # Light sources — colored glow
    _LIGHT_COLS = {"white": (255, 220, 120), "red": (255, 60, 60),
                   "green": (60, 220, 60),   "blue": (80, 140, 255)}
    for ls in arena["light_sources"]:
        cx_s, cy_s = w2s(ls["x"], ls["y"])
        r_px  = max(4, int(ls["radius"] * scl))
        lcol  = _LIGHT_COLS.get(ls.get("color", "white"), (255, 220, 120))
        for ring in range(r_px, 0, -max(1, r_px // 8)):
            alpha = int(70 * (1.0 - ring / r_px))
            s = pygame.Surface((ring * 2, ring * 2), pygame.SRCALPHA)
            pygame.draw.circle(s, (*lcol, alpha), (ring, ring), ring)
            surf.blit(s, (cx_s - ring, cy_s - ring))
        pygame.draw.circle(surf, lcol, (cx_s, cy_s), max(3, r_px // 6))

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
        from engine.robot_body import (
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


def light_at(wx: float, wy: float, arena: dict,
             channel: str = "white") -> float:
    """
    Return normalized light intensity at (wx, wy) for the given channel.
    channel: "white" sums all sources regardless of color.
             "red"/"green"/"blue" sums only matching sources.
    Intensity falls off linearly: 1.0 at centre, 0.0 at radius*2.
    """
    total = 0.0
    for ls in arena["light_sources"]:
        ls_color = ls.get("color", "white")
        # White channel reads all sources; colored channel reads matching
        if channel != "white" and ls_color != channel:
            continue
        dist = math.hypot(wx - ls["x"], wy - ls["y"])
        r    = max(0.01, ls["radius"])
        if dist < r * 3:
            total += max(0.0, 1.0 - dist / (r * 2))
    return min(1.0, total)
