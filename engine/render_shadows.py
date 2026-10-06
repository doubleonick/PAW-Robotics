"""
engine/render_shadows.py
------------------------
Shared shadow rendering for all PAW arena renderers.

Shadows are geometry-based: for each light × internal-wall pair, a shadow
polygon is projected away from the light through the wall endpoints.
Concentric darkening rings are drawn inside that polygon as semi-transparent
dark overlays — theme-independent, visible on any floor color.

Usage
-----
Call draw_shadows() after drawing the floor and before drawing light glows
and walls.  Pass a w2s callable that converts world metres to screen pixels,
the arena dict, the canvas surface, scale, and canvas rect.
"""

from __future__ import annotations
import math
import pygame

# Light source colour palette — matches arena.py and pygame_renderer.py
LIGHT_COLS: dict[str, tuple[int, int, int]] = {
    "white": (255, 220, 120),
    "red":   (255,  60,  60),
    "green": ( 60, 220,  60),
    "blue":  ( 80, 140, 255),
}


def draw_shadows(
        surf:        pygame.Surface,
        arena:       dict,
        w2s,
        scale:       float,
        canvas_rect: pygame.Rect,
        floor_col:   tuple[int,int,int] = (10, 18, 10),  # kept for API compat
) -> None:
    """
    Draw shadow polygons on surf for all light × internal-wall pairs.

    Shadows are rendered as semi-transparent black overlays — theme-independent.
    They darken whatever is already drawn (floor, light glows) so shadows are
    visible on both bright and dark floor themes.

    Parameters
    ----------
    surf        : pygame Surface to draw on
    arena       : arena dict (needs 'light_sources', 'internal_walls',
                  'width', 'height')
    w2s         : world-to-screen function, returns (sx, sy) in surf coords
    scale       : pixels per metre (used for ring count)
    canvas_rect : arena canvas rect on surf (clipping and local offsets)
    floor_col   : kept for API compatibility, not used
    """
    if not arena.get("light_sources") or not arena.get("internal_walls"):
        return

    aw = arena["width"]
    ah = arena["height"]

    sh_surf = pygame.Surface(
        (canvas_rect.width, canvas_rect.height), pygame.SRCALPHA)

    def _project(lx, ly, px, py, dist):
        dx, dy = px - lx, py - ly
        d = math.hypot(dx, dy)
        if d < 1e-6:
            return px, py
        return px + dx / d * dist, py + dy / d * dist

    def _clip(wx, wy):
        m = 0.005
        return (max(-aw / 2 + m, min(aw / 2 - m, wx)),
                max(-ah / 2 + m, min(ah / 2 - m, wy)))

    def _w2s_local(wx, wy):
        sx, sy = w2s(wx, wy)
        return (sx - canvas_rect.left, sy - canvas_rect.top)

    for ls in arena["light_sources"]:
        lx, ly = ls["x"], ls["y"]
        lr     = max(0.01, ls.get("radius", 0.2))
        lr_px  = max(4, int(lr * scale))
        n_rings = max(1, lr_px // 8)

        for iw in arena["internal_walls"]:
            wx0, wy0 = iw["x0"], iw["y0"]
            wx1, wy1 = iw["x1"], iw["y1"]

            mx, my       = (wx0 + wx1) / 2, (wy0 + wy1) / 2
            dist_to_wall = math.hypot(mx - lx, my - ly)
            if dist_to_wall >= lr * 2:
                continue

            reach = max(0.05, lr * 2 - dist_to_wall)

            far0 = _project(lx, ly, wx0, wy0, reach)
            far1 = _project(lx, ly, wx1, wy1, reach)

            sp0   = _w2s_local(wx0, wy0)
            sp1   = _w2s_local(wx1, wy1)
            sfar0 = _w2s_local(*_clip(*far0))
            sfar1 = _w2s_local(*_clip(*far1))

            # Concentric dark overlays — outermost first (transparent),
            # innermost last (opaque at wall face).
            # Pure black with alpha — visible on any background color.
            for ring in range(n_rings, 0, -1):
                frac  = ring / n_rings        # 1=full extent, 0=wall face
                t     = 1.0 - frac            # 0=far, 1=wall face
                alpha = int(200 * t)          # transparent far, dark at wall

                rp0 = (sp0[0] + (sfar0[0] - sp0[0]) * frac,
                       sp0[1] + (sfar0[1] - sp0[1]) * frac)
                rp1 = (sp1[0] + (sfar1[0] - sp1[0]) * frac,
                       sp1[1] + (sfar1[1] - sp1[1]) * frac)
                r_poly = [sp0, sp1, rp1, rp0]
                pygame.draw.polygon(sh_surf, (0, 0, 0, alpha), r_poly)

    surf.blit(sh_surf, (canvas_rect.left, canvas_rect.top))
